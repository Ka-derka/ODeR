import os
import subprocess
import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QComboBox, QCheckBox
)
from PySide6.QtGui import QTextCursor

from core import applog

LEVELS = ["All", "INFO", "WARNING", "ERROR"]
MAX_VISIBLE_LINES = 5000


class LogsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_seq = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(10)

        title = QLabel("Logs")
        title.setObjectName("heroTitle")
        layout.addWidget(title)
        subtitle = QLabel(f"Live app activity. Full history is kept on disk at {applog.log_file_path()}")
        subtitle.setObjectName("mutedLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.level_filter = QComboBox()
        self.level_filter.addItems(LEVELS)
        self.level_filter.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(QLabel("Level:"))
        toolbar.addWidget(self.level_filter)

        self.autoscroll_check = QCheckBox("Auto-scroll")
        self.autoscroll_check.setChecked(True)
        toolbar.addWidget(self.autoscroll_check)

        toolbar.addStretch(1)

        open_file_btn = QPushButton("Open log file")
        open_file_btn.clicked.connect(lambda: self._open_path(applog.log_file_path()))
        toolbar.addWidget(open_file_btn)

        open_folder_btn = QPushButton("Open log folder")
        open_folder_btn.clicked.connect(lambda: self._open_path(applog.log_dir()))
        toolbar.addWidget(open_folder_btn)

        clear_btn = QPushButton("Clear view")
        clear_btn.setToolTip("Clears this view only — the log file on disk is kept.")
        clear_btn.clicked.connect(self._clear_view)
        toolbar.addWidget(clear_btn)

        layout.addLayout(toolbar)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setObjectName("logText")
        layout.addWidget(self.text, 1)

        self._all_lines = []  # (seq, line) — kept so the level filter can re-render
        self._load_initial()

    # ---------- loading / polling ----------

    def _load_initial(self):
        lines = applog.get_all_lines()
        self._all_lines = lines
        self._last_seq = lines[-1][0] if lines else 0
        self._render_all()

    def poll_new(self):
        new_lines, latest = applog.get_new_lines(self._last_seq)
        if not new_lines:
            return
        self._last_seq = latest
        self._all_lines.extend(new_lines)
        if len(self._all_lines) > MAX_VISIBLE_LINES:
            self._all_lines = self._all_lines[-MAX_VISIBLE_LINES:]
        for _seq, line in new_lines:
            if self._line_passes_filter(line):
                self._append_line(line)

    # ---------- rendering ----------

    def _line_passes_filter(self, line):
        level = self.level_filter.currentText()
        if level == "All":
            return True
        return f"[{level}]" in line

    def _append_line(self, line):
        at_bottom = self._is_scrolled_to_bottom()
        self.text.appendPlainText(line)
        if self.autoscroll_check.isChecked() and at_bottom:
            self._scroll_to_bottom()

    def _render_all(self):
        self.text.clear()
        visible = [l for _s, l in self._all_lines if self._line_passes_filter(l)]
        self.text.setPlainText("\n".join(visible))
        self._scroll_to_bottom()

    def _apply_filter(self, _text):
        self._render_all()

    def _is_scrolled_to_bottom(self):
        bar = self.text.verticalScrollBar()
        return bar.value() >= bar.maximum() - 4

    def _scroll_to_bottom(self):
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text.setTextCursor(cursor)
        self.text.ensureCursorVisible()

    # ---------- actions ----------

    def _clear_view(self):
        self.text.clear()
        self._all_lines = []
        # keep _last_seq as-is so poll_new() only shows lines from this point on

    def _open_path(self, path):
        if not os.path.exists(path):
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass
