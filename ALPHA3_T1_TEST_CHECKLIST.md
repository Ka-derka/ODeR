# ODeR Alpha 3 / Creator 2026.0.2a test checklist

Use ordinary test files that you are allowed to redistribute. Keep a second BitTorrent client or machine available if you want to test a real swarm.

## Creator folder workflow

- [ ] Start ODeR Creator and confirm it reports `2026.0.2a`.
- [ ] Choose **File → Import folder** and select a folder containing files and subfolders.
- [ ] Confirm every file appears once with separate include, Bundle, and Torrent checkboxes.
- [ ] Confirm files are included and torrent-selected by default while Bundle is off.
- [ ] Deselect one file completely and confirm it is absent from the created project.
- [ ] Bundle one file, leave another torrent-only, and confirm the original subfolders become Creator folders.
- [ ] Save and reopen the `.odrproj`; confirm its source folder and all per-file source choices survive.

## Torrent authoring

- [ ] Add at least one valid `https://` or `udp://` tracker and optionally an HTTPS web seed.
- [ ] Test automatic piece size, then one manually selected piece size.
- [ ] Toggle private mode and confirm the project still validates.
- [ ] Build the library and confirm both `<name>.odrlib` and `<name>.torrent` are created.
- [ ] Build a folder with several unevenly sized files and confirm Creator does not report an incomplete torrent file map.
- [ ] Open the standalone torrent in another client and confirm its name, files, folders, trackers, and sizes match Creator.
- [ ] Confirm Creator preview shows `T1`, or `U1 · T1` when an update feed is also configured.
- [ ] Confirm a torrent-only artifact declares T1 as required and an artifact with a bundled or HTTPS fallback permits optional T1.

## ODeR import and browsing

- [ ] Start ODeR and confirm it reports `1.1.0-alpha.3`.
- [ ] Drag or double-click the T1 `.odrlib` and inspect its artwork and metadata preview.
- [ ] Confirm import completes without contacting a tracker or starting a download.
- [ ] Open the library and confirm Torrent appears in the Source column and source chooser.
- [ ] Confirm bundled and HTTPS fallbacks remain separately selectable where provided.
- [ ] Confirm library Information shows its T1 or U1/T1 extension badges.

## Torrent downloads

- [ ] Seed the generated `.torrent` from the original source folder in another client.
- [ ] Download one nested file from ODeR and confirm only that file is selected by ODeR.
- [ ] Confirm the Downloads page reports progress, speed, ETA, and the library/folder destination.
- [ ] Pause the job, close ODeR, reopen it, resume, and confirm partial data is reused.
- [ ] Confirm the completed file lands under `<Downloads>/<library>/<folder>/<filename>`.
- [ ] Compare its SHA-256 with the original.
- [ ] Disable DHT and local discovery and confirm a tracker-connected download still works.
- [ ] Disable T1 downloads entirely and confirm ODeR explains how to re-enable them.
- [ ] Test download and upload limits and confirm zero means Unlimited.
- [ ] Confirm ODeR stops the torrent after completion instead of continuing to seed.

## Validation and failure handling

- [ ] Remove peers and confirm a pending download can be paused without freezing the UI.
- [ ] Move a Creator source file before building and confirm validation identifies the missing file.
- [ ] Change a file after scanning and confirm the rebuilt package records the new size/hash consistently.
- [ ] Tamper with `extensions/T1.json`, the embedded `.torrent`, a file index, a path, or a hash and confirm import is rejected before library data changes.
- [ ] Confirm a package with unknown optional extension metadata still opens, while an unknown required extension is refused.
- [ ] Confirm normal directory crawling, `.oder` import/export, HTTPS downloads, bundled extraction, U1 updates, themes, and single-instance file opening still work.

## Packaging

- [ ] Install `ODeR Installer.exe` over Alpha 2 and confirm settings, libraries, downloads, and caches remain.
- [ ] Install `ODeR Creator Installer.exe` and confirm `.odrproj` file association still opens Creator.
- [ ] Confirm Windows file properties report `1.1.0-alpha.3` for ODeR and `2026.0.2a` for Creator.
- [ ] On macOS, open both `.app` bundles/DMGs and repeat one Creator build plus one T1 library import.
