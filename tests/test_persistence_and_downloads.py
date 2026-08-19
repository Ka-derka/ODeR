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
