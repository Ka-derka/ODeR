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

Status: implemented in ODeR 1.1.0-alpha.2+ and ODeR Creator 2026.0.1a+.

U1 is optional because a library remains browsable when updating is unavailable. It requires a valid HTTPS `library.update.feed_url`. The feed identifies the permanent library UUID, monotonically increasing revision, complete package size and SHA-256, download URL, minimum reader, and release notes.

ODeR downloads an update to temporary storage, verifies the feed metadata and complete `.odrlib`, confirms the permanent library identity and newer revision, previews changes, and only then replaces the managed package. User downloads, favorites, and preferences stay local.

## T1 — BitTorrent sources

Status: implemented in ODeR 1.1.0-alpha.3 and ODeR Creator 2026.0.2a.

T1 embeds a complete hybrid BitTorrent metainfo file at `torrents/library.torrent` and a portable mapping document at `extensions/T1.json`. Creator also writes the same metainfo beside the package as a standalone `.torrent`, making the result ready to seed or redistribute with an ordinary BitTorrent client. Trackers may use HTTP, HTTPS, or UDP; web seeds may use HTTP or HTTPS, with torrent pieces and ODeR's final SHA-256 providing content-integrity checks.

Each mapped file records its catalog artifact UUID, torrent file index, torrent-relative path, byte size, and SHA-256. The extension document records the torrent UUID, v1 and v2 info hashes, name, privacy flag, piece length, tracker tiers, HTTPS web seeds, and metainfo member path. ODeR checks all of these against the decoded torrent and core catalog before importing a package.

Requirement rules:

- T1 may be optional when every torrent-backed artifact has a complete core `embedded` or `https` fallback.
- T1 must be required when any advertised artifact depends on BitTorrent to be obtainable.
- U1 and T1 can coexist. A U1 update replaces the package metadata; T1 moves the declared content. Neither extension weakens core member hashes or path rules.

ODeR never starts a torrent during package import. A job starts only when the user chooses a Torrent source, and it requests only that mapped file. Partial data remains in a private staging folder for pause/retry, then the finished file is checked against its T1 byte size and SHA-256 before being moved into the normal structured download destination. The Alpha 3 client stops after completion; it does not silently keep seeding.

DHT and local peer discovery are enabled by default. UPnP and NAT-PMP are off by default. All are explicit user preferences alongside connection and transfer limits. Joining a swarm reveals the torrent info hash and the user's peer address to other participants; Creator and ODeR surface these controls rather than treating torrent transport as equivalent to an HTTPS request.
