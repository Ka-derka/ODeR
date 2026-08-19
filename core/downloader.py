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
    return {
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


def enqueue_many(profile_id, profile_name, entries, group_id=None, group_name=None):
    """Queue a batch with one read/write and deterministic collision-free paths."""
    with _file_lock:
        items = load_queue()
        active = {
            (item.get("profile_id"), item.get("url")): item
            for item in items
            if item.get("status") in {"pending", "downloading", "paused"}
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
        applog.log(f"removed from queue: {removed['name']} ({removed['profile_name']})")


def retry_item(item_id):
    with _file_lock:
        items = load_queue()
        for it in items:
            if it["id"] == item_id:
                it["status"] = "pending"
                it["error"] = None
                applog.log(f"retrying: {it['name']} ({it['profile_name']})")
        save_queue(items)


def pause_item(item_id):
    update_item(item_id, status="paused")


def resume_item(item_id):
    update_item(item_id, status="pending")


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
    return _update_group(group_id, {"pending", "downloading"}, status="paused")


def resume_group(group_id):
    return _update_group(group_id, {"paused"}, status="pending")


def retry_group(group_id):
    return _update_group(group_id, {"error"}, status="pending", error=None)


def remove_group(group_id):
    with _file_lock:
        items = load_queue()
        kept = [item for item in items if item.get("group_id") != group_id]
        removed = len(items) - len(kept)
        if removed:
            save_queue(kept)
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
        kept = [item for item in items if item.get("status") != "done"]
        removed = len(items) - len(kept)
        if removed:
            save_queue(kept)
        return removed


def summarize_group_items(items):
    """Summarize an already-loaded group without rereading queue.json."""
    total = sum(int(item.get("bytes_total") or 0) for item in items)
    done = sum(int(item.get("bytes_done") or 0) for item in items)
    speed = sum(float(item.get("speed_bps") or 0) for item in items if item.get("status") == "downloading")
    active = sum(1 for item in items if item.get("status") in {"pending", "downloading", "paused"})
    failed = sum(1 for item in items if item.get("status") == "error")
    completed = sum(1 for item in items if item.get("status") == "done")
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
    global _dispatcher_thread
    _stop_all.clear()
    if _dispatcher_thread is None or not _dispatcher_thread.is_alive():
        recovered = recover_interrupted_downloads()
        if recovered:
            log(f"resuming {recovered} download{'s' if recovered != 1 else ''} interrupted by the previous exit")
        _dispatcher_thread = threading.Thread(target=_dispatcher, args=(log,), daemon=True)
        _dispatcher_thread.start()
    return _dispatcher_thread


def stop_background_worker():
    _stop_all.set()


def destination_preview(profile_name, rel_path, name):
    """Return the path a queued download would use, without creating folders."""
    return _dest_path({
        "profile_name": profile_name,
        "rel_path": rel_path,
        "name": name,
        "destination_rel_path": destination_relative_path(profile_name, rel_path, name),
    })


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
