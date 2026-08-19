import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from core import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.temp.name, "state")
        os.makedirs(self.state, exist_ok=True)
        self.cache_path = os.path.join(self.temp.name, "cache.sqlite3")
        connection = sqlite3.connect(self.cache_path)
        try:
            connection.executescript(
                """PRAGMA user_version=1;
                   CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
                   INSERT INTO meta VALUES('fts_available','1');
                   CREATE TABLE nodes (
                       url TEXT PRIMARY KEY, name TEXT, is_dir INTEGER,
                       size TEXT, parent_url TEXT, crawled INTEGER
                   );
                   CREATE TABLE scan_runs (id TEXT PRIMARY KEY);
                   INSERT INTO nodes VALUES('https://secret.test/','/',1,NULL,NULL,1);
                   INSERT INTO nodes VALUES('https://secret.test/file','secret.bin',0,'1 KB','https://secret.test/',0);
                """
            )
            connection.commit()
        finally:
            connection.close()

        def state_path(name):
            return os.path.join(self.state, name)

        self.patchers = [
            patch.object(diagnostics.settings, "load_settings", return_value={
                "theme": "dark", "download_concurrency": 2,
                "network_max_connections": 12, "request_timeout_seconds": 20,
                "browser_page_size": 500, "update_channel": "stable",
            }),
            patch.object(diagnostics.settings, "settings_path", lambda: state_path("settings.json")),
            patch.object(diagnostics.profiles, "load_profiles", return_value=[{
                "id": "secret-profile", "name": "Secret directory",
                "base_url": "https://secret.test/",
            }]),
            patch.object(diagnostics.profiles, "profiles_index_path", lambda: state_path("profiles.json")),
            patch.object(diagnostics.downloader, "load_queue", return_value=[{
                "status": "pending", "name": "secret.bin",
                "url": "https://secret.test/file", "destination_rel_path": "Secret/secret.bin",
            }]),
            patch.object(diagnostics.downloader, "queue_path", lambda: state_path("queue.json")),
            patch.object(diagnostics, "favorites_path", lambda: state_path("favorites.json")),
            patch.object(diagnostics, "package_history_path", lambda: state_path("packages.json")),
            patch.object(diagnostics, "profile_crawl_state_path", lambda _pid: state_path("crawl.json")),
            patch.object(diagnostics, "data_dir", lambda: self.temp.name),
            patch.object(diagnostics.cache, "profile_cache_db_path", lambda _pid: self.cache_path),
            patch.object(
                diagnostics.cache, "profile_cache_checkpoint_path",
                lambda _pid: os.path.join(self.temp.name, "checkpoint.sqlite3"),
            ),
            patch.object(
                diagnostics.applog, "get_all_lines",
                return_value=[(1, "2026-08-20 [ERROR] https://secret.test/file failed")],
            ),
            patch.object(diagnostics.applog, "log", lambda _message: None),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_report_contains_health_counts_without_directory_identity(self):
        report = diagnostics.collect_report()
        encoded = json.dumps(report)
        self.assertNotIn("secret.test", encoded)
        self.assertNotIn("Secret directory", encoded)
        self.assertNotIn("secret.bin", encoded)
        self.assertEqual(report["directories"][0]["cache"]["health"], "ok")
        self.assertEqual(report["directories"][0]["cache"]["entries"], 2)
        self.assertEqual(report["downloads"]["structured_paths"], 1)

    def test_export_optionally_includes_recent_logs_and_valid_zip(self):
        destination = diagnostics.export_report(
            os.path.join(self.temp.name, "diagnostics"), include_logs=True
        )
        self.assertTrue(destination.endswith(".zip"))
        with zipfile.ZipFile(destination, "r") as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"diagnostics.json", "README.txt", "recent-log.txt"},
            )
            self.assertIn("secret.test", archive.read("recent-log.txt").decode("utf-8"))
            self.assertNotIn(
                "secret.test", archive.read("diagnostics.json").decode("utf-8")
            )


if __name__ == "__main__":
    unittest.main()
