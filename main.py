import os
import sys
import tempfile
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QMessageBox
from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer

from core.paths import DATA_DIR_OVERRIDE_ENV, resource_path
from core import applog, crawl_state, downloader, library
from core.profiles import load_profiles
from core.settings import load_settings
from core.state_schema import StateSchemaError
from core.version import APP_VERSION
from core.torrent_support import runtime_version as torrent_runtime_version
from gui.main_window import MainWindow
from gui.tray import setup_tray
from gui.single_instance import SingleInstance


def _run(smoke_test=False, smoke_scope=None):
    app = QApplication(sys.argv)
    if smoke_test:
        torrent_runtime_version()
        from core.update_security import runtime_self_test
        runtime_self_test()
    app.setQuitOnLastWindowClosed(smoke_test is True)
    app.setApplicationName("ODeR")
    app.setApplicationVersion(APP_VERSION)

    instance = SingleInstance(scope=smoke_scope, parent=app)
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
            if profile.get("kind", "directory") == "directory":
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
    if smoke_test:
        def finish_smoke_test():
            downloader.stop_background_worker()
            window.close()
            app.quit()

        QTimer.singleShot(250, finish_smoke_test)
    else:
        setup_tray(app, window)
        window.show()
        window.handle_external_arguments(sys.argv[1:], os.getcwd(), delay_ms=250)

    exit_code = app.exec()
    instance.close()
    return exit_code


def main():
    smoke_test = "--smoke-test" in sys.argv[1:]
    if not smoke_test:
        return _run()

    previous_override = os.environ.get(DATA_DIR_OVERRIDE_ENV)
    with tempfile.TemporaryDirectory(prefix="oder-smoke-") as smoke_directory:
        os.environ[DATA_DIR_OVERRIDE_ENV] = smoke_directory
        try:
            return _run(smoke_test=True, smoke_scope=smoke_directory)
        finally:
            applog.shutdown_logging()
            if previous_override is None:
                os.environ.pop(DATA_DIR_OVERRIDE_ENV, None)
            else:
                os.environ[DATA_DIR_OVERRIDE_ENV] = previous_override


if __name__ == "__main__":
    sys.exit(main())
