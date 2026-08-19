"""Favorites, saved searches, and recent package activity."""
import os
import threading
import uuid
from datetime import datetime, timezone

from core.paths import favorites_path, package_history_path
from core.persistence import load_json, save_json


_lock = threading.RLock()


def _load(path):
    with _lock:
        return load_json(path, [], list)


def _save(path, values):
    with _lock:
        save_json(path, values)


def favorites():
    return _load(favorites_path())


def add_folder(profile_id, url, label):
    with _lock:
        values = favorites()
        existing = next((item for item in values if item.get("kind") == "folder" and
                         item.get("profile_id") == profile_id and item.get("url") == url), None)
        if existing:
            return existing
        item = {"id": uuid.uuid4().hex[:12], "kind": "folder", "profile_id": profile_id,
                "url": url, "label": label, "created_at": datetime.now(timezone.utc).isoformat()}
        values.insert(0, item)
        _save(favorites_path(), values[:500])
        return item


def add_search(query, label, profile_id=None, filters=None):
    with _lock:
        values = favorites()
        item = {"id": uuid.uuid4().hex[:12], "kind": "search", "profile_id": profile_id,
                "query": query, "label": label or query, "filters": filters or {},
                "created_at": datetime.now(timezone.utc).isoformat()}
        values.insert(0, item)
        _save(favorites_path(), values[:500])
        return item


def remove_favorite(item_id):
    with _lock:
        values = [item for item in favorites() if item.get("id") != item_id]
        _save(favorites_path(), values)


def record_package(action, path, **details):
    with _lock:
        values = _load(package_history_path())
        item = {"id": uuid.uuid4().hex[:12], "action": action,
                "path": os.path.abspath(path), "timestamp": datetime.now(timezone.utc).isoformat()}
        item.update(details)
        values.insert(0, item)
        _save(package_history_path(), values[:100])
        return item


def recent_packages(limit=20):
    return _load(package_history_path())[:max(0, int(limit))]
