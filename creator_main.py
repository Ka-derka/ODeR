"""Entry point for the separate ODeR Creator authoring application."""
import os
import sys
import tempfile

from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from core.paths import DATA_DIR_OVERRIDE_ENV, resource_path
from core import applog
from core.version import CREATOR_NAME, CREATOR_VERSION
from core.torrent_support import runtime_version as torrent_runtime_version
from gui.creator_window import CreatorWindow


def _run(smoke_test=False):
    app = QApplication(sys.argv)
    if smoke_test:
        torrent_runtime_version()
    app.setApplicationName(CREATOR_NAME)
    app.setApplicationVersion(CREATOR_VERSION)
    app.setQuitOnLastWindowClosed(True)
    icon_path = resource_path("icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = CreatorWindow()
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


def main():
    smoke_test = "--smoke-test" in sys.argv[1:]
    if not smoke_test:
        return _run()

    previous_override = os.environ.get(DATA_DIR_OVERRIDE_ENV)
    with tempfile.TemporaryDirectory(prefix="oder-creator-smoke-") as smoke_directory:
        os.environ[DATA_DIR_OVERRIDE_ENV] = smoke_directory
        try:
            return _run(smoke_test=True)
        finally:
            applog.shutdown_logging()
            if previous_override is None:
                os.environ.pop(DATA_DIR_OVERRIDE_ENV, None)
            else:
                os.environ[DATA_DIR_OVERRIDE_ENV] = previous_override


if __name__ == "__main__":
    raise SystemExit(main())
