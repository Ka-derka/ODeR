import os
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QMessageBox
from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer

from core.paths import resource_path
from core import crawl_state, downloader, library
from core.profiles import load_profiles
from core.settings import load_settings
from core.state_schema import StateSchemaError
from core.version import APP_VERSION
from gui.main_window import MainWindow
from gui.tray import setup_tray
from gui.single_instance import SingleInstance


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # closing the window minimizes to tray, doesn't quit
    app.setApplicationName("ODeR")
    app.setApplicationVersion(APP_VERSION)

    instance = SingleInstance(parent=app)
    if not instance.acquire():
        if not instance.forward(sys.argv[1:], os.getcwd()):
            QMessageBox.warning(
                None,
                "ODeR is already running",
                "Another ODeR instance is running, but it could not be brought to the foreground.",
            )
            return 1
        return 0

    icon_path = resource_path("icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    try:
        load_settings()
        startup_profiles = load_profiles()
        downloader.load_queue()
        library.favorites()
        library.recent_packages(1)
        for profile in startup_profiles:
            crawl_state.load(profile.get("id"))
        window = MainWindow()
    except StateSchemaError as exc:
        QMessageBox.critical(
            None,
            "ODeR data needs a newer version",
            f"ODeR did not change your saved data.\n\n{exc}",
        )
        instance.close()
        return 2
    instance.message_received.connect(window.handle_external_message)
    for pending_message in instance.set_ready():
        window.handle_external_message(pending_message)
    setup_tray(app, window)
    window.show()
    window.handle_external_arguments(sys.argv[1:], os.getcwd(), delay_ms=250)

    exit_code = app.exec()
    instance.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
