# ODeR directory package format

This document defines version 1 of the user-facing `.oder` interchange format. It is intended to keep exported directories portable between ODeR releases and to let directory owners publish a validated index.

## Container

An `.oder` file is a ZIP or ZIP64 container. Version 1 permits exactly these root-level members:

| Member | Required | Purpose |
| --- | --- | --- |
| `manifest.json` | Yes | Package identity, version, scope, checksums and counts |
| `profile.json` | Yes | Portable directory definition |
| `cache.sqlite3` | Full packages only | Consistent cached directory index |

Member names are case-sensitive. Directories, duplicate names, encrypted entries, absolute paths, traversal paths, and unknown members are rejected. Readers must not rely on member order or a particular ZIP compression method.

Both JSON files are UTF-8. Each is limited to 2 MiB. The extracted cache is limited to 8 GiB.

## Manifest version 1

`manifest.json` contains:

```json
{
  "format": "oder-directory",
  "format_version": 1,
  "package_type": "definition",
  "scope": "directory",
  "created_at": "2026-08-20T00:00:00Z",
  "application": {
    "name": "ODeR",
    "version": "0.20.0"
  },
  "profile": {
    "source_profile_id": "optional-source-id",
    "name": "Example archive",
    "base_url": "https://example.com/files/"
  },
  "contents": {
    "profile": {
      "path": "profile.json",
      "size": 512,
      "sha256": "64-lowercase-hex-characters"
    }
  }
}
```

- `package_type` is `definition` or `full`. A full package must contain `cache.sqlite3`; a definition package must not.
- `scope` is `directory` or `subtree`.
- `created_at` is a timezone-aware ISO 8601 timestamp.
- `contents.profile` records the exact uncompressed byte size and SHA-256 hash of `profile.json`.
- A full package also has `contents.cache`, with `path`, `size`, `sha256`, and integer `counts` for `entries`, `folders`, and `files`.
- The manifest profile summary must agree with `profile.json`.

Additional JSON properties may be added in a compatible ODeR release. Readers should ignore properties they do not understand, but all version 1 validation rules still apply.

## Profile version 1

`profile.json` contains:

```json
{
  "schema_version": 1,
  "source_profile_id": "optional-source-id",
  "name": "Example archive",
  "base_url": "https://example.com/files/",
  "settings": {},
  "metadata": {
    "description": "A curated collection of public-domain software.",
    "creator": "Example curator",
    "category": "Software",
    "tags": ["shareware", "preservation"],
    "artwork_data_uri": "data:image/jpeg;base64,..."
  }
}
```

`base_url` must be an absolute HTTP or HTTPS URL and is normalized to a trailing slash. `source_profile_id` identifies the originating local profile when available and is used only to detect import conflicts. It is not used as the new local ID when importing as a copy.

A full package may also contain `cache_state`, which carries nonessential crawl metadata such as the last crawl time and recent history. A subtree definition may contain `source_directory` provenance. Neither changes the package's authority: the validated base URL and cache contents remain decisive.

ODeR 1.1 adds the optional `metadata` object without changing profile schema 1. Text lengths, tag counts, and embedded artwork are bounded; artwork must be a validated PNG, JPEG, or WebP image no larger than 1 MiB. Because version 1 readers ignore additional JSON properties, ODeR 1.0 can still open these packages and safely ignores presentation fields it does not understand.

## Cached index

`cache.sqlite3` is an ODeR SQLite cache snapshot. Import validation requires:

- the SQLite file signature and a successful integrity check;
- `meta` and `nodes` tables with the required node columns;
- a `meta.base_url` exactly matching the normalized profile base URL;
- actual entry, folder, and file counts matching the manifest;
- the exact byte size and SHA-256 digest recorded in the manifest.

Downloaded files, credentials, application-wide settings, favorites, and unrelated directories are never included.

## Compatibility and failure behavior

ODeR 0.20 and newer support format version 1 and profile schema version 1. Unsupported future versions are rejected without importing or replacing data. A future incompatible layout or changed field meaning requires a new `format_version`; a changed profile payload requires a new `schema_version`.

Import is staged and validated before profiles or caches are changed. Replacing an existing directory restores the previous profile and cache if the operation fails. Conflicts by original profile ID or normalized base URL require an explicit choice to replace the matching directory or import a separate copy.

Directory-hosted packages use the same format and validation rules. See [HOSTING.md](HOSTING.md) for discovery and publishing details.
