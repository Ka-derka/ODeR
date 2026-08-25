# ODeR 1.1.0 Alpha 3 — T-extended libraries

Alpha 3 turns `.odrlib` into a practical peer-to-peer sharing format while keeping the stable version 1 container intact. Torrent support is the independently versioned **T1 extension**, so it can be used alone or together with **U1** self-updating libraries.

## Highlights

- Open and validate T1 `.odrlib` packages with embedded hybrid v1/v2 torrent metadata.
- Choose **Torrent** beside bundled and HTTPS sources in curated-library tabs.
- Download only the selected file through the normal Downloads screen, with progress, pause, retry, partial-data reuse, and the usual recreated folder structure.
- Verify the completed file against both its declared byte size and SHA-256 before placing it in Downloads.
- Control DHT, local peer discovery, UPnP, NAT-PMP, peer limits, and upload/download limits in Settings.
- Keep imports passive: installing or opening a T1 library never starts a torrent.
- Stop the torrent when the selected file completes; Alpha 3 does not silently keep seeding.

## Format hardening

ODeR cross-checks the T1 extension document, embedded `.torrent`, v1/v2 info hashes, file indices, paths, sizes, hashes, artifact IDs, ZIP declarations, and required/optional extension rules before installing a library. Torrent-only files make T1 required; packages with complete bundled or HTTPS fallbacks may declare it optional.

## ODeR Creator 2026.0.2a

The companion Creator can scan a chosen folder and all subfolders into one checklist. Each file can be included in the catalog, bundled in the `.odrlib`, added to the torrent, or offered through HTTPS mirrors. Torrent is selected by default and bundling is opt-in.

Creator automatically builds the metainfo, embeds and maps it as T1, calculates each file's size and SHA-256, and writes a standalone `.torrent` beside the `.odrlib`. Curators can configure tracker tiers, HTTPS web seeds, private mode, piece size, and a comment before publishing.

Multi-file hybrid torrents correctly ignore libtorrent's internal alignment files while retaining the native indexes of every real file. This prevents larger folder imports from failing with an incomplete generated file map.

## Notes for testers

- This is a preview release; choose **Preview releases** in ODeR's update settings.
- A torrent still needs reachable peers, a tracker, a web seed, or DHT availability. Creating metainfo does not upload or seed the source files automatically.
- DHT and local discovery reveal participation in a torrent swarm to peers. Review the new Torrent Downloads settings before testing sensitive material.
- Windows builds are installer-only. macOS app/DMG builds remain available through the release workflow.
