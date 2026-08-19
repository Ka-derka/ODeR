import os
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer

from core.paths import resource_path
from core.version import APP_VERSION
from gui.main_window import MainWindow
from gui.tray import setup_tray


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # closing the window minimizes to tray, doesn't quit
    app.setApplicationName("ODeR")
    app.setApplicationVersion(APP_VERSION)

    icon_path = resource_path("icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    setup_tray(app, window)
    window.show()
    package_path = next((arg for arg in sys.argv[1:] if arg.lower().endswith(".oder") and os.path.isfile(arg)), None)
    if package_path:
        QTimer.singleShot(250, lambda path=os.path.abspath(package_path): window._import_profile_package(path))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
