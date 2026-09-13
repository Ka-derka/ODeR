import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from core.version import CREATOR_VERSION
from gui.creator_splash import CreatorSplashScreen


class CreatorSplashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_startup_reports_current_stage_and_hands_over_to_window(self):
        splash = CreatorSplashScreen()
        window = QWidget()
        try:
            splash.show()
            splash.set_status("Opening your project…")
            self.assertEqual(splash.message(), "Opening your project…")
            self.assertIn(CREATOR_VERSION, splash.accessibleDescription())
            self.assertIn("Opening your project", splash.accessibleDescription())
            self.assertFalse(splash.grab().isNull())
            window.show()
            self.app.processEvents()
            splash.finish(window)
            self.assertFalse(splash.isVisible())
            self.assertTrue(window.isVisible())
        finally:
            splash.close()
            window.close()


if __name__ == "__main__":
    unittest.main()
