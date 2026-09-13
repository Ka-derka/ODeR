"""Keep Creator responsive while it creates and checks a shareable library."""
from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QThread, QTimer, Qt, Slot
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout

from core.odrlib import build_library


class _BuildWorker(QThread):
    def __init__(self, project, destination, project_path, parent):
        super().__init__(parent)
        self.project = project
        self.destination = destination
        self.project_path = project_path
        self.build_result = None
        self.error = None

    def run(self):
        try:
            self.build_result = build_library(
                self.project, self.destination, project_path=self.project_path,
            )
        except Exception as exc:
            self.error = exc


class BuildProgressDialog(QDialog):
    """Build a project snapshot and close only after the worker has finished.

    ``exec()`` returns Accepted on success and Rejected on failure. The caller
    receives the package details in ``build_result`` or an exception in ``error``.
    The builder cannot yet cancel safely, so dismissing the dialog is disabled
    during work; the worker is never terminated while writing a package.
    """

    def __init__(self, project, destination, project_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create shareable library")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setMinimumWidth(460)
        self.build_result = None
        self.error = None
        self._started = False
        self._complete = False
        self._worker = _BuildWorker(deepcopy(project), destination, project_path, self)
        self._worker.finished.connect(self._build_finished, Qt.ConnectionType.QueuedConnection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        title = QLabel("Creating your library")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        status = QLabel("Preparing files and creating your library…")
        status.setWordWrap(True)
        layout.addWidget(status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Library creation in progress")
        layout.addWidget(self.progress)
        hint = QLabel(
            "Large libraries may take some time. Keep Creator open until the "
            "library is ready."
        )
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._started:
            self._started = True
            QTimer.singleShot(0, self._worker.start)

    @Slot()
    def _build_finished(self):
        # ``finished`` is delivered on the GUI thread. Wait for the worker's
        # final thread-local cleanup before allowing the dialog to be destroyed.
        self._worker.wait()
        self.build_result = self._worker.build_result
        self.error = self._worker.error
        self._complete = True
        super().done(QDialog.DialogCode.Rejected if self.error else QDialog.DialogCode.Accepted)

    def done(self, result):
        if self._complete:
            super().done(result)

    def reject(self):
        if self._complete:
            super().reject()

    def closeEvent(self, event):
        if self._complete:
            super().closeEvent(event)
        else:
            event.ignore()
