# ODeR

**Offline Directory Explorer & Retriever**

ODeR is a PySide6 desktop application for indexing web directory listings, browsing the cached tree offline, tracking changes, and downloading selected files. Each directory keeps its own crawl and download settings, while the local SQLite index remains fast enough for large archives.

Current version: **0.17.0**

## Highlights

- Browse cached directory trees without a network request.
- Resume interrupted crawls, update stale folders, or rebuild an entire index.
- Search locally with SQLite FTS5 plus site, type, size, file, and folder filters.
- Review snapshots of new, removed, and changed entries.
- Save favorite folders and reusable searches.
- Queue individual files or expandable download groups with speed and ETA.
- Import, export, validate, and compare versioned `.oder` directory packages.
- Export either a complete directory or a selected subtree.
- Manage, repair, compact, or clear cached indexes without touching downloads.
- Choose Graphite, Midnight, Light, OLED Black, or a custom color palette.
- Check stable or preview GitHub releases in-app and download verified updates.
- Keep one ODeR instance per Windows user and forward `.oder` files to the running window.
- Keep browsing, Home, Activity, and Downloads responsive while large indexes are updated.

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

The repository includes tests for cache paging and search, snapshots, crawl recovery, concurrent WAL reads, stable live UI updates, grouped downloads, favorites, `.oder` validation, subtree exports, conflict handling, package comparison, update selection, and verified update downloads. A configurable 100,000-entry cache benchmark is available at `tools/benchmark_cache.py`.

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

Installed builds can check GitHub for stable or preview releases from **Settings → Application updates**. ODeR checks at most once per day when automatic checks are enabled, and a manual **Check now** action is always available. Update checks send only the normal GitHub request and ODeR version user-agent; local directory URLs, searches, downloads, and usage data are not sent.

ODeR matches the exact `ODeR Installer.exe` release asset, streams it into `%LOCALAPPDATA%\ODeR\updates`, and verifies its SHA-256 digest before offering to launch it. GitHub's asset digest is preferred, with `SHA256SUMS.txt` as a fallback. A failed size or hash check deletes the partial download. When crawls or downloads are active, installation can wait until background work becomes idle.

Portable builds use the same release notification interface but download `ODeR-Portable.zip` instead of modifying the running executable. Source checkouts can inspect the latest release without launching an installer.

## `.oder` package format

An `.oder` file is a ZIP container with format version metadata and SHA-256 checksums. Downloaded files are never included.

```text
manifest.json       format/application versions, scope, timestamp, hashes and counts
profile.json        directory name, URL and crawl/download settings
cache.sqlite3       optional validated cached index
```

Definition-only packages are small and must be indexed after import. Full packages include a consistent SQLite snapshot and can be browsed immediately. Imports validate the archive layout, manifest version, sizes, checksums, profile schema, URL, SQLite integrity, required tables, and cache counts before changing application data.

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
