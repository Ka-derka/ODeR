from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from core import odrlib_store as store
from core.odrlib import (OdrLibError, build_library, inspect_update_feed, new_project,
                         save_project, load_project, write_update_feed, refresh_update_feed)
from core import update_security as security
from tests.test_odrlib_store import _Session


class SignedUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {"ODER_DATA_DIR_OVERRIDE": str(self.root / "data")})
        env.start()
        self.addCleanup(env.stop)
        log = patch("core.applog.log")
        log.start()
        self.addCleanup(log.stop)
        self.key = security.create_signing_key()
        self.project = new_project()
        self.project["library"]["update"].update(protocol="U1.1", signing_key=self.key,
                                                  feed_url="http://localhost/feed.json")
        self.project["publishing"]["package_url"] = "http://localhost/library.odrlib"

    def build(self, revision=1):
        self.project["library"]["revision"] = revision
        return build_library(self.project, str(self.root / f"library-{revision}.odrlib"))

    def installed(self):
        result = self.build()
        profile = store.import_library(result.path).profile
        store.trust_library_publisher(profile, self.key["key_id"])
        return profile

    def envelope(self, result):
        return json.loads(Path(result.feed_path).read_text("utf-8"))

    def session(self, result, envelope=None):
        return _Session({self.project["library"]["update"]["feed_url"]: json.dumps(envelope or self.envelope(result)).encode(),
                         self.project["publishing"]["package_url"]: Path(result.path).read_bytes()})

    def resign(self, envelope, **kwargs):
        return security.sign_feed(envelope["signed"], self.key, **kwargs)

    def test_keys_stay_outside_project_and_package(self):
        path = self.root / "project.odrproj"
        save_project(path, self.project)
        self.assertEqual(load_project(path)["library"]["update"]["signing_key"], self.key)
        result = self.build()
        self.assertIn("U1.1", [e.badge for e in result.package.extensions])
        self.assertTrue(next(e for e in result.package.extensions if e.badge == "U1.1").required)
        with zipfile.ZipFile(result.path) as archive:
            for name in archive.namelist():
                self.assertNotIn(b"PRIVATE KEY", archive.read(name))
        self.assertNotIn("PRIVATE KEY", path.read_text())
        self.assertEqual(len(list(Path(security.signing_key_directory()).glob("*.pem"))), 1)

    def test_untrusted_import_never_contacts_server_or_pins_key(self):
        profile = store.import_library(self.build().path).profile
        self.assertIsNone(security.trusted_state(self.project["library"]["id"]))
        session = Mock()
        with self.assertRaisesRegex(OdrLibError, "Trust"):
            store.check_for_update(profile, session)
        session.get.assert_not_called()
        with self.assertRaises(OdrLibError):
            store.trust_library_publisher(profile, "f" * 64)

    def test_signed_http_update_roundtrip(self):
        profile = self.installed()
        result = self.build(2)
        session = self.session(result)
        feed = store.check_for_update(profile, session)
        installed = store.download_update(profile, feed, session)
        self.assertEqual(installed.package.revision, 2)
        self.assertEqual(installed.profile["odrlib"]["update_key"], self.key)
        self.assertTrue(all(response.closed for response in session.returned))

    def test_tampering_and_wrong_publisher_are_rejected(self):
        envelope = self.envelope(self.build())
        for field, value in (("revision", 44), ("url", "http://attacker.test/payload"), ("sha256", "0" * 64)):
            altered = deepcopy(envelope)
            altered["signed"]["latest"][field] = value
            with self.subTest(field=field), self.assertRaises(OdrLibError):
                inspect_update_feed(altered, trusted_key=self.key)
        wrong_key = security.create_signing_key()
        with self.assertRaisesRegex(OdrLibError, "key changed"):
            inspect_update_feed(security.sign_feed(envelope["signed"], wrong_key), trusted_key=self.key)

    def test_expired_future_and_malformed_signed_metadata(self):
        envelope = self.envelope(self.build())
        now = datetime.now(timezone.utc)
        for stamp in (now - timedelta(days=40), now + timedelta(hours=1)):
            with self.subTest(stamp=stamp), self.assertRaises(OdrLibError):
                inspect_update_feed(self.resign(envelope, now=stamp))
        for value in (True, 1.5, "2"):
            altered = deepcopy(envelope)
            altered["signed"]["latest"]["revision"] = value
            with self.subTest(value=value), self.assertRaises(OdrLibError):
                inspect_update_feed(self.resign(altered))
        with self.assertRaises(OdrLibError):
            security.strict_json('{"a":1,"a":2}')
        with self.assertRaises(OdrLibError):
            security.strict_json('{"a":NaN}')

    def test_seen_revision_is_persisted_even_if_download_cancelled(self):
        profile = self.installed()
        older = self.build(2)
        newer = self.build(3)
        store.check_for_update(profile, self.session(newer))
        self.assertEqual(security.trusted_state(self.project["library"]["id"])["revision"], 3)
        with self.assertRaisesRegex(OdrLibError, "roll back"):
            store.check_for_update(profile, self.session(older))

    def test_same_revision_changed_bytes_and_older_timestamp_rejected(self):
        profile = self.installed()
        result = self.build(2)
        envelope = self.envelope(result)
        store.check_for_update(profile, self.session(result))
        altered = deepcopy(envelope)
        altered["signed"]["latest"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(OdrLibError, "without increasing"):
            store.check_for_update(profile, self.session(result, self.resign(altered)))
        with self.assertRaisesRegex(OdrLibError, "replayed"):
            store.check_for_update(profile, self.session(result, self.resign(envelope, now=datetime.now(timezone.utc) - timedelta(hours=1))))

    def test_unsigned_downgrade_wrong_channel_and_manual_bypass_rejected(self):
        profile = self.installed()
        result = self.build(2)
        envelope = self.envelope(result)
        unsigned = deepcopy(envelope["signed"])
        unsigned["format_version"] = 1
        with self.assertRaisesRegex(OdrLibError, "Unsigned"):
            store.check_for_update(profile, self.session(result, unsigned))
        altered = deepcopy(envelope)
        altered["signed"]["channel"] = "preview"
        with self.assertRaisesRegex(OdrLibError, "channel"):
            store.check_for_update(profile, self.session(result, self.resign(altered)))
        with self.assertRaisesRegex(OdrLibError, "signed update feed"):
            store.import_library(result.path, conflict_policy="replace", replace_profile_id=profile["id"])

    def test_mutated_dialog_info_cannot_change_authenticated_download(self):
        profile = self.installed()
        result = self.build(2)
        session = self.session(result)
        feed = store.check_for_update(profile, session)
        feed = replace(feed, url="http://attacker.test/evil", revision=500, sha256="0" * 64)
        self.assertEqual(store.download_update(profile, feed, session).package.revision, 2)

    def test_package_key_cannot_change_even_with_valid_old_key_feed(self):
        profile = self.installed()
        self.project["library"]["update"]["signing_key"] = security.create_signing_key()
        result = self.build(2)
        envelope = security.sign_feed(self.envelope(result)["signed"], self.key)
        session = self.session(result, envelope)
        feed = store.check_for_update(profile, session)
        with self.assertRaisesRegex(OdrLibError, "trusted publisher"):
            store.download_update(profile, feed, session)
        self.assertEqual(store.load_profile_package(profile).revision, 1)

    def test_corrupt_trust_fails_closed_without_backup_recovery(self):
        self.installed()
        path = self.root / "data" / "library-update-trust" / (self.project["library"]["id"] + ".json")
        path.write_text("broken")
        for _ in range(2):
            with self.assertRaisesRegex(OdrLibError, "unreadable"):
                security.trusted_state(self.project["library"]["id"])

    def test_http_requires_signed_mode_and_redirects_are_checked_before_following(self):
        session = Mock()
        for url in ("http://localhost/x", "https://user:pass@example.org/x", "https://example.org/x#fragment"):
            with self.assertRaises(OdrLibError):
                security.get_response(session, url)
        session.get.assert_not_called()
        response = Mock(status_code=302, headers={"Location": "http://example.org/x"})
        session.get.return_value = response
        with self.assertRaisesRegex(OdrLibError, "insecure"):
            security.get_response(session, "https://example.org/start", allow_http=True)
        self.assertEqual(session.get.call_count, 1)
        response.close.assert_called_once()

    def test_signed_t2_allows_http_metainfo(self):
        self.project["publishing"].update(torrent_updates=True, update_torrent_url="http://localhost/library.odrlib.torrent")
        result = self.build()
        feed = inspect_update_feed(result.feed_path)
        from core.torrent_updates import fetch_metainfo, validate_metainfo
        data = Path(result.update_torrent_path).read_bytes()
        session = _Session({feed.torrent["url"]: data})
        self.assertEqual(fetch_metainfo(feed.torrent, session, allow_http=True), data)
        self.assertEqual(validate_metainfo(data, feed.torrent, feed.size, allow_http=True).num_files(), 1)
        with self.assertRaises(OdrLibError):
            fetch_metainfo(feed.torrent, session)

    def test_refresh_feed_preserves_package_bytes_and_revision(self):
        profile = self.installed()
        result = self.build(2)
        store.check_for_update(profile, self.session(result))
        before = Path(result.path).read_bytes()
        write_update_feed(result.package, result.path, result.feed_path, self.project["publishing"]["package_url"], validity_days=90)
        self.assertEqual(Path(result.path).read_bytes(), before)
        self.assertEqual(store.check_for_update(profile, self.session(result)).revision, 2)
        refreshed = refresh_update_feed(self.project, result.path)
        self.assertEqual(refreshed.sha256, result.sha256)
        self.assertEqual(Path(result.path).read_bytes(), before)
        self.assertEqual(store.check_for_update(profile, self.session(result)).revision, 2)

    def test_real_localhost_server_roundtrip(self):
        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(self.root)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            self.project["library"]["update"]["feed_url"] = base + "/library-2.odrlib-feed.json"
            self.project["publishing"]["package_url"] = base + "/library-2.odrlib"
            profile = self.installed()
            self.build(2)
            feed = store.check_for_update(profile)
            self.assertEqual(store.download_update(profile, feed).package.revision, 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
