from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from core.creator_state import recent_projects, record_recent
from core.odrlib import load_project, new_artifact, new_item, new_project, save_project, scan_folder
from core.paths import DATA_DIR_OVERRIDE_ENV
from gui.creator_window import CreatorWindow


class CreatorWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        override = patch.dict(os.environ, {DATA_DIR_OVERRIDE_ENV: str(self.root / "state")})
        override.start()
        self.addCleanup(override.stop)
        self.window = CreatorWindow()

    def tearDown(self):
        with patch.object(self.window, "_confirm_discard", return_value=True):
            self.window.close()

    def _active_document(self):
        self.window.new_document()
        self.window.library_name.setText("My existing library")
        self.window._commit_editor()
        self.window.project_path = str(self.root / "existing.odrproj")
        self.window._set_dirty(False)

    def test_home_keeps_current_edits_and_folder_cancel_keeps_document(self):
        self._active_document()
        self.window.library_summary.setText("Changes not saved yet")
        self.window._show_home()
        expected = deepcopy(self.window.project)
        previous_path = self.window.project_path
        with (
            patch("gui.creator_window.QMessageBox.question", return_value=QMessageBox.Discard),
            patch("gui.creator_window.QFileDialog.getExistingDirectory", return_value=""),
        ):
            self.window.create_from_folder()
        self.assertEqual(self.window.project, expected)
        self.assertEqual(self.window.project_path, previous_path)
        self.assertTrue(self.window.dirty)
        self.assertIs(self.window.pages.currentWidget(), self.window.home_page)
        self.window.home_page.resume_button.click()
        self.assertIs(self.window.pages.currentWidget(), self.window.workspace)
        self.assertEqual(self.window.library_summary.text(), "Changes not saved yet")

    def test_folder_selection_cancel_does_not_replace_current_library(self):
        self._active_document()
        source = self.root / "New folder"
        source.mkdir()
        (source / "example.txt").write_text("A local test file", encoding="utf-8")
        expected = deepcopy(self.window.project)
        previous_path = self.window.project_path
        with (
            patch("gui.creator_window.QFileDialog.getExistingDirectory", return_value=str(source)),
            patch("gui.creator_window.FolderImportDialog") as dialog_type,
        ):
            dialog_type.return_value.exec.return_value = QDialog.Rejected
            self.window.create_from_folder()
        self.assertEqual(self.window.project, expected)
        self.assertEqual(self.window.project_path, previous_path)
        self.assertFalse(self.window.dirty)

    def test_accepted_folder_creates_named_library_only_after_selection(self):
        self._active_document()
        old_id = self.window.project["library"]["id"]
        source = self.root / "My new library"
        source.mkdir()
        (source / "example.txt").write_text("A local test file", encoding="utf-8")
        records = scan_folder(str(source))
        with (
            patch("gui.creator_window.QFileDialog.getExistingDirectory", return_value=str(source)),
            patch("gui.creator_window.FolderImportDialog") as dialog_type,
        ):
            dialog_type.return_value.exec.return_value = QDialog.Accepted
            dialog_type.return_value.selections.return_value = records
            self.window.create_from_folder()
        self.assertNotEqual(self.window.project["library"]["id"], old_id)
        self.assertEqual(self.window.project["library"]["name"], source.name)
        self.assertEqual(len(self.window.project["items"]), 1)
        self.assertIsNone(self.window.project_path)
        self.assertTrue(self.window.dirty)
        self.assertIs(self.window.pages.currentWidget(), self.window.workspace)

    def test_failed_save_as_preserves_old_destination_and_recent_history(self):
        self._active_document()
        previous_path = self.window.project_path
        record_recent(previous_path)
        destination = str(self.root / "failed.odrproj")
        with (
            patch("gui.creator_window.QFileDialog.getSaveFileName", return_value=(destination, "")),
            patch("gui.creator_window.save_project", side_effect=PermissionError("read only")),
            patch("gui.creator_window.QMessageBox.critical"),
        ):
            self.assertFalse(self.window.save_document_as())
        self.assertEqual(self.window.project_path, previous_path)
        self.assertEqual(recent_projects(), [previous_path])

    def test_programmatic_folder_choice_is_committed_before_discard_prompt(self):
        self._active_document()
        self.window.torrent_root.setText(str(self.root / "source"))
        with patch("gui.creator_window.QMessageBox.question", return_value=QMessageBox.Cancel) as ask:
            self.assertFalse(self.window._confirm_discard())
        ask.assert_called_once()
        self.assertEqual(self.window.project["torrent"]["root_path"], str(self.root / "source"))

    def _open_project_with_relative_sources(self):
        original = self.root / "original"
        source_folder = original / "files"
        source_folder.mkdir(parents=True)
        (source_folder / "payload.txt").write_text("A local test file", encoding="utf-8")
        project = new_project()
        project["library"]["artwork_path"] = "cover.png"
        project["torrent"]["root_path"] = "files"
        item = new_item(title="Payload")
        item["artwork_path"] = "item-cover.png"
        item["artifacts"].append(new_artifact(
            name="Payload", embedded_path="files/payload.txt",
            torrent_path="files/payload.txt", relative_path="payload.txt",
        ))
        project["items"].append(item)
        path = original / "original.odrproj"
        save_project(str(path), project)
        self.assertTrue(self.window.open_project_path(str(path)))
        return original, item["id"]

    def test_save_as_other_directory_keeps_relative_source_targets(self):
        original, _item_id = self._open_project_with_relative_sources()
        destination = self.root / "elsewhere" / "copy.odrproj"
        destination.parent.mkdir()
        with patch("gui.creator_window.QFileDialog.getSaveFileName", return_value=(str(destination), "")):
            self.assertTrue(self.window.save_document_as())
        stored = load_project(str(destination))
        targets = {
            "library cover": (stored["library"]["artwork_path"], original / "cover.png"),
            "file cover": (stored["items"][0]["artwork_path"], original / "item-cover.png"),
            "torrent root": (stored["torrent"]["root_path"], original / "files"),
        }
        for source in stored["items"][0]["artifacts"][0]["sources"]:
            targets[source["type"]] = (source["source_path"], original / "files" / "payload.txt")
        self.assertEqual(len(targets), 5)
        for label, (path, expected) in targets.items():
            with self.subTest(reference=label):
                resolved = Path(path) if Path(path).is_absolute() else destination.parent / path
                self.assertEqual(resolved.resolve(), expected.resolve())
        self.window._show_home()
        self.assertFalse(self.window.dirty)

    def test_file_editor_save_and_home_keep_torrent_source_without_false_dirty(self):
        _original, item_id = self._open_project_with_relative_sources()
        self.window._rebuild_tree(("file", item_id))
        self.assertTrue(self.window.save_document())
        self.assertFalse(self.window.dirty)
        self.window._show_home()
        self.assertFalse(self.window.dirty)
        artifact = self.window.project["items"][0]["artifacts"][0]
        sources = {source["type"]: source for source in artifact["sources"]}
        self.assertEqual(set(sources), {"embedded", "torrent"})
        self.assertEqual(sources["torrent"]["relative_path"], "payload.txt")
        self.assertEqual(self.window.file_embedded.text(), sources["embedded"]["source_path"])


if __name__ == "__main__":
    unittest.main()
