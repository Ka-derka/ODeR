"""Privacy-conscious support diagnostics for ODeR installations."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import platform
import sqlite3
import sys
import uuid
import zipfile

from core import applog, cache, downloader, profiles, settings
from core.paths import (
    data_dir, favorites_path, is_portable, package_history_path,
    profile_crawl_state_path,
)
from core.version import APP_NAME, APP_VERSION


REPORT_FORMAT = "oder-diagnostics"
REPORT_VERSION = 1


def suggested_filename():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"ODeR-Diagnostics-{stamp}.zip"


def _runtime_edition():
    if not getattr(sys, "frozen", False):
        return "development"
    return "portable" if is_portable() else "installed"


def _state_file(path):
    result = {
        "file": os.path.basename(path),
        "exists": os.path.isfile(path),
        "backup_exists": os.path.isfile(path + ".bak"),
        "bytes": os.path.getsize(path) if os.path.isfile(path) else 0,
    }
    if not result["exists"]:
        return result
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        if isinstance(value, dict) and value.get("format") == "oder-state":
            result.update(
                format=value.get("format"),
                kind=value.get("kind"),
                schema_version=value.get("schema_version"),
                written_by=value.get("written_by"),
            )
        else:
            result["format"] = "legacy"
    except Exception as exc:
        result.update(format="unreadable", error=exc.__class__.__name__)
    return result


def _cache_report(profile_id):
    path = cache.profile_cache_db_path(profile_id)
    checkpoint = cache.profile_cache_checkpoint_path(profile_id)
    result = {
        "exists": os.path.isfile(path),
        "bytes": os.path.getsize(path) if os.path.isfile(path) else 0,
        "wal_bytes": os.path.getsize(path + "-wal") if os.path.isfile(path + "-wal") else 0,
        "checkpoint_pending": os.path.isfile(checkpoint),
    }
    if not result["exists"]:
        result["health"] = "missing"
        return result
    connection = None
    try:
        uri = "file:" + os.path.abspath(path).replace("\\", "/") + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        result["schema_version"] = int(connection.execute("PRAGMA user_version").fetchone()[0])
        quick_check = str(connection.execute("PRAGMA quick_check(1)").fetchone()[0])
        result["health"] = quick_check
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "nodes" in tables:
            counts = connection.execute(
                "SELECT COUNT(*) entries, "
                "SUM(CASE WHEN is_dir=1 THEN 1 ELSE 0 END) folders, "
                "SUM(CASE WHEN is_dir=0 THEN 1 ELSE 0 END) files, "
                "SUM(CASE WHEN is_dir=1 AND crawled=0 THEN 1 ELSE 0 END) pending "
                "FROM nodes"
            ).fetchone()
            result.update(
                entries=int(counts["entries"] or 0),
                folders=int(counts["folders"] or 0),
                files=int(counts["files"] or 0),
                pending_folders=int(counts["pending"] or 0),
            )
        if "scan_runs" in tables:
            result["snapshots"] = int(
                connection.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0]
            )
        if "meta" in tables:
            fts = connection.execute(
                "SELECT value FROM meta WHERE key='fts_available'"
            ).fetchone()
            result["full_text_search"] = bool(fts and fts[0] == "1")
    except Exception as exc:
        result.update(health="error", error=f"{exc.__class__.__name__}: {exc}")
    finally:
        if connection is not None:
            connection.close()
    return result


def collect_report():
    saved_settings = settings.load_settings()
    saved_profiles = profiles.load_profiles()
    queue = downloader.load_queue()
    status_counts = {}
    for item in queue:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    state_files = [
        _state_file(settings.settings_path()),
        _state_file(profiles.profiles_index_path()),
        _state_file(downloader.queue_path()),
        _state_file(favorites_path()),
        _state_file(package_history_path()),
    ]
    directory_reports = []
    for number, profile in enumerate(saved_profiles, 1):
        directory_reports.append({
            "directory": number,
            "cache": _cache_report(profile["id"]),
            "crawl_state": _state_file(profile_crawl_state_path(profile["id"])),
        })

    return {
        "format": REPORT_FORMAT,
        "format_version": REPORT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "application": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "edition": _runtime_edition(),
        },
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "data_directory": data_dir(),
        },
        "preferences": {
            "theme": saved_settings.get("theme"),
            "download_concurrency": saved_settings.get("download_concurrency"),
            "network_max_connections": saved_settings.get("network_max_connections"),
            "request_timeout_seconds": saved_settings.get("request_timeout_seconds"),
            "browser_page_size": saved_settings.get("browser_page_size"),
            "update_channel": saved_settings.get("update_channel"),
            "last_update_error": saved_settings.get("last_update_error"),
        },
        "state_files": state_files,
        "downloads": {
            "items": len(queue),
            "status_counts": status_counts,
            "structured_paths": sum(
                bool(item.get("destination_rel_path")) for item in queue
            ),
        },
        "directories": directory_reports,
        "privacy": {
            "directory_names_included": False,
            "directory_urls_included": False,
            "download_names_included": False,
            "cache_contents_included": False,
        },
    }


def export_report(destination, include_logs=False):
    destination = os.path.abspath(destination)
    if not destination.lower().endswith(".zip"):
        destination += ".zip"
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temporary = destination + f".tmp-{uuid.uuid4().hex}"
    report = collect_report()
    readme = (
        "ODeR diagnostics package\n\n"
        "diagnostics.json contains application/runtime versions, state schema metadata, "
        "anonymous cache counts and SQLite health results. It does not include directory "
        "names or URLs, download names, settings contents, cached listings, or downloaded files.\n"
    )
    if include_logs:
        readme += (
            "\nrecent-log.txt was included at the user's request. Log messages can contain "
            "directory URLs and file names; review it before sharing this package.\n"
        )
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            archive.writestr(
                "diagnostics.json",
                json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            )
            archive.writestr("README.txt", readme)
            if include_logs:
                lines = [line for _sequence, line in applog.get_all_lines()[-2000:]]
                archive.writestr("recent-log.txt", "\n".join(lines) + ("\n" if lines else ""))
        os.replace(temporary, destination)
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass
    applog.log(f"diagnostics exported: {destination}")
    return destination
