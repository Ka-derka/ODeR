"""Manage site "profiles" — one per directory-listing site the user tracks."""
import os
import threading
import uuid

from core.paths import profiles_index_path, profile_dir, profile_cache_path
from core.persistence import load_json, save_json

_lock = threading.RLock()

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
    "hosted_oder_url": "",
}


def _normalize_profiles(values):
    normalized = []
    for value in values:
        if not isinstance(value, dict) or not value.get("id") or not value.get("base_url"):
            continue
        profile = dict(value)
        settings = dict(DEFAULT_SETTINGS)
        if isinstance(value.get("settings"), dict):
            settings.update(value["settings"])
        profile["settings"] = settings
        profile.setdefault("index_source", None)
        profile.setdefault("hosted_index", None)
        profile.setdefault("last_crawled", None)
        profile.setdefault("folders_cached", 0)
        profile.setdefault("last_crawl_stats", None)
        profile.setdefault("crawl_history", [])
        normalized.append(profile)
    return normalized


def _load_profiles_unlocked():
    p = profiles_index_path()
    return _normalize_profiles(load_json(p, [], list))


def _save_profiles_unlocked(profiles):
    save_json(profiles_index_path(), profiles)


def load_profiles():
    with _lock:
        return _load_profiles_unlocked()


def save_profiles(profiles):
    with _lock:
        _save_profiles_unlocked(profiles)


def get_profile(profile_id):
    with _lock:
        for p in _load_profiles_unlocked():
            if p["id"] == profile_id:
                return p
    return None


def create_profile(name, base_url):
    if not base_url.endswith("/"):
        base_url += "/"
    with _lock:
        profiles = _load_profiles_unlocked()
        profile = {
            "id": uuid.uuid4().hex[:12],
            "name": name.strip() or base_url,
            "base_url": base_url,
            "settings": dict(DEFAULT_SETTINGS),
            "index_source": None,
            "hosted_index": None,
            "last_crawled": None,
            "folders_cached": 0,
            "last_crawl_stats": None,
            "crawl_history": [],
        }
        profiles.append(profile)
        _save_profiles_unlocked(profiles)
    profile_dir(profile["id"])  # ensure folder exists
    return profile


def update_profile(profile_id, **fields):
    with _lock:
        profiles = _load_profiles_unlocked()
        updated = None
        changes = dict(fields)
        for p in profiles:
            if p["id"] == profile_id:
                settings = changes.pop("settings", None)
                if isinstance(settings, dict):
                    p["settings"].update(settings)
                p.update(changes)
                updated = p
                break
        if updated is not None:
            _save_profiles_unlocked(profiles)
        return updated


def delete_profile(profile_id, delete_files=False):
    with _lock:
        profiles = [p for p in _load_profiles_unlocked() if p["id"] != profile_id]
        _save_profiles_unlocked(profiles)
    if delete_files:
        import shutil
        d = profile_dir(profile_id)
        shutil.rmtree(d, ignore_errors=True)


def load_profile_cache(profile_id):
    p = profile_cache_path(profile_id)
    return load_json(p, None, dict) if os.path.exists(p) else None


def save_profile_cache(profile_id, tree):
    save_json(profile_cache_path(profile_id), tree)
