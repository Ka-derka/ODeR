# ODeR 1.1.0 Beta 1 test checklist

Use disposable test libraries and files. Test copyrighted material only when you are authorized to download and redistribute it.

## Install and upgrade

- [ ] Install over Alpha 3 and confirm ODeR reports `1.1.0-beta.1` while Creator still reports `2026.0.2a`.
- [ ] Confirm existing libraries, Downloads entries, settings, caches, and completed files remain present.
- [ ] On Intel macOS 12 Monterey, confirm `ODeR.app` and `ODeR Creator.app` launch instead of showing an unsupported-application warning.

## Existing-file opening

- [ ] Download one HTTPS file from an `.odrlib`, return to its library, select it, and confirm the action changes to **Open**.
- [ ] Click **Open** and double-click the row; confirm the local file opens and no new Downloads entry appears.
- [ ] Repeat with a completed T1 file whose entry says **Seeding**.
- [ ] Remove the completed entry from Downloads, leave the file in its structured folder, return to the library, and confirm it still opens directly.
- [ ] Test two different sources whose filenames collide and confirm each library item opens its own collision-safe destination.
- [ ] Rename or remove a downloaded file and confirm the library returns to **Download** rather than trying to open a missing path.
- [ ] Put a different-size file at the expected path and confirm ODeR does not mistake it for the expected library artifact.

## T1 seeding lifecycle

- [ ] In Creator, import a source tree with at least 179 files across 27 folders, build the `.odrlib`, and confirm no `libtorrent:213` v1/v2 metadata error appears.
- [ ] Import that larger `.odrlib` into ODeR and spot-check files from early, middle, and late folders; confirm every displayed name downloads the matching payload.
- [ ] Download a small T1 file and confirm its status changes to **Seeding** only after size and SHA-256 verification completes.
- [ ] With a second client on the LAN, add the generated `.torrent` and confirm it can receive data from ODeR. Local peer discovery should make this possible without public port forwarding.
- [ ] Quit ODeR from its tray menu, reopen it, and confirm the finished entry returns to **Seeding** without downloading the file again.
- [ ] Pause the seeding entry and confirm upload activity stops; resume it and confirm the peer can receive again.
- [ ] Remove the entry from Downloads and confirm the peer can no longer receive from that ODeR seed.
- [ ] Confirm the downloaded file remains in its normal library folder and still opens after the Downloads entry is removed.
- [ ] Repeat removal through **Clear finished** and confirm the same keep-file/stop-seed behavior.
- [ ] Download two selected files from the same multi-file torrent and confirm both complete without a duplicate-torrent error.
- [ ] Import the same `.odrlib` as a separate copy and confirm selecting its already-present file does not add a conflicting torrent handle.
- [ ] If testing on a filesystem without hard-link support, watch available space and confirm ODeR's fallback private seed copy is removed when the Downloads entry is removed.

## Internet peer test

- [ ] Test with a tracker or DHT-capable torrent and a peer outside the local network.
- [ ] If ODeR is behind CGNAT, confirm outgoing peer connections can still work; do not treat the inability to accept incoming connections as an ODeR failure.
- [ ] If UPnP or NAT-PMP is available on a public-IP connection, test the optional setting and confirm the router mapping disappears after ODeR quits.

## Queue and update behavior

- [ ] Confirm the bottom-right Downloads button reports seeding entries and its tooltip distinguishes active downloads, seeds, and failures.
- [ ] Confirm a seeding item can be opened from Downloads by double-click and from **Open file** in its menu.
- [ ] Confirm a seeding item counts as finished in a download group and does not keep an ODeR application update waiting for downloads to become idle.
- [ ] Confirm ordinary HTTPS and bundled downloads still complete, open, retry, pause, and clear normally.

## Regression pass

- [ ] Import, browse, update, and remove an `.odrlib` with U1 only, T1 only, and U1+T1.
- [ ] Crawl and update a normal directory library.
- [ ] Import/export a definition-only and full `.oder` package.
- [ ] Open Home, Favorites, Activity, Changes, Storage, Logs, Settings, and Downloads.
- [ ] Run `python -m unittest discover -s tests -v` and confirm all tests pass.
