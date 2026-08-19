"""GitHub release discovery and verified update downloads."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import os
import re
from urllib.parse import urlparse

import requests

from core.paths import updates_dir


REPOSITORY = "Ka-derka/ODeR"
GITHUB_API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
STABLE_RELEASE_URL = f"{GITHUB_API_ROOT}/releases/latest"
RELEASES_URL = f"{GITHUB_API_ROOT}/releases"
INSTALLER_ASSET_NAME = "ODeR Installer.exe"
PORTABLE_ASSET_NAME = "ODeR-Portable.zip"
INSTALLER_ASSET_NAMES = (INSTALLER_ASSET_NAME, "ODeR.Installer.exe")
PORTABLE_ASSET_NAMES = (PORTABLE_ASSET_NAME,)
CHECKSUM_ASSET_NAME = "SHA256SUMS.txt"
CHECK_INTERVAL = timedelta(hours=24)

_VERSION_PATTERN = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "api.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


class UpdateError(RuntimeError):
    """Raised when update metadata or a downloaded asset is unsafe or invalid."""


class DownloadCanceled(UpdateError):
    """Raised when the user cancels an update download."""


def _is_request_exception(exc):
    exception_type = getattr(requests, "RequestException", None)
    return isinstance(exception_type, type) and isinstance(exc, exception_type)


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    title: str
    notes: str
    published_at: str
    page_url: str
    channel: str
    asset: ReleaseAsset


def parse_version(value):
    """Return a tuple suitable for comparing semantic release versions."""
    match = _VERSION_PATTERN.fullmatch(str(value or "").strip())
    if not match:
        raise UpdateError(f"Invalid release version: {value!r}")
    major, minor, patch, suffix = match.groups()
    if suffix is None:
        prerelease_key = ()
        stable = 1
    else:
        prerelease_key = tuple(
            (0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in suffix.split(".")
        )
        stable = 0
    # A stable version sorts after every pre-release with the same numbers.
    return int(major), int(minor), int(patch), stable, prerelease_key


def is_newer_version(candidate, current):
    return parse_version(candidate) > parse_version(current)


def should_check(last_checked_at, now=None, interval=CHECK_INTERVAL):
    if not last_checked_at:
        return True
    now = now or datetime.now(timezone.utc)
    try:
        checked = datetime.fromisoformat(str(last_checked_at).replace("Z", "+00:00"))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    return now - checked.astimezone(timezone.utc) >= interval


def checked_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _headers(current_version):
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"ODeR/{current_version}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _validate_download_url(url):
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in _ALLOWED_DOWNLOAD_HOSTS:
        raise UpdateError("The release contains an untrusted download URL.")


def _request_json(session, url, current_version):
    response = None
    try:
        response = session.get(url, headers=_headers(current_version), timeout=20)
        response.raise_for_status()
        return response.json()
    except ValueError as exc:
        raise UpdateError(f"Could not read GitHub release information: {exc}") from exc
    except Exception as exc:
        if _is_request_exception(exc):
            raise UpdateError(f"Could not read GitHub release information: {exc}") from exc
        raise
    finally:
        if response is not None:
            response.close()


def _select_release(session, channel, current_version):
    if channel == "preview":
        releases = _request_json(session, RELEASES_URL, current_version)
        if not isinstance(releases, list):
            raise UpdateError("GitHub returned invalid release information.")
        release = next((item for item in releases if isinstance(item, dict) and not item.get("draft")), None)
    else:
        release = _request_json(session, STABLE_RELEASE_URL, current_version)
    if not isinstance(release, dict):
        raise UpdateError("No published GitHub release was found.")
    return release


def _asset_by_name(release, name):
    for asset in release.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == name:
            return asset
    return None


def _asset_by_names(release, names):
    for name in names:
        asset = _asset_by_name(release, name)
        if asset:
            return asset
    return None


def _download_text(session, asset, current_version):
    url = asset.get("browser_download_url")
    _validate_download_url(url)
    response = None
    try:
        response = session.get(url, headers=_headers(current_version), timeout=20)
        response.raise_for_status()
        _validate_download_url(getattr(response, "url", url))
        if len(response.content) > 1024 * 1024:
            raise UpdateError("The checksum file is unexpectedly large.")
        return response.content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UpdateError(f"Could not download the release checksums: {exc}") from exc
    except Exception as exc:
        if _is_request_exception(exc):
            raise UpdateError(f"Could not download the release checksums: {exc}") from exc
        raise
    finally:
        if response is not None:
            response.close()


def _checksum_from_text(text, asset_names):
    if isinstance(asset_names, str):
        asset_names = (asset_names,)
    accepted_names = set(asset_names)
    for raw_line in str(text or "").splitlines():
        parts = raw_line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, name = parts
        name = name.lstrip("*").strip()
        if name in accepted_names and _SHA256_PATTERN.fullmatch(digest):
            return digest.casefold()
    return None


def _resolve_checksum(session, release, asset, current_version):
    digest = str(asset.get("digest") or "")
    if digest.casefold().startswith("sha256:"):
        candidate = digest.split(":", 1)[1]
        if _SHA256_PATTERN.fullmatch(candidate):
            return candidate.casefold()
    checksum_asset = _asset_by_name(release, CHECKSUM_ASSET_NAME)
    if checksum_asset:
        asset_name = asset.get("name")
        checksum_names = {asset_name}
        if asset_name in INSTALLER_ASSET_NAMES:
            checksum_names.update(INSTALLER_ASSET_NAMES)
        candidate = _checksum_from_text(
            _download_text(session, checksum_asset, current_version), checksum_names
        )
        if candidate:
            return candidate
    raise UpdateError(f"The release does not provide a SHA-256 checksum for {asset.get('name', 'the update')}.")


def check_for_update(current_version, channel="stable", portable=False, session=None):
    """Return UpdateInfo for a newer release, or None when already current."""
    channel = "preview" if channel == "preview" else "stable"
    owns_session = session is None
    session = session or requests.Session()
    try:
        release = _select_release(session, channel, current_version)
        tag = str(release.get("tag_name") or "").strip()
        version = tag[1:] if tag.casefold().startswith("v") else tag
        if not is_newer_version(version, current_version):
            return None
        asset_names = PORTABLE_ASSET_NAMES if portable else INSTALLER_ASSET_NAMES
        expected_asset_name = PORTABLE_ASSET_NAME if portable else INSTALLER_ASSET_NAME
        asset = _asset_by_names(release, asset_names)
        if not asset:
            raise UpdateError(f"ODeR {version} does not include {expected_asset_name}.")
        url = asset.get("browser_download_url")
        _validate_download_url(url)
        checksum = _resolve_checksum(session, release, asset, current_version)
        return UpdateInfo(
            version=version,
            title=str(release.get("name") or f"ODeR {version}"),
            notes=str(release.get("body") or "No release notes were provided."),
            published_at=str(release.get("published_at") or ""),
            page_url=str(release.get("html_url") or f"https://github.com/{REPOSITORY}/releases"),
            channel=channel,
            asset=ReleaseAsset(
                name=str(asset.get("name")),
                url=str(url),
                size=max(0, int(asset.get("size") or 0)),
                sha256=checksum,
            ),
        )
    finally:
        if owns_session:
            session.close()


def download_update(info, destination_root=None, progress=None, canceled=None, session=None):
    """Download and verify an update, returning its final local path."""
    destination_root = destination_root or updates_dir()
    safe_name = os.path.basename(info.asset.name)
    if safe_name != info.asset.name or not safe_name:
        raise UpdateError("The release asset has an unsafe filename.")
    version_dir = os.path.join(destination_root, info.version)
    os.makedirs(version_dir, exist_ok=True)
    destination = os.path.join(version_dir, safe_name)
    partial = destination + ".part"
    owns_session = session is None
    session = session or requests.Session()
    _validate_download_url(info.asset.url)
    response = None
    downloaded = 0
    digest = hashlib.sha256()
    try:
        response = session.get(
            info.asset.url,
            headers=_headers(info.version),
            timeout=(20, 60),
            stream=True,
        )
        response.raise_for_status()
        _validate_download_url(getattr(response, "url", info.asset.url))
        with open(partial, "wb") as handle:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if canceled and canceled():
                    raise DownloadCanceled("The update download was canceled.")
                if not chunk:
                    continue
                handle.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, info.asset.size)
        if info.asset.size and downloaded != info.asset.size:
            raise UpdateError(
                f"The update size did not match GitHub (expected {info.asset.size:,} bytes, received {downloaded:,})."
            )
        if digest.hexdigest().casefold() != info.asset.sha256.casefold():
            raise UpdateError("The downloaded update failed SHA-256 verification and was deleted.")
        os.replace(partial, destination)
        return destination
    except OSError as exc:
        raise UpdateError(f"Could not download the update: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, UpdateError):
            raise
        if _is_request_exception(exc):
            raise UpdateError(f"Could not download the update: {exc}") from exc
        raise
    finally:
        if response is not None:
            response.close()
        if owns_session:
            session.close()
        if os.path.exists(partial):
            try:
                os.remove(partial)
            except OSError:
                pass
