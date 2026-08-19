# Releasing ODeR for Windows

This checklist creates the portable and installed editions from one source tree.

## Prerequisites

- 64-bit Windows
- Python 3.12
- Inno Setup 6 for the installer

## Prepare the release

1. Set the same version in `core/version.py`, `installer.iss`, `README.md` and `CHANGELOG.md`.
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

4. Build all available release assets:

   ```powershell
   .\build_windows.ps1
   ```

The script searches `PATH` plus the standard system-wide and per-user Inno Setup 6 installation directories. If Inno Setup is unavailable, it still produces the portable files and explains why the installer was skipped.

## Release assets

Upload these files from `release-dist\` to the GitHub release:

- `ODeR-Portable.zip` — recommended portable download
- `ODeR-Portable.exe` — optional direct executable download
- `ODeR Installer.exe` — installed edition
- `SHA256SUMS.txt` — integrity checksums

The portable ZIP contains `portable.flag`, `LICENSE`, and `THIRD_PARTY_NOTICES.md`. Keep the marker beside the executable even if the executable is renamed. The installer displays the MIT License, installs both licensing documents, and stores writable application data in `%LOCALAPPDATA%\ODeR`.

## Verify before publishing

Test on a clean Windows user account or Windows Sandbox:

1. Extract the portable ZIP and confirm a local `data` folder is created after launch.
2. Confirm the portable edition starts, crawls, downloads, and imports/exports `.oder` files.
3. Install `ODeR Installer.exe` and confirm `%LOCALAPPDATA%\ODeR` is created.
4. Confirm the Start menu shortcut, optional desktop shortcut and `.oder` file association work.
5. Uninstall ODeR and confirm the application files are removed. User data is intentionally retained.
6. Compare the SHA-256 hashes with `SHA256SUMS.txt`.

Unsigned first releases may trigger a Windows SmartScreen warning. Do not describe the build as code-signed unless both release executables were actually signed and verified.

## Publish on GitHub

1. Commit and push the exact source used for the binaries.
2. Open **Releases**, choose **Draft a new release**, and create the tag matching the application version, such as `v0.17.0`.
3. Attach the four release assets listed above.
4. Add release notes from `CHANGELOG.md` and save a draft.
5. Download and re-test the draft assets, then publish the release.

The in-app updater depends on the installer, portable ZIP, and checksum assets being present. GitHub currently normalizes the uploaded `ODeR Installer.exe` filename to `ODeR.Installer.exe`; the updater accepts both names. Keep `ODeR-Portable.zip` and `SHA256SUMS.txt` unchanged. Always upload the checksum file generated in the same build, and keep the installer `AppId` unchanged so Inno Setup treats future versions as upgrades.
