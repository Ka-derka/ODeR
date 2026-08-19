import os
import tempfile
import unittest
from unittest.mock import patch

from core import cache, crawl, crawl_state, hosted_oder, library, oder_package, profiles


class FakeResponse:
    def __init__(self, url, status=200, body=b"", headers=None):
        self.url = url
        self.status_code = status
        self._body = body
        self.headers = dict(headers or {})
        self.encoding = "utf-8"

    def iter_content(self, chunk_size=1024 * 1024):
        for offset in range(0, len(self._body), max(1, chunk_size)):
            yield self._body[offset:offset + chunk_size]

    def close(self):
        pass


class FakeSession:
    def __init__(self, routes):
        self.routes = dict(routes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        status, body, headers = self.routes.get(url, (404, b"", {}))
        return FakeResponse(url, status, body, headers)

    def close(self):
        pass


class HostedOderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = os.path.join(self.temp.name, "data")
        os.makedirs(self.data, exist_ok=True)

        def profile_dir(profile_id):
            value = os.path.join(self.data, "profiles", profile_id)
            os.makedirs(value, exist_ok=True)
            return value

        def profile_cache_path(profile_id):
            return os.path.join(profile_dir(profile_id), "cache.json")

        def profile_cache_db_path(profile_id):
            return os.path.join(profile_dir(profile_id), "cache.sqlite3")

        def profile_cache_checkpoint_path(profile_id):
            return os.path.join(profile_dir(profile_id), "cache.full-update-backup.sqlite3")

        self.patchers = [
            patch.object(profiles, "profiles_index_path", lambda: os.path.join(self.data, "profiles.json")),
            patch.object(profiles, "profile_dir", profile_dir),
            patch.object(profiles, "profile_cache_path", profile_cache_path),
            patch.object(cache, "profile_cache_path", profile_cache_path),
            patch.object(cache, "profile_cache_db_path", profile_cache_db_path),
            patch.object(cache, "profile_cache_checkpoint_path", profile_cache_checkpoint_path),
            patch.object(oder_package, "data_dir", lambda: self.data),
            patch.object(oder_package, "profile_dir", profile_dir),
            patch.object(oder_package, "profile_cache_db_path", profile_cache_db_path),
            patch.object(library, "package_history_path", lambda: os.path.join(self.data, "packages.json")),
            patch.object(crawl_state, "profile_crawl_state_path", lambda pid: os.path.join(profile_dir(pid), "crawl-state.json")),
        ]
        for patcher in self.patchers:
            patcher.start()

        self.profile = profiles.create_profile("Hosted archive", "https://example.test/files/")
        cache.initialize(self.profile["id"], self.profile["base_url"])
        base = self.profile["base_url"]
        cache.upsert_nodes(self.profile["id"], [
            (base + "docs/", "docs", 1, None, base, 1),
            (base + "readme.txt", "readme.txt", 0, "42 KB", base, 0),
        ])
        self.package_path = oder_package.export_directory(
            self.profile, os.path.join(self.temp.name, "hosted.oder"), include_cache=True,
        ).path
        with open(self.package_path, "rb") as handle:
            self.package_bytes = handle.read()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        cache._ACTIVE_FULL_UPDATES.clear()
        cache._SCHEMA_READY.clear()
        self.temp.cleanup()

    def _fetch(self, session, **kwargs):
        package_target = os.path.join(self.temp.name, "downloaded.oder")
        cache_target = os.path.join(self.temp.name, "materialized.sqlite3")
        return hosted_oder.fetch_hosted_index(
            session, self.profile["base_url"], package_target, cache_target,
            timeout=2, log=lambda _message: None, **kwargs,
        )

    def test_http_and_html_advertisements_are_resolved(self):
        html = '<html><head><link rel="oder-index" href="../indexes/latest.oder"></head></html>'
        urls = hosted_oder.advertised_package_urls(
            self.profile["base_url"], html,
            '<https://cdn.example.test/archive.oder>; rel="oder-index"; type="application/vnd.oder+zip"',
        )
        self.assertEqual(urls, [
            "https://cdn.example.test/archive.oder",
            "https://example.test/indexes/latest.oder",
        ])

    def test_advertised_package_is_downloaded_validated_and_applied(self):
        package_url = "https://cdn.example.test/releases/archive.oder"
        html = f'<link rel="oder-index" type="{hosted_oder.MEDIA_TYPE}" href="{package_url}">' 
        session = FakeSession({
            self.profile["base_url"]: (200, html.encode(), {"Content-Type": "text/html"}),
            package_url: (200, self.package_bytes, {
                "Content-Length": str(len(self.package_bytes)), "ETag": '"v1"',
            }),
        })
        result = self._fetch(session, auto_detect=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "downloaded")
        self.assertEqual(result.discovered_via, "advertised")
        self.assertEqual(result.requests, 2)
        self.assertTrue(os.path.isfile(result.cache_path))

        cache.replace_children(self.profile["id"], self.profile["base_url"], [])
        counts = oder_package.apply_hosted_cache(
            self.profile["id"], result.info, result.cache_path, self.profile["base_url"],
        )
        self.assertEqual(counts, {"entries": 3, "folders": 2, "files": 1})
        self.assertEqual(cache.get_node(self.profile["id"], self.profile["base_url"] + "readme.txt")["name"], "readme.txt")

    def test_conventional_root_package_is_detected(self):
        package_url = self.profile["base_url"] + "index.oder"
        session = FakeSession({
            self.profile["base_url"]: (200, b"<html></html>", {}),
            package_url: (200, self.package_bytes, {}),
        })
        result = self._fetch(session, auto_detect=True)
        self.assertEqual(result.source, package_url)
        self.assertEqual(result.discovered_via, "convention")

    def test_conditional_request_skips_unchanged_package(self):
        package_url = "https://cdn.example.test/archive.oder"
        session = FakeSession({package_url: (304, b"", {"ETag": '"v1"'})})
        previous = {
            "mode": "hosted_oder", "source": package_url, "etag": '"v1"',
            "base_url": self.profile["base_url"],
        }
        result = self._fetch(session, previous=previous, auto_detect=True)
        self.assertEqual(result.status, "unchanged")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][1]["headers"]["If-None-Match"], '"v1"')

    def test_wrong_directory_package_is_ignored(self):
        other = profiles.create_profile("Other", "https://other.example.test/")
        cache.initialize(other["id"], other["base_url"])
        other_path = oder_package.export_directory(
            other, os.path.join(self.temp.name, "other.oder"), include_cache=True,
        ).path
        with open(other_path, "rb") as handle:
            other_bytes = handle.read()
        url = "https://cdn.example.test/wrong.oder"
        messages = []
        result = hosted_oder.fetch_hosted_index(
            FakeSession({url: (200, other_bytes, {})}),
            self.profile["base_url"], os.path.join(self.temp.name, "wrong-download.oder"),
            os.path.join(self.temp.name, "wrong-cache.sqlite3"), explicit_url=url,
            auto_detect=False, log=messages.append,
        )
        self.assertIsNone(result)
        self.assertTrue(any("different directory" in message for message in messages))

    def test_crawl_uses_hosted_package_and_skips_folder_requests(self):
        package_url = self.profile["base_url"] + "index.oder"
        cache.replace_children(self.profile["id"], self.profile["base_url"], [
            (self.profile["base_url"] + "stale.bin", "stale.bin", 0, "1 KB", self.profile["base_url"], 0),
        ])
        session = FakeSession({
            self.profile["base_url"]: (200, b"<html></html>", {}),
            package_url: (200, self.package_bytes, {"ETag": '"crawl-v1"'}),
        })
        progress = []
        with (
            patch.object(crawl, "make_session", return_value=session),
            patch.object(crawl, "load_settings", return_value={
                "network_max_connections": 12, "incremental_stale_days": 7,
            }),
            patch.object(crawl, "fetch_html_with_backoff", side_effect=AssertionError("folder crawl should be skipped")),
        ):
            self.assertTrue(crawl.crawl_profile(
                self.profile, progress_cb=progress.append, log=lambda _message: None,
            ))
        self.assertEqual(progress[-1]["mode"], "hosted")
        self.assertTrue(progress[-1]["done"])
        self.assertEqual(progress[-1]["changes"]["new_count"], 2)
        self.assertEqual(progress[-1]["changes"]["removed_count"], 1)
        stored = profiles.get_profile(self.profile["id"])
        self.assertEqual(stored["hosted_index"]["source"], package_url)
        self.assertEqual(stored["hosted_index"]["etag"], '"crawl-v1"')

    def test_failed_hosted_apply_restores_previous_index_before_fallback(self):
        base = self.profile["base_url"]
        package_url = base + "index.oder"
        cache.replace_children(self.profile["id"], base, [
            (base + "last-known-good.bin", "last-known-good.bin", 0, "7 KB", base, 0),
        ])
        session = FakeSession({
            base: (200, b"<html></html>", {}),
            package_url: (200, self.package_bytes, {}),
        })

        def fail_after_replacement(profile_id, _info, _path, expected_base):
            cache.replace_children(profile_id, expected_base, [
                (expected_base + "partial.bin", "partial.bin", 0, "1 KB", expected_base, 0),
            ])
            raise oder_package.PackageError("simulated post-apply validation failure")

        messages = []
        with (
            patch.object(crawl, "make_session", return_value=session),
            patch.object(crawl, "load_settings", return_value={
                "network_max_connections": 12, "incremental_stale_days": 7,
            }),
            patch.object(crawl.oder_package, "apply_hosted_cache", side_effect=fail_after_replacement),
            patch.object(crawl.index_detect, "detect_index", side_effect=RuntimeError("fallback unavailable")),
        ):
            self.assertFalse(crawl.crawl_profile(
                self.profile, progress_cb=lambda _progress: None, log=messages.append,
            ))

        self.assertIsNotNone(cache.get_node(self.profile["id"], base + "last-known-good.bin"))
        self.assertIsNone(cache.get_node(self.profile["id"], base + "partial.bin"))
        self.assertTrue(any("restored the previous index" in message for message in messages))

    def test_missing_hosted_package_falls_back_to_existing_index_detection(self):
        base = self.profile["base_url"]
        nodes = {
            base: {"name": "/", "is_dir": True, "crawled": True},
            base + "fallback.txt": {"name": "fallback.txt", "is_dir": False, "size": "5 KB"},
        }
        session = FakeSession({})
        with (
            patch.object(crawl, "make_session", return_value=session),
            patch.object(crawl, "load_settings", return_value={
                "network_max_connections": 12, "incremental_stale_days": 7,
            }),
            patch.object(crawl.hosted_oder, "fetch_hosted_index", return_value=None),
            patch.object(crawl.index_detect, "detect_index", return_value={
                "mode": "full_tree", "source": base + "index.json", "nodes": nodes,
            }),
        ):
            self.assertTrue(crawl.crawl_profile(
                self.profile, progress_cb=lambda _progress: None, log=lambda _message: None,
            ))
        self.assertIsNotNone(cache.get_node(self.profile["id"], base + "fallback.txt"))
        # Full-tree contents are re-detected next time instead of persisting an
        # empty descriptor that could wipe the cache on a later update.
        self.assertIsNone(profiles.get_profile(self.profile["id"])["index_source"])

    def test_unchanged_hosted_full_update_does_not_mark_folders_pending(self):
        source = "https://cdn.example.test/archive.oder"
        cache.mark_crawled(self.profile["id"], self.profile["base_url"], True)
        cache.mark_crawled(self.profile["id"], self.profile["base_url"] + "docs/", True)
        profiles.update_profile(self.profile["id"], hosted_index={
            "mode": "hosted_oder", "source": source, "etag": '"stable"',
            "base_url": self.profile["base_url"],
        })
        profile = profiles.get_profile(self.profile["id"])
        session = FakeSession({source: (304, b"", {"ETag": '"stable"'})})
        with (
            patch.object(crawl, "make_session", return_value=session),
            patch.object(crawl, "load_settings", return_value={
                "network_max_connections": 12, "incremental_stale_days": 7,
            }),
        ):
            self.assertTrue(crawl.crawl_profile(
                profile, mode="full", progress_cb=lambda _progress: None,
                log=lambda _message: None,
            ))
        self.assertEqual(cache.pending_dirs(self.profile["id"]), [])

    def test_cleared_cache_forces_hosted_package_body_to_download_again(self):
        source = "https://cdn.example.test/archive.oder"
        profiles.update_profile(self.profile["id"], hosted_index={
            "mode": "hosted_oder", "source": source, "etag": '"old"',
            "base_url": self.profile["base_url"],
        })
        cache.clear_database(self.profile["id"], self.profile["base_url"])
        session = FakeSession({source: (200, self.package_bytes, {"ETag": '"new"'})})
        with (
            patch.object(crawl, "make_session", return_value=session),
            patch.object(crawl, "load_settings", return_value={
                "network_max_connections": 12, "incremental_stale_days": 7,
            }),
        ):
            self.assertTrue(crawl.crawl_profile(
                profiles.get_profile(self.profile["id"]), progress_cb=lambda _progress: None,
                log=lambda _message: None,
            ))
        self.assertNotIn("If-None-Match", session.calls[0][1]["headers"])
        self.assertEqual(cache.count_nodes(self.profile["id"]), 3)


if __name__ == "__main__":
    unittest.main()
