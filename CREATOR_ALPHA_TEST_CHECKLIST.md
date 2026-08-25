# ODeR Creator 2026.0.1a test checklist

## Project basics

- [ ] Start Creator and confirm a new Untitled Library project opens.
- [ ] Change library metadata, save an `.odrproj`, close Creator, and reopen it by double-clicking.
- [ ] Confirm Creator warns before discarding unsaved changes.
- [ ] Move a project folder containing its local source files and confirm relative sources still validate.

## Folders and files

- [ ] Add, edit, move between folders, and remove a file.
- [ ] Add file artwork and library artwork in PNG, JPEG, and WebP formats.
- [ ] Confirm a new file asks for its folder and download sources in the same dialog.
- [ ] Add an embedded file, an HTTPS-only file, and a file with both embedded and HTTPS sources.
- [ ] Add multiple HTTPS mirrors and optional SHA-256/size metadata.
- [ ] Create several folders, assign files through each file's Folder field, save, and reopen the project.
- [ ] Confirm assigned files appear beneath their folders and unassigned files appear under **Files without a folder**.
- [ ] Import a nested local folder and confirm its files and subfolders retain the same visible structure.

## Validation

- [ ] Confirm missing embedded files are reported as errors.
- [ ] Confirm HTTP links are rejected and HTTPS links are accepted.
- [ ] Confirm an online-only file without a SHA-256 is a warning rather than an error.
- [ ] Confirm unsupported or oversized artwork is rejected.
- [ ] Confirm a project with errors cannot be built.

## Package build

- [ ] Build an `.odrlib` containing artwork, folders, an embedded file, and an HTTPS mirror.
- [ ] Confirm Creator shows file/folder counts, final size, and package SHA-256.
- [ ] Open the package as a ZIP and confirm it contains `manifest.json`, `library.json`, catalog JSON, assets, and payload paths.
- [ ] Change one project field, increase the revision, rebuild, and confirm the permanent library ID stays unchanged while the package ID changes.
- [ ] Configure update-feed and package URLs, rebuild, and inspect the generated `.odrlib-feed.json`.
- [ ] Confirm the package manifest lists optional extension `U` version `1` and ODeR displays `U1`.
- [ ] Confirm a package without an update feed has no U1 declaration and still imports normally.

## Installed build

- [ ] Install `ODeR Creator Installer.exe` and confirm the Start menu shortcut works.
- [ ] Double-click an `.odrproj` and confirm it opens in Creator.
- [ ] Confirm `.oder` still opens in the normal ODeR application.
- [ ] Confirm Windows file properties show `1.1.0-alpha.2` for ODeR and `2026.0.1a` for Creator.
- [ ] Mount `ODeR Creator.dmg` on macOS, copy the app to Applications, and confirm `.odrproj` opens in Creator.
- [ ] Confirm no portable Creator or ODeR artifact is present in the release files.
