import glob
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from core import cache, profiles, settings
from core.persistence import load_json, save_json
from core.state_schema import load_document, save_document, StateVersionError


class PersistenceTests(unittest.TestCase):
    def test_legacy_state_is_migrated_into_versioned_envelope(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = os.path.join(temporary_dir, "profiles.json")
            legacy = [{"id": "p", "base_url": "https://example.test/"}]
            save_json(path, legacy)

            loaded = load_document(path, "profiles", [], list)

            self.assertEqual(loaded, legacy)
            with open(path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertEqual(stored["format"], "oder-state")
            self.assertEqual(stored["kind"], "profiles")
            self.assertEqual(stored["schema_version"], 1)
            self.assertEqual(stored["data"], legacy)

    def test_future_state_schema_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = os.path.join(temporary_dir, "settings.json")
            future = {
                "format": "oder-state", "kind": "settings", "schema_version": 999,
                "written_by": "9.0.0", "data": {"theme": "future"},
            }
            save_json(path, future)
            with self.assertRaises(StateVersionError):
                load_document(path, "settings", {}, dict)
            with self.assertRaises(StateVersionError):
                save_document(path, "settings", {"theme": "dark"}, dict)
            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), future)

    def test_download_queue_schema_two_pins_legacy_destination(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = os.path.join(temporary_dir, "queue.json")
            version_one = {
                "format": "oder-state", "kind": "download-queue", "schema_version": 1,
                "written_by": "0.20.0", "data": [{
                    "id": "q", "profile_name": "Site", "name": "file.mkv",
                    "rel_path": "Season%201", "url": "https://x/Season%201/file.mkv",
                }],
            }
            save_json(path, version_one)
            queue = load_document(path, "download-queue", [], list)
            self.assertEqual(
                queue[0]["destination_rel_path"], "Site/Season%201/file.mkv"
            )
            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["schema_version"], 2)

    def test_corrupt_primary_is_restored_from_last_known_good_backup(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = os.path.join(temporary_dir, "state.json")
            save_json(path, {"generation": 1})
            save_json(path, {"generation": 2})
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"generation":')

            recovered = load_json(path, {}, dict)

            self.assertEqual(recovered, {"generation": 1})
            self.assertEqual(load_json(path, {}, dict), {"generation": 1})
            self.assertTrue(glob.glob(path + ".corrupt-*"))

    def test_unrecoverable_json_is_preserved_before_defaults_are_used(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = os.path.join(temporary_dir, "state.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not-json")

            self.assertEqual(load_json(path, [], list), [])
            self.assertFalse(os.path.exists(path))
            self.assertTrue(glob.glob(path + ".corrupt-*"))

    def test_missing_primary_is_restored_from_backup(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = os.path.join(temporary_dir, "state.json")
            save_json(path, {"safe": True})
            os.remove(path)
            self.assertEqual(load_json(path, {}, dict), {"safe": True})
            self.assertTrue(os.path.isfile(path))

    def test_settings_merge_missing_custom_palette_values(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = os.path.join(temporary_dir, "settings.json")
            save_json(path, {"theme": "custom", "custom_theme": {"accent": "#123456"}})
            with patch("core.settings.settings_path", return_value=path):
                loaded = settings.load_settings()
            self.assertEqual(loaded["custom_theme"]["accent"], "#123456")
            self.assertEqual(
                loaded["custom_theme"]["background"],
                settings.DEFAULTS["custom_theme"]["background"],
            )

    def test_profile_updates_are_serialized_without_losing_fields(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            index_path = os.path.join(temporary_dir, "profiles.json")
            save_json(index_path, [{
                "id": "profile1", "name": "Example", "base_url": "https://example.test/",
                "settings": {},
            }])
            barrier = threading.Barrier(3)

            def update(field, value):
                barrier.wait()
                profiles.update_profile("profile1", **{field: value})

            with patch("core.profiles.profiles_index_path", return_value=index_path):
                first = threading.Thread(target=update, args=("last_crawled", "now"))
                second = threading.Thread(target=update, args=("folders_cached", 42))
                first.start()
                second.start()
                barrier.wait()
                first.join()
                second.join()
                loaded = profiles.get_profile("profile1")

            self.assertEqual(loaded["last_crawled"], "now")
            self.assertEqual(loaded["folders_cached"], 42)
            self.assertIn("hosted_oder_url", loaded["settings"])

    def test_invalid_cache_database_is_quarantined_and_recreated(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = os.path.join(temporary_dir, "cache.sqlite3")
            with open(path, "wb") as handle:
                handle.write(b"not sqlite")
            cache._SCHEMA_READY.discard("broken")
            with patch("core.cache.profile_cache_db_path", return_value=path):
                cache.initialize("broken", "https://example.test/")
                self.assertEqual(cache.get_base_url("broken"), "https://example.test/")
            self.assertTrue(glob.glob(path + ".corrupt-*"))

    def test_newer_cache_schema_is_preserved_and_refused(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = os.path.join(temporary_dir, "cache.sqlite3")
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA user_version=999")
            connection.commit()
            connection.close()
            cache._SCHEMA_READY.discard("future")
            with patch("core.cache.profile_cache_db_path", return_value=path):
                with self.assertRaises(cache.CacheVersionError):
                    cache.initialize("future", "https://example.test/")
            self.assertTrue(os.path.isfile(path))
            self.assertFalse(glob.glob(path + ".corrupt-*"))


if __name__ == "__main__":
    unittest.main()
