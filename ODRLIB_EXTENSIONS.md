# ODeR Library v1 extensions

The `.odrlib` version 1 container and catalog are the stable foundation. Extensions add independently versioned behaviour without changing the filename or pretending that a compatible feature is a new container generation.

## Manifest declaration

```json
"extensions": {
  "required": [],
  "optional": [
    {"id": "U", "version": 1}
  ]
}
```

The display name is the ID followed by its version: `U1`, `T1`, and so on. ODeR reserves one-letter IDs. Experimental or third-party extensions should use a distinctive uppercase hyphenated ID such as `X-EXAMPLE` and must not reuse an ODeR ID.

An extension belongs in `required` when ignoring it would make the library incomplete, misleading, or unsafe. It belongs in `optional` only when the core catalog remains useful without it. Readers reject unsupported required extensions before import. They may preserve and ignore unsupported optional extensions.

An ID can appear only once. Versions are positive integers and are scoped to the ID; U1 and T1 evolve independently. A breaking change to the ZIP/container or catalog foundation increments the core `format_version` instead.

## U1 — verified online updates

Status: implemented in ODeR 1.1.0-alpha.2 and ODeR Creator 2026.0.1a.

U1 is optional because a library remains browsable when updating is unavailable. It requires a valid HTTPS `library.update.feed_url`. The feed identifies the permanent library UUID, monotonically increasing revision, complete package size and SHA-256, download URL, minimum reader, and release notes.

ODeR downloads an update to temporary storage, verifies the feed metadata and complete `.odrlib`, confirms the permanent library identity and newer revision, previews changes, and only then replaces the managed package. User downloads, favorites, and preferences stay local.

## T1 — BitTorrent sources

Status: reserved for Alpha 3; not yet implemented or accepted as a required extension.

The planned T1 extension will allow Creator to build torrent metadata from selected bundled/source files, embed or reference that metadata in the package, and add torrent-backed artifact sources. The resulting `.odrlib` should be ready for both ODeR and redistribution without a separate preparation step.

The Alpha 3 specification must define info-hash versions, trackers/web seeds, file-to-artifact mapping, magnet/torrent handling, piece verification, safe download roots, seeding consent, and privacy controls. It must also define requirement rules:

- T1 may be optional when every torrent-backed artifact has a complete core `embedded` or `https` fallback.
- T1 must be required when any advertised artifact depends on BitTorrent to be obtainable.
- U1 and T1 can coexist. A U1 update replaces the package metadata; T1 moves the declared content. Neither extension weakens core member hashes or path rules.

Alpha 2 reserves the ID and the extension mechanism only. It does not parse torrent sources, create torrents, start a client, seed data, or contact trackers.
