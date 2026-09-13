import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from core.odrlib import (
    OdrLibError, build_library, import_folder_selection, inspect_update_feed,
    new_artifact, new_item, new_project, scan_folder, save_project, load_project,
)
from core import odrlib_store
from core.torrent_updates import validate_descriptor, fetch_metainfo, validate_metainfo
from tests.test_odrlib_store import _Session


class TorrentUpdateTests(unittest.TestCase):
    def setUp(self):
        self.log_patch = patch("core.applog.log")
        self.log_patch.start()
        self.addCleanup(self.log_patch.stop)

    def _project(self, root):
        project = new_project()
        project["library"].update({"name": "T2 sample", "creator": "Curator", "category": "Test"})
        project["library"]["update"]["feed_url"] = "https://example.org/feed.json"
        project["publishing"].update({
            "package_url": "https://example.org/library.odrlib", "torrent_updates": True,
            "update_torrent_url": "https://example.org/library.odrlib.torrent",
        })
        folder = Path(root) / "payload"
        folder.mkdir()
        (folder / "sample.txt").write_bytes(b"test payload")
        project, _ = import_folder_selection(project, str(folder), scan_folder(str(folder)))
        return project

    def test_build_roundtrip_and_package_torrent_is_separate(self):
        with tempfile.TemporaryDirectory() as root:
            project = self._project(root)
            path = os.path.join(root, "work.odrproj")
            save_project(path, project)
            loaded = load_project(path)
            self.assertTrue(loaded["publishing"]["torrent_updates"])
            built = build_library(project, os.path.join(root, "library.odrlib"))
            feed = inspect_update_feed(built.feed_path)
            self.assertEqual({e.badge for e in built.package.extensions}, {"U1", "T2"})
            self.assertTrue(any(e.required for e in built.package.extensions if e.badge == "T2"))
            self.assertNotEqual(built.torrent_path, built.update_torrent_path)
            data = Path(built.update_torrent_path).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), feed.torrent["sha256"])
            info = validate_metainfo(data, feed.torrent, built.size)
            self.assertEqual(info.num_files(), 1)
            self.assertEqual(feed.torrent["path"], "library.odrlib")
            self.assertNotIn("library.odrlib.torrent", {m["path"] for m in built.package.manifest["members"]})

    def test_t2_can_deliver_package_with_only_https_catalog_sources(self):
        with tempfile.TemporaryDirectory() as root:
            project = self._project(root)
            item = new_item(title="Remote file")
            item["artifacts"].append(new_artifact(name="remote.zip", url="https://example.org/remote.zip"))
            project["items"] = [item]
            project["collections"] = []
            built = build_library(project, os.path.join(root, "library.odrlib"))
            self.assertIsNone(built.torrent_path)
            self.assertTrue(built.update_torrent_path)
            self.assertFalse(next(e for e in built.package.extensions if e.badge == "T2").required)

    def test_metadata_rejects_traversal_bad_hash_and_wrong_package_size(self):
        with tempfile.TemporaryDirectory() as root:
            built = build_library(self._project(root), os.path.join(root, "library.odrlib"))
            feed = inspect_update_feed(built.feed_path)
            for value in ("../library.odrlib", "C:\\library.odrlib", "NUL.odrlib", "folder/library.odrlib"):
                with self.subTest(path=value), self.assertRaises(OdrLibError):
                    validate_descriptor({**feed.torrent, "path": value})
            session = _Session({feed.torrent["url"]: b"bad metadata"})
            with self.assertRaises(OdrLibError):
                fetch_metainfo(feed.torrent, session)
            self.assertTrue(session.returned[0].closed)
            with self.assertRaises(OdrLibError):
                validate_metainfo(Path(built.update_torrent_path).read_bytes(), feed.torrent, built.size + 1)

    def test_t2_requires_bootstrap_and_fallback_addresses(self):
        with tempfile.TemporaryDirectory() as root:
            project = self._project(root)
            project["publishing"]["update_torrent_url"] = "http://example.org/update.torrent"
            with self.assertRaises(OdrLibError):
                build_library(project, os.path.join(root, "library.odrlib"))

    def test_peer_delivery_and_https_fallback_keep_old_seed_metadata(self):
        for stalled in (False, True):
            with self.subTest(stalled=stalled), tempfile.TemporaryDirectory() as root:
                project = self._project(root)
                first = build_library(project, os.path.join(root, "one.odrlib"))
                project["library"]["revision"] = 2
                Path(root, "payload", "sample.txt").write_bytes(b"new payload!")
                second = build_library(project, os.path.join(root, "two.odrlib"))
                feed = inspect_update_feed(second.feed_path)
                package_data = Path(second.path).read_bytes()
                session = _Session({feed.url: package_data})
                with patch("core.paths.data_dir", return_value=os.path.join(root, "app-data")):
                    installed = odrlib_store.import_library(first.path)
                    source = installed.package.items[0]["artifacts"][0]["sources"][0]
                    old_metainfo = odrlib_store.torrent_metainfo(installed.profile, source)["data"]

                    def receive(_feed, destination, _session):
                        if stalled:
                            raise OdrLibError("no peers")
                        Path(destination).write_bytes(package_data)

                    with patch("core.torrent_updates.receive_package", side_effect=receive):
                        result = odrlib_store.download_update(installed.profile, feed, session,
                                                             prefer_torrent=True)
                    self.assertEqual(result.package.revision, 2)
                    self.assertEqual(len(session.returned), int(stalled))
                    self.assertEqual(odrlib_store.torrent_metainfo(result.profile, source)["data"], old_metainfo)

    def test_mismatched_peer_package_never_installs(self):
        with tempfile.TemporaryDirectory() as root:
            project = self._project(root)
            first = build_library(project, os.path.join(root, "one.odrlib"))
            project["library"]["revision"] = 2
            second = build_library(project, os.path.join(root, "two.odrlib"))
            feed = inspect_update_feed(second.feed_path)
            with patch("core.paths.data_dir", return_value=os.path.join(root, "app-data")):
                installed = odrlib_store.import_library(first.path)
                with patch("core.torrent_updates.receive_package", side_effect=lambda f, p, s: Path(p).write_bytes(b"bad")):
                    with self.assertRaises(OdrLibError):
                        odrlib_store.download_update(installed.profile, feed,
                                                     _Session({feed.url: b"bad"}), prefer_torrent=True)
                self.assertEqual(odrlib_store.load_profile_package(installed.profile).revision, 1)

    def test_real_package_transfer_over_loopback_only(self):
        from core.torrent_support import binding
        from core.torrent_updates import receive_package
        from core import downloader
        lt = binding()
        with tempfile.TemporaryDirectory() as root:
            built = build_library(self._project(root), os.path.join(root, "library.odrlib"))
            feed = inspect_update_feed(built.feed_path)
            data = Path(built.update_torrent_path).read_bytes()
            info = validate_metainfo(data, feed.torrent, feed.size)
            settings = {
                "enable_dht": False, "enable_lsd": False, "enable_upnp": False,
                "enable_natpmp": False, "listen_interfaces": "127.0.0.1:0",
                "outgoing_interfaces": "127.0.0.1", "allow_multiple_connections_per_ip": True,
            }
            seed = lt.session(settings)
            params = downloader._torrent_add_params(lt, info, root, 0)
            seed_handle = seed.add_torrent(params)
            receiver = None
            receiver_handle = None
            try:
                deadline = time.monotonic() + 8
                while not seed_handle.status().is_seeding and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(seed_handle.status().is_seeding)

                class ReceiverSession:
                    def add_torrent(self, params):
                        nonlocal receiver, receiver_handle
                        receiver = lt.session(settings)
                        receiver_handle = receiver.add_torrent(params)
                        receiver_handle.connect_peer(("127.0.0.1", seed.listen_port()))
                        return receiver_handle

                    def remove_torrent(self, handle):
                        nonlocal receiver, receiver_handle
                        receiver.remove_torrent(handle)
                        receiver_handle = None
                        receiver = None

                facade = types.SimpleNamespace(
                    session=lambda _settings: ReceiverSession(), add_torrent_params=lt.add_torrent_params,
                    torrent_flags=lt.torrent_flags, alert=lt.alert,
                )
                destination = os.path.join(root, "received.odrlib")
                with patch("core.torrent_support.binding", return_value=facade), patch(
                        "core.settings.load_settings", return_value={"torrent_enabled": True}):
                    receive_package(feed, destination, _Session({feed.torrent["url"]: data}),
                                    stall_timeout=8, total_timeout=12)
                self.assertEqual(Path(destination).read_bytes(), Path(built.path).read_bytes())
            finally:
                seed.remove_torrent(seed_handle)
                del seed_handle
                del seed
                receiver_handle = receiver = None
