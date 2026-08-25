"""Entry point for the separate ODeR Creator authoring application."""
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from core.paths import resource_path
from core.version import CREATOR_NAME, CREATOR_VERSION
from gui.creator_window import CreatorWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(CREATOR_NAME)
    app.setApplicationVersion(CREATOR_VERSION)
    app.setQuitOnLastWindowClosed(True)
    icon_path = resource_path("icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = CreatorWindow()
    smoke_test = "--smoke-test" in sys.argv[1:]
    if smoke_test:
        window.dirty = False
        QTimer.singleShot(250, app.quit)
    else:
        window.show()
    for argument in sys.argv[1:]:
        if not smoke_test and str(argument).casefold().endswith(".odrproj") and os.path.isfile(argument):
            window.open_project_path(argument, confirm=False)
            break
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
