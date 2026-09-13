import os
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from gui.creator_build import BuildProgressDialog


class CreatorBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_build_uses_snapshot_in_worker_and_keeps_gui_responsive(self):
        release_worker = threading.Event()
        worker_started = threading.Event()
        recorded = {}
        result = {"path": "example.odrlib"}

        def build(project, destination, *, project_path):
            recorded["project"] = project
            recorded["destination"] = destination
            recorded["project_path"] = project_path
            recorded["worker_thread"] = QThread.currentThread() != self.app.thread()
            worker_started.set()
            recorded["released"] = release_worker.wait(2)
            return result

        project = {"library": {"name": "Original name"}}
        with patch("gui.creator_build.build_library", side_effect=build):
            dialog = BuildProgressDialog(project, "example.odrlib", "example.odrproj")
            project["library"]["name"] = "Changed after starting"

            def respond_on_gui():
                if not worker_started.is_set():
                    QTimer.singleShot(5, respond_on_gui)
                    return
                recorded["gui_responded"] = True
                dialog.reject()
                recorded["close_ignored"] = not dialog.close()
                recorded["still_visible"] = dialog.isVisible()
                release_worker.set()

            QTimer.singleShot(10, respond_on_gui)
            try:
                self.assertEqual(dialog.exec(), QDialog.DialogCode.Accepted)
                self.assertIs(dialog.build_result, result)
                self.assertIsNone(dialog.error)
                self.assertTrue(recorded["worker_thread"])
                self.assertTrue(recorded["gui_responded"])
                self.assertTrue(recorded["released"])
                self.assertTrue(recorded["close_ignored"])
                self.assertTrue(recorded["still_visible"])
                self.assertEqual(recorded["project"]["library"]["name"], "Original name")
                self.assertEqual(recorded["destination"], "example.odrlib")
                self.assertEqual(recorded["project_path"], "example.odrproj")
                self.assertFalse(dialog._worker.isRunning())
            finally:
                release_worker.set()
                dialog._worker.wait(3000)
                dialog.close()

    def test_failure_returns_error_after_worker_has_stopped(self):
        error = ValueError("A source file is missing.")
        with patch("gui.creator_build.build_library", side_effect=error):
            dialog = BuildProgressDialog({}, "example.odrlib")
            self.assertEqual(dialog.exec(), QDialog.DialogCode.Rejected)
            self.assertIs(dialog.error, error)
            self.assertIsNone(dialog.build_result)
            self.assertFalse(dialog._worker.isRunning())
            dialog.close()


if __name__ == "__main__":
    unittest.main()
