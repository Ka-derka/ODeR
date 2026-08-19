# ODeR

**Offline Directory Explorer & Retriever**

ODeR is a PySide6 desktop application for indexing web directory listings, browsing the cached tree offline, tracking changes, and downloading selected files. Each directory keeps its own crawl and download settings, while the local SQLite index remains fast enough for large archives.

Current version: **0.21.0**

## Highlights

- Browse cached directory trees without a network request.
- Resume interrupted crawls, update stale folders, or rebuild an entire index.
- Search locally with SQLite FTS5 plus site, type, size, file, and folder filters.
- Review snapshots of new, removed, and changed entries.
- Save favorite folders and reusable searches.
- Queue individual files or expandable download groups with speed and ETA while recreating the directory's original folder hierarchy on disk.
- Import, export, validate, and compare versioned `.oder` directory packages.
- Export either a complete directory or a selected subtree.
- Manage, repair, compact, or clear cached indexes without touching downloads.
- Choose Graphite, Midnight, Light, OLED Black, or a custom color palette.
- Check stable or preview GitHub releases in-app and download verified updates.
- Keep one ODeR instance per Windows user and forward `.oder` files to the running window.
- Keep browsing, Home, Activity, and Downloads responsive while large indexes are updated.
- Discover and load a directory-hosted full `.oder` index instead of crawling every folder.
- Export a privacy-conscious diagnostics ZIP with schema, cache-health, and runtime information when troubleshooting.

## Requirements

- Python 3.11 or newer
- PySide6 6.6 or newer
- Requests 2.31 or newer

ODeR is designed primarily for Windows. The Python application can also run on other desktop platforms supported by PySide6, although the installer and `.oder` file association are Windows-specific.

## Run from source

```powershell
git clone https://github.com/Ka-derka/ODeR
cd ODeR
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

Application data is created in `data/` at runtime. This directory can contain profiles, cached indexes, crawl state, download history, logs, and downloaded files, so it is intentionally excluded from Git.

## Test

```powershell
python -m compileall -q core gui main.py
python -m unittest discover -s tests -v
```

The repository includes tests for cache paging and search, snapshots, crawl recovery, state migrations, structured and collision-safe download paths, diagnostics privacy and cache health, representative web-server directory listings, concurrent WAL reads, stable live UI updates, grouped downloads, favorites, hosted `.oder` discovery and conditional refreshes, package validation, subtree exports, conflict handling, package comparison, update selection, and verified update downloads. GitHub Actions runs the suite on Linux and Windows and smoke-builds the Windows portable executable. A configurable 100,000-entry cache benchmark is available at `tools/benchmark_cache.py`.

## Build for Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
.\build_windows.ps1
```

The script installs PyInstaller and prepares GitHub-ready files in `release-dist\`:

- `ODeR-Portable.exe` — single-file portable application.
- `ODeR-Portable.zip` — recommended portable download, including the executable, portable marker and licensing files.
- `ODeR Installer.exe` — Windows installer with Start menu/optional desktop shortcuts, uninstall support and the `.oder` file association. This is created when Inno Setup 6 is installed.
- `SHA256SUMS.txt` — SHA-256 checksums for the generated release assets.

Portable ODeR stores its writable `data` directory beside the executable. The installed application stores writable data in `%LOCALAPPDATA%\ODeR`, not in `Program Files`. See [RELEASING.md](RELEASING.md) for the complete release checklist.

## Application updates

Installed builds can check GitHub for stable or preview releases from **Settings → Application updates**. ODeR checks at most once per day when automatic checks are enabled, and manual **Check now** and **View releases** actions are always available. Update checks send only the normal GitHub request and ODeR version user-agent; local directory URLs, searches, downloads, and usage data are not sent.

ODeR scans recent published releases and selects the newest compatible download, so a malformed tag or incomplete release does not block valid updates. Short tags such as `0.18` are normalized to `0.18.0`, although canonical three-part tags remain required by the release checklist for compatibility with older clients.

The updater streams the installer into `%LOCALAPPDATA%\ODeR\updates` and verifies its SHA-256 digest before offering to launch it. GitHub's asset digest is preferred, with `SHA256SUMS.txt` as a fallback. Downloads are checked for expected size, available disk space, file type, archive structure, and trusted HTTPS origin. Failed partials are removed, while an already downloaded and verified update can be safely reused. When crawls or downloads are active, installation can wait until background work becomes idle.

Portable builds use the same release notification interface but download `ODeR-Portable.zip` instead of modifying the running executable. Source checkouts can inspect the latest release without launching an installer.

## Data recovery

Settings, profiles, favorites, package history, crawl state, and the download queue use versioned schemas and are written atomically with a last-known-good backup. Legacy state is migrated before the UI starts. If a JSON state file is truncated or damaged, ODeR restores its backup and preserves the damaged copy for diagnosis. Newer unsupported state is left untouched and startup explains that a newer ODeR version is required.

Invalid SQLite directory caches are similarly preserved before an empty rebuildable cache is created. A cache from a newer unsupported schema is never downgraded or overwritten. Full crawls and hosted `.oder` replacements are checkpointed: ODeR commits the new index only when the whole operation succeeds, and restores the last working index after a stop, failure, or interrupted process. See [DATA_COMPATIBILITY.md](DATA_COMPATIBILITY.md) for the compatibility contract.

## Structured downloads

Every new download receives a stable destination beneath the configured download directory:

```text
<download directory>/<ODeR directory name>/<source folders>/<file name>
```

For example, `Season%201/English/episode.mkv` from a directory named `Archive` is saved as `Archive/Season 1/English/episode.mkv`. Folder batches and selected-file batches retain the same hierarchy. ODeR safely normalizes Windows-reserved names, control characters, traversal components, and overly long components; distinct sources that normalize to the same path receive numbered filenames instead of overwriting one another. Existing completed files are kept when that preference is enabled.

Queue schema 2 pins the chosen relative destination so directory renames or future path-normalization improvements cannot move an active or completed queue item. Queues created by ODeR 0.20 are migrated while preserving their previous on-disk locations.

## Diagnostics

Use **Logs → Export diagnostics** to create a support ZIP. The main JSON report includes ODeR, Python, and operating-system versions; state-file schemas; anonymous cache counts; SQLite integrity and schema results; checkpoint state; and download status totals. It excludes tracked directory names and URLs, download names, cache contents, and downloaded files.

Recent logs can be included explicitly. Because log messages can contain directory URLs and filenames, ODeR asks before adding them and places a privacy reminder inside the package.

## `.oder` package format

An `.oder` file is a ZIP container with format version metadata and SHA-256 checksums. Downloaded files are never included.

```text
manifest.json       format/application versions, scope, timestamp, hashes and counts
profile.json        directory name, URL and crawl/download settings
cache.sqlite3       optional validated cached index
```

Definition-only packages are small and must be indexed after import. Full packages include a consistent SQLite snapshot and can be browsed immediately. Imports validate the archive layout, manifest version, sizes, checksums, profile schema, URL, SQLite integrity, required tables, and cache counts before changing application data. The complete version 1 compatibility contract is documented in [ODER_FORMAT.md](ODER_FORMAT.md).

## Hosted `.oder` indexes

A directory can publish a full `.oder` package so ODeR can load one validated index instead of crawling every folder. ODeR checks an exact URL configured in **Edit Site**, advertised package links, and these paths beneath the directory base URL:

```text
index.oder
directory.oder
.well-known/oder.oder
```

To advertise a package stored anywhere else, add this to the directory HTML:

```html
<link rel="oder-index" type="application/vnd.oder+zip" href="https://cdn.example.com/archive/latest.oder">
```

Servers can alternatively send an HTTP `Link` response header with `rel="oder-index"`. ODeR streams the package to a temporary file and checks its ZIP layout, manifest, SHA-256 hashes, cache counts, SQLite integrity, and exact base URL before applying it. Definition-only and mismatched packages are ignored. Saved `ETag` and `Last-Modified` values allow future updates to finish with a conditional request when the hosted package has not changed.

See [HOSTING.md](HOSTING.md) for publishing and server-configuration examples.

## Repository layout

```text
core/               cache, crawling, downloads, profiles and package handling
gui/                PySide6 windows, pages, widgets, dialogs and tray integration
tests/              standard-library unittest suite
.github/             workflows and collaboration templates
main.py              application entry point
build.spec           PyInstaller definition
installer.iss        optional Inno Setup installer
RELEASING.md          Windows build and GitHub release checklist
```

## Contributing

Bug reports and focused pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and [SECURITY.md](SECURITY.md) for private vulnerability reporting guidance.

## License

ODeR is licensed under the [MIT License](LICENSE).

Copyright © 2026 kaderka. Third-party dependencies retain their respective licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
