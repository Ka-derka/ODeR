import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton, QToolBar

from core.odrlib import new_artifact, new_collection, new_item
from core.paths import DATA_DIR_OVERRIDE_ENV
from gui.creator_window import CreatorWindow, NewFileDialog


class CreatorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oder-creator-ui-")
        self.addCleanup(self.temp.cleanup)
        self.environment = patch.dict(os.environ, {DATA_DIR_OVERRIDE_ENV: self.temp.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.window = CreatorWindow()

    def tearDown(self):
        with patch.object(self.window, "_confirm_discard", return_value=True):
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
        self.assertIn("Check library", block_buttons)
        self.assertIn("Create shareable library…", block_buttons)
        self.assertEqual(self.window.findChildren(QToolBar), [])
        self.assertIs(self.window.pages.currentWidget(), self.window.home_page)
        self.assertFalse(self.window.build_action.isEnabled())

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

    def test_torrent_update_publishing_survives_editor_navigation(self):
        self.window.feed_url.setText("https://example.org/feed.json")
        self.window.package_url.setText("https://example.org/library.odrlib")
        self.window.torrent_updates.setChecked(True)
        self.window.update_torrent_url.setText("https://example.org/library.odrlib.torrent")
        self.window._commit_editor()
        self.window._load_editor(("library", None))
        self.assertTrue(self.window.torrent_updates.isChecked())
        self.assertTrue(self.window.update_torrent_url.isEnabled())
        self.assertEqual(self.window.project["publishing"]["update_torrent_url"],
                         "https://example.org/library.odrlib.torrent")

    def test_details_are_folded_without_losing_metadata(self):
        self.assertFalse(self.window.sections["details"].toggle.isChecked())
        self.assertFalse(self.window.sections["publishing"].toggle.isChecked())
        self.assertFalse(self.window.sections["torrent"].toggle.isChecked())
        self.window.library_creator.setText("Example curator")
        self.window.library_version.setText("Summer 2026")
        self.window.torrent_comment.setText("Preserve this hidden value")
        self.window._show_home()
        self.window._show_workspace()
        self.assertEqual(self.window.project["library"]["creator"], "Example curator")
        self.assertEqual(self.window.project["torrent"]["comment"], "Preserve this hidden value")
        self.assertTrue(self.window.build_action.isEnabled())

    def test_new_online_file_does_not_require_a_local_torrent_source(self):
        dialog = NewFileDialog(parent=self.window)
        dialog.name.setText("Reference manual")
        dialog.urls.setPlainText("https://example.org/manual.pdf")
        self.assertFalse(dialog.torrent.isChecked())
        with patch("gui.creator_window.QMessageBox.warning") as warning:
            dialog._accept_checked()
        warning.assert_not_called()
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_optional_metadata_does_not_interrupt_creation(self):
        self.window.new_document()
        item = new_item(title="Guide")
        artifact = new_artifact(name="Guide", url="https://example.org/guide.pdf")
        artifact["sha256"] = "a" * 64
        item["artifacts"] = [artifact]
        self.window.project["items"].append(item)
        self.window.project_path = os.path.join(self.temp.name, "project.odrproj")
        with patch("gui.creator_window.QMessageBox.question") as question, \
             patch("gui.creator_window.QFileDialog.getSaveFileName", return_value=("out.odrlib", "")), \
             patch("gui.creator_window.BuildProgressDialog") as progress, \
             patch("gui.creator_window.PublishResultDialog") as result_dialog:
            progress.return_value.exec.return_value = QDialog.Accepted
            progress.return_value.build_result = SimpleNamespace(path="out.odrlib")
            self.window.build_package()
        question.assert_not_called()
        result_dialog.assert_called_once()
        self.assertTrue(os.path.isfile(self.window.project_path))

    def test_next_revision_is_explicit_and_keeps_library_identity(self):
        self.window.new_document()
        library_id = self.window.project["library"]["id"]
        with patch("gui.creator_window.QMessageBox.question", return_value=QMessageBox.Yes):
            self.window.prepare_next_revision()
        self.assertEqual(self.window.project["library"]["revision"], 2)
        self.assertEqual(self.window.project["library"]["id"], library_id)
        self.assertTrue(self.window.sections["publishing"].toggle.isChecked())
        self.assertTrue(self.window.dirty)

    def test_new_files_take_editable_library_defaults(self):
        item = new_item(title="Tool")
        self.window._apply_library_defaults(item, {
            "creator": "Curator", "category": "Tools", "license": {"name": "MIT", "url": ""},
        })
        self.assertEqual(item["creator"], "Curator")
        self.assertEqual(item["category"], "Tools")
        self.assertEqual(item["license"]["name"], "MIT")


if __name__ == "__main__":
    unittest.main()
