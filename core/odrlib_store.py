"""Installed ODeR Library packages and their local reader state."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile

import requests

from core.odrlib import (
    MAX_MANIFEST_BYTES, OdrLibError, LibraryPackageInfo, UpdateFeedInfo,
    inspect_library, inspect_update_feed,
)
from core.paths import profile_dir
from core.profiles import (
    DEFAULT_SETTINGS, create_imported_profile, get_profile, load_profiles,
    update_profile,
)
from core.updater import UpdateError, is_newer_version
from core.version import APP_NAME, APP_VERSION


PACKAGE_FILENAME = "library.odrlib"
UPDATE_DOWNLOAD_LIMIT = 1024 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class ImportPreview:
    package: LibraryPackageInfo
    profile: dict
    conflicts: tuple[dict, ...]


@dataclass(frozen=True)
class ImportResult:
    package: LibraryPackageInfo
    profile: dict
    replaced: bool


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_path(profile_id):
    return os.path.join(profile_dir(profile_id), PACKAGE_FILENAME)


def _profile_metadata(info):
    library = info.library
    return {
        "description": library.get("description", ""),
        "creator": info.creator,
        "category": info.category,
        "version": info.version,
        "tags": list(info.tags),
        "links": list(library.get("links") or []),
    }


def _profile_document(info, profile_id, package_path, artwork_path=""):
    updated_at = str(info.library.get("updated_at") or info.created_at or "")
    counts = {
        "items": info.item_count,
        "folders": info.collection_count,
        "artifacts": info.artifact_count,
        "embedded_bytes": info.embedded_bytes,
        "online_sources": info.online_source_count,
    }
    return {
        "id": profile_id,
        "kind": "odrlib",
        "name": info.name,
        "base_url": f"odrlib://{info.library_id}/",
        "settings": dict(DEFAULT_SETTINGS),
        "metadata": _profile_metadata(info),
        "created_with": {
            "name": info.created_by_name,
            "version": info.created_by_version,
        },
        "index_source": {"type": "odrlib", "package_id": info.package_id},
        "hosted_index": None,
        "last_crawled": updated_at,
        "folders_cached": info.collection_count,
        "last_crawl_stats": {
            "update_mode": "odrlib",
            "items": info.item_count,
            "folders": info.collection_count,
            "files": info.artifact_count,
        },
        "crawl_history": [],
        "odrlib_artwork_path": artwork_path,
        "odrlib": {
            "library_id": info.library_id,
            "package_id": info.package_id,
            "package_path": os.path.abspath(package_path),
            "revision": info.revision,
            "version": info.version,
            "created_at": info.created_at,
            "updated_at": updated_at,
            "update_feed_url": info.update_feed_url or "",
            "extensions": [extension.badge for extension in info.extensions],
            "counts": counts,
        },
    }


def package_artwork_bytes(info):
    if not info.artwork_path:
        return b""
    try:
        with zipfile.ZipFile(info.path, "r") as archive:
            return archive.read(info.artwork_path)
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        raise OdrLibError("The library artwork could not be read from the package.") from exc


def profile_preview(info):
    profile = _profile_document(info, "preview", info.path)
    profile["_artwork_bytes"] = package_artwork_bytes(info)
    return profile


def find_conflicts(info):
    return [
        profile for profile in load_profiles()
        if profile.get("kind") == "odrlib"
        and (profile.get("odrlib") or {}).get("library_id") == info.library_id
    ]


def inspect_for_import(path):
    info = inspect_library(path, verify_hashes=True)
    return ImportPreview(info, profile_preview(info), tuple(find_conflicts(info)))


def _copy_verified(source_path, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".odrlib-import-", suffix=".tmp", dir=os.path.dirname(destination)
    )
    os.close(descriptor)
    try:
        with open(source_path, "rb") as source, open(temporary, "wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        if _sha256_file(source_path) != _sha256_file(temporary):
            raise OdrLibError("The package changed while it was being imported.")
        os.replace(temporary, destination)
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass


def _extract_artwork(info, profile_id):
    if not info.artwork_path:
        return ""
    extension = os.path.splitext(info.artwork_path)[1].casefold()
    if extension not in {".png", ".jpg", ".jpeg", ".webp"}:
        extension = ".img"
    destination = os.path.join(profile_dir(profile_id), "library-cover" + extension)
    try:
        with zipfile.ZipFile(_package_path(profile_id), "r") as archive:
            with archive.open(info.artwork_path, "r") as source, open(destination, "wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        raise OdrLibError("The library artwork could not be installed.") from exc
    return destination


def import_library(path, *, conflict_policy="error", replace_profile_id=None):
    """Validate and install a package, or atomically replace the same library."""
    info = inspect_library(path, verify_hashes=True)
    conflicts = find_conflicts(info)
    target = get_profile(replace_profile_id) if replace_profile_id else None
    replacing = conflict_policy == "replace"
    if replacing:
        if not target or target.get("kind") != "odrlib":
            raise OdrLibError("Choose an existing curated library to replace.")
        current = target.get("odrlib") or {}
        if current.get("library_id") != info.library_id:
            raise OdrLibError("The package belongs to a different curated library.")
        if info.revision < int(current.get("revision") or 0):
            raise OdrLibError("An older library revision cannot replace a newer installed revision.")
        profile_id = target["id"]
    else:
        if conflicts and conflict_policy == "error":
            raise OdrLibError("This curated library is already installed.")
        if conflict_policy not in {"copy", "error"}:
            raise OdrLibError("The selected import conflict policy is not supported.")
        profile_id = uuid.uuid4().hex[:12]

    destination = _package_path(profile_id)
    _copy_verified(os.path.abspath(path), destination)
    installed = inspect_library(destination, verify_hashes=False)
    artwork_path = _extract_artwork(installed, profile_id)
    document = _profile_document(installed, profile_id, destination, artwork_path)
    if replacing:
        profile = update_profile(
            profile_id,
            **{key: value for key, value in document.items() if key not in {"id", "settings"}},
        )
    else:
        try:
            profile = create_imported_profile(document)
        except Exception:
            try:
                os.remove(destination)
            except OSError:
                pass
            raise
    return ImportResult(installed, profile, replacing)


def load_profile_package(profile):
    if not profile or profile.get("kind") != "odrlib":
        raise OdrLibError("This profile is not an ODeR Library package.")
    stored = profile.get("odrlib") or {}
    path = stored.get("package_path") or _package_path(profile["id"])
    info = inspect_library(path, verify_hashes=False)
    if info.library_id != stored.get("library_id"):
        raise OdrLibError("The installed package no longer matches its library profile.")
    return info


def save_library_copy(profile, destination):
    info = load_profile_package(profile)
    destination = os.path.abspath(destination)
    if not destination.casefold().endswith(".odrlib"):
        destination += ".odrlib"
    if os.path.normcase(destination) == os.path.normcase(info.path):
        raise OdrLibError("Choose a different location for the library copy.")
    _copy_verified(info.path, destination)
    return destination


def _embedded_sources(info):
    sources = {}
    for item in info.items:
        for artifact in item.get("artifacts") or []:
            for source in artifact.get("sources") or []:
                if source.get("type") == "embedded":
                    sources[source.get("path")] = source
    return sources


def extract_embedded(profile, source, destination):
    """Stream one declared payload to a safe caller-selected destination."""
    info = load_profile_package(profile)
    declared = _embedded_sources(info).get((source or {}).get("path"))
    if not declared:
        raise OdrLibError("The selected bundled file is not declared by this library.")
    expected_size = int(declared.get("size") or 0)
    expected_hash = str(declared.get("sha256") or "").casefold()
    destination = os.path.abspath(destination)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".odrlib-extract-", suffix=".part", dir=os.path.dirname(destination)
    )
    os.close(descriptor)
    digest = hashlib.sha256()
    size = 0
    try:
        with zipfile.ZipFile(info.path, "r") as archive:
            with archive.open(declared["path"], "r") as package_file, open(temporary, "wb") as output:
                for chunk in iter(lambda: package_file.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > expected_size:
                        raise OdrLibError("The bundled file is larger than its declared size.")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        if size != expected_size or digest.hexdigest() != expected_hash:
            raise OdrLibError("The bundled file failed its size or SHA-256 check.")
        os.replace(temporary, destination)
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass
    return {"path": destination, "size": size, "sha256": expected_hash}


def check_for_update(profile, session=None):
    stored = (profile or {}).get("odrlib") or {}
    feed_url = stored.get("update_feed_url")
    if not feed_url:
        raise OdrLibError("This library does not publish an update feed.")
    session = session or requests
    response = None
    try:
        response = session.get(
            feed_url,
            headers={"Accept": "application/json", "User-Agent": f"{APP_NAME}/{APP_VERSION}"},
            timeout=20,
            stream=True,
        )
        response.raise_for_status()
        chunks = []
        size = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_MANIFEST_BYTES:
                raise OdrLibError("The library update feed is too large.")
            chunks.append(chunk)
        value = json.loads(b"".join(chunks).decode("utf-8"))
    except OdrLibError:
        raise
    except Exception as exc:
        raise OdrLibError(f"The library update feed could not be downloaded: {exc}") from exc
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    feed = inspect_update_feed(value)
    if feed.library_id != stored.get("library_id"):
        raise OdrLibError("The update feed belongs to a different library.")
    minimum = feed.minimum_reader
    if minimum and not minimum[:4].isdigit():
        try:
            if is_newer_version(minimum, APP_VERSION):
                raise OdrLibError(f"This library update requires ODeR {minimum} or newer.")
        except UpdateError as exc:
            raise OdrLibError("The update feed declares an unsupported minimum ODeR version.") from exc
    return feed if feed.revision > int(stored.get("revision") or 0) else None


def download_update(profile, feed: UpdateFeedInfo, session=None):
    if not isinstance(feed, UpdateFeedInfo):
        raise OdrLibError("The library update information is invalid.")
    stored = (profile or {}).get("odrlib") or {}
    if feed.library_id != stored.get("library_id"):
        raise OdrLibError("The update belongs to a different library.")
    if feed.revision <= int(stored.get("revision") or 0):
        raise OdrLibError("The selected package is not newer than the installed library.")
    if feed.size > UPDATE_DOWNLOAD_LIMIT:
        raise OdrLibError("The library update is larger than the supported download limit.")
    session = session or requests
    descriptor, temporary = tempfile.mkstemp(
        prefix=".odrlib-update-", suffix=".odrlib", dir=profile_dir(profile["id"])
    )
    os.close(descriptor)
    digest = hashlib.sha256()
    size = 0
    try:
        response = None
        try:
            response = session.get(
                feed.url,
                headers={"Accept": "application/vnd.oder.library+zip", "User-Agent": f"{APP_NAME}/{APP_VERSION}"},
                timeout=30,
                stream=True,
            )
            response.raise_for_status()
            with open(temporary, "wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > feed.size:
                        raise OdrLibError("The library update is larger than its declared size.")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        except OdrLibError:
            raise
        except Exception as exc:
            raise OdrLibError(f"The library update could not be downloaded: {exc}") from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if size != feed.size or digest.hexdigest() != feed.sha256:
            raise OdrLibError("The downloaded library update failed its size or SHA-256 check.")
        package = inspect_library(temporary, verify_hashes=True)
        if package.library_id != feed.library_id or package.revision != feed.revision:
            raise OdrLibError("The downloaded package does not match its update feed.")
        return import_library(temporary, conflict_policy="replace", replace_profile_id=profile["id"])
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass
