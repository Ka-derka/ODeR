import os
import tempfile
import threading
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
        self.patchers = [
            patch.object(
                cache, "profile_cache_db_path",
                lambda _profile_id: os.path.join(self.profile_dir, "cache.sqlite3"),
            ),
            patch.object(
                cache, "profile_cache_checkpoint_path",
                lambda _profile_id: os.path.join(self.profile_dir, "cache.full-update-backup.sqlite3"),
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
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
        for patcher in reversed(self.patchers):
            patcher.stop()
        cache._ACTIVE_FULL_UPDATES.discard(self.profile_id)
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

    def test_folder_write_marks_parent_crawled_in_same_transaction(self):
        cache.mark_crawled(self.profile_id, self.base, False)
        cache.replace_children(self.profile_id, self.base, [])
        self.assertTrue(cache.get_node(self.profile_id, self.base)["crawled"])

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

    def test_single_folder_snapshot_does_not_copy_or_compare_descendants(self):
        run_id = cache.begin_snapshot(self.profile_id, "folder", self.base)
        cache.replace_children(self.profile_id, self.base + "photos/", [
            (self.base + "photos/holiday.jpg", "holiday.jpg", 0, "9 MB", self.base + "photos/", 0),
        ])
        result = cache.finish_snapshot(self.profile_id, run_id)
        self.assertEqual(result["changed_count"], 0)
        self.assertEqual(result["before_count"], 3)

    def test_grow_snapshot_is_limited_to_two_visible_levels(self):
        album = self.base + "photos/album/"
        cache.replace_children(self.profile_id, self.base + "photos/", [
            (self.base + "photos/holiday.jpg", "holiday.jpg", 0, "3 MB", self.base + "photos/", 0),
            (album, "album", 1, None, self.base + "photos/", 1),
        ])
        cache.replace_children(self.profile_id, album, [
            (album + "deep.jpg", "deep.jpg", 0, "4 MB", album, 0),
        ])
        run_id = cache.begin_snapshot(self.profile_id, "grow", self.base)
        result = cache.finish_snapshot(self.profile_id, run_id)
        # Three direct root entries plus the two children of its direct folder.
        # The deeper album child is outside a one-level grow operation.
        self.assertEqual(result["before_count"], 5)
        self.assertEqual(result["after_count"], 5)

    def test_database_records_schema_version(self):
        with cache._reader(self.profile_id) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], cache.SCHEMA_VERSION)
            self.assertEqual(
                conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
                str(cache.SCHEMA_VERSION),
            )

    def test_bulk_replace_rebuilds_search_and_live_triggers(self):
        cache.replace_all_nodes(self.profile_id, self.base, [
            (self.base + "archive/", "archive", 1, None, self.base, 1),
            (self.base + "archive/alpha.txt", "alpha.txt", 0, "1 KB", self.base + "archive/", 0),
        ])
        self.assertEqual([row["name"] for row in cache.search(self.profile_id, "alpha")], ["alpha.txt"])
        cache.upsert_nodes(self.profile_id, [
            (self.base + "archive/beta.txt", "beta.txt", 0, "2 KB", self.base + "archive/", 0),
        ])
        self.assertEqual([row["name"] for row in cache.search(self.profile_id, "beta")], ["beta.txt"])

    def test_full_update_checkpoint_rolls_back_every_cache_change(self):
        cache.begin_full_update(self.profile_id)
        cache.replace_all_nodes(self.profile_id, self.base, [
            (self.base + "replacement.bin", "replacement.bin", 0, "10 MB", self.base, 0),
        ])
        self.assertIsNotNone(cache.get_node(self.profile_id, self.base + "replacement.bin"))

        self.assertTrue(cache.rollback_full_update(self.profile_id))

        self.assertIsNone(cache.get_node(self.profile_id, self.base + "replacement.bin"))
        self.assertIsNotNone(cache.get_node(self.profile_id, self.base + "manual.pdf"))

    def test_successful_full_update_discards_checkpoint(self):
        checkpoint = cache.begin_full_update(self.profile_id)
        cache.replace_all_nodes(self.profile_id, self.base, [
            (self.base + "replacement.bin", "replacement.bin", 0, "10 MB", self.base, 0),
        ])
        cache.commit_full_update(self.profile_id)
        self.assertFalse(os.path.exists(checkpoint))
        self.assertIsNotNone(cache.get_node(self.profile_id, self.base + "replacement.bin"))

    def test_interrupted_full_update_is_recovered_during_initialize(self):
        checkpoint = cache.begin_full_update(self.profile_id)
        cache.replace_all_nodes(self.profile_id, self.base, [
            (self.base + "partial.bin", "partial.bin", 0, "1 MB", self.base, 0),
        ])
        cache._ACTIVE_FULL_UPDATES.discard(self.profile_id)  # simulate a new process
        cache.initialize(self.profile_id, self.base)
        self.assertFalse(os.path.exists(checkpoint))
        self.assertIsNone(cache.get_node(self.profile_id, self.base + "partial.bin"))
        self.assertIsNotNone(cache.get_node(self.profile_id, self.base + "manual.pdf"))

    def test_wal_reader_does_not_wait_for_python_writer_lock(self):
        writer_ready = threading.Event()
        release_writer = threading.Event()
        read_finished = threading.Event()

        def hold_writer_lock():
            with cache._lock(self.profile_id):
                writer_ready.set()
                release_writer.wait(2)

        def read_count():
            cache.count_nodes(self.profile_id)
            read_finished.set()

        holder = threading.Thread(target=hold_writer_lock)
        holder.start()
        self.assertTrue(writer_ready.wait(1))
        reader = threading.Thread(target=read_count)
        reader.start()
        try:
            self.assertTrue(read_finished.wait(0.5), "WAL reader waited on the in-process writer lock")
        finally:
            release_writer.set()
            holder.join(2)
            reader.join(2)

    def test_full_and_incremental_pending_markers(self):
        cache.mark_crawled(self.profile_id, self.base, True)
        cache.mark_crawled(self.profile_id, self.base + "photos/", True)
        self.assertEqual(cache.pending_dirs(self.profile_id), [])
        cache.mark_all_dirs_pending(self.profile_id)
        self.assertEqual(set(cache.pending_dirs(self.profile_id)), {self.base, self.base + "photos/"})


if __name__ == "__main__":
    unittest.main()
