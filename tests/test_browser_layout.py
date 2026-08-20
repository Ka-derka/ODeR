import os
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton, QToolButton
    from gui.browser_widget import BrowserWidget
    from gui.queue_widget import QueueWidget
    from gui.logs_page import LogsPage
    from gui.main_window import ActivityPage, HomePage, LibraryTile, MainWindow, SettingsPage
    from gui.profile_dialog import ProfileDialog
    PYSIDE_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE_AVAILABLE = False


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for browser layout tests")
class BrowserLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_file_action_buttons_are_centered_and_inset(self):
        child = {
            "name": "example-file.mkv",
            "url": "https://example.test/example-file.mkv",
            "size": "1 GB",
            "is_dir": False,
        }
        root = {"url": "https://example.test/", "parent_url": None}
        with (
            patch("gui.browser_widget.cache.migrate_json_if_needed"),
            patch("gui.browser_widget.cache.get_base_url", return_value=root["url"]),
            patch("gui.browser_widget.cache.get_node", return_value=root),
            patch("gui.browser_widget.cache.child_count", return_value=1),
            patch("gui.browser_widget.cache.get_children", return_value=[child]),
        ):
            widget = BrowserWidget()
            widget.setStyleSheet(
                "QPushButton { border: 1px solid; min-height: 28px; }"
                "QPushButton#rowActionButton { padding: 0; min-width: 74px; max-width: 74px; "
                "min-height: 22px; max-height: 22px; }"
            )
            widget.resize(1000, 420)
            widget.set_profile({"id": "test", "name": "Test", "base_url": root["url"]})
            widget.show()
            self.app.processEvents()

            item = widget.list_widget.topLevelItem(0)
            row_rect = widget.list_widget.visualItemRect(item)
            header = widget.list_widget.header()
            cell_rect = QRect(
                header.sectionViewportPosition(3),
                row_rect.top(),
                header.sectionSize(3),
                row_rect.height(),
            )
            download_rect, copy_rect = widget.action_delegate.button_rects(cell_rect)
            self.assertIsNone(widget.list_widget.itemWidget(item, 3))
            self.assertEqual((download_rect.width(), download_rect.height()), (76, 24))
            self.assertEqual((copy_rect.width(), copy_rect.height()), (76, 24))
            top_gap = download_rect.top() - cell_rect.top()
            bottom_gap = cell_rect.bottom() - download_rect.bottom()
            right_gap = cell_rect.right() - copy_rect.right()
            self.assertLessEqual(abs(top_gap - bottom_gap), 1)
            self.assertGreaterEqual(right_gap, 8)

            requested = []
            widget.action_delegate.download_requested.connect(
                lambda url, name: requested.append((url, name))
            )
            QTest.mouseClick(widget.list_widget.viewport(), Qt.LeftButton, pos=download_rect.center())
            self.app.processEvents()
            self.assertEqual(requested, [(child["url"], child["name"])])
            widget.close()

    def test_download_group_stays_expanded_after_refresh(self):
        item = {
            "id": "download-1",
            "group_id": "site-group",
            "group_name": "Example site",
            "profile_name": "Example",
            "name": "example-file.mkv",
            "status": "done",
            "bytes_done": 100,
            "bytes_total": 100,
        }
        summary = {
            "done": 1,
            "total": 1,
            "errors": 0,
            "active": False,
            "percent": 100,
            "bytes_done": 100,
            "bytes_total": 100,
            "speed_bps": 0,
        }
        with (
            patch("gui.queue_widget.downloader.load_queue", return_value=[item]),
            patch("gui.queue_widget.downloader.group_summary", return_value=summary),
        ):
            widget = QueueWidget()
            widget.refresh()
            widget.tree.topLevelItem(0).setExpanded(True)
            self.app.processEvents()
            widget.refresh()
            self.assertTrue(widget.tree.topLevelItem(0).isExpanded())
            widget.close()

    def test_activity_updates_existing_widgets_in_place(self):
        profile = {"id": "site-1", "name": "Example", "base_url": "https://example.test/", "crawl_history": []}
        first = {"running": True, "phase": "preparing", "crawled": 0, "folders_discovered": 0}
        second = {
            "running": True,
            "phase": "running",
            "crawled": 12,
            "folders_discovered": 20,
            "files_discovered": 40,
            "queued": 8,
            "rate": 3.0,
            "elapsed": 4.0,
        }
        with patch("gui.main_window.crawl_state.resumable", return_value=[]):
            widget = ActivityPage()
            widget.refresh([profile], {profile["id"]: first})
            controls = widget._active_widgets[profile["id"]]
            bar = controls["bar"]
            info = controls["info"]
            widget.refresh([profile], {profile["id"]: second})
            self.assertIs(widget._active_widgets[profile["id"]]["bar"], bar)
            self.assertIs(widget._active_widgets[profile["id"]]["info"], info)
            self.assertEqual(bar.value(), 60)
            self.assertIn("12", info.text())
            widget.close()

    def test_activity_shows_hosted_package_download_progress(self):
        profile = {"id": "site-1", "name": "Example", "base_url": "https://example.test/", "crawl_history": []}
        status = {
            "running": True, "phase": "hosted_download",
            "current": "https://cdn.example.test/archive.oder",
            "bytes_downloaded": 50, "bytes_total": 100,
        }
        with patch("gui.main_window.crawl_state.resumable", return_value=[]):
            widget = ActivityPage()
            widget.refresh([profile], {profile["id"]: status})
            controls = widget._active_widgets[profile["id"]]
            self.assertEqual(controls["bar"].value(), 50)
            self.assertIn("hosted index", controls["info"].text())
            self.assertIn("cdn.example.test", controls["info"].text())
            widget.close()

    def test_download_refresh_reads_queue_once_for_multiple_groups(self):
        items = [
            {"id": "a", "group_id": "g1", "group_name": "One", "profile_name": "Site", "name": "a", "status": "done", "bytes_done": 1, "bytes_total": 1},
            {"id": "b", "group_id": "g2", "group_name": "Two", "profile_name": "Site", "name": "b", "status": "done", "bytes_done": 1, "bytes_total": 1},
        ]
        with patch("gui.queue_widget.downloader.load_queue", return_value=items) as load_queue:
            widget = QueueWidget()
            widget.refresh()
            self.assertEqual(load_queue.call_count, 1)
            widget.close()

    def test_download_progress_updates_rows_without_rebuilding_tree(self):
        first = {
            "id": "download-1", "profile_name": "Example", "name": "file.bin",
            "status": "downloading", "bytes_done": 10, "bytes_total": 100,
        }
        second = dict(first, bytes_done=65, speed_bps=1024)
        with patch("gui.queue_widget.downloader.load_queue", side_effect=[[first], [second]]):
            widget = QueueWidget()
            widget.refresh()
            row = widget.tree.topLevelItem(0)
            bar = widget.tree.itemWidget(row, 3)
            widget.refresh()
            self.assertIs(widget.tree.topLevelItem(0), row)
            self.assertIs(widget.tree.itemWidget(row, 3), bar)
            self.assertEqual(bar.value(), 65)
            widget.close()

    def test_downloads_show_structured_relative_destination(self):
        item = {
            "id": "download-structured", "profile_name": "Example",
            "name": "episode.mkv", "destination_rel_path": "Example/Season 1/English/episode.mkv",
            "status": "pending", "bytes_done": 0, "bytes_total": None,
        }
        with patch("gui.queue_widget.downloader.load_queue", return_value=[item]):
            widget = QueueWidget()
            widget.refresh()
            self.assertEqual(
                widget.tree.topLevelItem(0).text(0), "Season 1/English/episode.mkv"
            )
            widget.close()

    def test_logs_page_exposes_diagnostics_export(self):
        widget = LogsPage()
        from PySide6.QtWidgets import QPushButton
        labels = {button.text() for button in widget.findChildren(QPushButton)}
        self.assertIn("Export diagnostics…", labels)
        widget.close()

    def test_home_cards_do_not_read_databases_on_ui_refresh(self):
        profile = {
            "id": "site-1", "name": "Example", "base_url": "https://example.test/",
            "last_crawled": None,
        }
        with (
            patch("gui.main_window.cache.migrate_json_if_needed") as migrate,
            patch("gui.main_window.cache.count_summary") as count,
        ):
            widget = HomePage()
            widget.refresh([profile])
            migrate.assert_not_called()
            count.assert_not_called()
            self.assertIn("loading", widget._meta_labels[profile["id"]].text().lower())
            widget.update_profile_stats(
                profile["id"], {"entries": 11, "folders": 3, "files": 8}, profile
            )
            self.assertIn("10 items", widget._meta_labels[profile["id"]].text())
            widget.close()

    def test_home_uses_square_library_tiles_with_overflow_actions(self):
        profiles = [
            {
                "id": f"library-{index}", "name": f"Library {index}",
                "base_url": f"https://example{index}.test/", "last_crawled": None,
            }
            for index in range(4)
        ]
        widget = HomePage()
        widget.resize(1120, 700)
        widget.refresh(profiles)
        widget.show()
        self.app.processEvents()
        self.app.processEvents()

        self.assertEqual(len(widget._tiles), 4)
        self.assertTrue(all(isinstance(tile, LibraryTile) for tile in widget._tiles))
        self.assertTrue(all(tile.width() == tile.height() for tile in widget._tiles))
        self.assertGreaterEqual(widget._last_column_count, 3)
        menu_button = widget._tiles[0].findChild(QToolButton, "libraryMenuButton")
        self.assertIsNotNone(menu_button)
        self.assertEqual(
            [action.text() for action in menu_button.menu().actions() if not action.isSeparator()],
            ["Settings", "Information", "Export .oder…"],
        )
        visible_buttons = {button.text() for button in widget.findChildren(QPushButton)}
        self.assertNotIn("Import .oder", visible_buttons)
        self.assertNotIn("Add library", visible_buttons)
        self.assertNotIn("Settings", visible_buttons)
        widget.close()

    def test_library_artwork_and_metadata_are_editable_and_visible_on_home(self):
        image = QImage(32, 24, QImage.Format_RGB32)
        image.fill(QColor("#336699"))
        artwork = ProfileDialog._encoded_jpeg(image)
        profile = {
            "id": "art-library", "name": "Art Library",
            "base_url": "https://example.test/",
            "metadata": {
                "description": "A curated collection",
                "creator": "Curator",
                "category": "Software",
                "tags": ["shareware", "preservation"],
                "artwork_data_uri": artwork,
            },
            "settings": {},
        }
        dialog = ProfileDialog(profile=profile)
        result = dialog.result_data()
        self.assertEqual(result["metadata"]["description"], "A curated collection")
        self.assertEqual(result["metadata"]["creator"], "Curator")
        self.assertEqual(result["metadata"]["tags"], ["shareware", "preservation"])
        self.assertEqual(result["metadata"]["artwork_data_uri"], artwork)
        dialog.close()

        tile = LibraryTile(profile, "No cache yet")
        self.assertIsNotNone(tile.artwork_label)
        self.assertFalse(tile.artwork_label.pixmap().isNull())
        self.assertEqual(tile.artwork_label.objectName(), "libraryCoverArtwork")
        tile.close()

    def test_sidebar_utilities_collapse_and_downloads_live_in_status_bar(self):
        with (
            patch("gui.main_window.load_profiles", return_value=[]),
            patch("gui.main_window.downloader.start_background_worker"),
            patch("gui.main_window.applog.log"),
            patch("gui.main_window.MainWindow._start_home_stats_refresh"),
            patch("gui.main_window.save_settings") as save,
        ):
            window = MainWindow()
            window.timer.stop()
            window.show()
            self.app.processEvents()

            self.assertFalse(hasattr(window, "downloads_btn"))
            self.assertEqual(window.status_downloads_btn.text(), "Downloads")
            self.assertGreater(window.favorites_btn.y(), window.new_btn.y())
            self.assertGreater(window.utility_toggle.y(), window.favorites_btn.y())
            self.assertEqual(window.utility_toggle.width(), window.new_btn.width())
            window._toggle_utility_section(False)
            self.assertFalse(window.utility_container.isVisible())
            save.assert_called_with({"sidebar_tools_expanded": False})
            with patch(
                "gui.main_window.downloader.load_queue",
                return_value=[{"status": "pending"}, {"status": "downloading"}],
            ):
                window._refresh_downloads_status_button()
            self.assertEqual(window.status_downloads_btn.text(), "Downloads · 2")
            window.hide()
            window.deleteLater()
            self.app.processEvents()

    def test_settings_has_no_manual_import_button(self):
        widget = SettingsPage()
        labels = {button.text() for button in widget.findChildren(QPushButton)}
        self.assertNotIn("Import .oder…", labels)
        self.assertIn("Compare two .oder files…", labels)
        widget.close()

    def test_profile_dialog_preserves_exact_hosted_package_url(self):
        profile = {
            "name": "Example", "base_url": "https://example.test/",
            "settings": {
                "auto_detect_index": True,
                "hosted_oder_url": "https://cdn.example.test/releases/latest.oder",
            },
        }
        dialog = ProfileDialog(profile=profile)
        result = dialog.result_data()
        self.assertEqual(
            result["settings"]["hosted_oder_url"],
            "https://cdn.example.test/releases/latest.oder",
        )
        self.assertTrue(result["settings"]["auto_detect_index"])
        dialog.close()


if __name__ == "__main__":
    unittest.main()
