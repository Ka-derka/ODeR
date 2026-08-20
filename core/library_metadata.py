"""Validation helpers for optional, portable library presentation metadata."""
from __future__ import annotations

import base64
import binascii
import re


MAX_DESCRIPTION_LENGTH = 4000
MAX_CREATOR_LENGTH = 200
MAX_CATEGORY_LENGTH = 100
MAX_TAGS = 20
MAX_TAG_LENGTH = 50
MAX_ARTWORK_BYTES = 1024 * 1024

_ARTWORK_URI = re.compile(
    r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\r\n]+)$",
    re.IGNORECASE,
)


class LibraryMetadataError(ValueError):
    """Library presentation metadata is malformed or exceeds safe limits."""


def _text(value, limit, field, strict):
    if value is None:
        return ""
    if not isinstance(value, str):
        if strict:
            raise LibraryMetadataError(f"Library {field} must be text.")
        value = str(value)
    value = value.replace("\x00", "").strip()
    if len(value) > limit:
        if strict:
            raise LibraryMetadataError(f"Library {field} is too long.")
        value = value[:limit].rstrip()
    return value


def decode_artwork_data_uri(value):
    """Return ``(mime_type, bytes)`` for a validated artwork data URI."""
    if not value:
        return None
    if not isinstance(value, str):
        raise LibraryMetadataError("Library artwork must be an embedded image.")
    match = _ARTWORK_URI.fullmatch(value.strip())
    if not match:
        raise LibraryMetadataError("Library artwork is not a supported PNG, JPEG, or WebP image.")
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise LibraryMetadataError("Library artwork contains invalid base64 data.") from exc
    if not data or len(data) > MAX_ARTWORK_BYTES:
        raise LibraryMetadataError("Library artwork is empty or larger than 1 MiB.")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        detected = "image/jpeg"
    elif len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        detected = "image/webp"
    else:
        raise LibraryMetadataError("Library artwork does not contain a supported image file.")
    if match.group(1).lower() != detected:
        raise LibraryMetadataError("Library artwork type does not match its image data.")
    return detected, data


def artwork_data_uri(mime_type, data):
    """Create a canonical data URI after validating an encoded artwork image."""
    encoded = base64.b64encode(bytes(data)).decode("ascii")
    value = f"data:{str(mime_type).lower()};base64,{encoded}"
    detected, _ = decode_artwork_data_uri(value)
    return value.replace(str(mime_type).lower(), detected, 1)


def normalize_library_metadata(value, *, strict=False):
    """Normalize optional metadata while keeping old profiles forward-compatible."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        if strict:
            raise LibraryMetadataError("Library metadata must be an object.")
        return {}

    result = {}
    for key, limit, label in (
        ("description", MAX_DESCRIPTION_LENGTH, "description"),
        ("creator", MAX_CREATOR_LENGTH, "creator or curator"),
        ("category", MAX_CATEGORY_LENGTH, "category"),
    ):
        normalized = _text(value.get(key), limit, label, strict)
        if normalized:
            result[key] = normalized

    raw_tags = value.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split(",")
    if not isinstance(raw_tags, (list, tuple)):
        if strict:
            raise LibraryMetadataError("Library tags must be a list of text values.")
        raw_tags = []
    tags = []
    seen = set()
    for raw in raw_tags:
        tag = _text(raw, MAX_TAG_LENGTH, "tag", strict)
        folded = tag.casefold()
        if tag and folded not in seen:
            tags.append(tag)
            seen.add(folded)
        if len(tags) >= MAX_TAGS:
            if strict and len(raw_tags) > MAX_TAGS:
                raise LibraryMetadataError(f"A library can have at most {MAX_TAGS} tags.")
            break
    if tags:
        result["tags"] = tags

    artwork = value.get("artwork_data_uri")
    if artwork:
        try:
            mime_type, data = decode_artwork_data_uri(artwork)
            result["artwork_data_uri"] = artwork_data_uri(mime_type, data)
        except LibraryMetadataError:
            if strict:
                raise
    return result
