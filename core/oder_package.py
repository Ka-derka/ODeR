"""Versioned import/export support for user-facing ``.oder`` packages.

An ODeR package is a ZIP container with a deliberately small, strict layout:

``manifest.json``
    Format/version metadata, content hashes and cache statistics.
``profile.json``
    The portable directory definition and (for full exports) crawl state.
``cache.sqlite3``
    Optional consistent snapshot of the cached directory index.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from urllib.parse import urlsplit, urlunsplit
from urllib.parse import unquote

from core import cache
from core.paths import data_dir, profile_cache_db_path, profile_dir
from core.library_metadata import LibraryMetadataError, normalize_library_metadata
from core.profiles import DEFAULT_SETTINGS, load_profiles, save_profiles
from core.version import APP_NAME, APP_VERSION
from core import library


FORMAT_ID = "oder-directory"
FORMAT_VERSION = 1
PROFILE_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
PROFILE_NAME = "profile.json"
CACHE_NAME = "cache.sqlite3"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_CACHE_BYTES = 8 * 1024 * 1024 * 1024
_ALLOWED_MEMBERS = {MANIFEST_NAME, PROFILE_NAME, CACHE_NAME}
_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class PackageError(ValueError):
    """The selected file is not a safe, supported ODeR package."""


class PackageConflictError(PackageError):
    """The import requires an explicit conflict policy."""


@dataclass(frozen=True)
class PackageInfo:
    path: str
    package_type: str
    created_at: str
    app_version: str
    name: str
    base_url: str
    source_profile_id: str | None
    has_cache: bool
    cache_entries: int
    cache_folders: int
    cache_files: int
    cache_size: int
    profile: dict
    scope: str = "directory"


@dataclass(frozen=True)
class ImportResult:
    profile: dict
    replaced: bool
    cache_imported: bool


@dataclass(frozen=True)
class PackageComparison:
    left: PackageInfo
    right: PackageInfo
    definition_differences: tuple[str, ...]
    new_count: int
    removed_count: int
    changed_count: int
    changes: tuple[dict, ...]


def _canonical_base_url(value: str) -> str:
    value = str(value or "").strip()
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise PackageError("The package profile does not contain a valid HTTP or HTTPS base URL.")
    path = parts.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, parts.query, ""))


def _json_bytes(value) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_json_copy(value, default):
    try:
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
            return default
        return json.loads(encoded)
    except (TypeError, ValueError):
        return default


def _profile_payload(profile: dict, include_cache: bool, root_url: str | None = None) -> dict:
    settings = _safe_json_copy(profile.get("settings") or {}, {})
    export_base = _canonical_base_url(root_url or profile.get("base_url", ""))
    export_name = str(profile.get("name") or "").strip()
    source_id = str(profile.get("id") or "") or None
    if root_url:
        leaf = unquote(urlsplit(export_base).path.rstrip("/").rsplit("/", 1)[-1]) or "subtree"
        export_name = f"{export_name} — {leaf}"
        source_id = None
    payload = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "source_profile_id": source_id,
        "name": export_name,
        "base_url": export_base,
        "settings": settings,
    }
    metadata = normalize_library_metadata(profile.get("metadata"))
    if metadata:
        payload["metadata"] = metadata
    if root_url:
        payload["source_directory"] = {
            "profile_id": str(profile.get("id") or ""),
            "name": str(profile.get("name") or ""),
            "base_url": _canonical_base_url(profile.get("base_url", "")),
            "root_url": export_base,
        }
    if include_cache:
        payload["cache_state"] = {
            "index_source": _safe_json_copy(profile.get("index_source"), None),
            "last_crawled": _safe_json_copy(profile.get("last_crawled"), None),
            "folders_cached": int(profile.get("folders_cached") or 0),
            "last_crawl_stats": _safe_json_copy(profile.get("last_crawl_stats"), None),
            "crawl_history": _safe_json_copy(profile.get("crawl_history") or [], []),
        }
    return payload


def _validate_profile_payload(value) -> dict:
    if not isinstance(value, dict) or value.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise PackageError("The directory definition uses an unsupported schema version.")
    name = str(value.get("name") or "").strip()
    if not name or len(name) > 200:
        raise PackageError("The package profile name is missing or too long.")
    base_url = _canonical_base_url(value.get("base_url", ""))
    source_id = value.get("source_profile_id")
    if source_id is not None:
        source_id = str(source_id)
        if not _PROFILE_ID_RE.fullmatch(source_id):
            raise PackageError("The package contains an invalid source profile identifier.")
    settings = value.get("settings") or {}
    if not isinstance(settings, dict) or len(_json_bytes(settings)) > MAX_JSON_BYTES:
        raise PackageError("The package profile settings are invalid or too large.")
    metadata = None
    if "metadata" in value:
        try:
            metadata = normalize_library_metadata(value.get("metadata"), strict=True)
        except LibraryMetadataError as exc:
            raise PackageError(str(exc)) from exc
    state = value.get("cache_state")
    if state is not None:
        if not isinstance(state, dict):
            raise PackageError("The package cache state is invalid.")
        try:
            folders_cached = int(state.get("folders_cached") or 0)
        except (TypeError, ValueError) as exc:
            raise PackageError("The package cached-folder count is invalid.") from exc
        history = state.get("crawl_history") or []
        if folders_cached < 0 or folders_cached > 10_000_000_000 or not isinstance(history, list) or len(history) > 10_000:
            raise PackageError("The package cache state contains invalid counts or history.")
        state = {
            "index_source": _safe_json_copy(state.get("index_source"), None),
            "last_crawled": _safe_json_copy(state.get("last_crawled"), None),
            "folders_cached": folders_cached,
            "last_crawl_stats": _safe_json_copy(state.get("last_crawl_stats"), None),
            "crawl_history": _safe_json_copy(history, []),
        }
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "source_profile_id": source_id,
        "name": name,
        "base_url": base_url,
        "settings": _safe_json_copy(settings, {}),
        "metadata": _safe_json_copy(metadata, None),
        "cache_state": _safe_json_copy(state, None),
    }


def _validate_cache_file(path: str, expected_base_url: str) -> dict:
    try:
        with open(path, "rb") as handle:
            if handle.read(16) != b"SQLite format 3\x00":
                raise PackageError("The cached index is not a SQLite database.")
        uri = "file:" + os.path.abspath(path).replace("\\", "/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            check = conn.execute("PRAGMA quick_check(1)").fetchone()
            if not check or str(check[0]).lower() != "ok":
                raise PackageError("The cached index failed SQLite's integrity check.")
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"meta", "nodes"}.issubset(tables):
                raise PackageError("The cached index does not contain the required ODeR tables.")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(nodes)")}
            required = {"url", "name", "is_dir", "size", "parent_url", "crawled"}
            if not required.issubset(columns):
                raise PackageError("The cached index uses an unsupported nodes schema.")
            row = conn.execute("SELECT value FROM meta WHERE key='base_url'").fetchone()
            db_base = _canonical_base_url(row[0]) if row else None
            if db_base != expected_base_url:
                raise PackageError("The cached index belongs to a different base URL than the profile.")
            counts = conn.execute(
                "SELECT COUNT(*) AS entries, "
                "SUM(CASE WHEN is_dir=1 THEN 1 ELSE 0 END) AS folders, "
                "SUM(CASE WHEN is_dir=0 THEN 1 ELSE 0 END) AS files FROM nodes"
            ).fetchone()
            return {
                "entries": int(counts["entries"] or 0),
                "folders": int(counts["folders"] or 0),
                "files": int(counts["files"] or 0),
            }
        finally:
            conn.close()
    except PackageError:
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise PackageError(f"The cached index could not be validated: {exc}") from exc


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, maximum: int) -> bytes:
    if info.file_size > maximum:
        raise PackageError(f"{info.filename} is larger than this format allows.")
    with archive.open(info, "r") as source:
        data = source.read(maximum + 1)
    if len(data) > maximum:
        raise PackageError(f"{info.filename} is larger than this format allows.")
    return data


def _extract_cache(archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: str, expected_hash: str) -> None:
    if info.file_size > MAX_CACHE_BYTES:
        raise PackageError("The cached index is larger than this ODeR version allows.")
    digest = hashlib.sha256()
    written = 0
    with archive.open(info, "r") as source, open(destination, "wb") as target:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_CACHE_BYTES:
                raise PackageError("The cached index exceeds the allowed extracted size.")
            digest.update(chunk)
            target.write(chunk)
    if digest.hexdigest() != expected_hash:
        raise PackageError("The cached index checksum does not match the manifest.")


def _content_record(manifest: dict, key: str, expected_path: str) -> dict:
    contents = manifest.get("contents")
    record = contents.get(key) if isinstance(contents, dict) else None
    if not isinstance(record, dict) or record.get("path") != expected_path:
        raise PackageError(f"The manifest does not describe {expected_path} correctly.")
    checksum = str(record.get("sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise PackageError(f"The manifest checksum for {expected_path} is invalid.")
    if not isinstance(record.get("size"), int) or record["size"] < 0:
        raise PackageError(f"The manifest size for {expected_path} is invalid.")
    return record


def inspect_package(path: str, cache_destination: str | None = None) -> PackageInfo:
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise PackageError("The selected .oder file does not exist.")
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackageError("The selected file is not a valid ZIP-based .oder package.") from exc
    with archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)):
            raise PackageError("The package contains duplicate files.")
        if not {MANIFEST_NAME, PROFILE_NAME}.issubset(names) or not set(names).issubset(_ALLOWED_MEMBERS):
            raise PackageError("The package layout is not supported by this ODeR version.")
        by_name = {item.filename: item for item in infos}
        if any(item.is_dir() or item.flag_bits & 0x1 for item in infos):
            raise PackageError("Directories and encrypted entries are not allowed inside .oder packages.")
        try:
            manifest_bytes = _read_member(archive, by_name[MANIFEST_NAME], MAX_JSON_BYTES)
            profile_bytes = _read_member(archive, by_name[PROFILE_NAME], MAX_JSON_BYTES)
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            profile = _validate_profile_payload(json.loads(profile_bytes.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile, RuntimeError) as exc:
            raise PackageError("The package JSON metadata is corrupt or is not valid UTF-8 JSON.") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT_ID:
            raise PackageError("This file is not an ODeR directory package.")
        version = manifest.get("format_version")
        if version != FORMAT_VERSION:
            raise PackageError(f"Package format version {version!r} is not supported (expected {FORMAT_VERSION}).")
        package_type = manifest.get("package_type")
        if package_type not in {"definition", "full"}:
            raise PackageError("The package type must be definition or full.")
        scope = str(manifest.get("scope") or "directory")
        if scope not in {"directory", "subtree"}:
            raise PackageError("The package scope must be directory or subtree.")
        has_cache = CACHE_NAME in by_name
        if has_cache != (package_type == "full"):
            raise PackageError("The package type and cached-index contents do not agree.")
        profile_record = _content_record(manifest, "profile", PROFILE_NAME)
        if profile_record["size"] != len(profile_bytes):
            raise PackageError("The directory definition size does not match the manifest.")
        if _sha256_bytes(profile_bytes) != profile_record["sha256"]:
            raise PackageError("The directory definition checksum does not match the manifest.")
        summary = manifest.get("profile") or {}
        if not isinstance(summary, dict):
            raise PackageError("The package profile summary is invalid.")
        if (summary.get("name") != profile["name"]
                or summary.get("source_profile_id") != profile.get("source_profile_id")
                or _canonical_base_url(summary.get("base_url", "")) != profile["base_url"]):
            raise PackageError("The manifest and directory definition describe different profiles.")
        created_at = str(manifest.get("created_at") or "")
        if not created_at or len(created_at) > 80:
            raise PackageError("The package export timestamp is missing or invalid.")
        try:
            parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if parsed_created_at.tzinfo is None:
                raise ValueError
        except ValueError as exc:
            raise PackageError("The package export timestamp is not a valid timezone-aware ISO timestamp.") from exc
        application = manifest.get("application") or {}
        if not isinstance(application, dict):
            raise PackageError("The package application metadata is invalid.")
        app_version = str(application.get("version") or "unknown")
        if len(app_version) > 80:
            raise PackageError("The package application version is invalid.")
        cache_counts = {"entries": 0, "folders": 0, "files": 0}
        cache_size = 0
        if has_cache:
            cache_record = _content_record(manifest, "cache", CACHE_NAME)
            cache_size = int(by_name[CACHE_NAME].file_size)
            if cache_record["size"] != cache_size:
                raise PackageError("The cached-index size does not match the manifest.")
            try:
                if cache_destination:
                    extracted = os.path.abspath(cache_destination)
                    os.makedirs(os.path.dirname(extracted), exist_ok=True)
                    try:
                        os.remove(extracted)
                    except FileNotFoundError:
                        pass
                    _extract_cache(archive, by_name[CACHE_NAME], extracted, cache_record["sha256"])
                    cache_counts = _validate_cache_file(extracted, profile["base_url"])
                else:
                    with tempfile.TemporaryDirectory(prefix="oder-validate-") as temp_dir:
                        extracted = os.path.join(temp_dir, CACHE_NAME)
                        _extract_cache(archive, by_name[CACHE_NAME], extracted, cache_record["sha256"])
                        cache_counts = _validate_cache_file(extracted, profile["base_url"])
            except (zipfile.BadZipFile, RuntimeError) as exc:
                raise PackageError("The cached index in the package is corrupt.") from exc
            expected_counts = cache_record.get("counts") or {}
            if not isinstance(expected_counts, dict):
                raise PackageError("The cached-index statistics in the manifest are invalid.")
            for key in ("entries", "folders", "files"):
                try:
                    expected = int(expected_counts.get(key, -1))
                except (TypeError, ValueError) as exc:
                    raise PackageError("The cached-index statistics in the manifest are invalid.") from exc
                if expected != cache_counts[key]:
                    raise PackageError("The cached-index statistics do not match the manifest.")
        return PackageInfo(
            path=path,
            package_type=package_type,
            created_at=created_at,
            app_version=app_version,
            name=profile["name"],
            base_url=profile["base_url"],
            source_profile_id=profile.get("source_profile_id"),
            has_cache=has_cache,
            cache_entries=cache_counts["entries"],
            cache_folders=cache_counts["folders"],
            cache_files=cache_counts["files"],
            cache_size=cache_size,
            profile=profile,
            scope=scope,
        )


def export_directory(profile: dict, destination: str, include_cache: bool = False,
                     root_url: str | None = None) -> PackageInfo:
    destination = os.path.abspath(destination)
    if not destination.lower().endswith(".oder"):
        destination += ".oder"
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    payload = _profile_payload(profile, include_cache, root_url)
    profile_bytes = _json_bytes(payload)
    cache_counts = {"entries": 0, "folders": 0, "files": 0}
    temp_archive = destination + f".tmp-{uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory(prefix="oder-export-") as temp_dir:
        cache_path = os.path.join(temp_dir, CACHE_NAME)
        cache_record = None
        if include_cache:
            try:
                if root_url:
                    cache.backup_subtree(str(profile["id"]), payload["base_url"], cache_path)
                else:
                    cache.backup_database(str(profile["id"]), cache_path)
            except (OSError, sqlite3.Error) as exc:
                raise PackageError(f"The cached index could not be exported: {exc}") from exc
            cache_counts = _validate_cache_file(cache_path, payload["base_url"])
            cache_record = {
                "path": CACHE_NAME,
                "size": os.path.getsize(cache_path),
                "sha256": _sha256_file(cache_path),
                "counts": cache_counts,
            }
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        contents = {
            "profile": {
                "path": PROFILE_NAME,
                "size": len(profile_bytes),
                "sha256": _sha256_bytes(profile_bytes),
            }
        }
        if cache_record:
            contents["cache"] = cache_record
        manifest = {
            "format": FORMAT_ID,
            "format_version": FORMAT_VERSION,
            "package_type": "full" if include_cache else "definition",
            "scope": "subtree" if root_url else "directory",
            "created_at": created_at,
            "application": {"name": APP_NAME, "version": APP_VERSION},
            "profile": {
                "source_profile_id": payload.get("source_profile_id"),
                "name": payload["name"],
                "base_url": payload["base_url"],
            },
            "contents": contents,
        }
        try:
            with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
                archive.writestr(MANIFEST_NAME, _json_bytes(manifest))
                archive.writestr(PROFILE_NAME, profile_bytes)
                if include_cache:
                    archive.write(cache_path, CACHE_NAME)
            os.replace(temp_archive, destination)
        except (OSError, zipfile.BadZipFile) as exc:
            try:
                os.remove(temp_archive)
            except FileNotFoundError:
                pass
            raise PackageError(f"The .oder package could not be written: {exc}") from exc
    info = PackageInfo(
        path=destination,
        package_type="full" if include_cache else "definition",
        created_at=created_at,
        app_version=APP_VERSION,
        name=payload["name"],
        base_url=payload["base_url"],
        source_profile_id=payload.get("source_profile_id"),
        has_cache=include_cache,
        cache_entries=cache_counts["entries"],
        cache_folders=cache_counts["folders"],
        cache_files=cache_counts["files"],
        cache_size=(cache_record or {}).get("size", 0),
        profile=payload,
        scope="subtree" if root_url else "directory",
    )
    library.record_package("export", destination, name=info.name, package_type=info.package_type,
                           scope=info.scope)
    return info


def find_conflicts(info: PackageInfo, profiles: list[dict] | None = None) -> list[dict]:
    conflicts = []
    for existing in profiles if profiles is not None else load_profiles():
        reasons = []
        if info.source_profile_id and existing.get("id") == info.source_profile_id:
            reasons.append("same original profile")
        try:
            if _canonical_base_url(existing.get("base_url", "")) == info.base_url:
                reasons.append("same base URL")
        except PackageError:
            pass
        if reasons:
            item = dict(existing)
            item["_conflict_reason"] = " and ".join(reasons)
            conflicts.append(item)
    return conflicts


def _unique_name(name: str, profiles: list[dict]) -> str:
    existing = {str(item.get("name") or "").casefold() for item in profiles}
    if name.casefold() not in existing:
        return name
    candidate = f"{name} (Imported)"
    number = 2
    while candidate.casefold() in existing:
        candidate = f"{name} (Imported {number})"
        number += 1
    return candidate


def _new_profile_id(profiles: list[dict]) -> str:
    used = {item.get("id") for item in profiles}
    while True:
        value = uuid.uuid4().hex[:12]
        if value not in used:
            return value


def _build_imported_profile(info: PackageInfo, profile_id: str, existing: dict | None) -> dict:
    payload = info.profile
    settings = dict(DEFAULT_SETTINGS)
    settings.update(payload.get("settings") or {})
    incoming_metadata = payload.get("metadata")
    if existing and not info.has_cache:
        result = dict(existing)
        result.update({"id": profile_id, "name": payload["name"], "base_url": payload["base_url"], "settings": settings})
        if incoming_metadata is not None:
            result["metadata"] = normalize_library_metadata(incoming_metadata)
        return result
    state = payload.get("cache_state") or {}
    metadata = (
        normalize_library_metadata(incoming_metadata)
        if incoming_metadata is not None
        else normalize_library_metadata((existing or {}).get("metadata"))
    )
    return {
        "id": profile_id,
        "name": payload["name"],
        "base_url": payload["base_url"],
        "settings": settings,
        "metadata": metadata,
        "index_source": state.get("index_source"),
        "hosted_index": None,
        "last_crawled": state.get("last_crawled"),
        "folders_cached": int(state.get("folders_cached") or 0),
        "last_crawl_stats": state.get("last_crawl_stats"),
        "crawl_history": state.get("crawl_history") if isinstance(state.get("crawl_history"), list) else [],
    }


def import_directory(path: str, conflict_policy: str = "error", replace_profile_id: str | None = None) -> ImportResult:
    info = inspect_package(path)
    profiles = load_profiles()
    conflicts = find_conflicts(info, profiles)
    existing = None
    if conflict_policy == "replace":
        existing = next((item for item in profiles if item.get("id") == replace_profile_id), None)
        if existing is None or not any(item.get("id") == replace_profile_id for item in conflicts):
            raise PackageConflictError("Choose an existing conflicting directory to replace.")
        if not info.has_cache and _canonical_base_url(existing.get("base_url", "")) != info.base_url:
            raise PackageConflictError("A definition-only package cannot replace a directory with a different base URL. Import it as a copy instead.")
        target_id = existing["id"]
    elif conflict_policy == "copy":
        target_id = _new_profile_id(profiles)
    elif conflict_policy == "error":
        if conflicts:
            raise PackageConflictError("A directory with the same source ID or base URL already exists.")
        target_id = _new_profile_id(profiles)
    else:
        raise PackageError("Unknown import conflict policy.")

    imported = _build_imported_profile(info, target_id, existing)
    if existing is None:
        imported["name"] = _unique_name(imported["name"], profiles)
    old_profiles = [dict(item) for item in profiles]
    if existing:
        new_profiles = [imported if item.get("id") == target_id else item for item in profiles]
    else:
        new_profiles = profiles + [imported]

    created_profile_dir = existing is None
    old_cache_snapshot = None
    with tempfile.TemporaryDirectory(prefix="oder-import-", dir=data_dir()) as temp_dir:
        incoming_cache = None
        if info.has_cache:
            incoming_cache = os.path.join(temp_dir, CACHE_NAME)
            with zipfile.ZipFile(info.path, "r") as archive:
                manifest = json.loads(_read_member(archive, archive.getinfo(MANIFEST_NAME), MAX_JSON_BYTES).decode("utf-8"))
                cache_record = _content_record(manifest, "cache", CACHE_NAME)
                _extract_cache(archive, archive.getinfo(CACHE_NAME), incoming_cache, cache_record["sha256"])
            _validate_cache_file(incoming_cache, info.base_url)
            if existing and cache.database_exists(target_id):
                old_cache_snapshot = os.path.join(temp_dir, "previous.sqlite3")
                cache.backup_database(target_id, old_cache_snapshot)
        try:
            profile_dir(target_id)
            if incoming_cache:
                cache.replace_database(target_id, incoming_cache)
            save_profiles(new_profiles)
        except Exception:
            try:
                save_profiles(old_profiles)
            except Exception:
                pass
            if old_cache_snapshot and os.path.exists(old_cache_snapshot):
                cache.replace_database(target_id, old_cache_snapshot)
            elif incoming_cache:
                for suffix in ("", "-wal", "-shm"):
                    try:
                        os.remove(profile_cache_db_path(target_id) + suffix)
                    except FileNotFoundError:
                        pass
            if created_profile_dir:
                shutil.rmtree(profile_dir(target_id), ignore_errors=True)
            raise
    result = ImportResult(profile=imported, replaced=existing is not None, cache_imported=info.has_cache)
    library.record_package("import", info.path, name=imported["name"],
                           package_type=info.package_type, replaced=result.replaced, scope=info.scope)
    return result


def apply_hosted_cache(profile_id: str, info: PackageInfo, materialized_cache_path: str,
                       expected_base_url: str) -> dict:
    """Apply a validated hosted index while preserving local profile settings/history."""
    expected_base_url = _canonical_base_url(expected_base_url)
    if not info.has_cache or info.package_type != "full":
        raise PackageError("A hosted index must be a full .oder package with a cached index.")
    if info.base_url != expected_base_url:
        raise PackageError("The hosted index belongs to a different base URL.")
    counts = _validate_cache_file(materialized_cache_path, expected_base_url)
    uri = "file:" + os.path.abspath(materialized_cache_path).replace("\\", "/") + "?mode=ro"
    incoming = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        rows = incoming.execute(
            "SELECT url,name,is_dir,size,parent_url,crawled FROM nodes ORDER BY rowid"
        )
        cache.replace_all_nodes(profile_id, expected_base_url, rows)
    finally:
        incoming.close()
    applied = cache.count_summary(profile_id)
    if applied != counts:
        raise PackageError("The hosted index changed unexpectedly while it was being applied.")
    return applied


def _materialize_cache(info: PackageInfo, destination: str) -> None:
    with zipfile.ZipFile(info.path, "r") as archive:
        manifest = json.loads(
            _read_member(archive, archive.getinfo(MANIFEST_NAME), MAX_JSON_BYTES).decode("utf-8")
        )
        record = _content_record(manifest, "cache", CACHE_NAME)
        _extract_cache(archive, archive.getinfo(CACHE_NAME), destination, record["sha256"])
    _validate_cache_file(destination, info.base_url)


def compare_packages(left_path: str, right_path: str, detail_limit: int = 2000) -> PackageComparison:
    """Compare two packages without importing either into the user's library."""
    left = inspect_package(left_path)
    right = inspect_package(right_path)
    differences = []
    if left.name != right.name:
        differences.append("Directory name")
    if left.base_url != right.base_url:
        differences.append("Base URL")
    if (left.profile.get("settings") or {}) != (right.profile.get("settings") or {}):
        differences.append("Directory settings")
    if (left.profile.get("metadata") or {}) != (right.profile.get("metadata") or {}):
        differences.append("Library metadata or artwork")
    if left.package_type != right.package_type:
        differences.append("Package type")
    if not left.has_cache or not right.has_cache:
        result = PackageComparison(left, right, tuple(differences), 0, 0, 0, tuple())
        library.record_package("compare", left.path, other_path=right.path,
                               result="definition comparison")
        return result

    with tempfile.TemporaryDirectory(prefix="oder-compare-") as temp_dir:
        left_db = os.path.join(temp_dir, "left.sqlite3")
        right_db = os.path.join(temp_dir, "right.sqlite3")
        _materialize_cache(left, left_db)
        _materialize_cache(right, right_db)
        conn = sqlite3.connect(left_db, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("ATTACH DATABASE ? AS rhs", (right_db,))
            left_start = len(left.base_url) + 1
            right_start = len(right.base_url) + 1
            new_count = conn.execute(
                """SELECT COUNT(*) FROM rhs.nodes r WHERE NOT EXISTS (
                       SELECT 1 FROM main.nodes l WHERE substr(l.url,?)=substr(r.url,?))""",
                (left_start, right_start),
            ).fetchone()[0]
            removed_count = conn.execute(
                """SELECT COUNT(*) FROM main.nodes l WHERE NOT EXISTS (
                       SELECT 1 FROM rhs.nodes r WHERE substr(r.url,?)=substr(l.url,?))""",
                (right_start, left_start),
            ).fetchone()[0]
            changed_count = conn.execute(
                """SELECT COUNT(*) FROM main.nodes l JOIN rhs.nodes r
                   ON substr(l.url,?)=substr(r.url,?)
                   WHERE l.name<>r.name OR l.is_dir<>r.is_dir OR
                   COALESCE(l.size_bytes,-1)<>COALESCE(r.size_bytes,-1)""",
                (left_start, right_start),
            ).fetchone()[0]
            remaining = max(0, min(100000, int(detail_limit)))
            changes = []
            if remaining:
                rows = conn.execute(
                    """SELECT 'new' change_type,r.url,r.name,r.is_dir,NULL old_size,r.size new_size
                       FROM rhs.nodes r WHERE NOT EXISTS (
                           SELECT 1 FROM main.nodes l WHERE substr(l.url,?)=substr(r.url,?))
                       ORDER BY r.is_dir DESC,r.name COLLATE NOCASE LIMIT ?""",
                    (left_start, right_start, remaining),
                ).fetchall()
                changes.extend(dict(row) for row in rows)
                remaining -= len(rows)
            if remaining:
                rows = conn.execute(
                    """SELECT 'removed' change_type,l.url,l.name,l.is_dir,l.size old_size,NULL new_size
                       FROM main.nodes l WHERE NOT EXISTS (
                           SELECT 1 FROM rhs.nodes r WHERE substr(r.url,?)=substr(l.url,?))
                       ORDER BY l.is_dir DESC,l.name COLLATE NOCASE LIMIT ?""",
                    (right_start, left_start, remaining),
                ).fetchall()
                changes.extend(dict(row) for row in rows)
                remaining -= len(rows)
            if remaining:
                rows = conn.execute(
                    """SELECT 'changed' change_type,r.url,r.name,r.is_dir,l.size old_size,r.size new_size
                       FROM main.nodes l JOIN rhs.nodes r ON substr(l.url,?)=substr(r.url,?)
                       WHERE l.name<>r.name OR l.is_dir<>r.is_dir OR
                       COALESCE(l.size_bytes,-1)<>COALESCE(r.size_bytes,-1)
                       ORDER BY r.is_dir DESC,r.name COLLATE NOCASE LIMIT ?""",
                    (left_start, right_start, remaining),
                ).fetchall()
                changes.extend(dict(row) for row in rows)
        finally:
            conn.close()
    result = PackageComparison(left, right, tuple(differences), int(new_count),
                               int(removed_count), int(changed_count), tuple(changes))
    library.record_package("compare", left.path, other_path=right.path,
                           new_count=result.new_count, removed_count=result.removed_count,
                           changed_count=result.changed_count)
    return result
