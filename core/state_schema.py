"""Versioned envelopes and migrations for ODeR's small JSON state files."""
from __future__ import annotations

from copy import deepcopy
import os
import threading

from core.persistence import load_json, save_json
from core.version import APP_VERSION


STATE_FORMAT = "oder-state"
SCHEMA_VERSIONS = {
    "settings": 1,
    "profiles": 1,
    "download-queue": 2,
    "favorites": 1,
    "package-history": 1,
    "crawl-state": 1,
}


class StateSchemaError(RuntimeError):
    """A state file cannot be migrated or safely interpreted."""


class StateVersionError(StateSchemaError):
    """A state file was written by a newer incompatible ODeR version."""


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _lock(path):
    absolute = os.path.abspath(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(absolute, threading.RLock())


def _valid_shape(value, kind, payload_type):
    if isinstance(value, payload_type) and not (
        isinstance(value, dict) and value.get("format") == STATE_FORMAT
    ):
        return True
    return (
        isinstance(value, dict)
        and value.get("format") == STATE_FORMAT
        and value.get("kind") == kind
        and isinstance(value.get("schema_version"), int)
        and isinstance(value.get("data"), payload_type)
    )


def _identity(value):
    return value


def _legacy_download_component(value, fallback="item"):
    value = "".join(c for c in str(value or "") if c not in '<>:"/\\|?*')
    value = value.strip().rstrip(" .")
    return value or fallback


def _migrate_download_queue_v1(value):
    """Pin existing queue items to the exact pre-0.21 destination layout."""
    migrated = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            migrated.append(raw)
            continue
        item = dict(raw)
        if not item.get("destination_rel_path"):
            parts = [_legacy_download_component(item.get("profile_name"), "profile")]
            for component in str(item.get("rel_path") or "").replace("\\", "/").split("/"):
                safe = _legacy_download_component(component, "")
                if safe and safe not in {".", ".."}:
                    parts.append(safe)
            parts.append(_legacy_download_component(item.get("name"), "item"))
            item["destination_rel_path"] = "/".join(parts)
        migrated.append(item)
    return migrated


MIGRATIONS = {
    (kind, 0): _identity for kind in SCHEMA_VERSIONS
}
MIGRATIONS[("download-queue", 1)] = _migrate_download_queue_v1


def _migrate(kind, version, value):
    current = SCHEMA_VERSIONS[kind]
    while version < current:
        migration = MIGRATIONS.get((kind, version))
        if migration is None:
            raise StateSchemaError(
                f"No migration is available for {kind} schema {version} to {version + 1}."
            )
        value = migration(value)
        version += 1
    return value, version


def _envelope(kind, value):
    return {
        "format": STATE_FORMAT,
        "kind": kind,
        "schema_version": SCHEMA_VERSIONS[kind],
        "written_by": APP_VERSION,
        "data": value,
    }


def load_document(path, kind, default, payload_type):
    """Load and, when necessary, migrate a state document atomically."""
    if kind not in SCHEMA_VERSIONS:
        raise ValueError(f"Unknown state document kind: {kind}")
    with _lock(path):
        existed = os.path.exists(path) or os.path.exists(path + ".bak")
        raw = load_json(
            path,
            deepcopy(default),
            validator=lambda value: _valid_shape(value, kind, payload_type),
        )
        if raw is None and default is None:
            return None
        if isinstance(raw, dict) and raw.get("format") == STATE_FORMAT:
            version = raw["schema_version"]
            current = SCHEMA_VERSIONS[kind]
            if version > current:
                raise StateVersionError(
                    f"{os.path.basename(path)} uses {kind} schema {version}, but this ODeR "
                    f"version supports up to schema {current}. Update ODeR before continuing."
                )
            value = raw["data"]
        else:
            version = 0
            value = raw

        migrated, final_version = _migrate(kind, version, deepcopy(value))
        if not isinstance(migrated, payload_type):
            raise StateSchemaError(f"The migrated {kind} document has an invalid data type.")
        if existed and (version == 0 or final_version != version):
            save_json(path, _envelope(kind, migrated))
        return migrated


def save_document(path, kind, value, payload_type, *, backup=True):
    """Save a state document using its current schema envelope."""
    if kind not in SCHEMA_VERSIONS:
        raise ValueError(f"Unknown state document kind: {kind}")
    if not isinstance(value, payload_type):
        raise TypeError(f"{kind} data must be {payload_type.__name__}")
    with _lock(path):
        # Refuse to overwrite a future document even if a caller attempts to
        # save without explicitly loading it first.
        if os.path.exists(path):
            raw = load_json(path, deepcopy(value))
            if isinstance(raw, dict) and raw.get("format") == STATE_FORMAT:
                version = raw.get("schema_version")
                if isinstance(version, int) and version > SCHEMA_VERSIONS[kind]:
                    raise StateVersionError(
                        f"Refusing to overwrite newer {kind} schema {version}."
                    )
        save_json(path, _envelope(kind, value), backup=backup)
