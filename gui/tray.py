import os
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication, QStyle
from PySide6.QtGui import QIcon

from core import downloader
from core import applog
from core.paths import resource_path


def setup_tray(app: QApplication, window):
    icon_path = resource_path("icon.png")
    icon = QIcon(icon_path) if os.path.exists(icon_path) else app.style().standardIcon(QStyle.SP_DirIcon)

    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("ODeR")

    menu = QMenu()

    show_action = menu.addAction("Show window")
    show_action.triggered.connect(lambda: (window.showNormal(), window.raise_(), window.activateWindow()))

    menu.addSeparator()

    pause_action = menu.addAction("Pause downloads")
    resume_action = menu.addAction("Resume downloads")
    resume_action.setVisible(False)

    def do_pause():
        downloader.pause_all()
        applog.log("Downloads paused (tray)")
        pause_action.setVisible(False)
        resume_action.setVisible(True)

    def do_resume():
        downloader.resume_all()
        applog.log("Downloads resumed (tray)")
        pause_action.setVisible(True)
        resume_action.setVisible(False)

    pause_action.triggered.connect(do_pause)
    resume_action.triggered.connect(do_resume)

    menu.addSeparator()
    quit_action = menu.addAction("Quit")

    def do_quit():
        applog.log("Application quitting (tray)")
        downloader.stop_background_worker()
        app.quit()

    quit_action.triggered.connect(do_quit)

    tray.setContextMenu(menu)

    def on_activated(reason):
        if reason == QSystemTrayIcon.DoubleClick:
            window.showNormal()
            window.raise_()
            window.activateWindow()

    tray.activated.connect(on_activated)
    tray.show()

    window.tray_icon = tray
    return tray
