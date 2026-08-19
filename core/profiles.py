"""Manage site "profiles" — one per directory-listing site the user tracks."""
import json
import os
import threading
import uuid

from core.paths import profiles_index_path, profile_dir, profile_cache_path

_lock = threading.Lock()

DEFAULT_SETTINGS = {
    "crawl_delay_seconds": 0.25,
    "crawl_concurrency": 8,
    "crawl_retry_on_block_seconds": 60,
    "max_crawl_retries": 3,
    "download_delay_seconds": 2.0,
    "max_concurrent_downloads": 1,
    "request_timeout_seconds": 20,
    "user_agent": "Mozilla/5.0 (offline-directory-browser)",
    "auto_detect_index": True,
}


def load_profiles():
    p = profiles_index_path()
    if not os.path.exists(p):
        return []
    with _lock:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)


def save_profiles(profiles):
    p = profiles_index_path()
    with _lock:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2)
        os.replace(tmp, p)


def get_profile(profile_id):
    for p in load_profiles():
        if p["id"] == profile_id:
            return p
    return None


def create_profile(name, base_url):
    if not base_url.endswith("/"):
        base_url += "/"
    profiles = load_profiles()
    profile = {
        "id": uuid.uuid4().hex[:12],
        "name": name.strip() or base_url,
        "base_url": base_url,
        "settings": dict(DEFAULT_SETTINGS),
        "index_source": None,
        "last_crawled": None,
        "folders_cached": 0,
        "last_crawl_stats": None,
        "crawl_history": [],
    }
    profiles.append(profile)
    save_profiles(profiles)
    profile_dir(profile["id"])  # ensure folder exists
    return profile


def update_profile(profile_id, **fields):
    profiles = load_profiles()
    updated = None
    for p in profiles:
        if p["id"] == profile_id:
            if "settings" in fields:
                p["settings"].update(fields.pop("settings"))
            p.update(fields)
            updated = p
            break
    if updated is not None:
        save_profiles(profiles)
    return updated


def delete_profile(profile_id, delete_files=False):
    profiles = load_profiles()
    profiles = [p for p in profiles if p["id"] != profile_id]
    save_profiles(profiles)
    if delete_files:
        import shutil
        d = profile_dir(profile_id)
        shutil.rmtree(d, ignore_errors=True)


def load_profile_cache(profile_id):
    p = profile_cache_path(profile_id)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_profile_cache(profile_id, tree):
    p = profile_cache_path(profile_id)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tree, f, indent=2)
    os.replace(tmp, p)
