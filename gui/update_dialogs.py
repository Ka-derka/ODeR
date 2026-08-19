"""Update-related dialogs and background tasks."""

from datetime import datetime
import threading

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout,
)

from core import updater


def format_size(value):
    value = max(0, int(value or 0))
    units = ("B", "KB", "MB", "GB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024


def format_published(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%d %b %Y")
    except (TypeError, ValueError):
        return "Unknown date"


class UpdateCheckTask(QThread):
    update_found = Signal(object)
    no_update = Signal()
    failed = Signal(str)

    def __init__(self, current_version, channel, portable, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.channel = channel
        self.portable = portable

    def run(self):
        try:
            info = updater.check_for_update(
                self.current_version, channel=self.channel, portable=self.portable
            )
            if info is None:
                self.no_update.emit()
            else:
                self.update_found.emit(info)
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDownloadTask(QThread):
    progress_changed = Signal(object, object)
    download_complete = Signal(str)
    failed = Signal(str)
    canceled = Signal()

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            path = updater.download_update(
                self.info,
                progress=lambda done, total: self.progress_changed.emit(done, total),
                canceled=self._cancel_event.is_set,
            )
            self.download_complete.emit(path)
        except updater.DownloadCanceled:
            self.canceled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """Show release notes and return the user's selected update action."""

    def __init__(self, info, mode="installed", parent=None):
        super().__init__(parent)
        self.info = info
        self.mode = mode
        self.action = "later"
        self.setWindowTitle(f"ODeR {info.version} is available")
        self.resize(640, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        title = QLabel(f"ODeR {info.version} is available")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        edition = {
            "installed": "Windows installer",
            "portable": "Portable ZIP",
            "source": "GitHub release",
        }.get(mode, "Update")
        details = QLabel(
            f"{edition} · {format_size(info.asset.size)} · Published {format_published(info.published_at)}"
        )
        details.setObjectName("mutedLabel")
        layout.addWidget(details)

        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.notes or "No release notes were provided.")
        layout.addWidget(notes, 1)

        actions = QHBoxLayout()
        view = QPushButton("View on GitHub")
        view.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(info.page_url)))
        actions.addWidget(view)
        actions.addStretch(1)

        later = QPushButton("Later")
        later.clicked.connect(self.reject)
        actions.addWidget(later)

        skip = QPushButton("Skip this version")
        skip.clicked.connect(self._skip)
        actions.addWidget(skip)

        primary_text = {
            "installed": "Download update",
            "portable": "Download portable ZIP",
            "source": "Open release page",
        }.get(mode, "Download update")
        primary = QPushButton(primary_text)
        primary.setObjectName("accentButton")
        primary.clicked.connect(self._primary)
        actions.addWidget(primary)
        layout.addLayout(actions)

    def _skip(self):
        self.action = "skip"
        self.accept()

    def _primary(self):
        self.action = "view" if self.mode == "source" else "download"
        self.accept()
