# Changelog

Notable changes to ODeR are recorded here.

## Unreleased

## 0.17.0 — 2026-08-19

- Moved cache initialization and Home statistics into a background task so the window and site cards appear immediately.
- Made crawl progress event-driven and throttled; Activity updates existing controls instead of rebuilding the page every second.
- Began folder network requests before preparing change baselines and limited folder/grow snapshots to the levels they can actually change.
- Combined each folder listing write and crawled-state update into one transaction, throttled aggregate counts, and added an index for the primary browse order.
- Added explicit SQLite schema-version metadata, WAL readers that do not wait on the in-process writer lock, and a single-query cache summary.
- Replaced per-file action widgets with a lightweight painted delegate, preserving correctly aligned Download and Copy link actions with far less UI overhead.
- Updated Downloads rows and progress bars in place, removed repeated queue-file reads, and throttled download progress persistence.
- Added regression coverage for responsive UI updates, concurrent cache reads, scoped snapshots, and schema metadata, plus a repeatable 100,000-entry cache benchmark.

## 0.16.2 — 2026-08-19

- Corrected the remaining file-row button alignment problem at scaled display settings.
- Kept expanded site groups open while the Downloads page refreshes each second.

## 0.16.1 — 2026-08-19

- Limited ODeR to one instance per Windows user; repeated launches now focus the existing window and forward `.oder` file-open requests to it.
- Centered file-row action buttons with reliable vertical and right-edge spacing at different display scales.

## 0.16.0 — 2026-08-19

- Added automatic daily and manual in-app update checks against GitHub Releases.
- Added Stable and Preview update channels, release-note dialogs, Home update banners, version skipping, and last-checked status.
- Added streamed installer and portable-ZIP downloads with visible progress and cancellation.
- Added mandatory SHA-256 validation using GitHub asset digests with `SHA256SUMS.txt` fallback; mismatched or incomplete downloads are deleted.
- Added safe installer handoff that waits for active crawls and downloads to become idle before closing ODeR.
- Kept portable updates non-destructive by downloading the new ZIP and opening its folder for the user.

## 0.15.2 — 2026-08-19

- Licensed ODeR under the MIT License, copyright 2026 kaderka.
- Documented runtime, transitive, build-tool, and binary-distribution third-party licensing considerations.
- Added distinct portable and installed storage modes: portable data stays beside the executable, while installed data uses `%LOCALAPPDATA%\ODeR`.
- Added one-command Windows release packaging for `ODeR-Portable.exe`, `ODeR-Portable.zip`, `ODeR Installer.exe`, and SHA-256 checksums.
- Included the MIT license and third-party notices in both portable and installed distributions.
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
