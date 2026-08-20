# Changelog

Notable changes to ODeR are recorded here.

## Unreleased

## 1.1.0-alpha.1 — 2026-08-20

- Added optional library artwork, descriptions, creator/curator credits, categories, and tags through a new Library details editor.
- Displayed custom artwork on Home library tiles while retaining deterministic generated covers for libraries without artwork.
- Expanded Library Information to show descriptive metadata and an artwork preview alongside cache and source details.
- Embedded size-limited, validated PNG/JPEG/WebP artwork and metadata inside existing `.oder` profile JSON so 1.1 preserves it while ODeR 1.0 remains able to import the package and ignore the optional fields.
- Added strict metadata normalization, duplicate-tag removal, length and count limits, 1 MiB artwork limits, and package comparison reporting for presentation changes.
- Added themed Library details and Indexing & downloads tabs plus regression coverage for persistence, artwork processing, Home display, and `.oder` round-tripping.

## 1.0.0 — 2026-08-20

- Promoted the tested RC1 code to the first stable ODeR release without introducing additional feature changes.
- Made `1.0.0` available to the Stable update channel while preserving correct upgrade ordering from `1.0.0-rc.1`.
- Finalized the 1.0 release notes, compatibility documentation, Windows portable package, installer, source archive, and integrity checksums.

## 1.0.0-rc.1 — 2026-08-20

- Marked the first ODeR 1.0 release candidate and added canonical prerelease-version validation to the release process.
- Replaced the Home location rows with responsive square library tiles, including distinctive covers and an upper-right menu for settings, information, and `.oder` export.
- Renamed tracked locations to libraries throughout the user-facing interface.
- Removed visible `.oder` import buttons while retaining drag-and-drop, file-association, double-click, and forwarded single-instance opening.
- Kept New tab and Favorites fixed in the sidebar and placed Activity, Changes, Storage, Logs, and Settings in a remembered section that expands downward.
- Moved Downloads out of the sidebar and into a permanent bottom-right status-bar button with a live queued/active count.
- Added UI regression coverage for the responsive library grid, overflow actions, import-button removal, sidebar collapse, and status-bar Downloads control.
- Retained the hardened `.oder` package, structured-download, recovery, diagnostics, hosted-index, and verified-update foundations developed across the 0.x releases for final 1.0 testing.

## 0.21.0 — 2026-08-20

- Added durable structured download destinations that recreate each directory's decoded folder hierarchy beneath its own site folder.
- Added download-queue schema 2 so destinations remain stable across restarts, directory renames, and future path-normalization changes while 0.20 queue items keep their previous locations.
- Hardened destination creation against traversal components, control characters, Windows-reserved names, overly long components, and distinct files that normalize to the same local path.
- Made the existing-file preference effective: completed files can now be kept without another network request, while disabling it continues to allow replacement.
- Moved recursive folder expansion and queue creation off the UI thread and replaced per-file queue and group-control rewrites with single batch transactions, substantially improving large folder downloads.
- Batched selected-file downloads and showed structured relative paths directly in the Downloads page.
- Added a diagnostics exporter to Logs with ODeR/runtime information, state schema metadata, anonymous cache counts, SQLite integrity results, pending checkpoint detection, and download status totals.
- Kept directory names, directory URLs, filenames, cached listings, and downloaded contents out of the default diagnostics report; recent logs are optional and carry an explicit privacy warning.
- Expanded the 100,000-entry benchmark to cover recursive download-folder expansion and full-update checkpoint creation/recovery.
- Added regression coverage for decoded hierarchy creation, legacy queue migration, reserved names, path collisions, traversal safety, one-write large batches, existing-file behavior, and diagnostics privacy/integrity.

## 0.20.0 — 2026-08-20

- Added versioned schema envelopes and explicit migrations for settings, profiles, the download queue, favorites, package history, and crawl state.
- Added startup compatibility checks that migrate legacy state before background work begins and leave newer unsupported schemas untouched with a clear update-required message.
- Made full directory refreshes all-or-nothing: a stopped, failed, or interrupted full crawl restores the last complete SQLite index instead of leaving a partly replaced cache.
- Applied the same checkpoint protection to directory-hosted `.oder` replacements, including failures after the incoming cache has begun applying.
- Added process-start recovery for full-update checkpoints left by a crash or forced shutdown.
- Hardened HTML listing parsing for double-quoted, single-quoted, and unquoted links, nested labels, encoded names, table-based sizes, and unsafe parent, query, fragment, or cross-origin links.
- Added representative Apache, nginx, Caddy, and simple-listing fixtures alongside migration, future-schema refusal, checkpoint, and hosted-rollback regression tests.
- Added Linux and Windows continuous testing plus a real Windows portable build, embedded-version smoke check, and short-lived CI artifact.
- Added canonical Git-tag validation to release metadata checks and published formal `.oder` version 1 and saved-data compatibility contracts.
- Corrected backup-disabled state writes so high-frequency queue progress saves no longer create an unintended backup copy on every update.

## 0.19.0 — 2026-08-19

- Made update version parsing tolerant of abbreviated GitHub tags such as `0.18` and `v0.18`, normalizing them to `0.18.0`.
- Replaced single-release update discovery with a scan of recent releases that ignores drafts, malformed tags, wrong channels, and incomplete assets before selecting the newest compatible update.
- Added flexible recognition of versioned installer/portable asset names while retaining trusted-host and mandatory SHA-256 validation.
- Added update size limits, free-space checks, executable/portable-ZIP structure validation, safe reuse of an already verified download, and cleanup of rejected partial files.
- Added persistent failed-check status, daily backoff after automatic failures, and **View releases** recovery actions for both update-check and download errors.
- Added atomic JSON writes, last-known-good backups, automatic recovery, and preservation of damaged settings, profiles, queue, favorites, package-history, and crawl-state files.
- Serialized profile, favorite, and download-queue mutations so concurrent background work cannot overwrite another completed change.
- Made downloads left in progress by an unexpected exit resume from their partial files on the next launch.
- Added safe cache recovery that preserves an invalid SQLite database before recreating an empty index, while refusing to overwrite cache schemas created by newer ODeR versions.
- Merged missing custom-theme palette fields from current defaults so older partial palettes remain usable after upgrades.
- Added release-build metadata verification and regression coverage for skipped-version updates, malformed releases, download payload validation, state recovery, concurrent profile writes, cache compatibility, and interrupted downloads.

## 0.18.0 — 2026-08-19

- Added automatic discovery and loading of full `.oder` indexes hosted by a directory or CDN, allowing complete indexes to replace folder-by-folder crawling.
- Added conventional `index.oder`, `directory.oder`, and `.well-known/oder.oder` discovery beneath each directory base URL.
- Added HTML and HTTP `Link` advertisement support using `rel="oder-index"` and the `application/vnd.oder+zip` media type.
- Added an optional exact hosted-package URL to Add/Edit Site for packages stored outside the directory root.
- Added streamed downloads, visible Activity progress, cancellation, package size limits, complete `.oder` validation, and exact base-URL matching before a hosted cache is applied.
- Added `ETag` and `Last-Modified` conditional requests so unchanged hosted indexes skip both downloading and crawling.
- Preserved local site settings and crawl history while applying hosted cache contents, with normal index detection and crawling retained as fallback paths.
- Fixed remembered recursive JSON/sitemap descriptors so later updates re-detect their contents instead of treating an intentionally unpersisted tree as empty.
- Added hosting documentation and regression coverage for advertisements, conventional paths, validation, change tracking, unchanged packages, and fallback behavior.

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
