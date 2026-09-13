import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog
from gui.creator_window import CreatorWindow
from gui.creator_build import BuildProgressDialog
from gui.update_trust import PublisherTrustDialog
from core.odrlib import save_project, load_project


class SignedUpdateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_trust_requires_explicit_confirmation(self):
        dialog = PublisherTrustDialog("a" * 64)
        self.assertFalse(dialog.trust_button.isEnabled())
        dialog.confirm.setChecked(True)
        self.assertTrue(dialog.trust_button.isEnabled())
        dialog.reject()
        self.assertEqual(dialog.result(), QDialog.Rejected)

    def test_creator_identity_and_settings_survive_save_and_navigation(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"ODER_DATA_DIR_OVERRIDE": root}):
            window = CreatorWindow()
            try:
                self.assertFalse(window.refresh_feed_action.isEnabled())
                window.new_document()
                self.assertFalse(window.dirty)
                with patch("gui.creator_window.QMessageBox.information"):
                    window._create_signing_identity()
                key = window.library_signing_key.copy()
                window.feed_url.setText("http://localhost/feed.json")
                window.package_url.setText("http://localhost/library.odrlib")
                window.feed_validity_days.setValue(90)
                window._commit_editor()
                path = os.path.join(root, "library.odrproj")
                save_project(path, window.project)
                window.project = load_project(path)
                window._load_editor(("library", None))
                self.assertEqual(window.update_protocol.currentData(), "U1.1")
                self.assertEqual(window.library_signing_key, key)
                self.assertEqual(window.feed_validity_days.value(), 90)
                self.assertFalse(window.create_signing_identity.isEnabled())
                window._create_signing_identity()
                self.assertEqual(window.library_signing_key, key)
            finally:
                with patch.object(window, "_confirm_discard", return_value=True):
                    window.close()

    def test_feed_refresh_uses_background_worker(self):
        sentinel = object()
        with patch("gui.creator_build.refresh_update_feed", return_value=sentinel) as refresh:
            dialog = BuildProgressDialog({}, "existing.odrlib", refresh=True)
            self.assertEqual(dialog.exec(), QDialog.Accepted)
            self.assertIs(dialog.build_result, sentinel)
            refresh.assert_called_once_with({}, "existing.odrlib")
            self.assertFalse(dialog._worker.isRunning())
