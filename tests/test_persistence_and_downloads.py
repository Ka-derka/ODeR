import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

try:
    import requests  # noqa: F401 - present in normal application installs
except ModuleNotFoundError:
    sys.modules["requests"] = types.ModuleType("requests")

from core import crawl_state, downloader, library


class PersistenceAndDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patchers = [
            patch.object(crawl_state, "profile_crawl_state_path", lambda profile_id: os.path.join(self.temp.name, profile_id, "state.json")),
            patch.object(downloader, "queue_path", lambda: os.path.join(self.temp.name, "queue.json")),
            patch.object(downloader.applog, "log", lambda _message: None),
            patch.object(library, "favorites_path", lambda: os.path.join(self.temp.name, "favorites.json")),
            patch.object(library, "package_history_path", lambda: os.path.join(self.temp.name, "packages.json")),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_running_state_is_resumable_after_restart(self):
        os.makedirs(os.path.join(self.temp.name, "profile-1"), exist_ok=True)
        profile = {"id": "profile-1", "name": "Example"}
        crawl_state.mark_started("profile-1", "incremental", "now", 3)
        result = crawl_state.resumable([profile])
        self.assertEqual(result[0][0], profile)
        crawl_state.mark_completed("profile-1", 4)
        self.assertEqual(crawl_state.resumable([profile]), [])

    def test_download_group_summary_and_controls(self):
        group = downloader.new_group("Folder")
        first = downloader.enqueue("p", "Site", "https://x/a", "a", "", group["id"], group["name"])
        second = downloader.enqueue("p", "Site", "https://x/b", "b", "", group["id"], group["name"])
        downloader.update_item(first["id"], status="done", bytes_done=100, bytes_total=100)
        downloader.update_item(second["id"], status="downloading", bytes_done=50, bytes_total=100, speed_bps=25)
        summary = downloader.group_summary(group["id"])
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["done"], 1)
        self.assertEqual(summary["percent"], 75)
        self.assertEqual(summary["eta_seconds"], 2)
        downloader.pause_group(group["id"])
        self.assertEqual({item["status"] for item in downloader.items_in_group(group["id"])}, {"done", "paused"})

    def test_interrupted_downloads_are_resumable_after_restart(self):
        item = downloader.enqueue("p", "Site", "https://x/file", "file", "")
        downloader.update_item(item["id"], status="downloading", bytes_done=1024, speed_bps=50)
        self.assertEqual(downloader.recover_interrupted_downloads(), 1)
        recovered = downloader.load_queue()[0]
        self.assertEqual(recovered["status"], "pending")
        self.assertEqual(recovered["bytes_done"], 1024)
        self.assertEqual(recovered["speed_bps"], 0.0)

    def test_download_destination_recreates_decoded_source_folders(self):
        root = os.path.join(self.temp.name, "downloads")
        with patch.object(downloader, "load_settings", return_value={"download_dir": root}):
            item = downloader.enqueue(
                "p", "Anime: Archive", "https://x/Season%201/Sub/episode.mkv",
                "episode?.mkv", "Season%201/Sub",
            )
            expected = os.path.join(
                root, "Anime Archive", "Season 1", "Sub", "episode.mkv"
            )
            self.assertEqual(downloader.destination_path(item), expected)
            self.assertFalse(os.path.exists(os.path.dirname(expected)))

    def test_structured_paths_handle_traversal_reserved_names_and_collisions(self):
        root = os.path.join(self.temp.name, "downloads")
        with patch.object(downloader, "load_settings", return_value={"download_dir": root}):
            first = downloader.enqueue(
                "p", "Site", "https://x/one", "a:b.txt", "../CON/%2e%2e/Safe%20Folder"
            )
            second = downloader.enqueue(
                "p", "Site", "https://x/two", "ab.txt", "../CON/%2e%2e/Safe%20Folder"
            )
            self.assertEqual(
                first["destination_rel_path"], "Site/_CON/Safe Folder/ab.txt"
            )
            self.assertEqual(
                second["destination_rel_path"], "Site/_CON/Safe Folder/ab (2).txt"
            )
            for item in (first, second):
                self.assertEqual(
                    os.path.commonpath((root, downloader.destination_path(item))), root
                )

    def test_batch_enqueue_writes_queue_once(self):
        entries = [
            {"url": f"https://x/folder/{number}.bin", "name": f"{number}.bin", "rel_path": "folder"}
            for number in range(2000)
        ]
        with (
            patch.object(downloader, "load_queue", return_value=[]),
            patch.object(downloader, "save_queue") as save_queue,
        ):
            result = downloader.enqueue_many("p", "Site", entries)
        self.assertEqual(result["added"], 2000)
        save_queue.assert_called_once()
        self.assertEqual(len(save_queue.call_args.args[0]), 2000)

    def test_existing_completed_file_is_kept_without_network_request(self):
        root = os.path.join(self.temp.name, "downloads")
        settings = {"download_dir": root, "skip_existing_downloads": True}
        with patch.object(downloader, "load_settings", return_value=settings):
            item = downloader.enqueue("p", "Site", "https://x/file.bin", "file.bin", "folder")
            destination = downloader._dest_path(item, create=True)
            with open(destination, "wb") as handle:
                handle.write(b"existing")
            with patch.object(downloader.requests, "get", side_effect=AssertionError("network should not be used")):
                downloader._download_one(item, {}, lambda _message: None)
        stored = downloader.load_queue()[0]
        self.assertEqual(stored["status"], "done")
        self.assertEqual(stored["result"], "existing")
        self.assertEqual(stored["bytes_done"], 8)

    def test_source_relative_directory_rejects_other_origins_and_siblings(self):
        base = "https://example.test/media/"
        self.assertEqual(
            downloader.source_relative_directory(base, base + "Season%201/Sub/"),
            "Season%201/Sub",
        )
        self.assertEqual(
            downloader.source_relative_directory(base, "https://example.test/media-other/"), ""
        )
        self.assertEqual(
            downloader.source_relative_directory(base, "https://other.test/media/folder/"), ""
        )

    def test_folder_and_saved_search_favorites(self):
        first = library.add_folder("p", "https://x/folder/", "Folder")
        duplicate = library.add_folder("p", "https://x/folder/", "Folder")
        self.assertEqual(first["id"], duplicate["id"])
        library.add_search("linux", "Linux", filters={"file_type": "archive"})
        self.assertEqual(len(library.favorites()), 2)
        library.remove_favorite(first["id"])
        self.assertEqual(library.favorites()[0]["kind"], "search")


if __name__ == "__main__":
    unittest.main()
