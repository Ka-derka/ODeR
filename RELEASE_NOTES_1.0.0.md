# ODeR 1.0.0 — First stable release

ODeR 1.0 is the first stable release of **Offline Directory Explorer & Retriever**: a desktop application for turning browsable web directories into fast local libraries that remain searchable and usable offline.

## Libraries that work offline

- Index Apache, nginx, Caddy, and simple HTML directory listings into separate local libraries.
- Browse cached folder trees without contacting the original server.
- Update one folder, grow the known tree, resume interrupted work, perform an incremental update, or rebuild the complete index.
- Search locally with SQLite FTS5 and combine library, file/folder, type, and size filters.
- Save favorite folders and searches, then review snapshots of added, removed, and changed entries.
- Keep the interface responsive while large indexes are opened or updated.

## A library-focused interface

- Home presents libraries as responsive square tiles with distinctive covers and summary information.
- Each library has a compact three-dot menu for Settings, Information, and `.oder` export.
- New tab and Favorites remain directly accessible, while Activity, Changes, Storage, Logs, and Settings live in a remembered More section.
- Downloads are always available from the lower-right status bar with a live queued/active count.
- Listing columns are resizable, file actions stay aligned at the right edge, and starting a crawl does not pull you away from the current page.
- Graphite, Midnight, Light, OLED Black, and visual custom-color themes are included.

## Portable `.oder` libraries

- Export a library definition, a complete cached index, or a selected subtree as a versioned `.oder` ZIP package.
- Open packages through drag-and-drop, Windows file association, or double-clicking; a running ODeR instance receives the file automatically.
- Duplicate imports can be copied into a separate library or used to replace the existing one.
- Packages are validated for safe layout, compatible versions, SHA-256 hashes, profile data, SQLite integrity, required tables, and entry counts before application data changes.
- A directory or CDN can host a complete `.oder` index for ODeR to discover and conditionally refresh instead of crawling every folder.

## Structured downloads

- Downloaded files recreate the library's decoded source-folder hierarchy beneath their own library folder.
- Individual files and expandable folder groups support pause, resume, retry, progress, speed, and ETA.
- Queue destinations remain stable across restarts and library renames.
- Interrupted transfers resume from partial files.
- Unsafe paths, Windows-reserved names, long components, and normalized-name collisions are handled without escaping the download directory or silently overwriting another file.

## Reliability and recovery

- Versioned settings, profiles, favorites, package history, crawl state, and download queues migrate atomically with last-known-good backups.
- Unsupported newer data is preserved and refused instead of being guessed at or downgraded.
- Full crawls and hosted-index replacements use checkpoints so a stop, failure, or interrupted process restores the last complete index.
- Invalid SQLite caches are preserved for diagnosis before a rebuildable cache is created.
- Only one ODeR instance runs per Windows user.
- Privacy-conscious diagnostics report runtime, schemas, anonymous counts, database health, and checkpoint state without including library identities or cached/downloaded contents by default.

## Verified application updates

- Installed and portable editions can check GitHub for updates from inside ODeR.
- Stable and Preview channels are separate, malformed or incomplete releases are skipped, and the newest compatible release is selected.
- Downloads require SHA-256 verification and are checked for trusted HTTPS origin, expected size, available disk space, file type, and portable archive structure.
- Installed updates wait for active work to become idle before handing off to the installer; portable updates are downloaded without modifying the running copy.

## Installation choices

- **ODeR Installer.exe** provides Start menu and optional desktop shortcuts, uninstall support, and the `.oder` file association. User data is stored under `%LOCALAPPDATA%\ODeR`.
- **ODeR-Portable.zip** can be extracted anywhere and keeps its `data` folder beside the executable.

This initial release is unsigned unless code signing was performed separately, so Windows SmartScreen may display a warning. ODeR is released under the MIT License, copyright 2026 kaderka.
