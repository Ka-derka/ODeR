"""ODeR Library v1 projects, package building, and strict validation.

``.odrproj`` is Creator's editable JSON project. ``.odrlib`` is the published
ZIP/ZIP64 container consumed by ODeR.  Projects may refer to local files, but
published packages contain only portable paths and declared HTTPS sources.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import PurePosixPath
import re
import tempfile
import uuid
from urllib.parse import urlsplit
import zipfile

from core.persistence import load_json, save_json
from core.version import APP_VERSION, CREATOR_NAME, CREATOR_VERSION


FORMAT_ID = "oder-library"
FORMAT_VERSION = 1
PROJECT_FORMAT_ID = "oder-creator-project"
PROJECT_FORMAT_VERSION = 1
FEED_FORMAT_ID = "oder-library-update-feed"
FEED_FORMAT_VERSION = 1

# ODeR Library format versions describe the stable container and catalog core.
# Optional behaviour is added through independently versioned extensions so a
# reader can make a safe decision without guessing from catalog fields.
UPDATE_EXTENSION_ID = "U"
UPDATE_EXTENSION_VERSION = 1
TORRENT_EXTENSION_ID = "T"  # Reserved for Alpha 3; deliberately unsupported here.
SUPPORTED_EXTENSIONS = {UPDATE_EXTENSION_ID: {UPDATE_EXTENSION_VERSION}}

MANIFEST_NAME = "manifest.json"
LIBRARY_NAME = "library.json"
ITEMS_NAME = "catalog/items-0001.json"
COLLECTIONS_NAME = "catalog/collections.json"

MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_CATALOG_BYTES = 128 * 1024 * 1024
MAX_ASSET_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024 * 1024
MAX_MEMBERS = 250_000
MAX_ITEMS = 200_000
MAX_COLLECTIONS = 50_000
MAX_ARTIFACTS_PER_ITEM = 200
MAX_SOURCES_PER_ARTIFACT = 32
MAX_COMPRESSION_RATIO = 500

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXTENSION_ID_RE = re.compile(r"^[A-Z][A-Z0-9-]{0,31}$")
_IMAGE_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_MEMBER_ROLES = {"asset", "catalog", "license", "payload"}


class OdrLibError(ValueError):
    """An editable project or published library is invalid or unsafe."""


@dataclass(frozen=True)
class ValidationIssue:
    level: str
    location: str
    message: str


@dataclass(frozen=True)
class ExtensionInfo:
    id: str
    version: int
    required: bool

    @property
    def badge(self):
        return f"{self.id}{self.version}"


@dataclass(frozen=True)
class LibraryPackageInfo:
    path: str
    package_id: str
    created_at: str
    created_by_name: str
    created_by_version: str
    library_id: str
    revision: int
    version: str
    name: str
    summary: str
    creator: str
    category: str
    tags: tuple[str, ...]
    artwork_path: str | None
    update_feed_url: str | None
    item_count: int
    collection_count: int
    artifact_count: int
    embedded_bytes: int
    online_source_count: int
    extensions: tuple[ExtensionInfo, ...]
    library: dict
    items: tuple[dict, ...]
    collections: tuple[dict, ...]
    manifest: dict


@dataclass(frozen=True)
class BuildResult:
    path: str
    size: int
    sha256: str
    package: LibraryPackageInfo
    warnings: tuple[ValidationIssue, ...]
    feed_path: str | None = None


@dataclass(frozen=True)
class UpdateFeedInfo:
    library_id: str
    channel: str
    revision: int
    version: str
    published_at: str
    url: str
    size: int
    sha256: str
    minimum_reader: str
    release_notes: str


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id():
    return str(uuid.uuid4())


def _json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_text(value, limit=4000):
    return str(value or "").replace("\x00", "").strip()[:limit].rstrip()


def _string_list(value, *, maximum=100, item_limit=200):
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    seen = set()
    for raw in value:
        text = _clean_text(raw, item_limit)
        folded = text.casefold()
        if text and folded not in seen:
            result.append(text)
            seen.add(folded)
        if len(result) >= maximum:
            break
    return result


def _valid_uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _https_url(value):
    text = _clean_text(value, 4096)
    parts = urlsplit(text)
    return text if parts.scheme.lower() == "https" and parts.netloc else None


def _portable_url(value):
    """Add HTTPS to a bare address while preserving invalid explicit schemes for validation."""
    text = _clean_text(value, 4096)
    if text.startswith("//"):
        text = "https:" + text
    elif text and "://" not in text:
        text = "https://" + text
    return _https_url(text) or text


def _url_list(value, *, maximum=20):
    return [_portable_url(url) for url in _string_list(value, maximum=maximum, item_limit=4096)]


def _safe_member_name(value):
    text = str(value or "")
    if not text or "\\" in text or text.startswith("/") or text.endswith("/"):
        return None
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def _safe_component(value, fallback="file"):
    text = "".join(c for c in str(value or "") if c not in '<>:"/\\|?*' and ord(c) >= 32)
    text = text.strip().rstrip(" .")
    return (text or fallback)[:180].rstrip(" .") or fallback


def _inspect_extensions(value):
    """Validate manifest extension declarations and reject unknown requirements."""
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise OdrLibError("The package extension declaration is invalid.")
    if set(value) - {"required", "optional"}:
        raise OdrLibError("The package extension declaration contains unsupported fields.")
    result = []
    seen = set()
    for group, required in (("required", True), ("optional", False)):
        records = value.get(group, [])
        if not isinstance(records, list) or len(records) > 64:
            raise OdrLibError("The package extension list is invalid.")
        for record in records:
            if not isinstance(record, dict) or set(record) != {"id", "version"}:
                raise OdrLibError("A package extension declaration is malformed.")
            extension_id = str(record.get("id") or "")
            version = record.get("version")
            if (not _EXTENSION_ID_RE.fullmatch(extension_id)
                    or isinstance(version, bool) or not isinstance(version, int)
                    or version < 1 or version > 65535):
                raise OdrLibError("A package extension ID or version is invalid.")
            if extension_id in seen:
                raise OdrLibError(f"Extension {extension_id} is declared more than once.")
            seen.add(extension_id)
            supported_versions = SUPPORTED_EXTENSIONS.get(extension_id, set())
            if required and version not in supported_versions:
                raise OdrLibError(
                    f"This package requires unsupported extension {extension_id}{version}."
                )
            result.append(ExtensionInfo(extension_id, version, required))
    return tuple(result)


def _resolve_source(path, project_path=None):
    path = os.path.expandvars(os.path.expanduser(str(path or "").strip()))
    if not path:
        return ""
    if os.path.isabs(path):
        return os.path.abspath(path)
    base = os.path.dirname(os.path.abspath(project_path)) if project_path else os.getcwd()
    return os.path.abspath(os.path.join(base, path))


def _portable_source(path, project_path):
    absolute = _resolve_source(path, project_path)
    if not absolute or not project_path:
        return absolute or str(path or "")
    project_dir = os.path.dirname(os.path.abspath(project_path))
    try:
        if os.path.commonpath((project_dir, absolute)) == project_dir:
            return os.path.relpath(absolute, project_dir)
    except ValueError:
        pass
    return absolute


def _detect_image_bytes(head):
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _detect_image(path):
    with open(path, "rb") as handle:
        head = handle.read(16)
    detected = _detect_image_bytes(head)
    if detected:
        return detected
    raise OdrLibError(f"Artwork is not a supported PNG, JPEG, or WebP image: {path}")


def new_artifact(*, name="New file", embedded_path="", url=""):
    sources = []
    if embedded_path:
        sources.append({"type": "embedded", "source_path": str(embedded_path)})
    if url:
        sources.append({"type": "https", "url": str(url)})
    return {
        "id": _new_id(),
        "name": _clean_text(name, 300) or "New file",
        "filename": _clean_text(os.path.basename(embedded_path) if embedded_path else "", 255),
        "media_type": "",
        "platform": "Any",
        "architecture": "Any",
        "size": None,
        "sha256": "",
        "sources": sources,
    }


def new_item(*, title="New item"):
    return {
        "id": _new_id(),
        "title": _clean_text(title, 300) or "New item",
        "summary": "",
        "description": "",
        "creator": "",
        "version": "",
        "category": "",
        "tags": [],
        "platform": "Any",
        "architecture": "Any",
        "license": {"name": "Unknown", "url": ""},
        "links": [],
        "artwork_path": "",
        "artifacts": [],
    }


def new_collection(*, name="New collection"):
    return {
        "id": _new_id(),
        "name": _clean_text(name, 300) or "New collection",
        "summary": "",
        "description": "",
        "item_ids": [],
    }


def new_project():
    now = _now_iso()
    return {
        "format": PROJECT_FORMAT_ID,
        "format_version": PROJECT_FORMAT_VERSION,
        "project_id": _new_id(),
        "library": {
            "id": _new_id(),
            "name": "Untitled Library",
            "summary": "",
            "description": "",
            "creator": "",
            "category": "",
            "tags": [],
            "languages": [],
            "links": [],
            "license": {"name": "Mixed / see individual items", "url": ""},
            "version": "1",
            "revision": 1,
            "artwork_path": "",
            "created_at": now,
            "update": {"feed_url": "", "channel": "stable"},
        },
        "items": [],
        "collections": [],
        "publishing": {"package_url": "", "release_notes": ""},
    }


def _normalize_artifact(value):
    value = value if isinstance(value, dict) else {}
    artifact_id = _valid_uuid(value.get("id")) or _new_id()
    sources = []
    for source in value.get("sources") or []:
        if not isinstance(source, dict):
            continue
        kind = str(source.get("type") or "").casefold()
        if kind == "embedded":
            path = _clean_text(source.get("source_path") or source.get("path"), 32768)
            if path:
                sources.append({"type": "embedded", "source_path": path})
        elif kind == "https":
            url = _portable_url(source.get("url"))
            if url:
                sources.append({"type": "https", "url": url})
    try:
        size = int(value["size"]) if value.get("size") not in {None, ""} else None
    except (TypeError, ValueError):
        size = None
    return {
        "id": artifact_id,
        "name": _clean_text(value.get("name"), 300) or "File",
        "filename": _clean_text(value.get("filename"), 255),
        "media_type": _clean_text(value.get("media_type"), 200),
        "platform": _clean_text(value.get("platform"), 100) or "Any",
        "architecture": _clean_text(value.get("architecture"), 100) or "Any",
        "size": size,
        "sha256": _clean_text(value.get("sha256"), 64).casefold(),
        "sources": sources,
    }


def _normalize_item(value):
    value = value if isinstance(value, dict) else {}
    license_value = value.get("license") if isinstance(value.get("license"), dict) else {}
    return {
        "id": _valid_uuid(value.get("id")) or _new_id(),
        "title": _clean_text(value.get("title"), 300) or "Untitled item",
        "summary": _clean_text(value.get("summary"), 1000),
        "description": _clean_text(value.get("description"), 20_000),
        "creator": _clean_text(value.get("creator"), 300),
        "version": _clean_text(value.get("version"), 100),
        "category": _clean_text(value.get("category"), 200),
        "tags": _string_list(value.get("tags"), maximum=50, item_limit=100),
        "platform": _clean_text(value.get("platform"), 100) or "Any",
        "architecture": _clean_text(value.get("architecture"), 100) or "Any",
        "license": {
            "name": _clean_text(license_value.get("name"), 200) or "Unknown",
            "url": _portable_url(license_value.get("url")),
        },
        "links": _url_list(value.get("links")),
        "artwork_path": _clean_text(value.get("artwork_path"), 32768),
        "artifacts": [
            _normalize_artifact(artifact)
            for artifact in (value.get("artifacts") or [])
            if isinstance(artifact, dict)
        ],
    }


def normalize_project(value):
    """Return a complete, editor-friendly project without touching source files."""
    value = deepcopy(value) if isinstance(value, dict) else new_project()
    library_value = value.get("library") if isinstance(value.get("library"), dict) else {}
    license_value = library_value.get("license") if isinstance(library_value.get("license"), dict) else {}
    update_value = library_value.get("update") if isinstance(library_value.get("update"), dict) else {}
    publishing = value.get("publishing") if isinstance(value.get("publishing"), dict) else {}
    try:
        revision = max(1, int(library_value.get("revision") or 1))
    except (TypeError, ValueError):
        revision = 1
    project = {
        "format": PROJECT_FORMAT_ID,
        "format_version": PROJECT_FORMAT_VERSION,
        "project_id": _valid_uuid(value.get("project_id")) or _new_id(),
        "library": {
            "id": _valid_uuid(library_value.get("id")) or _new_id(),
            "name": _clean_text(library_value.get("name"), 300) or "Untitled Library",
            "summary": _clean_text(library_value.get("summary"), 1000),
            "description": _clean_text(library_value.get("description"), 20_000),
            "creator": _clean_text(library_value.get("creator"), 300),
            "category": _clean_text(library_value.get("category"), 200),
            "tags": _string_list(library_value.get("tags"), maximum=50, item_limit=100),
            "languages": _string_list(library_value.get("languages"), maximum=30, item_limit=100),
            "links": _url_list(library_value.get("links")),
            "license": {
                "name": _clean_text(license_value.get("name"), 200) or "Mixed / see individual items",
                "url": _portable_url(license_value.get("url")),
            },
            "version": _clean_text(library_value.get("version"), 100) or "1",
            "revision": revision,
            "artwork_path": _clean_text(library_value.get("artwork_path"), 32768),
            "created_at": _clean_text(library_value.get("created_at"), 100) or _now_iso(),
            "update": {
                "feed_url": _portable_url(update_value.get("feed_url")),
                "channel": _clean_text(update_value.get("channel"), 50) or "stable",
            },
        },
        "items": [
            _normalize_item(item)
            for item in (value.get("items") or [])
            if isinstance(item, dict)
        ],
        "collections": [],
        "publishing": {
            "package_url": _portable_url(publishing.get("package_url")),
            "release_notes": _clean_text(publishing.get("release_notes"), 20_000),
        },
    }
    for raw in (value.get("collections") or []):
        if not isinstance(raw, dict):
            continue
        project["collections"].append({
            "id": _valid_uuid(raw.get("id")) or _new_id(),
            "name": _clean_text(raw.get("name"), 300) or "Untitled collection",
            "summary": _clean_text(raw.get("summary"), 1000),
            "description": _clean_text(raw.get("description"), 20_000),
            "item_ids": list(dict.fromkeys(
                value for value in (_valid_uuid(item_id) for item_id in raw.get("item_ids") or []) if value
            )),
        })
    return project


def _relativize_project(project, project_path):
    result = deepcopy(normalize_project(project))
    library = result["library"]
    if library.get("artwork_path"):
        library["artwork_path"] = _portable_source(library["artwork_path"], project_path)
    for item in result["items"]:
        if item.get("artwork_path"):
            item["artwork_path"] = _portable_source(item["artwork_path"], project_path)
        for artifact in item["artifacts"]:
            for source in artifact["sources"]:
                if source["type"] == "embedded":
                    source["source_path"] = _portable_source(source["source_path"], project_path)
    return result


def save_project(path, project):
    path = os.path.abspath(path)
    if not path.casefold().endswith(".odrproj"):
        path += ".odrproj"
    stored = _relativize_project(project, path)
    save_json(path, stored)
    return stored


def load_project(path):
    path = os.path.abspath(path)
    try:
        if os.path.getsize(path) > MAX_CATALOG_BYTES:
            raise OdrLibError("The Creator project is larger than the supported limit.")
    except OSError as exc:
        raise OdrLibError("The selected Creator project could not be read.") from exc
    raw = load_json(path, None)
    if not isinstance(raw, dict):
        raise OdrLibError("The selected Creator project is not valid JSON.")
    if raw.get("format") != PROJECT_FORMAT_ID:
        raise OdrLibError("The selected file is not an ODeR Creator project.")
    if raw.get("format_version") != PROJECT_FORMAT_VERSION:
        raise OdrLibError("This Creator project uses an unsupported format version.")
    if not _valid_uuid(raw.get("project_id")):
        raise OdrLibError("The Creator project ID is invalid.")
    library = raw.get("library")
    if not isinstance(library, dict) or not _valid_uuid(library.get("id")):
        raise OdrLibError("The Creator project's permanent library ID is invalid.")
    seen_ids = set()
    for kind, entries in (("item", raw.get("items")), ("collection", raw.get("collections"))):
        if not isinstance(entries, list):
            raise OdrLibError(f"The Creator project {kind} list is invalid.")
        for entry in entries:
            identifier = _valid_uuid(entry.get("id")) if isinstance(entry, dict) else None
            if not identifier or identifier in seen_ids:
                raise OdrLibError(f"The Creator project contains an invalid or duplicate {kind} ID.")
            seen_ids.add(identifier)
            if kind == "item":
                artifacts = entry.get("artifacts") or []
                if not isinstance(artifacts, list):
                    raise OdrLibError("The Creator project contains an invalid file list.")
                for artifact in artifacts:
                    artifact_id = _valid_uuid(artifact.get("id")) if isinstance(artifact, dict) else None
                    if not artifact_id or artifact_id in seen_ids:
                        raise OdrLibError("The Creator project contains an invalid or duplicate file ID.")
                    seen_ids.add(artifact_id)
    return normalize_project(raw)


def validate_project(project, project_path=None):
    """Return all actionable project errors and warnings."""
    project = normalize_project(project)
    issues = []
    library = project["library"]
    if len(project["items"]) > MAX_ITEMS:
        issues.append(ValidationIssue("error", "Library", f"A library can contain at most {MAX_ITEMS:,} files."))
    if len(project["collections"]) > MAX_COLLECTIONS:
        issues.append(ValidationIssue("error", "Library", f"A library can contain at most {MAX_COLLECTIONS:,} folders."))
    if not library["name"].strip():
        issues.append(ValidationIssue("error", "Library", "A library name is required."))
    if not library["creator"].strip():
        issues.append(ValidationIssue("warning", "Library", "Creator or curator is not set."))
    if not library["category"].strip():
        issues.append(ValidationIssue("warning", "Library", "Category is not set."))
    for label, url in (("license URL", library["license"].get("url")), ("update feed", library["update"].get("feed_url"))):
        if url and not _https_url(url):
            issues.append(ValidationIssue("error", "Library", f"The {label} must use a valid HTTPS URL."))
    for link in library["links"]:
        if not _https_url(link):
            issues.append(ValidationIssue("error", "Library", f"Library link is not HTTPS: {link}"))
    artwork = library.get("artwork_path")
    if artwork:
        resolved = _resolve_source(artwork, project_path)
        if not os.path.isfile(resolved):
            issues.append(ValidationIssue("error", "Library artwork", f"File was not found: {artwork}"))
        else:
            try:
                if os.path.getsize(resolved) > MAX_ASSET_BYTES:
                    raise OdrLibError("Artwork is larger than 16 MiB.")
                _detect_image(resolved)
            except (OSError, OdrLibError) as exc:
                issues.append(ValidationIssue("error", "Library artwork", str(exc)))

    item_ids = set()
    artifact_ids = set()
    total_embedded_bytes = 0
    for index, item in enumerate(project["items"], 1):
        location = f"File {index}: {item['title']}"
        if item["id"] in item_ids:
            issues.append(ValidationIssue("error", location, "The file ID is duplicated."))
        item_ids.add(item["id"])
        if not item["title"].strip():
            issues.append(ValidationIssue("error", location, "A title is required."))
        if not item["artifacts"]:
            issues.append(ValidationIssue("warning", location, "This file does not have an embedded file or download source."))
        if len(item["artifacts"]) > MAX_ARTIFACTS_PER_ITEM:
            issues.append(ValidationIssue("error", location, f"A file can contain at most {MAX_ARTIFACTS_PER_ITEM} source variants."))
        if item.get("artwork_path"):
            resolved = _resolve_source(item["artwork_path"], project_path)
            try:
                if not os.path.isfile(resolved):
                    raise OdrLibError(f"File was not found: {item['artwork_path']}")
                if os.path.getsize(resolved) > MAX_ASSET_BYTES:
                    raise OdrLibError("Artwork is larger than 16 MiB.")
                _detect_image(resolved)
            except (OSError, OdrLibError) as exc:
                issues.append(ValidationIssue("error", f"{location} artwork", str(exc)))
        for link in item["links"]:
            if not _https_url(link):
                issues.append(ValidationIssue("error", location, f"File link is not HTTPS: {link}"))
        license_url = item["license"].get("url")
        if license_url and not _https_url(license_url):
            issues.append(ValidationIssue("error", location, "The license URL must use HTTPS."))
        for artifact_index, artifact in enumerate(item["artifacts"], 1):
            artifact_location = f"{location} / Source variant {artifact_index}: {artifact['name']}"
            if artifact["id"] in artifact_ids:
                issues.append(ValidationIssue("error", artifact_location, "The artifact ID is duplicated."))
            artifact_ids.add(artifact["id"])
            if not artifact["sources"]:
                issues.append(ValidationIssue("error", artifact_location, "At least one embedded or HTTPS source is required."))
            if len(artifact["sources"]) > MAX_SOURCES_PER_ARTIFACT:
                issues.append(ValidationIssue("error", artifact_location, f"A file can contain at most {MAX_SOURCES_PER_ARTIFACT} sources."))
            embedded_count = 0
            for source in artifact["sources"]:
                if source["type"] == "embedded":
                    embedded_count += 1
                    resolved = _resolve_source(source.get("source_path"), project_path)
                    if not os.path.isfile(resolved):
                        issues.append(ValidationIssue("error", artifact_location, f"Embedded file was not found: {source.get('source_path', '')}"))
                    else:
                        try:
                            source_size = os.path.getsize(resolved)
                            total_embedded_bytes += source_size
                            if source_size > MAX_MEMBER_BYTES:
                                issues.append(ValidationIssue("error", artifact_location, "Embedded file exceeds the 128 GiB member limit."))
                        except OSError as exc:
                            issues.append(ValidationIssue("error", artifact_location, str(exc)))
                elif not _https_url(source.get("url")):
                    issues.append(ValidationIssue("error", artifact_location, "Online sources must use valid HTTPS URLs."))
            if embedded_count > 1:
                issues.append(ValidationIssue("error", artifact_location, "An artifact can contain at most one embedded source."))
            checksum = artifact.get("sha256") or ""
            if checksum and not _SHA256_RE.fullmatch(checksum):
                issues.append(ValidationIssue("error", artifact_location, "The expected SHA-256 checksum is malformed."))
            elif not embedded_count and not checksum:
                issues.append(ValidationIssue("warning", artifact_location, "The online-only file has no SHA-256 checksum."))
            if artifact.get("size") is not None and artifact["size"] < 0:
                issues.append(ValidationIssue("error", artifact_location, "The expected file size cannot be negative."))

    collection_ids = set()
    for collection in project["collections"]:
        location = f"Folder: {collection['name']}"
        if collection["id"] in collection_ids:
            issues.append(ValidationIssue("error", location, "The folder ID is duplicated."))
        collection_ids.add(collection["id"])
        missing = [item_id for item_id in collection["item_ids"] if item_id not in item_ids]
        if missing:
            issues.append(ValidationIssue("error", location, "The folder references files that no longer exist."))
    package_url = project["publishing"].get("package_url")
    if package_url and not _https_url(package_url):
        issues.append(ValidationIssue("error", "Publishing", "The package download URL must use HTTPS."))
    if library["update"].get("feed_url") and not package_url:
        issues.append(ValidationIssue("warning", "Publishing", "An update feed is declared, but no package download URL is set for feed generation."))
    if not project["items"]:
        issues.append(ValidationIssue("warning", "Library", "The library does not contain any files yet."))
    if total_embedded_bytes > MAX_TOTAL_BYTES:
        issues.append(ValidationIssue("error", "Library", "Embedded files exceed the 1 TiB package limit."))
    return issues


def _member_record(path, role, size, sha256):
    return {"path": path, "role": role, "size": int(size), "sha256": sha256}


def _write_bytes(archive, path, role, data, compression=zipfile.ZIP_DEFLATED):
    archive.writestr(path, data, compress_type=compression)
    return _member_record(path, role, len(data), hashlib.sha256(data).hexdigest())


def _write_file(archive, source_path, member_path, role, compression):
    digest = hashlib.sha256()
    size = 0
    info = zipfile.ZipInfo(member_path, date_time=datetime.now().timetuple()[:6])
    info.compress_type = compression
    with open(source_path, "rb") as source, archive.open(info, "w", force_zip64=True) as destination:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
            if size > MAX_MEMBER_BYTES:
                raise OdrLibError(f"Source file exceeds the 128 GiB member limit: {source_path}")
            destination.write(chunk)
    return _member_record(member_path, role, size, digest.hexdigest())


def _export_artwork(archive, source_value, project_path, member_stem, members):
    if not source_value:
        return None
    source_path = _resolve_source(source_value, project_path)
    mime_type = _detect_image(source_path)
    member_path = member_stem + _IMAGE_EXTENSIONS[mime_type]
    members.append(_write_file(archive, source_path, member_path, "asset", zipfile.ZIP_DEFLATED))
    return {"path": member_path, "media_type": mime_type}


def build_library(project, destination, *, project_path=None):
    """Build and fully re-inspect an immutable ``.odrlib`` package."""
    project = normalize_project(project)
    issues = validate_project(project, project_path)
    errors = [issue for issue in issues if issue.level == "error"]
    if errors:
        detail = "\n".join(f"{issue.location}: {issue.message}" for issue in errors[:20])
        raise OdrLibError(f"The project cannot be built yet:\n{detail}")
    destination = os.path.abspath(destination)
    if not destination.casefold().endswith(".odrlib"):
        destination += ".odrlib"
    source_paths = []
    if project["library"].get("artwork_path"):
        source_paths.append(_resolve_source(project["library"]["artwork_path"], project_path))
    for item in project["items"]:
        if item.get("artwork_path"):
            source_paths.append(_resolve_source(item["artwork_path"], project_path))
        source_paths.extend(
            _resolve_source(source["source_path"], project_path)
            for artifact in item["artifacts"] for source in artifact["sources"]
            if source["type"] == "embedded"
        )
    if any(os.path.normcase(path) == os.path.normcase(destination) for path in source_paths):
        raise OdrLibError("The output package cannot overwrite one of its own source files.")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".odrlib-build-", suffix=".tmp", dir=os.path.dirname(destination))
    os.close(fd)
    created_at = _now_iso()
    try:
        members = []
        exported_items = []
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            library = deepcopy(project["library"])
            library_artwork = _export_artwork(
                archive, library.pop("artwork_path", ""), project_path,
                "assets/library-cover", members,
            )
            if library_artwork:
                library["artwork"] = library_artwork
            library["updated_at"] = created_at

            for item in project["items"]:
                exported = deepcopy(item)
                item_artwork = _export_artwork(
                    archive, exported.pop("artwork_path", ""), project_path,
                    f"assets/items/{item['id']}", members,
                )
                if item_artwork:
                    exported["artwork"] = item_artwork
                exported_artifacts = []
                for artifact in item["artifacts"]:
                    exported_artifact = deepcopy(artifact)
                    exported_sources = []
                    embedded_record = None
                    for source in artifact["sources"]:
                        if source["type"] == "embedded":
                            source_path = _resolve_source(source["source_path"], project_path)
                            filename = _safe_component(
                                artifact.get("filename") or os.path.basename(source_path), "payload.bin"
                            )
                            member_path = f"payload/{item['id']}/{artifact['id']}/{filename}"
                            embedded_record = _write_file(
                                archive, source_path, member_path, "payload", zipfile.ZIP_STORED
                            )
                            members.append(embedded_record)
                            exported_sources.append({
                                "type": "embedded", "path": member_path,
                                "size": embedded_record["size"], "sha256": embedded_record["sha256"],
                            })
                        else:
                            exported_sources.append({"type": "https", "url": source["url"]})
                    exported_artifact["sources"] = exported_sources
                    if embedded_record:
                        exported_artifact["size"] = embedded_record["size"]
                        exported_artifact["sha256"] = embedded_record["sha256"]
                        if not exported_artifact.get("filename"):
                            exported_artifact["filename"] = os.path.basename(embedded_record["path"])
                    if not exported_artifact.get("media_type"):
                        guessed, _encoding = mimetypes.guess_type(exported_artifact.get("filename") or "")
                        exported_artifact["media_type"] = guessed or "application/octet-stream"
                    exported_artifacts.append(exported_artifact)
                exported["artifacts"] = exported_artifacts
                exported_items.append(exported)

            library_data = _json_bytes({"schema_version": 1, "library": library})
            items_data = _json_bytes({"schema_version": 1, "items": exported_items})
            collections_data = _json_bytes({"schema_version": 1, "collections": project["collections"]})
            if any(len(data) > MAX_CATALOG_BYTES for data in (library_data, items_data, collections_data)):
                raise OdrLibError("The generated catalog JSON exceeds the version 1 size limit.")
            members.extend((
                _write_bytes(archive, LIBRARY_NAME, "catalog", library_data),
                _write_bytes(archive, ITEMS_NAME, "catalog", items_data),
                _write_bytes(archive, COLLECTIONS_NAME, "catalog", collections_data),
            ))
            embedded_bytes = sum(member["size"] for member in members if member["role"] == "payload")
            artifact_count = sum(len(item["artifacts"]) for item in exported_items)
            online_sources = sum(
                1 for item in exported_items for artifact in item["artifacts"]
                for source in artifact["sources"] if source["type"] == "https"
            )
            if sum(member["size"] for member in members) > MAX_TOTAL_BYTES:
                raise OdrLibError("The generated package exceeds the 1 TiB uncompressed size limit.")
            optional_capabilities = []
            if embedded_bytes:
                optional_capabilities.append("embedded-payload")
            if online_sources:
                optional_capabilities.append("https-sources")
            extensions = {"required": [], "optional": []}
            if (library.get("update") or {}).get("feed_url"):
                # Kept as a hint for packages read by the earliest Alpha 2 build;
                # U1 is the authoritative declaration for current readers.
                optional_capabilities.append("update-feed-v1")
                extensions["optional"].append({
                    "id": UPDATE_EXTENSION_ID,
                    "version": UPDATE_EXTENSION_VERSION,
                })
            manifest = {
                "format": FORMAT_ID,
                "format_version": FORMAT_VERSION,
                "package_id": _new_id(),
                "created_at": created_at,
                "application": {"name": CREATOR_NAME, "version": CREATOR_VERSION},
                "library": {
                    "id": library["id"], "name": library["name"],
                    "revision": library["revision"], "version": library["version"],
                },
                "catalog": {
                    "items": len(exported_items), "collections": len(project["collections"]),
                    "artifacts": artifact_count, "embedded_bytes": embedded_bytes,
                    "online_sources": online_sources,
                },
                "capabilities": {
                    "required": ["catalog-v1"],
                    "optional": optional_capabilities,
                },
                "extensions": extensions,
                "members": sorted(members, key=lambda member: member["path"]),
            }
            manifest_data = _json_bytes(manifest)
            if len(manifest_data) > MAX_MANIFEST_BYTES:
                raise OdrLibError("The generated package manifest exceeds the version 1 size limit.")
            archive.writestr(MANIFEST_NAME, manifest_data, compress_type=zipfile.ZIP_DEFLATED)
        package = inspect_library(temporary)
        package_sha = _sha256_file(temporary)
        os.replace(temporary, destination)
        package = replace(package, path=destination)
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass

    feed_path = None
    package_url = project["publishing"].get("package_url")
    if (package.library.get("update") or {}).get("feed_url") and package_url:
        feed_path = os.path.splitext(destination)[0] + ".odrlib-feed.json"
        write_update_feed(
            package, destination, feed_path, package_url,
            project["publishing"].get("release_notes", ""), package_sha=package_sha,
        )
    return BuildResult(
        path=destination,
        size=os.path.getsize(destination),
        sha256=package_sha,
        package=package,
        warnings=tuple(issue for issue in issues if issue.level == "warning"),
        feed_path=feed_path,
    )


def _read_json_member(archive, name, maximum):
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise OdrLibError(f"The package is missing {name}.") from exc
    if info.file_size > maximum:
        raise OdrLibError(f"{name} is larger than the supported limit.")
    try:
        data = archive.read(info)
        return json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise OdrLibError(f"{name} is not valid UTF-8 JSON.") from exc


def _validate_archive_layout(archive):
    infos = archive.infolist()
    if not infos or len(infos) > MAX_MEMBERS:
        raise OdrLibError("The package contains an unsafe number of members.")
    names = []
    folded = set()
    total = 0
    for info in infos:
        name = _safe_member_name(info.filename)
        if not name or info.is_dir():
            raise OdrLibError(f"The package contains an unsafe member path: {info.filename!r}")
        key = name.casefold()
        if key in folded:
            raise OdrLibError(f"The package contains a duplicate member path: {name}")
        folded.add(key)
        names.append(name)
        if info.flag_bits & 0x1:
            raise OdrLibError("Encrypted ZIP members are not supported.")
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise OdrLibError(f"Unsupported ZIP compression for {name}.")
        if info.file_size < 0 or info.file_size > MAX_MEMBER_BYTES:
            raise OdrLibError(f"Package member is too large: {name}")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise OdrLibError("The package exceeds the total uncompressed size limit.")
        if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise OdrLibError(f"Package member has an unsafe compression ratio: {name}")
    return names


def inspect_library(path, *, verify_hashes=True):
    """Fully validate a published library and return its portable metadata."""
    path = os.path.abspath(path)
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise OdrLibError("The selected file is not a readable .odrlib ZIP package.") from exc
    with archive:
        names = _validate_archive_layout(archive)
        manifest = _read_json_member(archive, MANIFEST_NAME, MAX_MANIFEST_BYTES)
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT_ID:
            raise OdrLibError("The package manifest does not identify an ODeR Library.")
        if manifest.get("format_version") != FORMAT_VERSION:
            raise OdrLibError("This .odrlib format version is not supported.")
        capabilities = manifest.get("capabilities")
        if not isinstance(capabilities, dict) or capabilities.get("required") != ["catalog-v1"]:
            raise OdrLibError("The package requires unsupported capabilities.")
        optional_capabilities = capabilities.get("optional", [])
        if not isinstance(optional_capabilities, list) or not all(
                isinstance(value, str) for value in optional_capabilities):
            raise OdrLibError("The package capability declaration is invalid.")
        extensions = _inspect_extensions(manifest.get("extensions"))
        package_id = _valid_uuid(manifest.get("package_id"))
        if not package_id:
            raise OdrLibError("The package ID is invalid.")
        application = manifest.get("application")
        if not isinstance(application, dict):
            raise OdrLibError("The package does not identify its builder.")
        declared = manifest.get("members")
        if not isinstance(declared, list) or len(declared) != len(names) - 1:
            raise OdrLibError("The package member declaration is incomplete.")
        declared_by_path = {}
        for record in declared:
            if not isinstance(record, dict):
                raise OdrLibError("A package member declaration is invalid.")
            member_path = _safe_member_name(record.get("path"))
            role = str(record.get("role") or "")
            sha256 = str(record.get("sha256") or "").casefold()
            try:
                size = int(record.get("size"))
            except (TypeError, ValueError) as exc:
                raise OdrLibError("A package member size is invalid.") from exc
            if not member_path or member_path == MANIFEST_NAME or role not in _MEMBER_ROLES:
                raise OdrLibError("A package member declaration has an unsupported path or role.")
            if member_path in declared_by_path or not _SHA256_RE.fullmatch(sha256) or size < 0:
                raise OdrLibError("A package member declaration is duplicated or malformed.")
            declared_by_path[member_path] = {"role": role, "size": size, "sha256": sha256}
        actual_names = set(names) - {MANIFEST_NAME}
        if set(declared_by_path) != actual_names:
            raise OdrLibError("The package contains undeclared or missing members.")
        for required_name in (LIBRARY_NAME, ITEMS_NAME, COLLECTIONS_NAME):
            if (declared_by_path.get(required_name) or {}).get("role") != "catalog":
                raise OdrLibError(f"{required_name} must be declared as catalog data.")
        for member_path, record in declared_by_path.items():
            info = archive.getinfo(member_path)
            if info.file_size != record["size"]:
                raise OdrLibError(f"The declared size does not match {member_path}.")
            if verify_hashes:
                digest = hashlib.sha256()
                try:
                    with archive.open(info, "r") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
                    raise OdrLibError(f"Package member could not be read safely: {member_path}") from exc
                if digest.hexdigest() != record["sha256"]:
                    raise OdrLibError(f"The SHA-256 checksum does not match {member_path}.")

        library_doc = _read_json_member(archive, LIBRARY_NAME, MAX_CATALOG_BYTES)
        items_doc = _read_json_member(archive, ITEMS_NAME, MAX_CATALOG_BYTES)
        collections_doc = _read_json_member(archive, COLLECTIONS_NAME, MAX_CATALOG_BYTES)
        if not isinstance(library_doc, dict) or library_doc.get("schema_version") != 1 or not isinstance(library_doc.get("library"), dict):
            raise OdrLibError("library.json uses an unsupported schema.")
        if not isinstance(items_doc, dict) or items_doc.get("schema_version") != 1 or not isinstance(items_doc.get("items"), list):
            raise OdrLibError("The item catalog uses an unsupported schema.")
        if not isinstance(collections_doc, dict) or collections_doc.get("schema_version") != 1 or not isinstance(collections_doc.get("collections"), list):
            raise OdrLibError("The collection catalog uses an unsupported schema.")
        library = library_doc["library"]
        items = items_doc["items"]
        collections = collections_doc["collections"]
        if len(items) > MAX_ITEMS or len(collections) > MAX_COLLECTIONS:
            raise OdrLibError("The package catalog exceeds the supported item limits.")
        manifest_library = manifest.get("library")
        if not isinstance(manifest_library, dict):
            raise OdrLibError("The manifest library summary is missing.")
        library_id = _valid_uuid(library.get("id"))
        if not library_id or library_id != _valid_uuid(manifest_library.get("id")):
            raise OdrLibError("The library ID is invalid or does not match the manifest.")
        try:
            revision = int(library.get("revision"))
        except (TypeError, ValueError) as exc:
            raise OdrLibError("The library revision is invalid.") from exc
        if revision < 1 or revision != manifest_library.get("revision"):
            raise OdrLibError("The library revision does not match the manifest.")
        name = _clean_text(library.get("name"), 300)
        if not name or name != _clean_text(manifest_library.get("name"), 300):
            raise OdrLibError("The library name is missing or does not match the manifest.")
        version = _clean_text(library.get("version"), 100)
        if version != _clean_text(manifest_library.get("version"), 100):
            raise OdrLibError("The library version does not match the manifest.")
        for link in library.get("links") or []:
            if not _https_url(link):
                raise OdrLibError("The library contains an unsafe non-HTTPS link.")

        item_ids = set()
        artifact_ids = set()
        artifact_count = 0
        embedded_bytes = 0
        online_sources = 0
        for item in items:
            if not isinstance(item, dict) or not _valid_uuid(item.get("id")) or not _clean_text(item.get("title"), 300):
                raise OdrLibError("The package contains an invalid catalog item.")
            item_id = str(uuid.UUID(str(item["id"])))
            if item_id in item_ids:
                raise OdrLibError("The package contains duplicate item IDs.")
            item_ids.add(item_id)
            item_artwork = item.get("artwork") if isinstance(item.get("artwork"), dict) else {}
            if item_artwork.get("path"):
                record = declared_by_path.get(item_artwork["path"])
                if not record or record["role"] != "asset":
                    raise OdrLibError("An item's artwork is not a declared asset.")
                if record["size"] > MAX_ASSET_BYTES or not _detect_image_bytes(archive.read(item_artwork["path"])[:16]):
                    raise OdrLibError("An item's artwork is too large or uses an unsupported image type.")
            for link in item.get("links") or []:
                if not _https_url(link):
                    raise OdrLibError("An item contains an unsafe non-HTTPS link.")
            artifacts = item.get("artifacts")
            if not isinstance(artifacts, list) or len(artifacts) > MAX_ARTIFACTS_PER_ITEM:
                raise OdrLibError("A catalog item has an invalid artifact list.")
            for artifact in artifacts:
                artifact_count += 1
                if not isinstance(artifact, dict) or not _valid_uuid(artifact.get("id")):
                    raise OdrLibError("The package contains an invalid artifact.")
                artifact_id = _valid_uuid(artifact.get("id"))
                if artifact_id in artifact_ids:
                    raise OdrLibError("The package contains duplicate artifact IDs.")
                artifact_ids.add(artifact_id)
                sources = artifact.get("sources")
                if not isinstance(sources, list) or not sources or len(sources) > MAX_SOURCES_PER_ARTIFACT:
                    raise OdrLibError("An artifact has an invalid source list.")
                for source in sources:
                    if not isinstance(source, dict):
                        raise OdrLibError("An artifact source is invalid.")
                    if source.get("type") == "embedded":
                        member_path = _safe_member_name(source.get("path"))
                        record = declared_by_path.get(member_path)
                        if not record or record["role"] != "payload":
                            raise OdrLibError("An embedded artifact references an undeclared payload.")
                        if source.get("size") != record["size"] or source.get("sha256") != record["sha256"]:
                            raise OdrLibError("An embedded artifact's integrity metadata does not match its payload.")
                        embedded_bytes += record["size"]
                    elif source.get("type") == "https" and _https_url(source.get("url")):
                        online_sources += 1
                    else:
                        raise OdrLibError("An artifact uses an unsupported or unsafe source.")
        collection_ids = set()
        for collection in collections:
            if not isinstance(collection, dict) or not _valid_uuid(collection.get("id")) or not _clean_text(collection.get("name"), 300):
                raise OdrLibError("The package contains an invalid collection.")
            collection_id = str(uuid.UUID(str(collection["id"])))
            if collection_id in collection_ids:
                raise OdrLibError("The package contains duplicate collection IDs.")
            collection_ids.add(collection_id)
            if any(_valid_uuid(item_id) not in item_ids for item_id in collection.get("item_ids") or []):
                raise OdrLibError("A collection references an item that is not in the package.")
        counts = manifest.get("catalog")
        expected_counts = {
            "items": len(items), "collections": len(collections), "artifacts": artifact_count,
            "embedded_bytes": embedded_bytes, "online_sources": online_sources,
        }
        if not isinstance(counts, dict) or any(counts.get(key) != value for key, value in expected_counts.items()):
            raise OdrLibError("The manifest catalog counts do not match the package contents.")
        artwork = library.get("artwork") if isinstance(library.get("artwork"), dict) else {}
        artwork_path = artwork.get("path")
        if artwork_path:
            record = declared_by_path.get(artwork_path)
            if not record or record["role"] != "asset":
                raise OdrLibError("The library artwork is not a declared asset.")
            if record["size"] > MAX_ASSET_BYTES or not _detect_image_bytes(archive.read(artwork_path)[:16]):
                raise OdrLibError("The library artwork is too large or uses an unsupported image type.")
        update = library.get("update") if isinstance(library.get("update"), dict) else {}
        feed_url = update.get("feed_url") or None
        if feed_url and not _https_url(feed_url):
            raise OdrLibError("The library update feed does not use a valid HTTPS URL.")
        declared_u1 = any(
            extension.id == UPDATE_EXTENSION_ID
            and extension.version == UPDATE_EXTENSION_VERSION
            for extension in extensions
        )
        declared_update_extensions = [
            extension for extension in extensions if extension.id == UPDATE_EXTENSION_ID
        ]
        legacy_u1 = "update-feed-v1" in optional_capabilities
        if declared_u1 and not feed_url:
            raise OdrLibError("Extension U1 requires a valid HTTPS library update feed.")
        if feed_url and not declared_u1:
            if legacy_u1 and not declared_update_extensions:
                # Compatibility with packages created by the first Alpha 2 build.
                extensions = extensions + (ExtensionInfo(UPDATE_EXTENSION_ID, 1, False),)
            elif declared_update_extensions:
                # A future optional U version can be ignored while the core
                # catalog remains browsable. Do not apply its unknown feed.
                feed_url = None
            else:
                raise OdrLibError("A library update feed must be declared through extension U1.")
        return LibraryPackageInfo(
            path=path,
            package_id=package_id,
            created_at=_clean_text(manifest.get("created_at"), 100),
            created_by_name=_clean_text(application.get("name"), 200) or "Unknown builder",
            created_by_version=_clean_text(application.get("version"), 100),
            library_id=library_id,
            revision=revision,
            version=version,
            name=name,
            summary=_clean_text(library.get("summary"), 1000),
            creator=_clean_text(library.get("creator"), 300),
            category=_clean_text(library.get("category"), 200),
            tags=tuple(_string_list(library.get("tags"), maximum=50, item_limit=100)),
            artwork_path=artwork_path,
            update_feed_url=feed_url,
            item_count=len(items),
            collection_count=len(collections),
            artifact_count=artifact_count,
            embedded_bytes=embedded_bytes,
            online_source_count=online_sources,
            extensions=extensions,
            library=library,
            items=tuple(items),
            collections=tuple(collections),
            manifest=manifest,
        )


def write_update_feed(package, package_path, destination, package_url, release_notes="", *, package_sha=None):
    if not isinstance(package, LibraryPackageInfo):
        package = inspect_library(package_path)
    package_url = _https_url(package_url)
    if not package_url:
        raise OdrLibError("The package download URL must use HTTPS.")
    package_path = os.path.abspath(package_path)
    feed = {
        "format": FEED_FORMAT_ID,
        "format_version": FEED_FORMAT_VERSION,
        "library_id": package.library_id,
        "channel": _clean_text((package.library.get("update") or {}).get("channel"), 50) or "stable",
        "latest": {
            "revision": package.revision,
            "version": package.version,
            "published_at": package.created_at,
            "url": package_url,
            "size": os.path.getsize(package_path),
            "sha256": package_sha or _sha256_file(package_path),
            "minimum_reader": APP_VERSION,
            "release_notes": _clean_text(release_notes, 20_000),
        },
    }
    inspect_update_feed(feed)
    save_json(os.path.abspath(destination), feed, backup=False)
    return feed


def inspect_update_feed(value):
    """Validate an update-feed document or local JSON file without networking."""
    if isinstance(value, (str, os.PathLike)):
        path = os.path.abspath(os.fspath(value))
        try:
            if os.path.getsize(path) > MAX_MANIFEST_BYTES:
                raise OdrLibError("The update feed is larger than the supported limit.")
        except OSError as exc:
            raise OdrLibError("The update feed could not be read.") from exc
        value = load_json(path, None)
    if not isinstance(value, dict) or value.get("format") != FEED_FORMAT_ID:
        raise OdrLibError("The document is not an ODeR Library update feed.")
    if value.get("format_version") != FEED_FORMAT_VERSION:
        raise OdrLibError("This update-feed format version is not supported.")
    library_id = _valid_uuid(value.get("library_id"))
    if not library_id:
        raise OdrLibError("The update feed contains an invalid library ID.")
    latest = value.get("latest")
    if not isinstance(latest, dict):
        raise OdrLibError("The update feed does not contain a latest release.")
    try:
        revision = int(latest.get("revision"))
        size = int(latest.get("size"))
    except (TypeError, ValueError) as exc:
        raise OdrLibError("The update feed contains an invalid revision or package size.") from exc
    sha256 = str(latest.get("sha256") or "").casefold()
    url = _https_url(latest.get("url"))
    if revision < 1 or size < 1 or size > MAX_TOTAL_BYTES or not _SHA256_RE.fullmatch(sha256) or not url:
        raise OdrLibError("The update feed contains unsafe or incomplete package metadata.")
    return UpdateFeedInfo(
        library_id=library_id,
        channel=_clean_text(value.get("channel"), 50) or "stable",
        revision=revision,
        version=_clean_text(latest.get("version"), 100),
        published_at=_clean_text(latest.get("published_at"), 100),
        url=url,
        size=size,
        sha256=sha256,
        minimum_reader=_clean_text(latest.get("minimum_reader"), 100),
        release_notes=_clean_text(latest.get("release_notes"), 20_000),
    )


def import_folder(project, folder):
    """Add each file below a folder as one embedded catalog item."""
    project = normalize_project(project)
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        raise OdrLibError("Choose an existing folder to import.")
    collection_by_rel = {collection["name"]: collection for collection in project["collections"]}
    added = 0
    for root, directories, files in os.walk(folder):
        directories.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for filename in files:
            source_path = os.path.join(root, filename)
            item = new_item(title=os.path.splitext(filename)[0] or filename)
            item["category"] = "Software" if os.path.splitext(filename)[1].casefold() in {".exe", ".msi", ".zip", ".7z", ".rar"} else ""
            item["artifacts"].append(new_artifact(name=filename, embedded_path=source_path))
            project["items"].append(item)
            relative_parent = os.path.relpath(root, folder)
            if relative_parent != ".":
                collection_name = relative_parent.replace("\\", " / ").replace("/", " / ")
                collection = collection_by_rel.get(collection_name)
                if collection is None:
                    collection = new_collection(name=collection_name)
                    collection_by_rel[collection_name] = collection
                    project["collections"].append(collection)
                collection["item_ids"].append(item["id"])
            added += 1
            if len(project["items"]) >= MAX_ITEMS:
                return project, added
    return project, added
