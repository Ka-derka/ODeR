"""
Download queue shared across all profiles. Each profile gets its own
"lane": a background worker thread that only runs while that profile has
pending items, respecting *that profile's* download_delay_seconds and
max_concurrent_downloads (so a fast, permissive site and a strict,
rate-limited site don't have to share one global pace).

A lightweight dispatcher thread starts/stops lanes as needed. Everything
else (pause, retry, remove) just edits queue.json; lanes notice on their
next poll.
"""
import os
import hashlib
import shutil
import time
import threading
import unicodedata
import uuid
import requests
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

from core.paths import queue_path
from core.settings import load_settings, downloads_root
from core.profiles import get_profile
from core.state_schema import load_document, save_document
from core import applog

_file_lock = threading.RLock()
_stop_all = threading.Event()
_paused_all = threading.Event()  # when set, no NEW downloads start (in-flight ones finish)
_lane_threads = {}  # profile_id -> Thread
_dispatcher_thread = None
_seed_restore_thread = None
_torrent_lock = threading.RLock()
_torrent_session = None
_torrent_handles = {}  # (torrent_id,) -> {handle, staging}

FINISHED_STATUSES = {"done", "seeding"}


def pause_all():
    _paused_all.set()


def resume_all():
    _paused_all.clear()


def is_paused():
    return _paused_all.is_set()


def load_queue():
    with _file_lock:
        return load_document(queue_path(), "download-queue", [], list)


def save_queue(items, *, backup=True):
    with _file_lock:
        save_document(queue_path(), "download-queue", items, list, backup=backup)


def new_group(name):
    return {"id": uuid.uuid4().hex[:12], "name": str(name or "Download group")}


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL", "CLOCK$",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _safe_component(value, fallback="item", *, decode=True):
    original = str(value or "")
    value = unquote(original) if decode else original
    value = unicodedata.normalize("NFC", value)
    value = "".join(
        character for character in value
        if character not in '<>:"/\\|?*' and ord(character) >= 32
    )
    value = value.strip().rstrip(" .")
    if not value:
        value = fallback
    stem = value.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        value = "_" + value
    if len(value) > 180:
        suffix = hashlib.sha256(original.encode("utf-8", "replace")).hexdigest()[:10]
        extension = os.path.splitext(value)[1][:20]
        keep = max(1, 180 - len(extension) - len(suffix) - 2)
        value = f"{value[:keep]}~{suffix}{extension}"
    return value or fallback


def _safe_relative_path(rel_path, *, decode=True):
    parts = []
    for raw in str(rel_path or "").replace("\\", "/").split("/"):
        part = _safe_component(raw, "", decode=decode)
        if part and part not in (".", ".."):
            parts.append(part)
    return parts


def source_relative_directory(base_url, parent_url):
    """Return a URL folder path relative to a directory root, if it is inside it."""
    base = urlsplit(str(base_url or ""))
    parent = urlsplit(str(parent_url or ""))
    if (base.scheme.casefold(), base.netloc.casefold()) != (
        parent.scheme.casefold(), parent.netloc.casefold()
    ):
        return ""
    base_path = base.path if base.path.endswith("/") else base.path + "/"
    if not parent.path.startswith(base_path):
        return ""
    return parent.path[len(base_path):].strip("/")


def destination_relative_path(profile_name, rel_path, name):
    parts = [_safe_component(profile_name, "profile")]
    parts.extend(_safe_relative_path(rel_path))
    parts.append(_safe_component(name, "download"))
    return "/".join(parts)


def _collision_name(relative_path, number):
    parts = relative_path.replace("\\", "/").split("/")
    stem, extension = os.path.splitext(parts[-1])
    parts[-1] = f"{stem} ({number}){extension}"
    return "/".join(parts)


def _new_queue_item(profile_id, profile_name, entry, group_id, group_name, destination_rel_path):
    item = {
        "id": uuid.uuid4().hex[:12],
        "profile_id": profile_id,
        "profile_name": profile_name,
        "url": entry["url"],
        "name": entry["name"],
        "rel_path": entry.get("rel_path") or "",
        "destination_rel_path": destination_rel_path,
        "status": "pending",
        "bytes_done": 0,
        "bytes_total": None,
        "error": None,
        "group_id": group_id,
        "group_name": group_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "speed_bps": 0.0,
        "eta_seconds": None,
    }
    for key in ("transport", "torrent"):
        if key in entry:
            item[key] = entry[key]
    return item


def enqueue_many(profile_id, profile_name, entries, group_id=None, group_name=None):
    """Queue a batch with one read/write and deterministic collision-free paths."""
    with _file_lock:
        items = load_queue()
        active = {
            (item.get("profile_id"), item.get("url")): item
            for item in items
            if item.get("status") in {"pending", "downloading", "paused", "seeding"}
        }
        destinations = {}
        for item in items:
            relative = _item_relative_path(item)
            if relative:
                destinations.setdefault(relative.casefold(), item.get("url"))

        result_items = []
        added = 0
        reused = 0
        for raw in entries:
            entry = dict(raw)
            key = (profile_id, entry.get("url"))
            if key in active:
                result_items.append(active[key])
                reused += 1
                continue
            relative = destination_relative_path(
                profile_name, entry.get("rel_path", ""), entry.get("name", "download")
            )
            candidate = relative
            number = 2
            while (
                candidate.casefold() in destinations
                and destinations[candidate.casefold()] != entry.get("url")
            ):
                candidate = _collision_name(relative, number)
                number += 1
            item = _new_queue_item(
                profile_id, profile_name, entry, group_id, group_name, candidate
            )
            items.append(item)
            result_items.append(item)
            active[key] = item
            destinations[candidate.casefold()] = entry.get("url")
            added += 1
        if added:
            save_queue(items)
    if added == 1:
        applog.log(f"queued: {result_items[-1]['name']} ({profile_name})")
    elif added:
        applog.log(f"queued {added} structured downloads ({profile_name})")
    return {"items": result_items, "added": added, "reused": reused}


def enqueue(profile_id, profile_name, url, name, rel_path, group_id=None, group_name=None):
    result = enqueue_many(
        profile_id,
        profile_name,
        [{"url": url, "name": name, "rel_path": rel_path}],
        group_id,
        group_name,
    )
    return result["items"][0]


def enqueue_torrent(profile_id, profile_name, source, name, rel_path, group_id=None, group_name=None):
    """Queue one validated T1 file through the same user-facing download list."""
    source = dict(source or {})
    torrent_id = str(source.get("torrent_id") or "")
    file_index = int(source.get("file_index"))
    if not torrent_id or file_index < 0:
        raise ValueError("The selected torrent source is incomplete.")
    url = f"torrent://{torrent_id}/{file_index}"
    result = enqueue_many(
        profile_id,
        profile_name,
        [{
            "url": url, "name": name, "rel_path": rel_path,
            "transport": "torrent", "torrent": source,
        }],
        group_id,
        group_name,
    )
    return result["items"][0]


def update_item(item_id, **fields):
    with _file_lock:
        items = load_queue()
        for it in items:
            if it["id"] == item_id:
                it.update(fields)
                break
        progress_only = set(fields).issubset({"bytes_done", "bytes_total", "speed_bps", "eta_seconds"})
        save_queue(items, backup=not progress_only)


def remove_item(item_id):
    with _file_lock:
        items = load_queue()
        removed = next((it for it in items if it["id"] == item_id), None)
        items = [it for it in items if it["id"] != item_id]
        save_queue(items)
    if removed:
        _release_torrent_item(removed, delete_payload=True)
        applog.log(f"removed from queue: {removed['name']} ({removed['profile_name']})")


def retry_item(item_id):
    with _file_lock:
        items = load_queue()
        for it in items:
            if it["id"] == item_id and it.get("status") == "error":
                it["status"] = "pending"
                it["error"] = None
                applog.log(f"retrying: {it['name']} ({it['profile_name']})")
        save_queue(items)


def pause_item(item_id):
    item = next((value for value in load_queue() if value.get("id") == item_id), None)
    if not item or item.get("status") not in {"pending", "downloading", "seeding"}:
        return
    fields = {"status": "paused", "speed_bps": 0.0, "eta_seconds": None}
    if item.get("status") == "seeding":
        fields["seed_ready"] = True
    update_item(item_id, **fields)
    if item.get("transport") == "torrent":
        _release_torrent_item(item, delete_payload=False)


def resume_item(item_id):
    item = next((value for value in load_queue() if value.get("id") == item_id), None)
    if not item or item.get("status") != "paused":
        return
    if item.get("transport") == "torrent" and item.get("seed_ready"):
        update_item(item_id, status="seeding", error=None)
        threading.Thread(target=_restore_torrent_seed, args=(item, applog.log), daemon=True).start()
    else:
        update_item(item_id, status="pending", error=None)


def items_in_group(group_id):
    return [item for item in load_queue() if item.get("group_id") == group_id]


def _update_group(group_id, statuses, **fields):
    with _file_lock:
        items = load_queue()
        changed = 0
        for item in items:
            if item.get("group_id") == group_id and item.get("status") in statuses:
                item.update(fields)
                changed += 1
        if changed:
            save_queue(items)
        return changed


def pause_group(group_id):
    items = [
        item for item in load_queue()
        if item.get("group_id") == group_id
        and item.get("status") in {"pending", "downloading", "seeding"}
    ]
    for item in items:
        pause_item(item["id"])
    return len(items)


def resume_group(group_id):
    items = [
        item for item in load_queue()
        if item.get("group_id") == group_id and item.get("status") == "paused"
    ]
    for item in items:
        resume_item(item["id"])
    return len(items)


def retry_group(group_id):
    return _update_group(group_id, {"error"}, status="pending", error=None)


def remove_group(group_id):
    with _file_lock:
        items = load_queue()
        kept = [item for item in items if item.get("group_id") != group_id]
        removed = len(items) - len(kept)
        removed_items = [item for item in items if item.get("group_id") == group_id]
        if removed:
            save_queue(kept)
    for item in removed_items:
        _release_torrent_item(item, delete_payload=True)
    return removed


def retry_failed():
    with _file_lock:
        items = load_queue()
        changed = 0
        for item in items:
            if item.get("status") == "error":
                item.update(status="pending", error=None)
                changed += 1
        if changed:
            save_queue(items)
        return changed


def clear_completed():
    with _file_lock:
        items = load_queue()
        removed_items = [item for item in items if item.get("status") in FINISHED_STATUSES]
        kept = [item for item in items if item.get("status") not in FINISHED_STATUSES]
        removed = len(items) - len(kept)
        if removed:
            save_queue(kept)
    for item in removed_items:
        _release_torrent_item(item, delete_payload=True)
    return removed


def summarize_group_items(items):
    """Summarize an already-loaded group without rereading queue.json."""
    total = sum(int(item.get("bytes_total") or 0) for item in items)
    done = sum(int(item.get("bytes_done") or 0) for item in items)
    speed = sum(float(item.get("speed_bps") or 0) for item in items if item.get("status") == "downloading")
    active = sum(1 for item in items if item.get("status") in {"pending", "downloading", "paused"})
    failed = sum(1 for item in items if item.get("status") == "error")
    completed = sum(1 for item in items if item.get("status") in FINISHED_STATUSES)
    eta = ((total - done) / speed) if total and speed > 0 and done < total else None
    percent = min(100, int(done * 100 / total)) if total else (100 if items and completed == len(items) else 0)
    return {"items": len(items), "total": len(items), "done": completed,
            "errors": failed, "percent": percent,
            "bytes_total": total or None, "bytes_done": done,
            "speed_bps": speed, "eta_seconds": eta, "active": active,
            "failed": failed, "completed": completed}


def group_summary(group_id):
    return summarize_group_items(items_in_group(group_id))


def _item_relative_path(item):
    stored = item.get("destination_rel_path")
    if stored:
        return "/".join(_safe_relative_path(stored, decode=False))
    # Defensive fallback for a manually edited or partially migrated queue.
    return destination_relative_path(
        item.get("profile_name", "profile"),
        item.get("rel_path", ""),
        item.get("name", "download"),
    )


def _download_root():
    global_dir = (load_settings().get("download_dir") or "").strip()
    return os.path.abspath(os.path.expanduser(global_dir or downloads_root()))


def _dest_path(item, *, create=False):
    root = _download_root()
    relative = _item_relative_path(item)
    parts = _safe_relative_path(relative, decode=False)
    if not parts:
        parts = ["profile", "download"]
    destination = os.path.abspath(os.path.join(root, *parts))
    if os.path.commonpath((root, destination)) != root:
        raise ValueError("The download destination escaped the configured download directory.")
    if create:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
    return destination


def destination_path(item):
    return _dest_path(item)


def _download_one(item, settings, log):
    if item.get("transport") == "torrent":
        return _download_torrent_one(item, settings, log)
    dest = _dest_path(item, create=True)
    part = dest + ".part"
    if os.path.isfile(dest) and load_settings().get("skip_existing_downloads", True):
        existing_size = os.path.getsize(dest)
        update_item(
            item["id"], status="done", bytes_done=existing_size,
            bytes_total=existing_size, speed_bps=0.0, eta_seconds=0,
            error=None, result="existing",
        )
        log(f"kept existing download: {dest}")
        return
    headers = {"User-Agent": settings.get("user_agent", "Mozilla/5.0 (offline-directory-browser)")}
    existing = 0
    if os.path.exists(part):
        existing = os.path.getsize(part)
        headers["Range"] = f"bytes={existing}-"

    update_item(item["id"], status="downloading", error=None)
    started = time.monotonic()
    sample_started = started
    sample_bytes = existing
    last_queue_update = 0.0
    try:
        with requests.get(item["url"], headers=headers, stream=True,
                           timeout=settings.get("request_timeout_seconds", 20)) as resp:
            if resp.status_code == 416:
                os.replace(part, dest)
                update_item(item["id"], status="done", bytes_done=existing, bytes_total=existing)
                return
            resp.raise_for_status()
            mode = "ab" if existing and resp.status_code == 206 else "wb"
            if mode == "wb":
                existing = 0
            total = resp.headers.get("Content-Length")
            total_bytes = (int(total) + existing) if total else None
            done = existing
            last_status_check = done
            with open(part, mode) as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if _stop_all.is_set():
                        update_item(item["id"], status="paused", bytes_done=done, bytes_total=total_bytes)
                        return
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if done - last_status_check >= 1024 * 1024:
                            current = next((q for q in load_queue() if q["id"] == item["id"]), None)
                            if current and current.get("status") == "paused":
                                update_item(item["id"], status="paused", bytes_done=done, bytes_total=total_bytes)
                                return
                            last_status_check = done
                        now = time.monotonic()
                        elapsed_sample = max(0.001, now - sample_started)
                        speed = max(0.0, (done - sample_bytes) / elapsed_sample)
                        eta = ((total_bytes - done) / speed) if total_bytes and speed > 0 else None
                        # Persist progress at a UI-visible cadence instead of
                        # rewriting and reparsing the whole queue for every
                        # network chunk (often dozens of times per second).
                        if now - last_queue_update >= 0.25:
                            update_item(item["id"], bytes_done=done, bytes_total=total_bytes,
                                        speed_bps=speed, eta_seconds=eta)
                            last_queue_update = now
                        if elapsed_sample >= 2.0:
                            sample_started = now
                            sample_bytes = done
        os.replace(part, dest)
        update_item(item["id"], status="done", bytes_done=done, bytes_total=done,
                    speed_bps=0.0, eta_seconds=0)
        log(f"downloaded: {item['name']} ({item['profile_name']})")
    except Exception as e:
        update_item(item["id"], status="error", error=str(e))
        log(f"error downloading {item['name']}: {e}")


def _torrent_identity(item):
    source = dict(item.get("torrent") or {})
    # The UUID belongs to the embedded torrent, not to one installed copy of
    # the library. Sharing it lets duplicate imports reuse one libtorrent
    # handle instead of trying to add the same info hash twice to a session.
    return (str(source.get("torrent_id") or ""),)


def _torrent_file_index(item):
    try:
        return int((item.get("torrent") or {}).get("file_index"))
    except (TypeError, ValueError):
        return -1


def _torrent_session_settings(lt, settings):
    values = {
        "enable_dht": bool(settings.get("torrent_enable_dht", True)),
        "enable_lsd": bool(settings.get("torrent_enable_lsd", True)),
        "enable_upnp": bool(settings.get("torrent_enable_upnp", False)),
        "enable_natpmp": bool(settings.get("torrent_enable_natpmp", False)),
        "connections_limit": max(10, int(settings.get("torrent_connections_limit", 80))),
        "alert_mask": int(lt.alert.category_t.error_notification),
        "download_rate_limit": max(0, int(settings.get("torrent_download_limit_kib", 0))) * 1024,
        "upload_rate_limit": max(0, int(settings.get("torrent_upload_limit_kib", 0))) * 1024,
    }
    return values


def _get_torrent_session(lt, settings):
    global _torrent_session
    with _torrent_lock:
        values = _torrent_session_settings(lt, settings)
        if _torrent_session is None:
            _torrent_session = lt.session(values)
        else:
            try:
                _torrent_session.apply_settings(values)
            except (AttributeError, RuntimeError):
                pass
        return _torrent_session


def _torrent_handle_is_valid(record):
    if not record:
        return False
    try:
        return bool(record["handle"].is_valid())
    except (AttributeError, RuntimeError):
        return False


def _ensure_torrent_handle(lt, info, item, staging, file_index, settings):
    """Return the shared handle for one library/torrent and enable one file."""
    key = _torrent_identity(item)
    with _torrent_lock:
        record = _torrent_handles.get(key)
        if not _torrent_handle_is_valid(record):
            session = _get_torrent_session(lt, settings)
            params = _torrent_add_params(lt, info, staging, file_index)
            handle = session.add_torrent(params)
            record = {"handle": handle, "staging": staging}
            _torrent_handles[key] = record
        else:
            handle = record["handle"]
            handle.file_priority(file_index, 4)
        return _torrent_session, record["handle"]


def _torrent_staging_path(item):
    root = _download_root()
    staging_root = os.path.abspath(os.path.join(root, ".oder-torrents"))
    identity = "\0".join(_torrent_identity(item)).encode("utf-8", "replace")
    component = hashlib.sha256(identity).hexdigest()[:24]
    staging = os.path.abspath(os.path.join(staging_root, component))
    if os.path.commonpath((staging_root, staging)) != staging_root:
        raise ValueError("The torrent staging path escaped the download directory.")
    return staging


def _torrent_payload_path(staging, relative):
    """Resolve libtorrent's exact file path without renaming its components."""
    text = str(relative or "").replace("\\", "/")
    native = text.replace("/", os.sep)
    drive, _tail = os.path.splitdrive(native)
    parts = text.split("/")
    if (
            not text or drive or os.path.isabs(native)
            or any(part in {"", ".", ".."} for part in parts)
            or any("\x00" in part for part in parts)):
        raise ValueError("The torrent contains an unsafe payload path.")
    staging = os.path.abspath(staging)
    candidate = os.path.abspath(os.path.join(staging, *parts))
    try:
        inside = os.path.normcase(os.path.commonpath((staging, candidate))) == os.path.normcase(staging)
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("The torrent payload path escaped its staging folder.")
    return candidate


def _torrent_add_params(lt, info, staging, file_index):
    params = lt.add_torrent_params()
    params.ti = info
    params.save_path = staging
    # Boost.Python returns a copy when this vector property is read. Build the
    # complete list first and assign it once, otherwise all files remain at 0.
    priorities = [0] * info.num_files()
    priorities[file_index] = 4
    params.file_priorities = priorities
    return params


def _sha256_path(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_torrent_payload(downloaded, destination):
    """Expose a completed payload without taking it away from libtorrent."""
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temporary = f"{destination}.oder-{uuid.uuid4().hex}.tmp"
    try:
        try:
            os.link(downloaded, temporary)
        except OSError:
            # Network/removable filesystems may not support hard links. Keep a
            # private seed copy in that case so seeding remains deterministic.
            shutil.copy2(downloaded, temporary)
        os.replace(temporary, destination)
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


def _prepare_seed_payload(item, destination, downloaded, expected_size):
    """Make the private torrent path reference an already-downloaded file."""
    if os.path.isfile(downloaded) and os.path.getsize(downloaded) == expected_size:
        return
    try:
        os.remove(downloaded)
    except OSError:
        pass
    if not os.path.isfile(destination) or os.path.getsize(destination) != expected_size:
        raise RuntimeError("The completed file is missing or has a different size, so it cannot be seeded.")
    os.makedirs(os.path.dirname(downloaded), exist_ok=True)
    try:
        os.link(destination, downloaded)
    except OSError:
        shutil.copy2(destination, downloaded)


def _remaining_torrent_items(item):
    key = _torrent_identity(item)
    return [
        value for value in load_queue()
        if value.get("transport") == "torrent" and _torrent_identity(value) == key
    ]


def _release_torrent_item(item, *, delete_payload):
    """Stop one queue entry from participating without deleting its final file."""
    if not item or item.get("transport") != "torrent":
        return
    key = _torrent_identity(item)
    file_index = _torrent_file_index(item)
    remaining = _remaining_torrent_items(item)
    active_remaining = [
        value for value in remaining
        if value.get("status") in {"pending", "downloading", "seeding", "done"}
    ]
    same_file_active = any(_torrent_file_index(value) == file_index for value in active_remaining)
    same_file_stored = any(_torrent_file_index(value) == file_index for value in remaining)
    with _torrent_lock:
        record = _torrent_handles.get(key)
        if _torrent_handle_is_valid(record) and not same_file_active and file_index >= 0:
            try:
                record["handle"].file_priority(file_index, 0)
            except RuntimeError:
                pass
        if _torrent_handle_is_valid(record) and not active_remaining:
            try:
                _torrent_session.remove_torrent(record["handle"])
            except (AttributeError, RuntimeError):
                pass
            _torrent_handles.pop(key, None)

    staging = _torrent_staging_path(item)
    if delete_payload and not same_file_stored:
        relative = item.get("seed_payload_rel") or (item.get("torrent") or {}).get("path")
        try:
            payload = _torrent_payload_path(staging, relative)
            os.remove(payload)
        except (OSError, ValueError):
            pass
        if record and _torrent_handle_is_valid(record) and active_remaining:
            try:
                record["handle"].force_recheck()
            except RuntimeError:
                pass
    if not remaining:
        try:
            shutil.rmtree(staging)
        except OSError:
            pass


def _download_torrent_one(item, _profile_settings, log):
    """Download, verify, publish, and continue seeding one T1 file."""
    from core import odrlib_store
    from core.torrent_support import binding, torrent_info

    destination = _dest_path(item, create=True)
    profile = get_profile(item.get("profile_id"))
    if not profile or profile.get("kind") != "odrlib":
        update_item(item["id"], status="error", error="The source library is no longer installed.")
        return
    settings = load_settings()
    source = dict(item.get("torrent") or {})
    staging = _torrent_staging_path(item)
    os.makedirs(staging, exist_ok=True)
    update_item(item["id"], status="downloading", error=None)
    try:
        payload = odrlib_store.torrent_metainfo(profile, source)
        lt = binding()
        info = torrent_info(payload["data"])
        file_index = int(source["file_index"])
        if file_index < 0 or file_index >= info.num_files():
            raise ValueError("The selected T1 file index is outside the torrent.")
        relative = str(info.files().file_path(file_index)).replace("\\", "/")
        downloaded = _torrent_payload_path(staging, relative)
        expected_size = int(source.get("size") or info.files().file_size(file_index))
        expected_hash = str(source.get("sha256") or "").casefold()

        if os.path.isfile(destination) and settings.get("skip_existing_downloads", True):
            if os.path.getsize(destination) != expected_size:
                raise RuntimeError(
                    "An existing destination has a different size. Remove or rename it before retrying."
                )
            if expected_hash and _sha256_path(destination) != expected_hash:
                raise RuntimeError(
                    "An existing destination failed the T1 SHA-256 check. Remove or rename it before retrying."
                )
            _prepare_seed_payload(item, destination, downloaded, expected_size)
            _session, _handle = _ensure_torrent_handle(
                lt, info, item, staging, file_index, settings
            )
            update_item(
                item["id"], status="seeding", bytes_done=expected_size,
                bytes_total=expected_size, speed_bps=0.0, eta_seconds=0,
                error=None, result="existing", seed_ready=True,
                seed_payload_rel=relative,
            )
            log(f"seeding existing torrent download: {item['name']} ({item['profile_name']})")
            return

        _session, handle = _ensure_torrent_handle(
            lt, info, item, staging, file_index, settings
        )
        last_update = 0.0
        while True:
            if _stop_all.is_set():
                progress = handle.file_progress()
                done = int(progress[file_index]) if file_index < len(progress) else 0
                update_item(
                    item["id"], status="paused", bytes_done=done,
                    bytes_total=expected_size, speed_bps=0.0, eta_seconds=None,
                )
                return
            current = next((entry for entry in load_queue() if entry.get("id") == item["id"]), None)
            if not current or current.get("status") == "paused":
                _release_torrent_item(item, delete_payload=not current)
                return
            status = handle.status()
            error = getattr(status, "errc", None)
            if error and error.value():
                raise RuntimeError(error.message())
            progress = handle.file_progress()
            done = min(expected_size, int(progress[file_index]) if file_index < len(progress) else 0)
            speed = max(0.0, float(status.download_payload_rate))
            eta = (expected_size - done) / speed if speed and done < expected_size else None
            now = time.monotonic()
            if now - last_update >= 0.5:
                update_item(
                    item["id"], bytes_done=done, bytes_total=expected_size,
                    speed_bps=speed, eta_seconds=eta,
                )
                last_update = now
            if done >= expected_size:
                break
            time.sleep(0.25)

        if not os.path.isfile(downloaded):
            raise RuntimeError("The completed torrent file was not found in its safe staging folder.")
        actual_size = os.path.getsize(downloaded)
        if actual_size != expected_size or (expected_hash and _sha256_path(downloaded) != expected_hash):
            raise RuntimeError("The completed torrent file failed its size or SHA-256 check.")
        _publish_torrent_payload(downloaded, destination)
        update_item(
            item["id"], status="seeding", bytes_done=actual_size, bytes_total=actual_size,
            speed_bps=0.0, eta_seconds=0, error=None, result="downloaded",
            seed_ready=True, seed_payload_rel=relative,
        )
        log(f"torrent downloaded and seeding: {item['name']} ({item['profile_name']})")
    except Exception as exc:
        update_item(item["id"], status="error", error=str(exc), speed_bps=0.0, eta_seconds=None)
        _release_torrent_item(item, delete_payload=False)
        log(f"torrent error downloading {item['name']}: {exc}")


def _restore_torrent_seed(item, log):
    """Reattach a completed queue item to libtorrent after application startup."""
    from core import odrlib_store
    from core.torrent_support import binding, torrent_info

    current = next((value for value in load_queue() if value.get("id") == item.get("id")), None)
    if not current or current.get("status") not in {"done", "seeding"}:
        return False
    profile = get_profile(item.get("profile_id"))
    if not profile or profile.get("kind") != "odrlib":
        update_item(item["id"], status="done", speed_bps=0.0, eta_seconds=0)
        return False
    settings = load_settings()
    if not settings.get("torrent_enabled", True):
        update_item(item["id"], status="done", speed_bps=0.0, eta_seconds=0)
        return False
    source = dict(item.get("torrent") or {})
    payload = odrlib_store.torrent_metainfo(profile, source)
    lt = binding()
    info = torrent_info(payload["data"])
    file_index = int(source.get("file_index"))
    if file_index < 0 or file_index >= info.num_files():
        raise ValueError("The selected T1 file index is outside the torrent.")
    expected_size = int(source.get("size") or info.files().file_size(file_index))
    destination = _dest_path(item)
    if not os.path.isfile(destination) or os.path.getsize(destination) != expected_size:
        update_item(
            item["id"], status="done", speed_bps=0.0, eta_seconds=0,
            seed_ready=False, seed_error="The downloaded file is missing or has a different size.",
        )
        return False
    relative = str(info.files().file_path(file_index)).replace("\\", "/")
    staging = _torrent_staging_path(item)
    downloaded = _torrent_payload_path(staging, relative)
    _prepare_seed_payload(item, destination, downloaded, expected_size)
    _ensure_torrent_handle(lt, info, item, staging, file_index, settings)
    update_item(
        item["id"], status="seeding", bytes_done=expected_size,
        bytes_total=expected_size, speed_bps=0.0, eta_seconds=0,
        error=None, seed_ready=True, seed_payload_rel=relative,
    )
    return True


def _restore_torrent_seeds(log):
    restored = 0
    for item in load_queue():
        if _stop_all.is_set():
            break
        if item.get("transport") != "torrent" or item.get("status") not in FINISHED_STATUSES:
            continue
        try:
            if _restore_torrent_seed(item, log):
                restored += 1
        except Exception as exc:
            update_item(
                item["id"], status="done", speed_bps=0.0, eta_seconds=0,
                seed_error=str(exc),
            )
            log(f"could not restore torrent seeding for {item.get('name', 'download')}: {exc}")
    if restored:
        log(f"restored seeding for {restored} torrent download{'s' if restored != 1 else ''}")


def _profile_lane(profile_id, log):
    """Runs while `profile_id` has pending items; exits when it runs dry
    (the dispatcher will start a fresh lane if more get added later)."""
    while not _stop_all.is_set():
        if _paused_all.is_set():
            time.sleep(1)
            continue

        profile = get_profile(profile_id)
        if profile is None:
            return
        settings = profile["settings"]
        global_settings = load_settings()
        max_concurrent = min(
            max(1, int(settings.get("max_concurrent_downloads", 1))),
            max(1, int(global_settings.get("download_concurrency", 2))),
            max(1, int(global_settings.get("network_max_connections", 12))),
        )
        delay = max(float(settings.get("download_delay_seconds", 2.0)), float(global_settings.get("download_start_delay", 0.5)))

        items = load_queue()
        pending = [it for it in items if it["profile_id"] == profile_id and it["status"] == "pending"]
        if not pending:
            return  # lane goes idle; dispatcher restarts it if needed

        slots = threading.Semaphore(max_concurrent)
        batch = pending[:max_concurrent]
        threads = []
        for it in batch:
            def run(item=it):
                with slots:
                    _download_one(item, settings, log)
            t = threading.Thread(target=run, daemon=True)
            t.start()
            threads.append(t)
            time.sleep(delay)  # stagger starts even within a concurrent batch
        for t in threads:
            t.join()


def _dispatcher(log):
    while not _stop_all.is_set():
        items = load_queue()
        pending_profile_ids = {it["profile_id"] for it in items if it["status"] == "pending"}
        for pid in pending_profile_ids:
            lane = _lane_threads.get(pid)
            if lane is None or not lane.is_alive():
                t = threading.Thread(target=_profile_lane, args=(pid, log), daemon=True)
                _lane_threads[pid] = t
                t.start()
        time.sleep(1)


def start_background_worker(log=print):
    global _dispatcher_thread, _seed_restore_thread
    _stop_all.clear()
    if _dispatcher_thread is None or not _dispatcher_thread.is_alive():
        recovered = recover_interrupted_downloads()
        if recovered:
            log(f"resuming {recovered} download{'s' if recovered != 1 else ''} interrupted by the previous exit")
        _dispatcher_thread = threading.Thread(target=_dispatcher, args=(log,), daemon=True)
        _dispatcher_thread.start()
    if _seed_restore_thread is None or not _seed_restore_thread.is_alive():
        _seed_restore_thread = threading.Thread(
            target=_restore_torrent_seeds, args=(log,), daemon=True
        )
        _seed_restore_thread.start()
    return _dispatcher_thread


def stop_background_worker():
    global _torrent_session
    _stop_all.set()
    with _torrent_lock:
        if _torrent_session is not None:
            try:
                _torrent_session.pause()
            except RuntimeError:
                pass
        _torrent_handles.clear()
        _torrent_session = None


def destination_preview(profile_name, rel_path, name):
    """Return the path a queued download would use, without creating folders."""
    return _dest_path({
        "profile_name": profile_name,
        "rel_path": rel_path,
        "name": name,
        "destination_rel_path": destination_relative_path(profile_name, rel_path, name),
    })


def _source_identity(source):
    source = dict(source or {})
    source_type = source.get("type")
    if source_type == "https":
        return "https", str(source.get("url") or "")
    if source_type == "torrent":
        try:
            index = int(source.get("file_index"))
        except (TypeError, ValueError):
            index = -1
        return "torrent", str(source.get("torrent_id") or ""), index
    return source_type, str(source.get("path") or "")


def find_existing_download(
        profile_id, profile_name, sources, name, rel_path="", expected_size=None):
    """Find a completed local artifact by queue identity, then canonical path."""
    try:
        expected_size = int(expected_size) if expected_size is not None else None
    except (TypeError, ValueError):
        expected_size = None

    def acceptable(path):
        try:
            return os.path.isfile(path) and (
                expected_size is None or os.path.getsize(path) == expected_size
            )
        except OSError:
            return False

    identities = {_source_identity(source) for source in sources or []}
    for item in reversed(load_queue()):
        if item.get("profile_id") != profile_id:
            continue
        if item.get("transport") == "torrent":
            identity = _source_identity({"type": "torrent", **dict(item.get("torrent") or {})})
        else:
            identity = ("https", str(item.get("url") or ""))
        if identities and identity not in identities:
            continue
        try:
            path = destination_path(item)
        except ValueError:
            continue
        if acceptable(path):
            return path

    candidate = destination_preview(profile_name, rel_path, name)
    if acceptable(candidate):
        return candidate

    # A queue record may have been removed after this artifact received a
    # collision suffix such as ``file (2).zip``. Recover it only when exactly
    # one matching-size sibling is available; ambiguity must fall back to the
    # normal download/source chooser instead of opening the wrong file.
    directory = os.path.dirname(candidate)
    stem, extension = os.path.splitext(os.path.basename(candidate))
    matches = []
    try:
        for entry in os.scandir(directory):
            entry_stem, entry_extension = os.path.splitext(entry.name)
            if (
                    entry.is_file()
                    and entry_extension.casefold() == extension.casefold()
                    and entry_stem.casefold().startswith(f"{stem} (".casefold())
                    and entry_stem.endswith(")")
                    and entry_stem[len(stem) + 2:-1].isdigit()
                    and acceptable(entry.path)):
                matches.append(entry.path)
    except OSError:
        return None
    return matches[0] if len(matches) == 1 else None


def recover_interrupted_downloads():
    """Make downloads interrupted by a process exit resumable on next launch."""
    with _file_lock:
        items = load_queue()
        recovered = 0
        for item in items:
            if item.get("status") == "downloading":
                item.update(status="pending", speed_bps=0.0, eta_seconds=None,
                            error="Resuming after ODeR was closed")
                recovered += 1
        if recovered:
            save_queue(items)
        return recovered
