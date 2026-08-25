# ODeR Library (`.odrlib`) format version 1

Status: written by ODeR Creator 2026.0.1a and read by ODeR 1.1.0-alpha.2.

An `.odrlib` file is an immutable ZIP/ZIP64 container for a curated catalog, its artwork, optional bundled files, and references to downloads. It is intentionally different from `.oder`, which represents one cached web-directory index. Format version 1 is a stable core with independently versioned extensions; features such as online updating and future BitTorrent sources do not require an `.odrlib2` rename.

## Container layout

```text
manifest.json
library.json
catalog/items-0001.json
catalog/collections.json
assets/library-cover.png|jpg|webp
assets/items/<item UUID>.png|jpg|webp
payload/<item UUID>/<artifact UUID>/<filename>
licenses/...
```

Only `manifest.json`, `library.json`, `catalog/items-0001.json`, and `catalog/collections.json` are required. Assets, payloads, and license files are optional. Version 1 readers must not infer undeclared content from ZIP paths.

All paths use `/`, are relative, and may not contain empty, `.` or `..` components. Duplicate paths, case-insensitive duplicates, directory entries, encrypted members, absolute paths, backslashes, and undeclared members are invalid. Creator emits JSON and assets with DEFLATE compression and stores payload files without recompression.

## Manifest

`manifest.json` identifies the format and declares every other member:

```json
{
  "format": "oder-library",
  "format_version": 1,
  "package_id": "f73b87a3-6236-458f-a58c-befdc8d4fb26",
  "created_at": "2026-08-20T12:00:00Z",
  "application": {
    "name": "ODeR Creator",
    "version": "2026.0.1a"
  },
  "library": {
    "id": "726f470c-e318-4fda-99e5-e6412f851f83",
    "name": "Example Library",
    "revision": 3,
    "version": "Summer 2026"
  },
  "catalog": {
    "items": 20,
    "collections": 4,
    "artifacts": 27,
    "embedded_bytes": 123456789,
    "online_sources": 12
  },
  "capabilities": {
    "required": ["catalog-v1"],
    "optional": ["embedded-payload", "https-sources", "update-feed-v1"]
  },
  "extensions": {
    "required": [],
    "optional": [
      {"id": "U", "version": 1}
    ]
  },
  "members": [
    {
      "path": "library.json",
      "role": "catalog",
      "size": 1200,
      "sha256": "<64 lowercase hexadecimal characters>"
    }
  ]
}
```

`package_id` changes for every build. `library.id` remains permanent across every revision of the same library. `library.revision` is a monotonically increasing positive integer used for reliable update ordering; `library.version` is a curator-controlled display label.

Every member except `manifest.json` must appear exactly once in `members`. Supported roles are `catalog`, `asset`, `payload`, and `license`. Size and SHA-256 must match the uncompressed member data.

Readers reject unknown required capabilities. Unknown optional capabilities may be ignored when doing so cannot change the meaning or integrity of recognized content.

## Extension model

`extensions.required` and `extensions.optional` contain records with an uppercase extension `id` and a positive integer `version`. The short display form joins them, so update extension `U` version `1` is shown as `U1`.

- A reader must reject an unknown or unsupported required extension before installing the package.
- A reader may retain and ignore an unknown optional extension when the core catalog remains meaningful without it.
- An extension ID may be declared only once across both lists.
- Extensions add behaviour and source mechanisms; they do not silently weaken core path, size, member, or checksum checks.
- A package without `extensions` is valid legacy `.odrlib` v1. Early Alpha 2 packages that combine `update-feed-v1` with a valid feed URL are interpreted as U1.

Alpha 2 implements `U1` (verified HTTPS update feeds). `T1` is reserved for Alpha 3's BitTorrent source and creation contract and is intentionally not accepted as a required extension yet. A future incompatible container or catalog redesign may increment `format_version`; adding a known extension does not.

The extension lifecycle, authoring rules, U1 contract, and Alpha 3 T1 boundary are documented in [ODRLIB_EXTENSIONS.md](ODRLIB_EXTENSIONS.md).

## Library metadata

`library.json` contains:

```json
{
  "schema_version": 1,
  "library": {
    "id": "726f470c-e318-4fda-99e5-e6412f851f83",
    "name": "Example Library",
    "summary": "A short description.",
    "description": "A longer description.",
    "creator": "Example Curator",
    "category": "Software",
    "tags": ["shareware", "preservation"],
    "languages": ["English"],
    "links": ["https://example.org/library"],
    "license": {
      "name": "Mixed / see individual items",
      "url": "https://example.org/rights"
    },
    "version": "Summer 2026",
    "revision": 3,
    "created_at": "2026-08-01T12:00:00Z",
    "updated_at": "2026-08-20T12:00:00Z",
    "artwork": {
      "path": "assets/library-cover.webp",
      "media_type": "image/webp"
    },
    "update": {
      "feed_url": "https://example.org/library.odrlib-feed.json",
      "channel": "stable"
    }
  }
}
```

Remote links and update URLs use HTTPS. Artwork is PNG, JPEG, or WebP and must be a declared `asset` member.

## Items, artifacts, and sources

`catalog/items-0001.json` contains an `items` array. Every item has a permanent UUID, title, optional descriptive metadata, rights information, artwork, and zero or more artifacts.

```json
{
  "schema_version": 1,
  "items": [
    {
      "id": "840169ee-9f43-46b0-893c-71a8338bfb25",
      "title": "Example Utility",
      "summary": "Portable system utility.",
      "description": "",
      "creator": "Example Publisher",
      "version": "2.1",
      "category": "Utilities",
      "tags": ["portable"],
      "platform": "Windows",
      "architecture": "x86-64",
      "license": {"name": "Freeware", "url": ""},
      "links": ["https://example.org/utility"],
      "artifacts": [
        {
          "id": "72756645-f0d4-4859-801c-4305dbd86af1",
          "name": "Windows portable",
          "filename": "utility.zip",
          "media_type": "application/zip",
          "platform": "Windows",
          "architecture": "x86-64",
          "size": 123456,
          "sha256": "<64 lowercase hexadecimal characters>",
          "sources": [
            {
              "type": "embedded",
              "path": "payload/840169ee-9f43-46b0-893c-71a8338bfb25/72756645-f0d4-4859-801c-4305dbd86af1/utility.zip",
              "size": 123456,
              "sha256": "<same SHA-256>"
            },
            {
              "type": "https",
              "url": "https://example.org/utility.zip"
            }
          ]
        }
      ]
    }
  ]
}
```

Version 1 supports `embedded` and `https` sources. A single artifact can offer both, allowing the bundled copy to work offline while retaining an official or mirrored online source. An embedded source must point to a declared `payload` member and repeat its exact size and SHA-256. Online-only artifacts may omit size and SHA-256, although Creator warns because integrity cannot then be checked before download.

ODeR treats artifacts as downloads. Packages cannot request execution, installation, post-processing, scripts, registry changes, or elevated privileges.

## Collections

`catalog/collections.json` contains named groups of item UUIDs:

```json
{
  "schema_version": 1,
  "collections": [
    {
      "id": "027489e1-4bc7-470d-a0b8-a37dc38bc626",
      "name": "Essentials",
      "summary": "Recommended starting points.",
      "description": "",
      "item_ids": ["840169ee-9f43-46b0-893c-71a8338bfb25"]
    }
  ]
}
```

Every referenced item must exist in the package.

## U1: update feed

When U1 is declared, `library.update.feed_url` is required and must use HTTPS. Creator can emit a small adjacent JSON feed:

```json
{
  "format": "oder-library-update-feed",
  "format_version": 1,
  "library_id": "726f470c-e318-4fda-99e5-e6412f851f83",
  "channel": "stable",
  "latest": {
    "revision": 3,
    "version": "Summer 2026",
    "published_at": "2026-08-20T12:00:00Z",
    "url": "https://example.org/library.odrlib",
    "size": 123456789,
    "sha256": "<SHA-256 of the complete .odrlib file>",
    "minimum_reader": "1.1.0-alpha.2",
    "release_notes": "Added five preservation tools."
  }
}
```

ODeR matches `library_id`, compares the integer revision, downloads to a temporary file, verifies the complete package hash and package manifest, previews catalog changes, and only then replaces the local catalog. Favorites, downloads, and local preferences are not package members and remain local.

Publisher signatures are reserved as an additive optional version 1 capability. Unsigned libraries remain valid for direct and community sharing.

## Creator project format

An `.odrproj` file is editable Creator state, not a distributable library. It contains source paths and publishing settings and may create a `.bak` recovery copy when saved. Local paths inside the project folder are stored relatively; sources elsewhere remain absolute. Projects never embed credentials or publisher private keys.

Consumers should receive `.odrlib`, not `.odrproj`.

## Safety limits implemented by Creator 2026.0.1a and ODeR 1.1.0-alpha.2

- 250,000 ZIP members
- 200,000 catalog items
- 50,000 collections
- 200 artifacts per item
- 32 sources per artifact
- 128 GiB per member
- 1 TiB total uncompressed data
- 16 MiB per artwork asset
- 500:1 maximum compression ratio
- ZIP Stored and DEFLATE compression only
- HTTPS remote sources only
- complete declared-member size and SHA-256 verification

These are reader safety ceilings rather than recommendations. Creators should split unwieldy catalogs into focused libraries where practical.
