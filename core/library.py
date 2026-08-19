"""Favorites, saved searches, and recent package activity."""
import json
import os
import uuid
from datetime import datetime, timezone

from core.paths import favorites_path, package_history_path


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def _save(path, values):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(values, handle, indent=2)
    os.replace(temp, path)


def favorites():
    return _load(favorites_path())


def add_folder(profile_id, url, label):
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
    values = favorites()
    item = {"id": uuid.uuid4().hex[:12], "kind": "search", "profile_id": profile_id,
            "query": query, "label": label or query, "filters": filters or {},
            "created_at": datetime.now(timezone.utc).isoformat()}
    values.insert(0, item)
    _save(favorites_path(), values[:500])
    return item


def remove_favorite(item_id):
    values = [item for item in favorites() if item.get("id") != item_id]
    _save(favorites_path(), values)


def record_package(action, path, **details):
    values = _load(package_history_path())
    item = {"id": uuid.uuid4().hex[:12], "action": action,
            "path": os.path.abspath(path), "timestamp": datetime.now(timezone.utc).isoformat()}
    item.update(details)
    values.insert(0, item)
    _save(package_history_path(), values[:100])
    return item


def recent_packages(limit=20):
    return _load(package_history_path())[:max(0, int(limit))]
