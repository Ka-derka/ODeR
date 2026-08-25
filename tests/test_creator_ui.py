import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QToolBar

from core.odrlib import new_artifact, new_collection, new_item
from gui.creator_window import CreatorWindow, NewFileDialog


class CreatorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = CreatorWindow()

    def tearDown(self):
        self.window.dirty = False
        self.window.close()

    def test_first_project_exposes_library_folders_files_and_build_actions(self):
        self.assertEqual(self.window.tree.topLevelItemCount(), 3)
        self.assertEqual(self.window.tree.topLevelItem(0).text(0), "Untitled Library")
        self.assertIn("Folders", self.window.tree.topLevelItem(1).text(0))
        self.assertIn("Files", self.window.tree.topLevelItem(2).text(0))
        self.assertEqual(self.window.build_action.shortcut().toString(), "Ctrl+B")
        block_buttons = {button.text() for button in self.window.findChildren(QPushButton)}
        self.assertNotIn("Add item", block_buttons)
        self.assertNotIn("Add collection", block_buttons)
        self.assertIn("Validate project", block_buttons)
        self.assertIn("Build .odrlib", block_buttons)
        self.assertEqual(self.window.findChildren(QToolBar), [])

    def test_file_folder_workflow_assigns_from_file_editor(self):
        folder = new_collection(name="Utilities")
        item = new_item(title="Preservation Utility")
        item["artifacts"].append(new_artifact(name=item["title"], url="https://example.org/tool.zip"))
        self.window.project["collections"].append(folder)
        self.window.project["items"].append(item)
        self.window._assign_item_folder(item["id"], folder["id"])
        self.window._rebuild_tree(("file", item["id"]))
        self.assertEqual(self.window.item_folder.currentData(), folder["id"])
        self.assertEqual(self.window.tree.topLevelItem(1).child(0).child(0).text(0), "Preservation Utility")
        self.window.item_folder.setCurrentIndex(0)
        self.window._commit_editor()
        self.assertEqual(self.window.project["collections"][0]["item_ids"], [])

    def test_new_file_dialog_creates_file_and_returns_folder(self):
        folder = new_collection(name="Games")
        dialog = NewFileDialog([folder], folder["id"], self.window)
        dialog.name.setText("Open Game")
        dialog.urls.setPlainText("example.org/game.zip")
        item, folder_id = dialog.result_data()
        self.assertEqual(item["title"], "Open Game")
        self.assertEqual(item["artifacts"][0]["sources"][0]["url"], "example.org/game.zip")
        self.assertEqual(folder_id, folder["id"])
        dialog.close()


if __name__ == "__main__":
    unittest.main()
