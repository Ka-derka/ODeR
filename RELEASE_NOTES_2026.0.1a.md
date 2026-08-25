# ODeR Creator 2026.0.1a — First Creator alpha

This preview begins ODeR's calendar-style release numbering and introduces the first usable version of **ODeR Creator**, a separate authoring workstation for curators and archivists. The normal ODeR application remains focused on indexing and browsing libraries.

## ODeR Creator

- Create, save, reopen, and drag-and-drop editable `.odrproj` projects.
- Describe a library with artwork, curator, category, tags, languages, links, rights, version, and independent numeric revision.
- Organize content as folders and files, with folder selection built directly into file creation and editing.
- Edit each file's metadata, artwork, platform, architecture, license, bundled content, HTTPS mirrors, checksum, and expected size on one screen.
- Paste bare domains such as `example.org/files`; Creator adds `https://` automatically while still rejecting explicitly insecure HTTP links.
- Import an entire local folder while retaining its visible folder-and-file structure.
- Validate missing sources, unsafe links, invalid artwork, duplicate identities, broken folders, and weak online-only integrity before publishing.
- Export a complete `.odrlib` package and re-open it through the strict reader before reporting a successful build.
- Generate a companion update feed and declare the `U1` extension when feed and public package URLs are configured.

## `.odrlib` version 1

- New, visibly distinct curated-library format alongside the existing `.oder` directory-index format.
- ZIP/ZIP64 container with a manifest, library metadata, item and collection catalogs, artwork, and optional embedded payloads.
- Permanent UUIDs for libraries, items, collections, artifacts, and individual package builds.
- Separate human-readable versions and monotonically increasing revisions for dependable update ordering.
- Declared sizes and SHA-256 hashes for every member, plus a SHA-256 for the complete package in update feeds.
- HTTPS mirrors, stored embedded payloads, safe paths, strict member declarations, and conservative archive limits.
- No scripts, installers, automatic execution, registry actions, or elevation requests.
- Extensible v1 manifest with required/optional extension declarations; `U1` is implemented now and `T1` is reserved for Alpha 3 torrent creation.

## Versioning and packaging

- ODeR Creator reports `2026.0.1a` independently from the browser's `1.1.0-alpha.2` release line.
- The updater understands both earlier semantic versions and the new compact calendar prerelease scheme.
- Creator is available as a dedicated Windows installer and a native macOS `.app`/DMG with `.odrproj` file association; it is intentionally not distributed as a portable edition.
- Installed Creator associates `.odrproj` files without taking ownership of `.oder` files from the browser.

This is an alpha authoring release. Keep source files and project backups until a built library has been validated and tested on another machine.
