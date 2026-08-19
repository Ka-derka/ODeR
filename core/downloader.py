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
import json
import time
import threading
import uuid
import requests
from datetime import datetime, timezone

from core.paths import queue_path, downloads_dir
from core.settings import load_settings, downloads_root
from core.profiles import get_profile
from core import applog

_file_lock = threading.Lock()
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
    p = queue_path()
    if not os.path.exists(p):
        return []
    with _file_lock:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)


def save_queue(items):
    with _file_lock:
        p = queue_path()
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
        os.replace(tmp, p)


def new_group(name):
    return {"id": uuid.uuid4().hex[:12], "name": str(name or "Download group")}


def enqueue(profile_id, profile_name, url, name, rel_path, group_id=None, group_name=None):
    items = load_queue()
    for existing in items:
        if existing.get("profile_id") == profile_id and existing.get("url") == url and existing.get("status") in {"pending", "downloading", "paused"}:
            return existing
    item = {
        "id": uuid.uuid4().hex[:12],
        "profile_id": profile_id,
        "profile_name": profile_name,
        "url": url,
        "name": name,
        "rel_path": rel_path,
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
    items.append(item)
    save_queue(items)
    applog.log(f"queued: {name} ({profile_name})")
    return item


def update_item(item_id, **fields):
    items = load_queue()
    for it in items:
        if it["id"] == item_id:
            it.update(fields)
            break
    save_queue(items)


def remove_item(item_id):
    items = load_queue()
    removed = next((it for it in items if it["id"] == item_id), None)
    items = [it for it in items if it["id"] != item_id]
    save_queue(items)
    if removed:
        applog.log(f"removed from queue: {removed['name']} ({removed['profile_name']})")


def retry_item(item_id):
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


def pause_group(group_id):
    for item in items_in_group(group_id):
        if item.get("status") in {"pending", "downloading"}:
            pause_item(item["id"])


def resume_group(group_id):
    for item in items_in_group(group_id):
        if item.get("status") == "paused":
            resume_item(item["id"])


def retry_group(group_id):
    for item in items_in_group(group_id):
        if item.get("status") == "error":
            retry_item(item["id"])


def remove_group(group_id):
    for item in list(items_in_group(group_id)):
        remove_item(item["id"])


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


def _safe_component(value, fallback="item"):
    value = str(value or "")
    value = "".join(c for c in value if c not in '<>:"/\\|?*')
    value = value.strip().rstrip(" .")
    return value or fallback


def _safe_relative_path(rel_path):
    parts = []
    for raw in str(rel_path or "").replace("\\", "/").split("/"):
        part = _safe_component(raw, "")
        if part and part not in (".", ".."):
            parts.append(part)
    return parts


def _dest_path(profile_name, rel_path, name):
    global_dir = (load_settings().get("download_dir") or "").strip()
    folder = os.path.abspath(global_dir) if global_dir else downloads_dir(profile_name)
    if global_dir:
        folder = os.path.join(folder, _safe_component(profile_name, "profile"))
    safe_parts = _safe_relative_path(rel_path)
    if safe_parts:
        folder = os.path.join(folder, *safe_parts)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, _safe_component(name))


def destination_path(item):
    return _dest_path(item.get("profile_name", "profile"), item.get("rel_path", ""), item.get("name", "item"))


def _download_one(item, settings, log):
    dest = _dest_path(item["profile_name"], item["rel_path"], item["name"])
    part = dest + ".part"
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
        _dispatcher_thread = threading.Thread(target=_dispatcher, args=(log,), daemon=True)
        _dispatcher_thread.start()
    return _dispatcher_thread


def stop_background_worker():
    _stop_all.set()


def destination_preview(profile_name, rel_path, name):
    """Return the path a queued download would use, without creating folders."""
    base = os.path.join(downloads_dir(profile_name), *(_safe_relative_path(rel_path)))
    return os.path.join(base, _safe_component(name))
