"""Small, independent workspace preferences for ODeR Creator."""
from __future__ import annotations

import os

from core import paths
from core.persistence import load_json, save_json


MAX_RECENT_PROJECTS = 12


def _state_path() -> str:
    return os.path.join(paths.data_dir(), "creator", "recent-projects.json")


def _normal_path(value) -> str | None:
    try:
        value = os.fspath(value)
        if not isinstance(value, str) or not value or "\0" in value:
            return None
        return os.path.normpath(os.path.abspath(os.path.expanduser(value)))
    except (TypeError, ValueError, OSError):
        return None


def _unique_paths(values) -> list[str]:
    result = []
    seen = set()
    for value in values:
        path = _normal_path(value)
        if path is None:
            continue
        key = os.path.normcase(path)
        if key not in seen:
            result.append(path)
            seen.add(key)
        if len(result) >= MAX_RECENT_PROJECTS:
            break
    return result


def recent_projects() -> list[str]:
    """Return newest-first paths, retaining temporarily unavailable projects."""
    try:
        state = load_json(_state_path(), {}, expected_type=dict)
    except OSError:
        return []
    values = state.get("projects", [])
    return _unique_paths(values) if isinstance(values, list) else []


def record_recent(path) -> bool:
    """Remember a successfully opened/saved project without failing that action.

    Recent history is a convenience: a read-only preferences directory must not
    turn a successful project save into an apparent failure.
    """
    normalized = _normal_path(path)
    if normalized is None:
        return False
    try:
        save_json(_state_path(), {
            "version": 1,
            "projects": _unique_paths([normalized, *recent_projects()]),
        })
    except OSError:
        return False
    return True
