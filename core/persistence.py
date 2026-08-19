"""Crash-safe JSON persistence with a last-known-good backup.

Small JSON files hold ODeR's settings, profiles, queue, favorites, and crawl
state.  They are important enough that a truncated write must not prevent the
application from starting.  This module keeps writes atomic, flushes them to
disk, and restores a valid ``.bak`` copy when the primary file is damaged.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import shutil
import threading


def _temporary_path(path: str, label: str = "tmp") -> str:
    return f"{path}.{os.getpid()}.{threading.get_ident()}.{label}"


def _read_json(path: str, expected_type=None, validator=None):
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if expected_type is not None and not isinstance(value, expected_type):
        raise ValueError(f"expected {expected_type.__name__} JSON")
    if validator is not None and not validator(value):
        raise ValueError("JSON structure validation failed")
    return value


def _flush_copy(source: str, destination: str) -> None:
    temporary = _temporary_path(destination, "copy")
    try:
        with open(source, "rb") as source_handle, open(temporary, "wb") as target:
            shutil.copyfileobj(source_handle, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass


def _quarantine(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    candidate = f"{path}.corrupt-{stamp}"
    counter = 1
    while os.path.exists(candidate):
        candidate = f"{path}.corrupt-{stamp}-{counter}"
        counter += 1
    try:
        os.replace(path, candidate)
        return candidate
    except OSError:
        return None


def _log_recovery(message: str) -> None:
    try:
        from core import applog
        applog.log(message)
    except Exception:
        pass


def load_json(path: str, default, expected_type=None, validator=None):
    """Load JSON, restoring a valid backup when the primary is unreadable."""
    if not os.path.exists(path):
        backup = path + ".bak"
        try:
            recovered = _read_json(backup, expected_type, validator)
        except (OSError, UnicodeError, ValueError, TypeError):
            return deepcopy(default)
        try:
            _flush_copy(backup, path)
            _log_recovery(f"Restored missing {os.path.basename(path)} from its last-known-good backup.")
        except OSError as exc:
            _log_recovery(f"Using backup data for missing {os.path.basename(path)}; restoring it failed: {exc}")
        return recovered
    try:
        return _read_json(path, expected_type, validator)
    except (OSError, UnicodeError, ValueError, TypeError):
        backup = path + ".bak"
        try:
            recovered = _read_json(backup, expected_type, validator)
        except (OSError, UnicodeError, ValueError, TypeError):
            quarantined = _quarantine(path)
            if quarantined:
                _log_recovery(
                    f"Damaged state file was preserved as {os.path.basename(quarantined)}; "
                    "ODeR continued with safe defaults."
                )
            return deepcopy(default)

        quarantined = _quarantine(path)
        try:
            _flush_copy(backup, path)
            detail = f"; damaged copy saved as {os.path.basename(quarantined)}" if quarantined else ""
            _log_recovery(f"Recovered {os.path.basename(path)} from its last-known-good backup{detail}.")
        except OSError as exc:
            _log_recovery(f"Using backup data for {os.path.basename(path)}; restoring the file failed: {exc}")
        return recovered


def save_json(path: str, value, *, indent: int = 2, backup: bool = True) -> None:
    """Atomically save JSON and retain the previous valid value as ``.bak``."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = _temporary_path(path)
    backup_path = path + ".bak"
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=indent, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        if backup and os.path.exists(path):
            try:
                _read_json(path)
            except (OSError, UnicodeError, ValueError, TypeError):
                _quarantine(path)
            else:
                _flush_copy(path, backup_path)

        os.replace(temporary, path)
        if not os.path.exists(backup_path):
            _flush_copy(path, backup_path)
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass
