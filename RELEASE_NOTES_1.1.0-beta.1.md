# ODeR 1.1.0 Beta 1 — keep sharing, open locally

Beta 1 turns a completed T1 download into a useful long-lived seed instead of stopping the torrent as soon as the file arrives. It also makes curated libraries behave more like a local collection: selecting a file you already have opens it instead of adding another download that immediately finishes.

## Persistent T1 seeding

- A verified T1 download now changes to **Seeding** in Downloads and remains available to peers while ODeR is running.
- ODeR restores completed T1 seeds after an application restart, including compatible completed torrent entries left by Alpha 3.
- Multiple selected files from one torrent share a torrent handle, and separate imports of the same library can reuse it instead of conflicting over the same info hash.
- The normal downloaded file and ODeR's private seed payload use a hard link when the filesystem supports it, so they do not consume the file's full size twice. ODeR keeps a private copy only when a hard link is unavailable.
- Pausing a seeding entry pauses its participation. Resuming reattaches it without downloading the finished file again.
- Removing the entry from Downloads—or using **Clear finished**—stops that seed and removes ODeR's private staging data. The downloaded file in the library's normal folder is deliberately kept.
- Seeding does not block application updates from installing when all actual downloads and crawls are idle.

Torrent package import remains passive. ODeR starts no transfer or seed merely because an `.odrlib` was installed; the user must choose a file first.

## Open files already on disk

- Curated-library tabs now detect completed files retained in Downloads, including collision-renamed destinations.
- If the Downloads record was removed, ODeR also checks the expected structured library folder on disk.
- The action changes from **Download** to **Open** when a matching-size local file exists.
- Button, double-click, and context-menu actions open that local file without displaying a mirror chooser or creating a duplicate queue job.
- The action refreshes while the library tab is visible, so a completed background download becomes openable without reopening the tab.

## macOS release hardening

- GitHub Actions now deliberately builds Intel x64 applications instead of inheriting the architecture of the moving `macos-latest` runner.
- The Intel build targets macOS 12 Monterey or newer and pins compatible Qt and libtorrent wheels.
- Release automation checks every bundled native component's architecture and deployment target before uploading the DMGs.

## Larger Creator libraries

- ODeR Creator now uses libtorrent's canonical file-entry builder for hybrid torrents. This fixes `libtorrent:213` ("the v1 and v2 file metadata does not match") seen when larger libraries contain many folders or similarly prefixed folder names.
- T1 file indices are matched back to catalog files by their full torrent path after libtorrent has ordered the tree, instead of assuming the output remains in the Creator's input order.
- Regression coverage now builds and parses a 179-file, 27-folder hybrid torrent matching the scale of the reported failure.

## Versions

- ODeR: `1.1.0-beta.1`
- ODeR Creator: `2026.0.2a` (unchanged)

This is a preview release. In an older ODeR installation, select **Preview releases** under **Settings → Application updates** before checking for it.
