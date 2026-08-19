# Changelog

Notable changes to ODeR are recorded here.

## Unreleased

- Licensed ODeR under the MIT License, copyright 2026 kaderka.
- Documented runtime, transitive, build-tool, and binary-distribution third-party licensing considerations.
- Added distinct portable and installed storage modes: portable data stays beside the executable, while installed data uses `%LOCALAPPDATA%\ODeR`.
- Added one-command Windows release packaging for `ODeR-Portable.exe`, `ODeR-Portable.zip`, `ODeR Installer.exe`, and SHA-256 checksums.
- Included the MIT license and third-party notices in both portable and installed distributions.

## 0.15.2 — 2026-08-19

- Fixed the sidebar at a slimmer width and reduced navigation button height.
- Added clearly bounded tab rows with separate right-aligned close buttons.
- Made the Name, Size, and Type listing columns user-resizable.
- Kept Download and Copy link grouped at the far-right edge.
- Prevented crawl actions from automatically switching to Activity.

## 0.15.0 — 2026-08-19

- Added durable crawl recovery, incremental updates, snapshots, change history, and notifications.
- Added filtered FTS5 search, favorites, saved searches, configurable paging, and a storage manager.
- Added grouped downloads with aggregate progress, speed, ETA, and batch controls.
- Added subtree `.oder` exports and package comparison without importing.
- Added drag-and-drop import, recent package history, and Windows `.oder` file association.

## 0.12.7 — 2026-08-19

- Added validated `.oder` definition and full-index import/export.
- Added copy/replace conflict handling and package progress dialogs.
- Preserved and refined the Graphite, Midnight, Light, OLED, and custom theme system.
