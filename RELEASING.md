# Releasing ODeR for Windows and macOS

This checklist creates supported installer/disk-image editions from one source tree. Portable builds are no longer release artifacts.

## Prerequisites

- 64-bit Windows with Python 3.12 and Inno Setup 6 for Windows installers
- Intel x64 macOS with Python 3.10 and the built-in `hdiutil` for Monterey-compatible `.app` bundles and DMGs

## Prepare the release

1. Set ODeR's canonical SemVer in `core/version.py`, `installer.iss`, `README.md`, and `CHANGELOG.md` (for example `1.1.0-alpha.2`). Set Creator's independent calendar version in `core/version.py`, `creator_installer.iss`, and its changelog entry (for example `2026.0.1a`). The two applications do not need matching versions.
2. Run the tests:

   ```powershell
   python -m unittest discover -s tests -v
   ```

3. Create or activate a clean virtual environment:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   ```

4. Build all available release assets. The build stops before packaging if its version metadata is inconsistent:

   ```powershell
   .\build_windows.ps1
   ```

The script searches `PATH` plus the standard system-wide and per-user Inno Setup 6 installation directories. It stops if Inno Setup is unavailable because the private PyInstaller executables are installer payloads, not standalone release files.

5. On a Mac, create both native application bundles and disk images:

   ```bash
   bash build_macos.sh
   ```

The macOS script builds Intel x64 `ODeR.app` and `ODeR Creator.app` bundles, verifies that every native component supports macOS 12 Monterey, places each in a compressed DMG, and generates checksums. It uses the pinned compatibility dependencies in `requirements-macos-intel.txt`. Build Mac artifacts on Intel macOS; a Windows host cannot produce a valid native `.app` bundle. GitHub Actions uses the explicit `macos-15-intel` runner so `macos-latest` cannot silently switch the release to Apple silicon.

## Release assets

Upload the applicable files from `release-dist` to the GitHub release:

- `ODeR Installer.exe` — installed edition
- `ODeR Creator Installer.exe` — installed Creator edition with `.odrproj` association
- `ODeR.dmg` — macOS ODeR application
- `ODeR Creator.dmg` — macOS Creator application
- `SHA256SUMS.txt` — integrity checksums; combine the Windows and macOS lines if all assets share one release

The Windows installers display the MIT License, install both licensing documents, and store writable application data in `%LOCALAPPDATA%\ODeR`. ODeR for macOS stores writable data in `~/Library/Application Support/ODeR`.

## Verify before publishing

Test on a clean Windows user account or Windows Sandbox:

1. Install `ODeR Installer.exe` and confirm `%LOCALAPPDATA%\ODeR` is created.
2. Confirm crawling, downloads, `.oder` import/export, and `.odrlib` import/browse/update/download all work.
3. Confirm the Start menu shortcut, optional desktop shortcut, single-instance forwarding, and `.oder`/`.odrlib` file associations work.
4. Uninstall ODeR and confirm the application files are removed. User data is intentionally retained.
5. Install `ODeR Creator Installer.exe` and confirm its shortcuts, build flow, U1 output, and `.odrproj` association work.
6. Compare the SHA-256 hashes with `SHA256SUMS.txt`.

On a clean Intel Mac running macOS 12 Monterey (and, if available, a newer macOS version):

1. Mount both DMGs, copy each `.app` into Applications, and launch it.
2. Confirm ODeR creates `~/Library/Application Support/ODeR` and opens `.oder`/`.odrlib` documents.
3. Confirm Creator opens `.odrproj`, validates a project, and produces a readable `.odrlib` with U1 when a feed is configured.
4. Confirm ODeR selects, verifies, downloads, and opens `ODeR.dmg` from a preview-channel update.
5. Compare both DMG hashes with `SHA256SUMS.txt`.
6. In **System Information → Software → Applications**, confirm both applications report **64-Bit (Intel)** and do not show an unsupported-application warning.

Unsigned first releases may trigger a Windows SmartScreen warning. Do not describe the build as code-signed unless both release executables were actually signed and verified.

## Publish on GitHub

1. Commit and push the exact source used for the binaries.
2. Open **Releases**, choose **Draft a new release**, and create the tag matching the application version exactly, such as `v0.21.0`.
3. Attach the installers, DMGs, and checksum file listed above.
4. Add release notes from `CHANGELOG.md` and save a draft.
5. Download and re-test the draft assets, then publish the release.

For any alpha, beta, or release candidate, use the exact ODeR versioned tag (for example, `v1.1.0-alpha.2`) and enable GitHub's **Set as a pre-release** option. Do not mark a prerelease as the latest stable release. Installed testers on an older ODeR version must select **Preview releases** in **Settings → Application updates** before checking; the Stable channel intentionally ignores prereleases.

The in-app updater depends on `ODeR Installer.exe` (or GitHub's normalized `ODeR.Installer.exe`), `ODeR.dmg`, and the matching checksum entries being present. Always upload checksums generated from the exact published files, and keep the Windows installer `AppId` unchanged so Inno Setup treats future versions as upgrades.

Publish ODeR tags as SemVer (`v1.1.0`, `v1.1.0-alpha.2`, and so on). Creator's calendar version is displayed in its executable and installer but does not replace the ODeR GitHub release tag. Legacy semantic and calendar-style ODeR tags remain readable so existing installations can update directly without installing intermediate releases.
