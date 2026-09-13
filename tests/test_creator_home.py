import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.creator_state import MAX_RECENT_PROJECTS, recent_projects, record_recent
from core.paths import DATA_DIR_OVERRIDE_ENV
from gui.creator_home import CreatorHomePage


class CreatorRecentProjectsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        override = patch.dict(os.environ, {DATA_DIR_OVERRIDE_ENV: str(self.directory / "state")})
        override.start()
        self.addCleanup(override.stop)

    def test_successful_open_moves_project_to_front_and_retains_missing_paths(self):
        older = self.directory / "old.odrproj"
        newer = self.directory / "new.odrproj"
        self.assertTrue(record_recent(older))
        self.assertTrue(record_recent(newer))
        self.assertTrue(record_recent(older.parent / "." / older.name))
        self.assertEqual(recent_projects(), [str(older), str(newer)])
        self.assertTrue((self.directory / "state" / "creator" / "recent-projects.json").is_file())
        self.assertFalse(older.exists())

    def test_history_is_bounded_and_bad_preferences_do_not_break_save(self):
        for number in range(MAX_RECENT_PROJECTS + 3):
            record_recent(self.directory / f"project-{number}.odrproj")
        paths = recent_projects()
        self.assertEqual(len(paths), MAX_RECENT_PROJECTS)
        self.assertTrue(paths[0].endswith(f"project-{MAX_RECENT_PROJECTS + 2}.odrproj"))
        with patch("core.creator_state.save_json", side_effect=PermissionError("read only")):
            self.assertFalse(record_recent(self.directory / "new.odrproj"))


class CreatorHomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_actions_resume_and_missing_recent_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, {DATA_DIR_OVERRIDE_ENV: str(root / "state")}):
                available = root / "Library.odrproj"
                available.write_text("{}", encoding="utf-8")
                missing = root / "Disconnected.odrproj"
                record_recent(missing)
                record_recent(available)
                page = CreatorHomePage()
                try:
                    events = []
                    page.create_from_folder.connect(lambda: events.append("folder"))
                    page.open_project.connect(lambda: events.append("open"))
                    page.blank_project.connect(lambda: events.append("blank"))
                    page.resume_project.connect(lambda: events.append("resume"))
                    page.recent_project.connect(events.append)
                    page.folder_button.click()
                    page.open_button.click()
                    page.blank_button.click()
                    self.assertTrue(page.resume_card.isHidden())
                    page.set_current_project("Work in progress")
                    self.assertFalse(page.resume_card.isHidden())
                    page.resume_button.click()
                    page.recent_list.itemActivated.emit(page.recent_list.topLevelItem(0), 0)
                    missing_item = page.recent_list.topLevelItem(1)
                    self.assertFalse(missing_item.flags() & Qt.ItemIsEnabled)
                    page.recent_list.itemActivated.emit(missing_item, 0)
                    self.assertEqual(events, ["folder", "open", "blank", "resume", str(available)])
                    self.assertEqual(recent_projects(), [str(available), str(missing)])
                finally:
                    page.close()


if __name__ == "__main__":
    unittest.main()
