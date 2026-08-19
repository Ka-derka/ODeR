import os
import tempfile
import unittest
from unittest.mock import patch

from core import cache


class CacheFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.profile_id = "cache-features"
        self.base = "https://example.test/files/"
        self.profile_dir = os.path.join(self.temp.name, self.profile_id)
        os.makedirs(self.profile_dir, exist_ok=True)
        self.patcher = patch.object(
            cache, "profile_cache_db_path",
            lambda _profile_id: os.path.join(self.profile_dir, "cache.sqlite3"),
        )
        self.patcher.start()
        cache.initialize(self.profile_id, self.base)
        cache.replace_children(self.profile_id, self.base, [
            (self.base + "photos/", "photos", 1, None, self.base, 1),
            (self.base + "manual.pdf", "manual.pdf", 0, "2 MB", self.base, 0),
            (self.base + "movie.mp4", "movie.mp4", 0, "150 MB", self.base, 0),
        ])
        cache.replace_children(self.profile_id, self.base + "photos/", [
            (self.base + "photos/holiday.jpg", "holiday.jpg", 0, "3 MB", self.base + "photos/", 0),
        ])

    def tearDown(self):
        self.patcher.stop()
        cache._SCHEMA_READY.discard(self.profile_id)
        self.temp.cleanup()

    def test_paging_and_filtered_search(self):
        first = cache.get_children(self.profile_id, self.base, limit=2, offset=0)
        second = cache.get_children(self.profile_id, self.base, limit=2, offset=2)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 1)
        self.assertEqual(cache.child_count(self.profile_id, self.base), 3)
        self.assertEqual([row["name"] for row in cache.search(self.profile_id, "holiday")], ["holiday.jpg"])
        self.assertEqual([row["name"] for row in cache.search(self.profile_id, "*.pdf")], ["manual.pdf"])
        self.assertEqual([row["name"] for row in cache.search(
            self.profile_id, "movie", file_type="video", min_size=100 * 1024 * 1024,
        )], ["movie.mp4"])
        self.assertEqual(cache.search(self.profile_id, "manual", include_files=False), [])

    def test_atomic_folder_refresh_removes_disappeared_subtree(self):
        result = cache.replace_children(self.profile_id, self.base, [
            (self.base + "manual.pdf", "manual.pdf", 0, "2 MB", self.base, 0),
        ])
        self.assertEqual(result["removed_roots"], 2)
        self.assertIsNone(cache.get_node(self.profile_id, self.base + "photos/holiday.jpg"))
        self.assertEqual(cache.count_nodes(self.profile_id), 2)

    def test_snapshot_records_new_removed_and_changed(self):
        run_id = cache.begin_snapshot(self.profile_id, "incremental", self.base)
        cache.replace_children(self.profile_id, self.base, [
            (self.base + "photos/", "photos", 1, None, self.base, 1),
            (self.base + "manual.pdf", "manual.pdf", 0, "4 MB", self.base, 0),
            (self.base + "new.zip", "new.zip", 0, "8 MB", self.base, 0),
        ])
        result = cache.finish_snapshot(self.profile_id, run_id)
        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(result["changed_count"], 1)
        types = {row["change_type"] for row in cache.snapshot_changes(self.profile_id, run_id)}
        self.assertEqual(types, {"new", "removed", "changed"})

    def test_full_and_incremental_pending_markers(self):
        cache.mark_crawled(self.profile_id, self.base, True)
        cache.mark_crawled(self.profile_id, self.base + "photos/", True)
        self.assertEqual(cache.pending_dirs(self.profile_id), [])
        cache.mark_all_dirs_pending(self.profile_id)
        self.assertEqual(set(cache.pending_dirs(self.profile_id)), {self.base, self.base + "photos/"})


if __name__ == "__main__":
    unittest.main()
