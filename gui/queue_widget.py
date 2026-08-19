import os
import subprocess
import sys
from collections import OrderedDict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QHBoxLayout, QLabel, QMenu, QPushButton,
    QProgressBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core import downloader


def fmt_bytes(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def fmt_duration(seconds):
    if not seconds or seconds < 0:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


class QueueWidget(QWidget):
    """Download queue with expandable batch groups and aggregate progress."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Site", "Status", "Progress", "Speed / ETA"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 190), (2, 145), (3, 250), (4, 150)):
            self.tree.setColumnWidth(column, width)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemDoubleClicked.connect(self._open_completed)

        title = QLabel("Downloads")
        title.setObjectName("pageTitle")
        self.summary_label = QLabel()
        self.summary_label.setObjectName("mutedLabel")

        controls = QHBoxLayout()
        controls.addWidget(title)
        controls.addWidget(self.summary_label, 1)
        for label, callback in (
            ("Pause all", downloader.pause_all),
            ("Resume all", downloader.resume_all),
            ("Retry failed", self._retry_failed),
            ("Clear completed", self._clear_completed),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addLayout(controls)
        layout.addWidget(self.tree, 1)

    @staticmethod
    def _progress(item):
        total = int(item.get("bytes_total") or 0)
        done = int(item.get("bytes_done") or 0)
        if total:
            return min(100, int(done * 100 / total)), f"{fmt_bytes(done)} / {fmt_bytes(total)}"
        if item.get("status") == "done":
            return 100, "Complete"
        return 0, item.get("status", "")

    def refresh(self):
        expanded = {
            top.data(0, Qt.UserRole + 1)
            for index in range(self.tree.topLevelItemCount())
            for top in (self.tree.topLevelItem(index),)
            if top.isExpanded()
        }
        self.tree.clear()
        items = list(reversed(downloader.load_queue()))
        groups = OrderedDict()
        singles = []
        for item in items:
            group_id = item.get("group_id")
            if group_id:
                groups.setdefault(group_id, []).append(item)
            else:
                singles.append(item)

        for group_id, members in groups.items():
            summary = downloader.group_summary(group_id)
            group_name = members[0].get("group_name") or "Download batch"
            status = f"{summary['done']}/{summary['total']} complete"
            if summary.get("errors"):
                status += f" · {summary['errors']} failed"
            top = QTreeWidgetItem([group_name, members[0].get("profile_name", ""), status, "", ""])
            top.setData(0, Qt.UserRole, ("group", group_id))
            top.setData(0, Qt.UserRole + 1, group_id)
            top.setExpanded(group_id in expanded or bool(summary.get("active")))
            self.tree.addTopLevelItem(top)
            bar = QProgressBar()
            bar.setValue(summary.get("percent", 0))
            bar.setFormat(f"{fmt_bytes(summary.get('bytes_done'))} / {fmt_bytes(summary.get('bytes_total'))}")
            self.tree.setItemWidget(top, 3, bar)
            speed = summary.get("speed_bps") or 0
            top.setText(4, f"{fmt_bytes(speed)}/s" + (f" · {fmt_duration(summary.get('eta_seconds'))}" if speed else ""))
            for item in members:
                self._add_item(item, top)

        for item in singles:
            self._add_item(item)

        active = sum(item.get("status") in ("pending", "downloading", "paused") for item in items)
        done = sum(item.get("status") == "done" for item in items)
        errors = sum(item.get("status") == "error" for item in items)
        speed = sum(float(item.get("speed_bps") or 0) for item in items if item.get("status") == "downloading")
        self.summary_label.setText(
            f"{active} active · {done} completed · {errors} failed" + (f" · {fmt_bytes(speed)}/s" if speed else "")
        )

    def _add_item(self, item, parent=None):
        status = item.get("status", "")
        if item.get("error"):
            status += f": {item['error']}"
        row = QTreeWidgetItem([item.get("name", ""), item.get("profile_name", ""), status, "", ""])
        row.setData(0, Qt.UserRole, ("item", item["id"]))
        (parent.addChild if parent else self.tree.addTopLevelItem)(row)
        value, text = self._progress(item)
        bar = QProgressBar()
        bar.setValue(value)
        bar.setFormat(text)
        self.tree.setItemWidget(row, 3, bar)
        speed = float(item.get("speed_bps") or 0)
        row.setText(4, f"{fmt_bytes(speed)}/s" + (f" · {fmt_duration(item.get('eta_seconds'))}" if speed else ""))

    def _retry_failed(self):
        for item in downloader.load_queue():
            if item.get("status") == "error":
                downloader.retry_item(item["id"])
        self.refresh()

    def _clear_completed(self):
        for item in downloader.load_queue():
            if item.get("status") == "done":
                downloader.remove_item(item["id"])
        self.refresh()

    @staticmethod
    def _open_path(path):
        if not path or not os.path.exists(path):
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

    def _payload_item(self, payload):
        if not payload or payload[0] != "item":
            return None
        return next((item for item in downloader.load_queue() if item.get("id") == payload[1]), None)

    def _context_menu(self, position):
        row = self.tree.itemAt(position)
        payload = row.data(0, Qt.UserRole) if row else None
        if not payload:
            return
        menu = QMenu(self)
        if payload[0] == "group":
            pause = menu.addAction("Pause batch")
            resume = menu.addAction("Resume batch")
            retry = menu.addAction("Retry failed in batch")
            menu.addSeparator()
            remove = menu.addAction("Remove batch from queue")
            chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
            group_id = payload[1]
            if chosen == pause:
                downloader.pause_group(group_id)
            elif chosen == resume:
                downloader.resume_group(group_id)
            elif chosen == retry:
                downloader.retry_group(group_id)
            elif chosen == remove:
                downloader.remove_group(group_id)
        else:
            item = self._payload_item(payload)
            if not item:
                return
            retry = menu.addAction("Retry")
            pause = menu.addAction("Pause")
            resume = menu.addAction("Resume")
            open_file = open_folder = None
            if item.get("status") == "done":
                menu.addSeparator()
                open_file = menu.addAction("Open file")
                open_folder = menu.addAction("Open containing folder")
            menu.addSeparator()
            remove = menu.addAction("Remove from queue")
            chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
            if chosen == retry:
                downloader.retry_item(item["id"])
            elif chosen == pause:
                downloader.pause_item(item["id"])
            elif chosen == resume:
                downloader.resume_item(item["id"])
            elif chosen == remove:
                downloader.remove_item(item["id"])
            elif chosen == open_file:
                self._open_path(downloader.destination_path(item))
            elif chosen == open_folder:
                self._open_path(os.path.dirname(downloader.destination_path(item)))
        self.refresh()

    def _open_completed(self, row, _column):
        item = self._payload_item(row.data(0, Qt.UserRole))
        if item and item.get("status") == "done":
            self._open_path(downloader.destination_path(item))
