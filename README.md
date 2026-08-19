# ODeR

**Offline Directory Explorer & Retriever**

ODeR is a PySide6 desktop application for indexing web directory listings, browsing the cached tree offline, tracking changes, and downloading selected files. Each directory keeps its own crawl and download settings, while the local SQLite index remains fast enough for large archives.

Current version: **0.15.2**

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

## Requirements

- Python 3.11 or newer
- PySide6 6.6 or newer
- Requests 2.31 or newer

ODeR is designed primarily for Windows. The Python application can also run on other desktop platforms supported by PySide6, although the installer and `.oder` file association are Windows-specific.

## Run from source

```powershell
git clone <your-repository-url>
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

The repository includes tests for cache paging and search, snapshots, crawl recovery, grouped downloads, favorites, `.oder` validation, subtree exports, conflict handling, and package comparison.

## Build for Windows

```powershell
.\build_windows.ps1
```

The script installs PyInstaller and creates `dist\OfflineDirectoryBrowser.exe`. If Inno Setup is installed and `iscc.exe` is available, it also creates an installer in `installer-dist\` with the `.oder` file association.

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
```

## Contributing

Bug reports and focused pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and [SECURITY.md](SECURITY.md) for private vulnerability reporting guidance.

## License

ODeR is licensed under the [MIT License](LICENSE).

Copyright © 2026 kaderka. Third-party dependencies retain their respective licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
