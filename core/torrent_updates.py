"""T2 package delivery. U1 remains the authority for revision and SHA-256.

The bootstrap feed and metainfo are fetched over HTTPS. The package can come
from peers; its complete size, digest, and library identity are still checked
by odrlib_store before installation. No networking happens during import.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import PurePosixPath
import re
import tempfile
import time
from urllib.parse import urlsplit

from core.odrlib import MAX_TORRENT_BYTES, OdrLibError


def validate_descriptor(value):
    if not isinstance(value, dict) or value.get("extension") != "T2":
        raise OdrLibError("The update torrent must declare extension T2.")
    url = str(value.get("url") or "")
    try:
        parsed = urlsplit(url)
        valid_url = parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
        parsed.port
    except ValueError:
        valid_url = False
    size = value.get("size")
    digest = str(value.get("sha256") or "").lower()
    path = str(value.get("path") or "")
    # T2 v2 delivers exactly one bare .odrlib filename. No directory traversal,
    # alternate streams, Windows devices, or implicit file-index selection.
    if (not valid_url or type(size) is not int or not 0 < size <= MAX_TORRENT_BYTES
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not path.lower().endswith(".odrlib") or len(path) > 240
            or PurePosixPath(path).name != path or any(c in path for c in '\\/:<>"|?*')
            or any(ord(c) < 32 for c in path) or path.endswith((" ", "."))
            or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", path, re.I)):
        raise OdrLibError("The update torrent contains unsafe or incomplete metadata.")
    return {"extension": "T2", "url": url, "size": size, "sha256": digest, "path": path}


def build_update_torrent(package_path, url, options):
    from core.torrent_support import create_package_metainfo
    from core.version import CREATOR_NAME, CREATOR_VERSION
    package_path = os.path.abspath(package_path)
    name = os.path.basename(package_path)
    try:
        data = create_package_metainfo(package_path, trackers=options.get("trackers") or (),
                                       private=bool(options.get("private")),
                                       creator=f"{CREATOR_NAME} {CREATOR_VERSION}")
    except Exception as exc:
        raise OdrLibError(f"Could not create the package update torrent: {exc}") from exc
    descriptor = validate_descriptor({
        "extension": "T2", "url": url, "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "path": name,
    })
    destination = package_path + ".torrent"
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(package_path), prefix=".update-torrent-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return destination, descriptor


def fetch_metainfo(descriptor, session):
    descriptor = validate_descriptor(descriptor)
    response = session.get(descriptor["url"], stream=True, timeout=20)
    try:
        response.raise_for_status()
        # requests follows redirects; bootstrap metadata must stay on HTTPS.
        if getattr(response, "url", descriptor["url"]) and urlsplit(
                getattr(response, "url", descriptor["url"])).scheme != "https":
            raise OdrLibError("The update torrent redirected away from HTTPS.")
        result = bytearray()
        for chunk in response.iter_content(64 * 1024):
            result.extend(chunk)
            if len(result) > descriptor["size"]:
                raise OdrLibError("The update torrent exceeds its declared size.")
        data = bytes(result)
        if len(data) != descriptor["size"] or hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
            raise OdrLibError("The update torrent failed its size or SHA-256 check.")
        return data
    finally:
        response.close()


def validate_metainfo(data, descriptor, package_size):
    from core.torrent_support import inspect_metainfo, torrent_info
    descriptor = validate_descriptor(descriptor)
    metadata = inspect_metainfo(data)
    files = metadata["files"]
    info = torrent_info(data)
    # Reject extra payloads, padding, renamed paths and symlinks before starting
    # a session, even when the feed's metainfo hash is otherwise correct.
    if (len(files) != 1 or info.num_files() != 1
            or files[0]["path"] != descriptor["path"] or files[0]["size"] != package_size
            or info.files().file_flags(0) & info.files().flag_symlink):
        raise OdrLibError("The update torrent must contain exactly the declared .odrlib package.")
    return info


def receive_package(feed, destination, http_session, *, stall_timeout=20, total_timeout=600):
    """Receive into disposable staging; no user files are ever torrent targets."""
    from core import downloader
    from core.settings import load_settings
    from core.torrent_support import binding
    settings = load_settings()
    if not settings.get("torrent_enabled", True):
        raise OdrLibError("Torrent downloads are disabled in Settings.")
    descriptor = validate_descriptor(feed.torrent)
    data = fetch_metainfo(descriptor, http_session)
    info = validate_metainfo(data, descriptor, feed.size)
    lt = binding()
    with tempfile.TemporaryDirectory(prefix=".t2-transfer-", dir=os.path.dirname(destination)) as staging:
        session = lt.session(downloader._torrent_session_settings(lt, settings))
        handle = None
        try:
            params = downloader._torrent_add_params(lt, info, staging, 0)
            handle = session.add_torrent(params)
            started = last_progress = time.monotonic()
            received = -1
            while True:
                status = handle.status()
                error = getattr(status, "errc", None)
                if error and error.value():
                    raise OdrLibError(f"Torrent update failed: {error.message()}")
                amount = int(handle.file_progress()[0])
                if amount >= feed.size:
                    break
                now = time.monotonic()
                if amount > received:
                    last_progress, received = now, amount
                if now - last_progress > stall_timeout or now - started > total_timeout:
                    raise OdrLibError("No torrent update progress; trying the HTTPS copy.")
                time.sleep(0.25)
            # Copy while storage is owned by libtorrent, then release it before
            # removing staging. The caller verifies the final package digest.
            import shutil
            shutil.copyfile(os.path.join(staging, descriptor["path"]), destination)
        finally:
            if handle is not None:
                session.remove_torrent(handle)
            # Session teardown synchronously releases its disk worker/files.
            del handle
            del session
