import os
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QPushButton
    from gui.browser_widget import BrowserWidget
    from gui.queue_widget import QueueWidget
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
            actions = widget.list_widget.itemWidget(item, 3)
            buttons = actions.findChildren(QPushButton)
            self.assertEqual(len(buttons), 2)
            self.assertEqual([button.height() for button in buttons], [24, 24])

            row_rect = widget.list_widget.visualItemRect(item)
            self.assertEqual(actions.geometry().top(), row_rect.top())
            self.assertEqual(actions.height(), row_rect.height())
            top_gap = buttons[0].y()
            bottom_gap = actions.height() - buttons[0].geometry().bottom() - 1
            right_gap = actions.width() - buttons[-1].geometry().right() - 1
            self.assertLessEqual(abs(top_gap - bottom_gap), 1)
            self.assertGreaterEqual(right_gap, 8)
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


if __name__ == "__main__":
    unittest.main()
