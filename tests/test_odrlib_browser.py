import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView, QLabel

from core.odrlib import build_library, new_artifact, new_collection, new_item, new_project
from core.odrlib_store import import_library, inspect_for_import
from gui.odrlib_browser import OdrLibBrowserWidget
from gui.package_dialogs import ImportOdrLibDialog


class OdrLibBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _package(root):
        payload = os.path.join(root, "manual.txt")
        with open(payload, "wb") as handle:
            handle.write(b"offline manual")
        project = new_project()
        project["library"].update({
            "name": "Curated Manuals",
            "creator": "Example Curator",
            "version": "Spring 2026",
            "revision": 2,
        })
        item = new_item(title="System Manual")
        item["artifacts"].append(new_artifact(name="Text edition", embedded_path=payload))
        project["items"].append(item)
        folder = new_collection(name="Documentation")
        folder["item_ids"].append(item["id"])
        project["collections"].append(folder)
        return build_library(project, os.path.join(root, "manuals.odrlib")).path

    def test_import_preview_and_read_only_browser(self):
        with tempfile.TemporaryDirectory() as root:
            package = self._package(root)
            app_data = os.path.join(root, "app-data")
            with patch("core.paths.data_dir", return_value=app_data):
                preview = inspect_for_import(package)
                dialog = ImportOdrLibDialog(preview)
                labels = {label.text() for label in dialog.findChildren(QLabel)}
                self.assertIn("Import ODeR Library?", labels)
                self.assertIn("Creator/Curator:", labels)
                self.assertIn("Index Source:", labels)
                dialog.close()

                installed = import_library(package)
                widget = OdrLibBrowserWidget()
                widget.set_profile(installed.profile)
                self.assertFalse(widget.update_button.isHidden())
                self.assertIn("does not contain", widget.update_button.toolTip())
                self.assertEqual(widget.tree.columnCount(), 5)
                self.assertEqual(widget.tree.header().sectionResizeMode(1), QHeaderView.Interactive)
                self.assertEqual(widget.tree.topLevelItemCount(), 2)
                folder_root = widget.tree.topLevelItem(0)
                self.assertEqual(folder_root.child(0).text(0), "Documentation")
                file_row = folder_root.child(0).child(0)
                self.assertEqual(file_row.text(0), "System Manual")
                widget.tree.setCurrentItem(file_row)
                self.assertTrue(widget.download_button.isEnabled())
                widget.search.setText("missing")
                self.assertEqual(widget.tree.topLevelItem(0).childCount(), 0)
                widget.close()


if __name__ == "__main__":
    unittest.main()
