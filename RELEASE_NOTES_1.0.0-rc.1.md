# ODeR 1.0.0-rc.1 — Release Candidate 1

ODeR RC1 is the first feature-complete candidate for the 1.0 release. It brings the work from the 0.x series together into a build intended for final real-world testing of upgrades, saved data, downloads, `.oder` packages, and the redesigned library interface.

## A library-focused Home screen

- Tracked locations are now called **libraries** throughout the interface.
- Home displays libraries as responsive square tiles that adapt to the available window width.
- Each tile has a compact three-dot menu for **Settings**, **Information**, and **Export `.oder`**.
- `.oder` packages can still be opened by double-clicking them, using the Windows file association, or dragging them anywhere onto ODeR; the redundant visible import buttons have been removed.
- **New tab** and **Favorites** remain immediately available in the sidebar. Activity, Changes, Storage, Logs, and Settings now live in a remembered **More** section that expands downward.
- Downloads have moved to a permanent button at the lower-right of the status bar, with a live queued/active count.

## Offline libraries and faster maintenance

- Browse previously indexed directory trees without contacting the server.
- Use progressive browsing, update a folder, grow the known tree, resume interrupted work, or rebuild a complete index.
- Large crawls and folder updates keep the interface responsive, update Activity in place, and no longer force the view away from the current page.
- Search cached content locally with SQLite FTS5, filters, favorites, saved searches, snapshots, and change history.
- A directory can publish a validated hosted `.oder` index so clients can load it instead of crawling every folder.

## Portable `.oder` library packages

- Export a definition-only package, a complete cached index, or a selected subtree.
- Import conflicts can create a separate copy or replace an existing library.
- Packages are checked before import for archive layout, version compatibility, safe paths, hashes, profile data, SQLite integrity, required tables, and entry counts.
- Failed or interrupted replacements restore the last complete index.

## Structured, recoverable downloads

- Downloads recreate the library's decoded folder hierarchy beneath its own local folder.
- Unsafe and Windows-reserved path components are normalized, collisions are numbered, and distinct files are not silently overwritten.
- Individual files and expandable folder groups support pause, resume, retry, aggregate progress, speed, and ETA.
- Queue destinations remain stable after restarts and library renames, and interrupted transfers resume from their partial files.

## Reliability, updates, and diagnostics

- Versioned saved data is migrated atomically with last-known-good backups; unsupported newer formats are left untouched.
- Full crawls and hosted-index replacements use rollback checkpoints.
- Only one ODeR instance runs per Windows user; later launches focus it and forward `.oder` files.
- Installed and portable editions can find and download verified GitHub updates using mandatory SHA-256 checks and trusted HTTPS sources.
- Diagnostics export reports runtime, schema, cache-health, checkpoint, and anonymous queue information without including library URLs, names, cached listings, or downloaded contents by default.

## Release-candidate notes

- GitHub tag: `v1.0.0-rc.1`
- This release should be marked as a **pre-release** on GitHub.
- Existing users must select **Preview releases** under **Settings → Application updates** to receive RC1 in-app. The Stable channel intentionally ignores it.
- The binaries are unsigned unless code signing was performed separately, so Windows SmartScreen may display a warning.
- The planned `.odrlib` software-distribution format and community/cloud features are future work and are not part of RC1.

Please report any data loss, broken upgrades, corrupted indexes, package import failures, stuck downloads, interface freezes, or scaling/layout problems as release-blocking issues.
