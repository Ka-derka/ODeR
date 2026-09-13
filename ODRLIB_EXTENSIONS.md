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

An ID can appear only once. Versions are positive integers, with the explicitly supported string `"1.1"` for U1.1 (never a JSON float), and are scoped to the ID; U1 and T1 evolve independently. A breaking change to the ZIP/container or catalog foundation increments the core `format_version` instead.

## U1.1 — signed HTTP/HTTPS updates

Status: implemented for testing. Requires `{"id":"U","version":"1.1"}` in
`extensions.required`, `library.update.protocol = "U1.1"`, and an Ed25519 public
signing identity in `library.update.signing_key`. Legacy readers reject this
required extension rather than silently treating its feeds as unsigned U1.

HTTP is allowed for signed feeds, packages and T2 metainfo; it is not encrypted.
Importing does not establish trust. The reader explicitly pins the publisher key
before networking, checks feed signatures/expiry, and retains revision and issue-time
high-water marks. Unexpected keys and unsigned downgrades are rejected.
See [U1.1 setup, wire format and test checklist](U11_SIGNED_UPDATES.md).

## U1 — verified online updates

Status: implemented in ODeR 1.1.0-alpha.2+ and ODeR Creator 2026.0.1a+.

U1 is optional because a library remains browsable when updating is unavailable. It requires a valid HTTPS `library.update.feed_url`. The feed identifies the permanent library UUID, monotonically increasing revision, complete package size and SHA-256, download URL, minimum reader, and release notes.

ODeR downloads an update to temporary storage, verifies the feed metadata and complete `.odrlib`, confirms the permanent library identity and newer revision, previews changes, and only then replaces the managed package. User downloads, favorites, and preferences stay local.

## T1 — BitTorrent sources

Status: implemented in ODeR 1.1.0-alpha.3 and ODeR Creator 2026.0.2a.

T1 embeds a complete hybrid BitTorrent metainfo file at `torrents/library.torrent` and a portable mapping document at `extensions/T1.json`. Creator also writes the same metainfo beside the package as a standalone `.torrent`, making the result ready to seed or redistribute with an ordinary BitTorrent client. Trackers may use HTTP, HTTPS, or UDP; web seeds may use HTTP or HTTPS, with torrent pieces and ODeR's final SHA-256 providing content-integrity checks.

Creator feeds files through libtorrent's canonical file-entry builder. Because hybrid torrent construction can insert padding and reorder a directory tree, T1 maps each catalog artifact back to the generated file by its complete torrent path and records libtorrent's final native index.

Each mapped file records its catalog artifact UUID, torrent file index, torrent-relative path, byte size, and SHA-256. The extension document records the torrent UUID, v1 and v2 info hashes, name, privacy flag, piece length, tracker tiers, HTTPS web seeds, and metainfo member path. ODeR checks all of these against the decoded torrent and core catalog before importing a package.

Requirement rules:

- T1 may be optional when every torrent-backed artifact has a complete core `embedded` or `https` fallback.
- T1 must be required when any advertised artifact depends on BitTorrent to be obtainable.
- U1 and T1 can coexist. A U1 update replaces the package metadata; T1 moves the declared content. Neither extension weakens core member hashes or path rules.

ODeR never starts a torrent during package import. A job starts only when the user chooses a Torrent source, and it requests only that mapped file. Partial data remains in a private staging folder for pause/retry. The finished file is checked against its T1 byte size and SHA-256, exposed at the normal structured download destination, and kept seeding while its finished entry remains in Downloads. ODeR restores those seeds after restart. Removing the entry or using **Clear finished** stops its seed and removes only ODeR's private staging link/copy; the visible downloaded file is kept.

DHT and local peer discovery are enabled by default. UPnP and NAT-PMP are off by default. All are explicit user preferences alongside connection and transfer limits. Joining a swarm reveals the torrent info hash and the user's peer address to other participants; Creator and ODeR surface these controls rather than treating torrent transport as equivalent to an HTTPS request.

## T2 — torrent-delivered library updates (development)

T2 is a superset of T1. Its manifest uses `{"id": "T", "version": 2}` instead of T1; both versions must not be declared together. T2 retains T1's catalog-source layout and validation (`extensions/T1.json` and embedded payload metainfo), and requires U1 and its HTTPS feed. A T2 library with no torrent-backed catalog files may omit T1.json. T2 must be required when a catalog artifact depends exclusively on torrent delivery; otherwise it may be optional so older readers can use the core sources and HTTPS U1 updates.

The first implementation keeps the U1 feed schema at version 1, with an optional `latest.torrent` object. The normal `latest.url`, `size`, `sha256`, `revision`, `library_id` and reader requirements remain authoritative. Example additional object:

```json
"torrent": {
  "extension": "T2",
  "url": "https://example.org/releases/library.odrlib.torrent",
  "size": 420,
  "sha256": "<64 hexadecimal characters: SHA-256 of the .torrent file>",
  "path": "library.odrlib"
}
```

The example size/hash must be replaced with actual values; Creator writes them automatically. This object describes metainfo, while `latest.size`/`latest.sha256` describe the complete package. The metainfo must contain exactly one bare `.odrlib` filename, with the feed's package size and no additional files, directories, symlinks, or padding. Both metainfo and complete package are verified before installation. HTTPS remains the bootstrap and fallback; this is not a feed discovered through DHT and it is not a replacement for publisher authentication/signatures.

Creator builds the package first, then generates `<package>.odrlib.torrent` from its finished bytes. The package cannot embed its own update torrent or hash. The ordinary `<package>.torrent` still describes catalog payloads and is separate from the package-update torrent.

ODeR's update dialog offers peer delivery explicitly. Transfers use disposable staging and existing torrent network preferences. After 20 seconds without downloaded-byte progress, or a ten-minute overall transfer limit, ODeR falls back to the HTTPS package. The entire package is rechecked against the feed and inspected before replacing the installed revision. Old payload metainfo is retained locally so existing downloads/seeds remain attached to their original swarm.

Current boundaries: checks and installation remain reader-triggered; catalog updates do not silently download new files, overwrite changed local files, delete removed files, or migrate seeds to new info hashes. The temporary package-transfer session stops on completion; continuous redistribution of packages is currently done through a normal torrent client. Scheduled checks, persistent package seeding, publisher signatures, and content reconciliation remain future work. Test Mac runtime compatibility before promoting this prototype to a release.

### Publishing with Creator

1. Open the existing `.odrproj`, retain its library identity and increase Revision.
2. In **Publishing and updates**, enter the feed URL, package HTTPS URL, and release notes.
3. Enable **Share library updates through torrents (T2)** and enter the HTTPS URL for the package update `.torrent`.
4. Build. Publish the `.odrlib` and `.odrlib.torrent` at those addresses. Use revision-specific package/metainfo URLs so older feeds keep referring to matching bytes.
5. Add the package update torrent to a torrent client, choosing the build output directory as its data location, and verify it is seeding. If there is also a catalog payload torrent, seed it separately from its source folder.
6. Publish the generated `.odrlib-feed.json` at the stable feed address last.
7. In ODeR, choose **Check for updates**, enable peer delivery in the prompt, and apply the revision. Test from another connection as well as localhost.
