import csv
import os
import threading
import uuid
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QMessageBox, QStackedWidget, QLineEdit, QFrame, QGridLayout, QScrollArea,
    QToolButton, QListWidget, QListWidgetItem, QApplication, QMenu, QSizePolicy, QProgressBar,
    QFormLayout, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QFileDialog, QColorDialog,
    QProgressDialog, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QThread, QStandardPaths
from PySide6.QtGui import QShortcut, QKeySequence, QColor

from core.profiles import load_profiles, create_profile, update_profile, delete_profile, get_profile
from core import cache, library, crawl_state
from core.crawl import crawl_profile, crawl_folder
from core import downloader
from core import applog
from core.paths import data_dir
from core.settings import load_settings, save_settings, downloads_root
from core.oder_package import (
    compare_packages, export_directory, find_conflicts, import_directory, inspect_package,
)
from core.version import APP_VERSION

from gui.profile_dialog import ProfileDialog
from gui.browser_widget import BrowserWidget
from gui.queue_widget import QueueWidget
from gui.logs_page import LogsPage
from gui.package_dialogs import (
    ExportDirectoryDialog, ImportDirectoryDialog, PackageComparisonDialog, PackageTask, format_bytes,
)


THEME_PRESETS = {
    "dark": {
        "background": "#0F1115", "panel": "#151922", "card": "#1B202A",
        "text": "#F2F4F7", "muted": "#98A2B3", "accent": "#7C5CFF",
        "button": "#202632", "button_hover": "#2A3240", "button_pressed": "#343E4F",
        "button_text": "#F2F4F7", "button_border": "#343C4A",
    },
    "midnight": {
        "background": "#07101F", "panel": "#0B1628", "card": "#10213A",
        "text": "#EAF2FF", "muted": "#8FA4C2", "accent": "#36A3FF",
        "button": "#142842", "button_hover": "#1B3555", "button_pressed": "#24446A",
        "button_text": "#EEF6FF", "button_border": "#2A4666",
    },
    "light": {
        "background": "#F3F5F8", "panel": "#FFFFFF", "card": "#FFFFFF",
        "text": "#18202A", "muted": "#667085", "accent": "#4F46E5",
        "button": "#F8FAFC", "button_hover": "#EEF2F7", "button_pressed": "#E2E8F0",
        "button_text": "#18202A", "button_border": "#C9D2DF",
    },
    "oled": {
        "background": "#000000", "panel": "#080808", "card": "#0E0E0E",
        "text": "#F5F5F5", "muted": "#9B9B9B", "accent": "#00C2A8",
        "button": "#151515", "button_hover": "#202020", "button_pressed": "#2A2A2A",
        "button_text": "#F2F2F2", "button_border": "#303030",
    },
}

THEME_CHOICES = [
    ("Graphite", "dark"),
    ("Midnight", "midnight"),
    ("Light", "light"),
    ("OLED Black", "oled"),
    ("Custom", "custom"),
]


def _hex_rgb(value):
    value = str(value or "").strip().lstrip("#")
    if len(value) != 6:
        return (0, 0, 0)
    try:
        return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


def _mix_hex(a, b, amount):
    ar, ag, ab = _hex_rgb(a)
    br, bg, bb = _hex_rgb(b)
    amount = max(0.0, min(1.0, float(amount)))
    vals = [round(x + (y - x) * amount) for x, y in ((ar, br), (ag, bg), (ab, bb))]
    return "#" + "".join(f"{v:02X}" for v in vals)


def _is_light_color(value):
    r, g, b = _hex_rgb(value)
    # Perceptual luminance is enough here to choose readable foregrounds.
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 150


def _expanded_palette(base):
    p = dict(base)
    light = _is_light_color(p["background"])
    p["accent_hover"] = _mix_hex(p["accent"], "#000000" if light else "#FFFFFF", 0.13)
    p["accent_text"] = "#111827" if _is_light_color(p["accent"]) else "#FFFFFF"
    p["input"] = _mix_hex(p["card"], p["background"], 0.12 if light else 0.22)
    p["header"] = _mix_hex(p["panel"], p["background"], 0.22 if light else 0.34)
    p["section_body"] = _mix_hex(p["panel"], p["background"], 0.12 if light else 0.26)
    p["selection"] = _mix_hex(p["accent"], p["background"], 0.82 if light else 0.73)
    p["selection_text"] = p["text"]
    p["focus"] = p["accent"]
    p["divider"] = p["button_border"]
    p["scroll_track"] = _mix_hex(p["panel"], p["background"], 0.35)
    p["scroll_handle"] = _mix_hex(p["button_border"], p["muted"], 0.38)
    p["disabled"] = _mix_hex(p["button"], p["background"], 0.45)
    p["disabled_text"] = _mix_hex(p["muted"], p["background"], 0.35)
    return p


APP_QSS_TEMPLATE = r"""
* { font-family: 'Segoe UI', Arial, sans-serif; }
QMainWindow, QDialog, QMessageBox { background: @BACKGROUND@; color: @TEXT@; }
QWidget { color: @TEXT@; }
QStackedWidget, QStackedWidget > QWidget { background: @BACKGROUND@; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QFrame#sidebar { background: @PANEL@; border-right: 1px solid @BUTTON_BORDER@; }
QFrame#pageHeader { background: @PANEL@; border-bottom: 1px solid @BUTTON_BORDER@; }
QFrame#divider { background: @DIVIDER@; color: @DIVIDER@; max-height: 1px; }
QLabel#appLogo { font-size: 22px; font-weight: 700; color: @TEXT@; }
QLabel#sectionLabel { color: @MUTED@; font-size: 11px; font-weight: 700; padding-top: 12px; }
QLabel#pageTitle { font-size: 22px; font-weight: 700; color: @TEXT@; }
QLabel#heroTitle { font-size: 28px; font-weight: 700; color: @TEXT@; }
QLabel#mutedLabel { color: @MUTED@; }
QFrame#breadcrumbBar { background: @CARD@; border: 1px solid @BUTTON_BORDER@; border-radius: 10px; }
QLabel#breadcrumbLabel { color: @TEXT@; background: transparent; padding: 1px 4px; }
QPushButton#sidebarButton { min-height: 26px; max-height: 30px; padding: 2px 7px; text-align: center; border-radius: 4px; }
QPushButton#sidebarAccent { min-height: 26px; max-height: 30px; padding: 2px 7px; background: @ACCENT@; border-color: @ACCENT@; color: @ACCENT_TEXT@; font-weight: 600; }
QPushButton#sidebarAccent:hover { background: @ACCENT_HOVER@; border-color: @ACCENT_HOVER@; }
QPushButton#sidebarSymbol { min-height: 30px; min-width: 48px; max-width: 48px; padding: 0; font-size: 16px; text-align: center; }
QPushButton, QToolButton {
    background: @BUTTON@; color: @BUTTON_TEXT@; border: 1px solid @BUTTON_BORDER@;
    border-radius: 2px; padding: 6px 10px; min-height: 28px;
}
QPushButton:hover, QToolButton:hover { background: @BUTTON_HOVER@; }
QPushButton:pressed, QToolButton:pressed { background: @BUTTON_PRESSED@; }
QPushButton:disabled, QToolButton:disabled { background: @DISABLED@; color: @DISABLED_TEXT@; }
QPushButton#accentButton { background: @ACCENT@; border-color: @ACCENT@; color: @ACCENT_TEXT@; font-weight: 600; }
QPushButton#accentButton:hover { background: @ACCENT_HOVER@; border-color: @ACCENT_HOVER@; }
QPushButton#tableButton { padding: 0; min-width: 78px; max-width: 78px; min-height: 27px; max-height: 27px; text-align: center; }
QPushButton#smallActionButton { padding: 0 10px; min-width: 88px; max-width: 88px; min-height: 28px; max-height: 28px; text-align: center; }
QWidget#tabRow { background: @BUTTON@; border: 1px solid @BUTTON_BORDER@; border-radius: 5px; }
QWidget#tabRow[selected="true"] { background: @SELECTION@; border-color: @ACCENT@; }
QToolButton#tabButton { background: transparent; color: @BUTTON_TEXT@; border: none; border-radius: 4px; padding: 3px 7px; text-align: left; min-height: 24px; max-height: 26px; }
QToolButton#tabButton:hover { background: @BUTTON_HOVER@; }
QWidget#tabRow[selected="true"] QToolButton#tabButton { color: @TEXT@; }
QToolButton#tabCloseButton { background: @INPUT@; color: @MUTED@; border: 1px solid @BUTTON_BORDER@; border-radius: 4px; padding: 0; min-width: 23px; max-width: 23px; min-height: 23px; max-height: 23px; font-weight: 700; }
QToolButton#tabCloseButton:hover { background: @BUTTON_HOVER@; color: @TEXT@; border-color: @ACCENT@; }
QToolButton#tabCloseButton:pressed { background: @BUTTON_PRESSED@; }
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background: @INPUT@; border: 1px solid @BUTTON_BORDER@; border-radius: 5px;
    padding: 7px 9px; color: @TEXT@; selection-background-color: @ACCENT@; selection-color: @ACCENT_TEXT@;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus { border: 1px solid @FOCUS@; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { background: @DISABLED@; color: @DISABLED_TEXT@; }
QPlainTextEdit#logText { font-family: Consolas, 'Courier New', monospace; font-size: 12px; border-radius: 6px; }
QComboBox {
    background: @BUTTON@; color: @BUTTON_TEXT@; border: 1px solid @BUTTON_BORDER@;
    border-radius: 2px; padding: 5px 28px 5px 8px; min-height: 28px;
}
QComboBox:hover { background: @BUTTON_HOVER@; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: @PANEL@; color: @TEXT@; border: 1px solid @BUTTON_BORDER@; selection-background-color: @SELECTION@; selection-color: @TEXT@; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QListWidget { background: @BACKGROUND@; border: none; outline: none; }
QListWidget::item { padding: 7px 10px; margin: 1px 0; border-radius: 5px; }
QTreeWidget, QTableWidget { background: @BACKGROUND@; color: @TEXT@; border: none; outline: none; gridline-color: @BUTTON_BORDER@; alternate-background-color: @CARD@; }
QTreeWidget::item, QTableWidget::item { padding: 7px 4px; }
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected { background: @SELECTION@; color: @SELECTION_TEXT@; }
QHeaderView::section { background: @HEADER@; color: @MUTED@; border: none; border-bottom: 1px solid @BUTTON_BORDER@; padding: 8px; font-size: 11px; }
QProgressBar { background: @INPUT@; color: @TEXT@; border: 1px solid @BUTTON_BORDER@; border-radius: 5px; text-align: center; min-height: 15px; }
QProgressBar::chunk { background: @ACCENT@; border-radius: 4px; }
QFrame#card { background: @CARD@; border: 1px solid @BUTTON_BORDER@; border-radius: 8px; }
QLabel#cardTitle { font-size: 15px; font-weight: 600; color: @TEXT@; }
QLabel#cardMeta { color: @MUTED@; background: transparent; }
QStatusBar { background: @PANEL@; color: @MUTED@; border-top: 1px solid @BUTTON_BORDER@; }
QToolButton#settingsSectionHeader {
    background: @HEADER@; color: @TEXT@; border: 1px solid @BUTTON_BORDER@;
    border-radius: 3px 3px 0 0; padding: 9px 10px; text-align: left;
    font-size: 13px; font-weight: 600;
}
QToolButton#settingsSectionHeader:hover { background: @BUTTON_HOVER@; }
QFrame#settingsSectionBody { background: @SECTION_BODY@; border: 1px solid @BUTTON_BORDER@; border-top: none; border-radius: 0 0 3px 3px; }
QLabel#shortcutBadge { background: @BUTTON@; border: 1px solid @BUTTON_BORDER@; border-radius: 4px; color: @BUTTON_TEXT@; padding: 4px 8px; min-width: 78px; }
QMenu { background: @PANEL@; color: @TEXT@; border: 1px solid @BUTTON_BORDER@; padding: 4px; }
QMenu::item { padding: 6px 24px 6px 10px; border-radius: 2px; }
QMenu::item:selected { background: @SELECTION@; color: @TEXT@; }
QToolTip { background: @PANEL@; color: @TEXT@; border: 1px solid @BUTTON_BORDER@; padding: 4px; }
QScrollBar:vertical { background: @SCROLL_TRACK@; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: @SCROLL_HANDLE@; min-height: 28px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: @MUTED@; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: @SCROLL_TRACK@; height: 11px; margin: 0; }
QScrollBar::handle:horizontal { background: @SCROLL_HANDLE@; min-width: 28px; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background: @MUTED@; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""


def _render_theme_qss(base):
    p = _expanded_palette(base)
    qss = APP_QSS_TEMPLATE
    for key, value in p.items():
        qss = qss.replace(f"@{key.upper()}@", value)
    return qss


class TabButton(QToolButton):
    closeRequested = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.property("closable") and event.position().x() >= self.width() - 26:
            self.closeRequested.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class HomePage(QWidget):
    open_site_requested = Signal(str)
    export_site_requested = Signal(str)
    add_site_requested = Signal()
    import_directory_requested = Signal()
    open_downloads_requested = Signal()
    open_settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(36, 34, 36, 30)
        self.layout.setSpacing(14)
        title = QLabel("ODeR")
        title.setObjectName("heroTitle")
        subtitle = QLabel("Browse cached directory listings like a local library — even when you're offline.")
        subtitle.setObjectName("mutedLabel")
        self.layout.addWidget(title)
        self.layout.addWidget(subtitle)

        quick = QHBoxLayout()
        quick.setSpacing(10)
        for label, signal in (("Add site", self.add_site_requested),
                              ("Import .oder", self.import_directory_requested),
                              ("Downloads", self.open_downloads_requested),
                              ("Settings", self.open_settings_requested)):
            btn = QPushButton(label)
            btn.setObjectName("smallActionButton")
            btn.setMinimumHeight(42)
            btn.clicked.connect(lambda _=False, sig=signal: sig.emit())
            quick.addWidget(btn)
        self.layout.addLayout(quick)

        section = QLabel("MY LOCATIONS")
        section.setObjectName("sectionLabel")
        self.layout.addWidget(section)
        self.cards_wrap = QWidget()
        self.cards_grid = QGridLayout(self.cards_wrap)
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setSpacing(12)
        self.layout.addWidget(self.cards_wrap)
        self.layout.addStretch(1)
        self.refresh([])

    def refresh(self, profiles):
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not profiles:
            empty = QLabel("No sites yet. Add a site to start building your offline library.")
            empty.setObjectName("mutedLabel")
            self.cards_grid.addWidget(empty, 0, 0)
            return
        for idx, profile in enumerate(profiles):
            cache.migrate_json_if_needed(profile["id"], profile["base_url"])
            total_items = cache.count_nodes(profile["id"]) - 1
            folders = cache.count_dirs(profile["id"])
            files = cache.count_files(profile["id"])
            status = "Cached ✓" if total_items > 0 else "No cache yet"
            card = QFrame()
            card.setObjectName("card")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(16, 14, 16, 14)
            name = QLabel(profile["name"])
            name.setObjectName("cardTitle")
            layout.addWidget(name)
            url = QLabel(profile.get("base_url", ""))
            url.setObjectName("cardMeta")
            url.setWordWrap(True)
            layout.addWidget(url)
            meta = QLabel(f"{total_items:,} items  ·  {folders:,} folders  ·  {files:,} files  ·  {status}  ·  {profile.get('last_crawled') or 'Not updated'}")
            meta.setObjectName("cardMeta")
            layout.addWidget(meta)
            actions = QHBoxLayout()
            open_btn = QPushButton("Open tab")
            open_btn.clicked.connect(lambda _, pid=profile["id"]: self.open_site_requested.emit(pid))
            actions.addWidget(open_btn)
            export_btn = QPushButton("Export .oder")
            export_btn.clicked.connect(lambda _, pid=profile["id"]: self.export_site_requested.emit(pid))
            actions.addWidget(export_btn)
            layout.addLayout(actions)
            row, col = divmod(idx, 2)
            self.cards_grid.addWidget(card, row, col)


class SearchPage(QWidget):
    open_result_requested = Signal(str, str)
    favorite_added = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 34, 36, 30)
        layout.setSpacing(12)
        self.title = QLabel("Search cache")
        self.title.setObjectName("heroTitle")
        layout.addWidget(self.title)
        self.summary = QLabel("Search all cached directory listings without making a network request.")
        self.summary.setObjectName("mutedLabel")
        layout.addWidget(self.summary)
        filters = QHBoxLayout()
        self.site_filter = QComboBox()
        self.type_filter = QComboBox()
        self.type_filter.addItem("All types", "all")
        for label, value in (("Archives", "archive"), ("Documents", "document"), ("Images", "image"),
                             ("Video", "video"), ("Audio", "audio"), ("Applications", "application")):
            self.type_filter.addItem(label, value)
        self.size_filter = QComboBox()
        self.size_filter.addItem("Any size", (None, None))
        self.size_filter.addItem("Under 1 MB", (None, 1024 * 1024))
        self.size_filter.addItem("1–100 MB", (1024 * 1024, 100 * 1024 * 1024))
        self.size_filter.addItem("Over 100 MB", (100 * 1024 * 1024, None))
        self.files_only = QCheckBox("Files")
        self.files_only.setChecked(True)
        self.folders_only = QCheckBox("Folders")
        self.folders_only.setChecked(True)
        self.save_search_btn = QPushButton("Save search")
        self.save_search_btn.clicked.connect(self._save_search)
        for widget in (QLabel("Site:"), self.site_filter, QLabel("Type:"), self.type_filter,
                       QLabel("Size:"), self.size_filter, self.files_only, self.folders_only,
                       self.save_search_btn):
            filters.addWidget(widget)
        filters.addStretch(1)
        layout.addLayout(filters)
        self.site_filter.currentIndexChanged.connect(self._rerun)
        self.type_filter.currentIndexChanged.connect(self._rerun)
        self.size_filter.currentIndexChanged.connect(self._rerun)
        self.files_only.toggled.connect(self._rerun)
        self.folders_only.toggled.connect(self._rerun)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self._open_item)
        layout.addWidget(self.results, 1)
        self._matches = []
        self._query = ""

    def refresh_profiles(self):
        selected = self.site_filter.currentData()
        self.site_filter.blockSignals(True)
        self.site_filter.clear()
        self.site_filter.addItem("All sites", None)
        for profile in load_profiles():
            self.site_filter.addItem(profile["name"], profile["id"])
        index = self.site_filter.findData(selected)
        self.site_filter.setCurrentIndex(index if index >= 0 else 0)
        self.site_filter.blockSignals(False)

    def _rerun(self, *_args):
        if self._query:
            self.search(self._query)

    def search(self, query):
        query = query.strip()
        self._query = query
        if not self.site_filter.count():
            self.refresh_profiles()
        self.results.clear()
        self._matches = []
        if not query:
            self.title.setText("Search cache")
            self.summary.setText("Type a file or folder name in the sidebar search box.")
            return
        self.title.setText(f"Search results for “{query}”")
        profiles = load_profiles()
        profile_id = self.site_filter.currentData()
        if profile_id:
            profiles = [profile for profile in profiles if profile["id"] == profile_id]
        min_size, max_size = self.size_filter.currentData() or (None, None)
        results = cache.search_all(
            profiles, query, limit_per_profile=500,
            file_type=self.type_filter.currentData() or "all",
            min_size=min_size, max_size=max_size,
            include_files=self.files_only.isChecked(), include_dirs=self.folders_only.isChecked(),
        )
        for profile, node in results:
            base = cache.get_base_url(profile["id"]) or profile["base_url"]
            rel = node["url"][len(base):].strip("/") if node["url"].startswith(base) else node["url"]
            kind = "Folder" if node["is_dir"] else "File"
            text = f"{profile['name']}  ·  {kind}  ·  {node['name']}\n{rel or 'root'}"
            item = QListWidgetItem(text)
            self.results.addItem(item)
            self._matches.append((profile["id"], node["url"]))
        self.summary.setText(f"{len(self._matches):,} cached match{'es' if len(self._matches) != 1 else ''}")

    def _save_search(self):
        if not self._query:
            return
        min_size, max_size = self.size_filter.currentData() or (None, None)
        library.add_search(
            self._query, self._query, self.site_filter.currentData(),
            {"file_type": self.type_filter.currentData(), "min_size": min_size, "max_size": max_size,
             "include_files": self.files_only.isChecked(), "include_dirs": self.folders_only.isChecked()},
        )
        self.favorite_added.emit()
        self.summary.setText("Saved search added to Favorites")

    def apply_saved(self, item):
        self.refresh_profiles()
        profile_id = item.get("profile_id")
        if profile_id:
            index = self.site_filter.findData(profile_id)
            if index >= 0:
                self.site_filter.setCurrentIndex(index)
        filters = item.get("filters") or {}
        index = self.type_filter.findData(filters.get("file_type", "all"))
        self.type_filter.setCurrentIndex(max(0, index))
        size_value = (filters.get("min_size"), filters.get("max_size"))
        index = next((i for i in range(self.size_filter.count())
                      if tuple(self.size_filter.itemData(i) or (None, None)) == size_value), -1)
        self.size_filter.setCurrentIndex(max(0, index))
        self.files_only.setChecked(filters.get("include_files", True))
        self.folders_only.setChecked(filters.get("include_dirs", True))
        self.search(item.get("query", ""))

    def _open_item(self, item):
        row = self.results.row(item)
        if 0 <= row < len(self._matches):
            self.open_result_requested.emit(*self._matches[row])


class CollapsibleSection(QWidget):
    def __init__(self, title, description="", expanded=False, parent=None, layout_type="vbox"):
        super().__init__(parent)
        outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        self.header=QToolButton(); self.header.setCheckable(True); self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.header.setText(title if not description else f"{title}  —  {description}"); self.header.setCursor(Qt.PointingHandCursor)
        self.header.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed); self.header.setMinimumHeight(42); self.header.setObjectName("settingsSectionHeader")
        self.header.clicked.connect(self._toggle); outer.addWidget(self.header)
        self.body=QFrame(); self.body.setObjectName("settingsSectionBody")
        if layout_type == "form":
            self.body_layout=QFormLayout(self.body)
            self.body_layout.setContentsMargins(12,10,12,12)
            self.body_layout.setHorizontalSpacing(14)
            self.body_layout.setVerticalSpacing(10)
            self.body_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        else:
            self.body_layout=QVBoxLayout(self.body)
            self.body_layout.setContentsMargins(12,10,12,12)
            self.body_layout.setSpacing(10)
        outer.addWidget(self.body); self.body.setVisible(expanded)
    def _toggle(self, checked):
        self.body.setVisible(checked); self.header.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)


def _normalize_hex(value):
    value=str(value or '').strip()
    if len(value)==7 and value.startswith('#'):
        try: int(value[1:],16); return value.upper()
        except ValueError: pass
    return None


class ColorPickerField(QWidget):
    """Compact swatch + hex editor. Clicking the swatch opens QColorDialog."""
    def __init__(self, value, label="Color", parent=None):
        super().__init__(parent)
        self.label = label
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.swatch = QPushButton("")
        self.swatch.setFixedSize(34, 28)
        self.swatch.setToolTip(f"Choose {label.lower()} color")
        self.swatch.clicked.connect(self._choose)
        row.addWidget(self.swatch)
        self.edit = QLineEdit()
        self.edit.setMaximumWidth(104)
        self.edit.setPlaceholderText("#RRGGBB")
        self.edit.textChanged.connect(self._update_swatch)
        row.addWidget(self.edit)
        self.set_color(value)

    def _choose(self):
        current = QColor(_normalize_hex(self.edit.text()) or "#000000")
        picked = QColorDialog.getColor(current, self, f"Choose {self.label.lower()} color")
        if picked.isValid():
            self.set_color(picked.name(QColor.NameFormat.HexRgb).upper())

    def _update_swatch(self, _text=None):
        value = _normalize_hex(self.edit.text())
        if value:
            # The swatch intentionally uses its chosen color rather than the app theme.
            self.swatch.setStyleSheet(f"QPushButton {{ background-color: {value}; border: 1px solid #7A7A7A; padding: 0; }}")
            self.swatch.setToolTip(f"{self.label}: {value} — click to choose")
        else:
            self.swatch.setStyleSheet("QPushButton { background: transparent; border: 1px dashed #7A7A7A; padding: 0; }")
            self.swatch.setToolTip(f"Invalid color — click to choose {self.label.lower()}")

    def set_color(self, value):
        normalized = _normalize_hex(value) or "#000000"
        self.edit.setText(normalized)
        self._update_swatch()


class SettingsPage(QWidget):
    settings_changed = Signal()
    import_directory_requested = Signal()
    compare_packages_requested = Signal()
    open_storage_requested = Signal()
    open_changes_requested = Signal()
    def __init__(self, parent=None):
        super().__init__(parent); self._settings=load_settings()
        root=QVBoxLayout(self); root.setContentsMargins(36,28,36,28); root.setSpacing(10)
        title=QLabel("Settings"); title.setObjectName("heroTitle"); root.addWidget(title)
        subtitle=QLabel("Application storage, downloads, networking, appearance and behavior."); subtitle.setObjectName("mutedLabel"); root.addWidget(subtitle)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        body=QWidget(); form=QVBoxLayout(body); form.setContentsMargins(0,4,8,12); form.setSpacing(10)

        storage=CollapsibleSection("Storage & downloads", "global locations and download defaults", True, layout_type="form"); sf=storage.body_layout
        self.download_dir=QLineEdit(self._settings.get('download_dir',downloads_root())); browse=QPushButton("Browse…"); row=QHBoxLayout(); row.addWidget(self.download_dir,1); row.addWidget(browse); browse.clicked.connect(self._browse_downloads); sf.addRow("Download directory",row)
        self.dl_concurrency=QSpinBox(); self.dl_concurrency.setRange(1,64); self.dl_concurrency.setValue(int(self._settings.get('download_concurrency',2))); sf.addRow("Global download concurrency",self.dl_concurrency)
        self.dl_delay=QDoubleSpinBox(); self.dl_delay.setRange(0,60); self.dl_delay.setDecimals(2); self.dl_delay.setSuffix(' s'); self.dl_delay.setValue(float(self._settings.get('download_start_delay',0.5))); sf.addRow("Delay between download starts",self.dl_delay)
        self.overwrite_downloads=QCheckBox("Keep existing completed files and skip them"); self.overwrite_downloads.setChecked(bool(self._settings.get('skip_existing_downloads',True))); sf.addRow(self.overwrite_downloads); form.addWidget(storage)

        network=CollapsibleSection("Networking", "timeouts, rate limits and browser fallback", True, layout_type="form"); nf=network.body_layout
        self.timeout=QSpinBox(); self.timeout.setRange(1,600); self.timeout.setSuffix(' s'); self.timeout.setValue(int(self._settings.get('request_timeout_seconds',20))); nf.addRow('Request timeout',self.timeout)
        self.max_connections=QSpinBox(); self.max_connections.setRange(1,128); self.max_connections.setValue(int(self._settings.get('network_max_connections',12))); nf.addRow('Global background connection limit',self.max_connections)
        self.backoff=QSpinBox(); self.backoff.setRange(1,3600); self.backoff.setSuffix(' s'); self.backoff.setValue(int(self._settings.get('network_backoff_seconds',60))); nf.addRow('Default rate-limit backoff',self.backoff)
        self.user_agent=QLineEdit(self._settings.get('user_agent',f'ODeR/{APP_VERSION}')); nf.addRow('User-Agent',self.user_agent)
        self.external_browser=QCheckBox('Open protected/download URLs in the system browser'); self.external_browser.setChecked(bool(self._settings.get('open_external_downloads_in_browser',True))); nf.addRow(self.external_browser)
        self.follow_redirects=QCheckBox('Follow normal HTTP redirects'); self.follow_redirects.setChecked(bool(self._settings.get('follow_redirects',True))); nf.addRow(self.follow_redirects); form.addWidget(network)

        appearance=CollapsibleSection("Appearance", "built-in themes and a visual custom palette", False, layout_type="form"); af=appearance.body_layout
        self.theme=QComboBox()
        for label, key in THEME_CHOICES:
            self.theme.addItem(label, key)
        wanted_theme=self._settings.get('theme','dark')
        idx=self.theme.findData(wanted_theme)
        self.theme.setCurrentIndex(idx if idx >= 0 else self.theme.findData('dark'))
        af.addRow('Theme',self.theme)
        theme_hint=QLabel('Graphite is the balanced default; Midnight is blue-toned, Light is high-contrast, and OLED uses true black surfaces.')
        theme_hint.setObjectName('mutedLabel'); theme_hint.setWordWrap(True); af.addRow('',theme_hint)
        self.remember_sidebar=QCheckBox(); self.remember_sidebar.setChecked(False); self.remember_sidebar.hide()
        self.color_fields={}; self.color_edits={}; defaults=THEME_PRESETS['dark']; custom=self._settings.get('custom_theme',{}) or {}
        grid=QGridLayout(); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(8)
        color_defs=[('background','Background'),('panel','Panels'),('card','Cards'),('text','Text'),('muted','Muted text'),('accent','Accent'),('button','Buttons'),('button_hover','Button hover'),('button_pressed','Button pressed'),('button_text','Button text'),('button_border','Button border')]
        for i,(key,label) in enumerate(color_defs):
            r,c=divmod(i,2)
            grid.addWidget(QLabel(label),r,c*2)
            field=ColorPickerField(custom.get(key,defaults[key]), label)
            self.color_fields[key]=field; self.color_edits[key]=field.edit
            grid.addWidget(field,r,c*2+1)
        af.addRow('Custom palette',grid)
        custom_actions=QHBoxLayout(); copy_preset=QPushButton('Copy selected preset to custom'); copy_preset.clicked.connect(self._copy_preset_to_custom); custom_actions.addWidget(copy_preset); custom_actions.addStretch(1)
        af.addRow('',custom_actions); form.addWidget(appearance)

        behavior=CollapsibleSection("Behavior & cache", "startup checks and progressive browsing", False, layout_type="form"); bf=behavior.body_layout
        self.lazy=QCheckBox('Enable progressive/lazy directory browsing'); self.lazy.setChecked(bool(self._settings.get('lazy_directory_browsing',True))); bf.addRow(self.lazy)
        self.startup_check=QCheckBox('Check saved directories at startup (local cache only)'); self.startup_check.setChecked(bool(self._settings.get('startup_check_directories',True))); bf.addRow(self.startup_check)
        self.startup_init=QCheckBox('Initialize/migrate saved caches at startup'); self.startup_init.setChecked(bool(self._settings.get('startup_initialize_caches',True))); bf.addRow(self.startup_init)
        self.confirm_full=QCheckBox('Confirm before a full site update'); self.confirm_full.setChecked(bool(self._settings.get('confirm_full_updates',True))); bf.addRow(self.confirm_full)
        self.resume_startup=QCheckBox('Resume unfinished crawls when ODeR starts'); self.resume_startup.setChecked(bool(self._settings.get('resume_crawls_at_startup',False))); bf.addRow(self.resume_startup)
        self.notify_changes=QCheckBox('Show a notification when directory contents change'); self.notify_changes.setChecked(bool(self._settings.get('notify_directory_changes',True))); bf.addRow(self.notify_changes)
        self.stale_days=QSpinBox(); self.stale_days.setRange(1,3650); self.stale_days.setSuffix(' days'); self.stale_days.setValue(int(self._settings.get('incremental_stale_days',7))); bf.addRow('Incremental update age',self.stale_days)
        self.page_size=QSpinBox(); self.page_size.setRange(50,5000); self.page_size.setSingleStep(50); self.page_size.setValue(int(self._settings.get('browser_page_size',500))); bf.addRow('Entries per browser page',self.page_size); form.addWidget(behavior)

        keyboard=CollapsibleSection("Keyboard", "quick navigation and actions", False); kg=QGridLayout(); kg.setHorizontalSpacing(16); kg.setVerticalSpacing(7)
        for i,(key,desc) in enumerate([('Ctrl+T','New tab'),('Ctrl+W','Close tab'),('Ctrl+L','Focus search'),('Ctrl+F','Search current folder'),('F5','Update current folder'),('Ctrl+Shift+F5','Update entire site'),('Alt+Left / Alt+Right','Back / forward')]):
            badge=QLabel(key); badge.setObjectName('shortcutBadge'); badge.setAlignment(Qt.AlignCenter); kg.addWidget(badge,i,0); kg.addWidget(QLabel(desc),i,1)
        keyboard.body_layout.addLayout(kg); form.addWidget(keyboard)

        packaging=CollapsibleSection("Application & packages", ".oder transfer and application storage", False); info=QLabel(f"ODeR {APP_VERSION}\nData folder: {data_dir()}\nPortable builds keep writable data next to the executable. Installed builds should keep writable data in the user profile rather than Program Files.")
        info.setObjectName('mutedLabel'); info.setWordWrap(True); packaging.body_layout.addWidget(info)
        package_actions=QHBoxLayout(); import_package=QPushButton('Import .oder…'); import_package.clicked.connect(self.import_directory_requested.emit); package_actions.addWidget(import_package)
        compare_package=QPushButton('Compare two .oder files…'); compare_package.clicked.connect(self.compare_packages_requested.emit); package_actions.addWidget(compare_package)
        storage_manager=QPushButton('Storage manager'); storage_manager.clicked.connect(self.open_storage_requested.emit); package_actions.addWidget(storage_manager)
        changes=QPushButton('Change history'); changes.clicked.connect(self.open_changes_requested.emit); package_actions.addWidget(changes)
        package_actions.addStretch(1); packaging.body_layout.addLayout(package_actions)
        recent=library.recent_packages(5)
        if recent:
            recent_label=QLabel('Recent packages:\n'+'\n'.join(f"• {item.get('action','package').title()}: {os.path.basename(item.get('path',''))}" for item in recent))
            recent_label.setObjectName('mutedLabel'); recent_label.setWordWrap(True); packaging.body_layout.addWidget(recent_label)
        form.addWidget(packaging)
        form.addStretch(1); scroll.setWidget(body); root.addWidget(scroll,1)
        actions=QHBoxLayout(); save=QPushButton('Save settings'); save.setObjectName('accentButton'); save.clicked.connect(self.save); reset=QPushButton('Reset defaults'); reset.clicked.connect(self.reset); actions.addWidget(save); actions.addWidget(reset); actions.addStretch(1); root.addLayout(actions)

    def _browse_downloads(self):
        d=QFileDialog.getExistingDirectory(self,'Choose download directory',self.download_dir.text())
        if d: self.download_dir.setText(d)

    def _copy_preset_to_custom(self):
        key=self.theme.currentData() or 'dark'
        if key == 'custom':
            key = 'dark'
        preset=THEME_PRESETS.get(key, THEME_PRESETS['dark'])
        for name, value in preset.items():
            if name in self.color_fields:
                self.color_fields[name].set_color(value)
        self.theme.setCurrentIndex(self.theme.findData('custom'))

    def reset(self):
        self.download_dir.setText(downloads_root()); self.dl_concurrency.setValue(2); self.dl_delay.setValue(0.5); self.overwrite_downloads.setChecked(True)
        self.timeout.setValue(20); self.max_connections.setValue(12); self.backoff.setValue(60); self.user_agent.setText(f'ODeR/{APP_VERSION}'); self.external_browser.setChecked(True); self.follow_redirects.setChecked(True)
        idx=self.theme.findData('dark'); self.theme.setCurrentIndex(idx if idx >= 0 else 0); self.remember_sidebar.setChecked(False); self.lazy.setChecked(True); self.startup_check.setChecked(True); self.startup_init.setChecked(True); self.confirm_full.setChecked(True); self.resume_startup.setChecked(False); self.notify_changes.setChecked(True); self.stale_days.setValue(7); self.page_size.setValue(500)
        defaults=THEME_PRESETS['dark']
        for k,v in defaults.items(): self.color_fields[k].set_color(v)

    def save(self):
        theme=self.theme.currentData() or 'dark'; colors={k:v.text().strip() for k,v in self.color_edits.items()}
        if theme=='custom':
            bad=[k for k,v in colors.items() if not _normalize_hex(v)]
            if bad: QMessageBox.warning(self,'Invalid theme color',f"These colors are not valid #RRGGBB values: {', '.join(bad)}"); return
            colors={k:_normalize_hex(v) for k,v in colors.items()}
        vals={'download_dir':self.download_dir.text().strip(),'download_concurrency':self.dl_concurrency.value(),'download_start_delay':self.dl_delay.value(),'skip_existing_downloads':self.overwrite_downloads.isChecked(),'request_timeout_seconds':self.timeout.value(),'network_max_connections':self.max_connections.value(),'network_backoff_seconds':self.backoff.value(),'user_agent':self.user_agent.text().strip(),'open_external_downloads_in_browser':self.external_browser.isChecked(),'follow_redirects':self.follow_redirects.isChecked(),'theme':theme,'custom_theme':colors,'sidebar_collapsed':False,'lazy_directory_browsing':self.lazy.isChecked(),'startup_check_directories':self.startup_check.isChecked(),'startup_initialize_caches':self.startup_init.isChecked(),'confirm_full_updates':self.confirm_full.isChecked(),'resume_crawls_at_startup':self.resume_startup.isChecked(),'notify_directory_changes':self.notify_changes.isChecked(),'incremental_stale_days':self.stale_days.value(),'browser_page_size':self.page_size.value()}
        save_settings(vals); self.settings_changed.emit(); QMessageBox.information(self,'Settings saved','Settings saved. Theme and sidebar changes are applied immediately; network/download defaults apply to new work and background workers.')


class ActivityPage(QWidget):
    open_site_requested = Signal(str)
    stop_requested = Signal(str)
    resume_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(36, 28, 36, 28)
        self.layout.setSpacing(14)
        title = QLabel("Activity")
        title.setObjectName("heroTitle")
        self.layout.addWidget(title)
        subtitle = QLabel("Live crawl progress and recent cache updates.")
        subtitle.setObjectName("mutedLabel")
        self.layout.addWidget(subtitle)
        self.active_wrap = QWidget()
        self.active_layout = QVBoxLayout(self.active_wrap)
        self.active_layout.setContentsMargins(0, 0, 0, 0)
        self.active_layout.setSpacing(10)
        self.layout.addWidget(self.active_wrap)
        hist_title = QLabel("RECENT CRAWLS")
        hist_title.setObjectName("sectionLabel")
        self.layout.addWidget(hist_title)
        self.history = QListWidget()
        self.history.itemDoubleClicked.connect(self._open_history)
        self.layout.addWidget(self.history, 1)
        self._history_refs = []

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    @staticmethod
    def _duration(seconds):
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds}s"
        m, s = divmod(seconds, 60)
        if m < 60:
            return f"{m}m {s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h {m:02d}m"

    @staticmethod
    def _eta(seconds):
        if seconds <= 0:
            return "Calculating…"
        return ActivityPage._duration(seconds)

    def refresh(self, profiles, statuses):
        self._clear_layout(self.active_layout)
        active = [(p, statuses.get(p["id"], {})) for p in profiles if statuses.get(p["id"], {}).get("running")]
        resumable_ids = {profile["id"] for profile, _state in crawl_state.resumable(profiles)}
        if not active and not resumable_ids:
            empty = QLabel("No crawls are running right now.")
            empty.setObjectName("mutedLabel")
            self.active_layout.addWidget(empty)
        for profile, st in active:
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 14, 16, 14)
            top = QHBoxLayout()
            name = QLabel(profile["name"])
            name.setObjectName("cardTitle")
            top.addWidget(name, 1)
            open_btn = QPushButton("Open site")
            open_btn.clicked.connect(lambda _, pid=profile["id"]: self.open_site_requested.emit(pid))
            top.addWidget(open_btn)
            stop_btn = QPushButton("Stop")
            stop_btn.clicked.connect(lambda _, pid=profile["id"]: self.stop_requested.emit(pid))
            top.addWidget(stop_btn)
            cl.addLayout(top)

            scanned = int(st.get("crawled", 0))
            discovered = max(scanned, int(st.get("folders_discovered", 0)))
            queued = max(0, int(st.get("queued", 0)))
            rate = float(st.get("rate", 0.0))
            elapsed = float(st.get("elapsed", 0.0))
            coverage = int((scanned / discovered) * 100) if discovered else 0
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(coverage)
            bar.setFormat(f"{coverage}% of discovered folders")
            cl.addWidget(bar)

            remaining_eta = (queued / rate) if rate > 0 and queued > 0 else 0
            current = st.get("current") or "Finishing…"
            if isinstance(current, str):
                current = current.replace(profile.get("base_url", ""), "") or "/"
            info = QLabel(
                f"Folders scanned: <b>{scanned:,}</b>  ·  Discovered: <b>{discovered:,}</b>  ·  "
                f"Queued: <b>{queued:,}</b>  ·  Files found: <b>{int(st.get('files_discovered', 0)):,}</b><br>"
                f"Requests: <b>{int(st.get('requests', 0)):,}</b>  ·  Speed: <b>{rate:.1f} folders/s</b>  ·  "
                f"Workers: <b>{int(st.get('workers', 1))}</b>  ·  Elapsed: <b>{self._duration(elapsed)}</b>  ·  "
                f"Queue ETA: <b>{self._eta(remaining_eta)}</b><br>"
                f"Current: {current}"
            )
            info.setWordWrap(True)
            cl.addWidget(info)
            self.active_layout.addWidget(card)

        active_ids = {profile["id"] for profile, _status in active}
        for profile in profiles:
            if profile["id"] in active_ids or profile["id"] not in resumable_ids:
                continue
            state = crawl_state.load(profile["id"])
            card = QFrame()
            card.setObjectName("card")
            row = QHBoxLayout(card)
            label = QLabel(
                f"<b>{profile['name']}</b><br>Unfinished {state.get('mode', 'resume')} update · "
                f"{int(state.get('completed_count', 0)):,} folders scanned"
            )
            row.addWidget(label, 1)
            resume = QPushButton("Resume")
            resume.setObjectName("accentButton")
            resume.clicked.connect(lambda _=False, pid=profile["id"]: self.resume_requested.emit(pid))
            row.addWidget(resume)
            self.active_layout.addWidget(card)

        self.history.clear()
        self._history_refs = []
        for profile in profiles:
            for entry in (profile.get("crawl_history") or []):
                started = entry.get("started_at") or ""
                try:
                    dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    when = dt.astimezone().strftime("%Y-%m-%d %H:%M")
                except Exception:
                    when = started[:16]
                mode = entry.get("mode", "completed")
                status = "Stopped" if mode == "stopped" else ("Failed" if mode == "failed" or entry.get("error") else "Completed")
                text = (f"{profile['name']}  ·  {status}  ·  {when}  ·  "
                        f"{int(entry.get('directories', 0)):,} folders  ·  {int(entry.get('files', 0)):,} files  ·  "
                        f"{int(entry.get('requests', 0)):,} requests  ·  {self._duration(entry.get('duration_seconds', 0))}  ·  "
                        f"+{int(entry.get('new_count', 0))} / −{int(entry.get('removed_count', 0))} / ~{int(entry.get('changed_count', 0))}")
                item = QListWidgetItem(text)
                self.history.addItem(item)
                self._history_refs.append(profile["id"])
        if not self.history.count():
            self.history.addItem("No crawl history yet.")

    def _open_history(self, item):
        row = self.history.row(item)
        if 0 <= row < len(self._history_refs):
            self.open_site_requested.emit(self._history_refs[row])


class FavoritesPage(QWidget):
    open_folder_requested = Signal(str, str)
    open_search_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 28)
        title = QLabel("Favorites")
        title.setObjectName("heroTitle")
        layout.addWidget(title)
        hint = QLabel("Pinned folders and reusable offline searches.")
        hint.setObjectName("mutedLabel")
        layout.addWidget(hint)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._open)
        layout.addWidget(self.list, 1)
        actions = QHBoxLayout()
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(remove)
        actions.addWidget(refresh)
        actions.addStretch(1)
        layout.addLayout(actions)
        self._items = []
        self.refresh()

    def refresh(self):
        self.list.clear()
        self._items = library.favorites()
        profiles = {profile["id"]: profile for profile in load_profiles()}
        for saved in self._items:
            profile = profiles.get(saved.get("profile_id"), {})
            if saved.get("kind") == "folder":
                text = f"Folder · {saved.get('label', 'Saved folder')}\n{saved.get('url', '')}"
            else:
                where = profile.get("name", "All sites")
                text = f"Search · {saved.get('label') or saved.get('query')} · {where}"
            self.list.addItem(text)
        if not self._items:
            self.list.addItem("No favorites yet. Right-click a folder or save a cache search.")

    def _open(self, item):
        row = self.list.row(item)
        if not 0 <= row < len(self._items):
            return
        saved = self._items[row]
        if saved.get("kind") == "folder":
            self.open_folder_requested.emit(saved.get("profile_id", ""), saved.get("url", ""))
        else:
            self.open_search_requested.emit(saved)

    def _remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self._items):
            library.remove_favorite(self._items[row].get("id"))
            self.refresh()


class StoragePage(QWidget):
    optimize_requested = Signal(str)
    clear_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 28)
        title = QLabel("Storage manager")
        title.setObjectName("heroTitle")
        layout.addWidget(title)
        hint = QLabel("Inspect, repair, compact, or clear each cached index. Downloaded files are never cleared here.")
        hint.setObjectName("mutedLabel")
        layout.addWidget(hint)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Directory", "Entries", "Pending", "Index size", "Search", "Last scan", "Snapshots"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        for label, callback in (("Refresh", self.refresh), ("Repair & compact", self._optimize),
                                ("Clear cached index", self._clear), ("Open data folder", self._open_data)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.refresh()

    @staticmethod
    def _bytes(value):
        return format_bytes(value)

    def refresh(self):
        profiles = load_profiles()
        self.table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            try:
                stats = cache.storage_stats(profile["id"])
            except Exception:
                stats = {}
            values = [profile["name"], f"{int(stats.get('entries', 0)):,}", f"{int(stats.get('pending', 0)):,}",
                      self._bytes(stats.get("bytes", 0)), "FTS" if stats.get("fts") else "Basic",
                      str(stats.get("last_scanned") or "—")[:19], str(stats.get("snapshots", 0))]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, profile["id"])
                self.table.setItem(row, column, item)

    def _selected_id(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def _optimize(self):
        profile_id = self._selected_id()
        if profile_id:
            self.optimize_requested.emit(profile_id)

    def _clear(self):
        profile_id = self._selected_id()
        if profile_id:
            self.clear_requested.emit(profile_id)

    @staticmethod
    def _open_data():
        try:
            os.startfile(data_dir())
        except Exception:
            pass


class ChangesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 28)
        title = QLabel("Directory changes")
        title.setObjectName("heroTitle")
        layout.addWidget(title)
        controls = QHBoxLayout()
        self.profile = QComboBox()
        self.snapshot = QComboBox()
        self.profile.currentIndexChanged.connect(self.refresh_snapshots)
        self.snapshot.currentIndexChanged.connect(self.refresh_changes)
        export = QPushButton("Export CSV…")
        export.clicked.connect(self._export_csv)
        controls.addWidget(QLabel("Directory:"))
        controls.addWidget(self.profile)
        controls.addWidget(QLabel("Snapshot:"))
        controls.addWidget(self.snapshot, 1)
        controls.addWidget(export)
        layout.addLayout(controls)
        self.summary = QLabel()
        self.summary.setObjectName("mutedLabel")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Change", "Name", "Kind", "Previous size", "New size"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self._changes = []
        self.refresh_profiles()

    def refresh_profiles(self):
        selected = self.profile.currentData()
        self.profile.blockSignals(True)
        self.profile.clear()
        for profile in load_profiles():
            self.profile.addItem(profile["name"], profile["id"])
        index = self.profile.findData(selected)
        self.profile.setCurrentIndex(index if index >= 0 else 0)
        self.profile.blockSignals(False)
        self.refresh_snapshots()

    def refresh_snapshots(self, *_args):
        profile_id = self.profile.currentData()
        self.snapshot.blockSignals(True)
        self.snapshot.clear()
        for run in cache.list_snapshots(profile_id, 100) if profile_id else []:
            label = (f"{str(run.get('finished_at') or run.get('started_at'))[:19]} · {run.get('mode')} · "
                     f"+{run.get('new_count', 0)} / −{run.get('removed_count', 0)} / ~{run.get('changed_count', 0)}")
            self.snapshot.addItem(label, run.get("id"))
        self.snapshot.blockSignals(False)
        self.refresh_changes()

    def refresh_changes(self, *_args):
        profile_id, run_id = self.profile.currentData(), self.snapshot.currentData()
        self._changes = cache.snapshot_changes(profile_id, run_id) if profile_id and run_id else []
        self.table.setRowCount(len(self._changes))
        for row, change in enumerate(self._changes):
            values = [change.get("change_type", ""), change.get("name", ""),
                      "Folder" if change.get("is_dir") else "File",
                      change.get("old_size") or "—", change.get("new_size") or "—"]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.summary.setText(f"{len(self._changes):,} recorded changes" if run_id else "No completed snapshots yet")

    def _export_csv(self):
        if not self._changes:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export changes", "directory-changes.csv", "CSV files (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=["change_type", "url", "name", "is_dir", "old_size", "new_size"])
            writer.writeheader()
            writer.writerows(self._changes)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ODeR")
        self.setAcceptDrops(True)
        self.resize(1360, 820)
        self.setMinimumSize(1040, 680)
        self._apply_settings_style()
        self._crawl_status_lock = threading.Lock()
        self._crawl_status = {}
        self._crawl_stop_events = {}
        self._pages = {}
        self._tab_buttons = {}
        self._tab_closers = {}
        self._tab_rows = {}
        self._tab_names = {}
        self._current_key = None
        self._sidebar_collapsed = False
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._run_search)
        self._package_tasks = {}

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(190)
        sl = QVBoxLayout(self.sidebar)
        sl.setContentsMargins(9, 12, 9, 10)
        sl.setSpacing(5)

        header_row = QHBoxLayout()
        self.logo = QLabel("ODeR")
        self.logo.setObjectName("appLogo")
        header_row.addWidget(self.logo, 1)
        sl.addLayout(header_row)

        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("Search cached files…")
        self.global_search.returnPressed.connect(self._run_search_now)
        self.global_search.textChanged.connect(lambda _: self._search_timer.start())
        sl.addWidget(self.global_search)

        self.tab_section = QLabel("TABS")
        self.tab_section.setObjectName("sectionLabel")
        sl.addWidget(self.tab_section)

        self.tab_scroll = QScrollArea()
        self.tab_scroll.setWidgetResizable(True)
        self.tab_container = QWidget()
        self.tab_layout = QVBoxLayout(self.tab_container)
        self.tab_layout.setContentsMargins(0, 0, 0, 0)
        self.tab_layout.setSpacing(2)
        self.tab_layout.addStretch(1)
        self.tab_scroll.setWidget(self.tab_container)
        sl.addWidget(self.tab_scroll, 1)

        self.new_btn = QPushButton("New tab")
        self.new_btn.setObjectName("sidebarButton")
        self.new_btn.clicked.connect(self._new_tab)
        sl.addWidget(self.new_btn)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setObjectName("divider")
        sl.addWidget(divider)

        self.downloads_btn = QPushButton("Downloads")
        self.downloads_btn.setObjectName("sidebarButton")
        self.downloads_btn.clicked.connect(lambda: self._show_special("downloads"))
        self.activity_btn = QPushButton("Activity")
        self.activity_btn.setObjectName("sidebarButton")
        self.activity_btn.clicked.connect(lambda: self._show_special("activity"))
        self.favorites_btn = QPushButton("Favorites")
        self.favorites_btn.setObjectName("sidebarButton")
        self.favorites_btn.clicked.connect(lambda: self._show_special("favorites"))
        self.changes_btn = QPushButton("Changes")
        self.changes_btn.setObjectName("sidebarButton")
        self.changes_btn.clicked.connect(lambda: self._show_special("changes"))
        self.storage_btn = QPushButton("Storage")
        self.storage_btn.setObjectName("sidebarButton")
        self.storage_btn.clicked.connect(lambda: self._show_special("storage"))
        self.logs_btn = QPushButton("Logs")
        self.logs_btn.setObjectName("sidebarButton")
        self.logs_btn.clicked.connect(lambda: self._show_special("logs"))
        sl.addWidget(self.downloads_btn)
        sl.addWidget(self.activity_btn)
        sl.addWidget(self.favorites_btn)
        sl.addWidget(self.changes_btn)
        sl.addWidget(self.storage_btn)
        sl.addWidget(self.logs_btn)
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setObjectName("sidebarButton")
        self.settings_btn.clicked.connect(lambda: self._show_special("settings"))
        sl.addWidget(self.settings_btn)

        self.add_btn = QPushButton("Add site")
        self.add_btn.setObjectName("sidebarAccent")
        self.add_btn.clicked.connect(self._add_profile)
        sl.addWidget(self.add_btn)
        root_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.downloads = None
        self.settings = None
        self.search_page = None
        self.activity = None
        self.logs = None
        self.favorites = None
        self.storage = None
        self.changes = None

        try:
            startup_settings=load_settings()
            if startup_settings.get("startup_initialize_caches", True):
                for profile in load_profiles():
                    try:
                        cache.migrate_json_if_needed(profile["id"], profile.get("base_url", ""))
                        cache.initialize(profile["id"], profile.get("base_url", ""))
                    except Exception as exc:
                        applog.log(f"startup cache check failed for {profile.get('name','site')}: {exc}")
        except Exception as exc:
            applog.log(f"startup cache initialization failed: {exc}")

        self.home = self._make_home_page()
        # Populate the home page from profiles that were already saved before
        # creating the first page. Previously HomePage started with an empty
        # placeholder and was only refreshed as a side effect of adding/editing
        # a site, making existing directories appear only after a new one was
        # added.
        self.home.refresh(load_profiles())
        self._add_page("home", "Home", "", self.home, closable=False)
        self._rebuild_tab_bar()
        self._select_key("home")

        # Shortcuts from the tier-1 usability pass.
        for sequence, callback in (("Ctrl+T", self._new_tab), ("Ctrl+W", self._close_current_tab),
                                   ("Ctrl+L", self._focus_global_search), ("Ctrl+F", self._focus_page_search),
                                   ("F5", self._refresh_current), ("Ctrl+Shift+F5", self._full_refresh_current),
                                   ("Alt+Left", self._go_back), ("Alt+Right", self._go_forward)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        downloader.start_background_worker(log=applog.log)
        applog.log("Application started")
        self.statusBar().showMessage("Ready · ODeR")
        if load_settings().get("resume_crawls_at_startup", False):
            QTimer.singleShot(800, self._resume_startup_crawls)

    def _apply_settings_style(self):
        settings=load_settings(); theme=settings.get("theme","dark")
        colors=THEME_PRESETS.get(theme, THEME_PRESETS["dark"]).copy()
        if theme=="custom":
            custom=settings.get("custom_theme") or {}
            colors=THEME_PRESETS["dark"].copy()
            for key in colors:
                val=_normalize_hex(custom.get(key))
                if val: colors[key]=val
        self.setStyleSheet(_render_theme_qss(colors))
        if hasattr(self,"home"):
            self.home.refresh(load_profiles())

    # ---------- tabs ----------

    def _make_home_page(self):
        page = HomePage()
        page.open_site_requested.connect(self._open_site_tab)
        page.export_site_requested.connect(self._export_profile)
        page.add_site_requested.connect(self._add_profile)
        page.import_directory_requested.connect(self._import_profile_package)
        page.open_downloads_requested.connect(lambda: self._show_special("downloads"))
        page.open_settings_requested.connect(lambda: self._show_special("settings"))
        return page

    def _make_search_page(self):
        page = SearchPage()
        page.open_result_requested.connect(self._open_search_result)
        page.favorite_added.connect(self._favorites_changed)
        page.refresh_profiles()
        return page

    def _add_page(self, key, label, icon, widget, closable=True):
        self._pages[key] = widget
        self._tab_names[key] = (label, icon, closable)
        self.stack.addWidget(widget)

    def _remove_page(self, key):
        if key == "home":
            return
        widget = self._pages.pop(key, None)
        self._tab_names.pop(key, None)
        self._tab_buttons.pop(key, None)
        self._tab_closers.pop(key, None)
        self._tab_rows.pop(key, None)

        # Special pages are intentionally lazy-created. Dropping the Python
        # reference when a tab closes prevents the periodic timer from
        # touching a QWidget that Qt has already destroyed.
        if key == "downloads":
            self.downloads = None
        elif key == "settings":
            self.settings = None
        elif key == "search":
            self.search_page = None
        elif key == "activity":
            self.activity = None
        elif key == "logs":
            self.logs = None
        elif key == "favorites":
            self.favorites = None
        elif key == "storage":
            self.storage = None
        elif key == "changes":
            self.changes = None

        if widget is not None:
            self.stack.removeWidget(widget)
            widget.deleteLater()
        if self._current_key == key:
            self._current_key = None
        self._rebuild_tab_bar()

    def _tab_context_menu(self, key, pos):
        if key not in self._tab_names:
            return
        menu = QMenu(self)
        if key.startswith("site:"):
            edit = menu.addAction("Edit site")
            export_site = menu.addAction("Export directory…")
            remove_site = menu.addAction("Remove site")
            menu.addSeparator()
        else:
            edit = export_site = remove_site = None
        close = menu.addAction("Close tab") if self._tab_names[key][2] else None
        chosen = menu.exec(pos)
        if chosen == edit:
            self._select_key(key)
            self._edit_profile()
        elif chosen == export_site:
            self._export_profile(key.split(":", 1)[1])
        elif chosen == remove_site:
            self._select_key(key)
            self._remove_profile()
        elif chosen == close:
            self._close_tab(key)

    def _tab_symbol(self, key):
        if key == "home": return "⌂"
        if key == "downloads": return "↓"
        if key == "activity": return "◷"
        if key == "logs": return "≡"
        if key == "settings": return "⚙"
        if key == "search": return "⌕"
        if key == "favorites": return "☆"
        if key == "storage": return "▤"
        if key == "changes": return "Δ"
        if key.startswith("site:"): return "▣"
        if key.startswith("newtab:"): return "+"
        return "•"

    def _make_tab_row(self, key):
        label, icon, closable = self._tab_names[key]
        row = QWidget()
        row.setObjectName("tabRow")
        row.setProperty("selected", False)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(3, 2, 3, 2)
        layout.setSpacing(3)

        button = QToolButton()
        button.setObjectName("tabButton")
        button.setText(label)
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        button.clicked.connect(lambda _=False, k=key: self._select_key(k))
        button.setContextMenuPolicy(Qt.CustomContextMenu)
        button.customContextMenuRequested.connect(lambda p, k=key, b=button: self._tab_context_menu(k, b.mapToGlobal(p)))
        button.setToolTip(label)
        self._tab_buttons[key] = button
        layout.addWidget(button, 1)
        if closable:
            close_button = QToolButton()
            close_button.setObjectName("tabCloseButton")
            close_button.setText("×")
            close_button.setCursor(Qt.PointingHandCursor)
            close_button.setToolTip(f"Close {label}")
            close_button.clicked.connect(lambda _=False, k=key: self._close_tab(k))
            self._tab_closers[key] = close_button
            layout.addWidget(close_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        self._tab_rows[key] = row
        return row

    def _rebuild_tab_bar(self):
        # Remove the old row widgets cleanly before rebuilding. Do not keep
        # references to their child QToolButtons after the row is detached.
        while self.tab_layout.count() > 1:
            item = self.tab_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        self._tab_buttons = {}
        self._tab_closers = {}
        self._tab_rows = {}
        for key in list(self._pages):
            self.tab_layout.insertWidget(self.tab_layout.count() - 1, self._make_tab_row(key))
        self._apply_sidebar_mode()
        if self._current_key in self._tab_buttons:
            self._mark_selected(self._current_key)

    def _mark_selected(self, key):
        for k, btn in self._tab_buttons.items():
            btn.setProperty("selected", k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()
            row = self._tab_rows.get(k)
            if row is not None:
                row.setProperty("selected", k == key)
                row.style().unpolish(row)
                row.style().polish(row)
                row.update()

    def _select_key(self, key):
        if key not in self._pages:
            return
        self._current_key = key
        self.stack.setCurrentWidget(self._pages[key])
        self._mark_selected(key)
        if key == "downloads" and self.downloads is not None:
            self.downloads.refresh()
        elif key == "activity" and self.activity is not None:
            self._refresh_activity()
        elif key == "search" and self.search_page is not None:
            self.search_page.search(self.global_search.text())
            self.global_search.setFocus()
        elif key == "logs" and self.logs is not None:
            self.logs.poll_new()
        elif key == "favorites" and self.favorites is not None:
            self.favorites.refresh()
        elif key == "storage" and self.storage is not None:
            self.storage.refresh()
        elif key == "changes" and self.changes is not None:
            self.changes.refresh_profiles()
        self.statusBar().showMessage(self._tab_names.get(key, ("", "", True))[0])

    def _close_tab(self, key):
        if key == "home" or key not in self._pages:
            return
        was_current = self._current_key == key
        keys = list(self._pages.keys())
        index = keys.index(key)
        fallback = None
        if index > 0:
            fallback = keys[index - 1]
        elif index + 1 < len(keys):
            fallback = keys[index + 1]
        self._remove_page(key)
        if was_current and fallback in self._pages:
            self._select_key(fallback)

    def _close_current_tab(self):
        if self._current_key and self._current_key != "home":
            self._close_tab(self._current_key)

    def _new_tab(self):
        # Each Ctrl+T / + New tab creates a real, independent tab instead of
        # merely switching back to Home. This is the key browser-like behavior.
        key = f"newtab:{uuid.uuid4().hex[:8]}"
        page = self._make_home_page()
        self._add_page(key, "New tab", "", page, closable=True)
        self._rebuild_tab_bar()
        self._select_key(key)

    def _show_special(self, key):
        if key == "downloads" and self.downloads is None:
            self.downloads = QueueWidget()
            self._add_page("downloads", "Downloads", "", self.downloads, closable=True)
            self._rebuild_tab_bar()
        elif key == "settings" and self.settings is None:
            self.settings = SettingsPage()
            self.settings.settings_changed.connect(self._apply_settings_style)
            self.settings.import_directory_requested.connect(self._import_profile_package)
            self.settings.compare_packages_requested.connect(self._compare_package_files)
            self.settings.open_storage_requested.connect(lambda: self._show_special("storage"))
            self.settings.open_changes_requested.connect(lambda: self._show_special("changes"))
            self._add_page("settings", "Settings", "", self.settings, closable=True)
            self._rebuild_tab_bar()
        elif key == "search" and self.search_page is None:
            self.search_page = self._make_search_page()
            self._add_page("search", "Search", "", self.search_page, closable=True)
            self._rebuild_tab_bar()
        elif key == "activity" and self.activity is None:
            self.activity = ActivityPage()
            self.activity.open_site_requested.connect(self._open_site_tab)
            self.activity.stop_requested.connect(self._stop_crawl_for)
            self.activity.resume_requested.connect(lambda pid: self._start_crawl_for(pid, "resume"))
            self._add_page("activity", "Activity", "", self.activity, closable=True)
            self._rebuild_tab_bar()
        elif key == "logs" and self.logs is None:
            self.logs = LogsPage()
            self._add_page("logs", "Logs", "", self.logs, closable=True)
            self._rebuild_tab_bar()
        elif key == "favorites" and self.favorites is None:
            self.favorites = FavoritesPage()
            self.favorites.open_folder_requested.connect(self._open_favorite_folder)
            self.favorites.open_search_requested.connect(self._open_saved_search)
            self._add_page("favorites", "Favorites", "", self.favorites, closable=True)
            self._rebuild_tab_bar()
        elif key == "storage" and self.storage is None:
            self.storage = StoragePage()
            self.storage.optimize_requested.connect(self._optimize_cache)
            self.storage.clear_requested.connect(self._clear_cache)
            self._add_page("storage", "Storage", "", self.storage, closable=True)
            self._rebuild_tab_bar()
        elif key == "changes" and self.changes is None:
            self.changes = ChangesPage()
            self._add_page("changes", "Changes", "", self.changes, closable=True)
            self._rebuild_tab_bar()
        self._select_key(key)

    def _open_site_tab(self, profile_id):
        profile = get_profile(profile_id)
        if not profile:
            return
        key = f"site:{profile_id}"
        if key not in self._pages:
            browser = BrowserWidget()
            browser.set_profile(profile)
            browser.navigate_requested.connect(lambda _unused=None, pid=profile_id: self._start_crawl_for(pid, "resume"))
            browser.update_folder_requested.connect(lambda url, pid=profile_id: self._start_folder_crawl_for(pid, url, False))
            browser.grow_level_requested.connect(lambda url, pid=profile_id: self._start_folder_crawl_for(pid, url, True))
            browser.full_update_requested.connect(lambda pid=profile_id: self._start_crawl_for(pid, "full"))
            browser.incremental_update_requested.connect(lambda pid=profile_id: self._start_crawl_for(pid, "incremental"))
            browser.resume_update_requested.connect(lambda pid=profile_id: self._start_crawl_for(pid, "resume"))
            browser.export_subtree_requested.connect(lambda url, pid=profile_id: self._export_profile(pid, url))
            browser.favorite_added.connect(self._favorites_changed)
            browser.open_downloads_requested.connect(lambda: self._show_special("downloads"))
            self._add_page(key, profile["name"], "", browser, closable=True)
            self._rebuild_tab_bar()
        self._select_key(key)
        self.statusBar().showMessage(f"Opened {profile['name']}")

    def _reload_tabs(self, select_key=None):
        self.home.refresh(load_profiles())
        for key, widget in list(self._pages.items()):
            if key.startswith("site:"):
                pid = key.split(":", 1)[1]
                profile = get_profile(pid)
                if not profile:
                    self._remove_page(key)
                else:
                    self._tab_names[key] = (profile["name"], "", True)
                    widget.set_profile(profile)
        self._rebuild_tab_bar()
        if select_key:
            self._select_key(select_key)

    # ---------- sidebar/search ----------

    def _toggle_sidebar(self):
        # The navigation rail is intentionally fixed so the content area never
        # shifts because of an accidental collapse/expand action.
        return None

    def _apply_sidebar_mode(self):
        self._sidebar_collapsed = False
        self.sidebar.setFixedWidth(190)
        self.logo.setText("ODeR")
        self.global_search.setVisible(True)
        self.tab_section.setVisible(True)
        self.new_btn.setVisible(True)
        self.downloads_btn.setVisible(True)
        self.activity_btn.setVisible(True)
        self.favorites_btn.setVisible(True)
        self.changes_btn.setVisible(True)
        self.storage_btn.setVisible(True)
        self.logs_btn.setVisible(True)
        self.settings_btn.setVisible(True)
        self.add_btn.setVisible(True)
        for button in (self.new_btn, self.downloads_btn, self.activity_btn, self.favorites_btn,
                       self.changes_btn, self.storage_btn, self.logs_btn, self.settings_btn):
            button.setObjectName("sidebarButton")
            button.setFixedHeight(30)
        self.add_btn.setObjectName("sidebarAccent")
        self.add_btn.setFixedHeight(30)
        self.new_btn.setText("New tab")
        self.downloads_btn.setText("Downloads")
        self.activity_btn.setText("Activity")
        self.favorites_btn.setText("Favorites")
        self.changes_btn.setText("Changes")
        self.storage_btn.setText("Storage")
        self.logs_btn.setText("Logs")
        self.settings_btn.setText("Settings")
        self.add_btn.setText("Add site")
        self.new_btn.setToolTip("New tab")
        self.downloads_btn.setToolTip("Downloads")
        self.activity_btn.setToolTip("Activity")
        self.favorites_btn.setToolTip("Favorites")
        self.changes_btn.setToolTip("Directory changes")
        self.storage_btn.setToolTip("Storage manager")
        self.logs_btn.setToolTip("Logs")
        self.settings_btn.setToolTip("Settings")
        self.add_btn.setToolTip("Add site")

        for key, button in self._tab_buttons.items():
            label, _icon, _closable = self._tab_names[key]
            button.setText(label)
            button.setToolTip(label)
            button.style().unpolish(button); button.style().polish(button); button.update()

    def _focus_global_search(self):
        self.global_search.setFocus()
        self.global_search.selectAll()

    def _focus_page_search(self):
        widget = self._pages.get(self._current_key)
        if isinstance(widget, BrowserWidget):
            widget.focus_search()
        else:
            self._focus_global_search()

    def _run_search_now(self):
        self._search_timer.stop()
        self._run_search()

    def _run_search(self):
        query = self.global_search.text().strip()
        if not query:
            return
        self._show_special("search")
        if self.search_page is not None:
            self.search_page.search(query)

    def _open_search_result(self, profile_id, url):
        self._open_site_tab(profile_id)
        browser = self._pages.get(f"site:{profile_id}")
        if isinstance(browser, BrowserWidget):
            browser.navigate_to_url(url)

    def _favorites_changed(self):
        if self.favorites is not None:
            self.favorites.refresh()

    def _open_favorite_folder(self, profile_id, url):
        self._open_site_tab(profile_id)
        browser = self._pages.get(f"site:{profile_id}")
        if isinstance(browser, BrowserWidget) and not browser.navigate_to_url(url):
            QMessageBox.information(self, "Folder not in cache", "This saved folder is no longer present in the cached index.")

    def _open_saved_search(self, saved):
        self.global_search.setText(saved.get("query", ""))
        self._show_special("search")
        if self.search_page is not None:
            self.search_page.apply_saved(saved)

    # ---------- .oder packages ----------

    def _start_package_task(self, label, operation, on_success, error_title="Package operation failed"):
        token = uuid.uuid4().hex
        progress = QProgressDialog(label, "", 0, 0, self)
        progress.setWindowTitle("ODeR")
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.show()

        thread = QThread(self)
        worker = PackageTask(token, operation)
        worker.moveToThread(thread)
        self._package_tasks[token] = {
            "thread": thread,
            "worker": worker,
            "progress": progress,
            "on_success": on_success,
            "error_title": error_title,
        }
        thread.started.connect(worker.run)
        worker.finished.connect(self._package_task_succeeded)
        worker.failed.connect(self._package_task_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(lambda t=token: self._finish_package_task(t))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    @Slot(str, object)
    def _package_task_succeeded(self, token, result):
        state = self._package_tasks.get(token)
        if not state:
            return
        state["progress"].close()
        try:
            state["on_success"](result)
        except Exception as exc:
            applog.log(f"package completion failed: {exc}")
            QMessageBox.warning(self, "Package operation failed", str(exc))

    @Slot(str, str)
    def _package_task_failed(self, token, message):
        state = self._package_tasks.get(token)
        if not state:
            return
        state["progress"].close()
        applog.log(f"package operation failed: {message}")
        QMessageBox.warning(self, state["error_title"], message)

    def _finish_package_task(self, token):
        self._package_tasks.pop(token, None)

    def _export_profile(self, profile_id, root_url=None):
        profile = get_profile(profile_id)
        if not profile:
            QMessageBox.warning(self, "Directory unavailable", "That directory no longer exists.")
            return
        available = cache.database_exists(profile_id) and cache.count_crawled_dirs(profile_id) > 0
        scoped = cache.subtree_counts(profile_id, root_url) if available and root_url else {}
        all_entries = cache.count_nodes(profile_id) if available else 0
        estimated_size = cache.database_size(profile_id) if available else 0
        if root_url and all_entries:
            estimated_size = int(estimated_size * scoped.get("entries", 0) / all_entries)
        stats = {
            "available": available,
            "entries": scoped.get("entries", cache.count_nodes(profile_id) if available else 0),
            "folders": scoped.get("folders", cache.count_dirs(profile_id) if available else 0),
            "files": scoped.get("files", cache.count_files(profile_id) if available else 0),
            "size": estimated_size,
        }
        dialog_profile = dict(profile)
        if root_url:
            node = cache.get_node(profile_id, root_url) or {}
            dialog_profile["name"] = f"{profile['name']} — {node.get('name') or 'folder'}"
            dialog_profile["base_url"] = root_url
        dialog = ExportDirectoryDialog(dialog_profile, stats, self)
        if not dialog.exec():
            return
        display_name = profile["name"]
        if root_url:
            node = cache.get_node(profile_id, root_url) or {}
            display_name += " - " + (node.get("name") or "folder")
        safe_name = "".join(ch for ch in display_name if ch not in '<>:"/\\|?*').strip() or "directory"
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or data_dir()
        suggested = os.path.join(documents, safe_name + ".oder")
        destination, _ = QFileDialog.getSaveFileName(
            self, "Export ODeR directory", suggested, "ODeR directory package (*.oder)"
        )
        if not destination:
            return
        if not destination.lower().endswith(".oder"):
            destination += ".oder"
        include_cache = dialog.include_cache()
        profile_snapshot = dict(profile)
        self._start_package_task(
            "Creating directory package…",
            lambda: export_directory(profile_snapshot, destination, include_cache, root_url=root_url),
            self._export_package_finished,
            "Export failed",
        )

    def _export_package_finished(self, info):
        applog.log(f"directory exported: {info.name} -> {info.path}")
        kind = "with its cached index" if info.has_cache else "as a definition"
        QMessageBox.information(self, "Export complete", f'"{info.name}" was exported {kind}.\n\n{info.path}')

    def _import_profile_package(self, path=None):
        if isinstance(path, bool):
            path = None
        if not path:
            documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or data_dir()
            path, _ = QFileDialog.getOpenFileName(
                self, "Import ODeR directory", documents, "ODeR directory package (*.oder)"
            )
        if not path:
            return
        self._start_package_task(
            "Validating directory package…",
            lambda: inspect_package(path),
            lambda info: self._confirm_package_import(path, info),
            "Import validation failed",
        )

    def _compare_package_files(self):
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or data_dir()
        left, _ = QFileDialog.getOpenFileName(self, "Choose older ODeR package", documents, "ODeR directory package (*.oder)")
        if not left:
            return
        right, _ = QFileDialog.getOpenFileName(self, "Choose newer ODeR package", os.path.dirname(left), "ODeR directory package (*.oder)")
        if not right:
            return
        self._start_package_task(
            "Comparing directory packages…", lambda: compare_packages(left, right),
            lambda result: PackageComparisonDialog(result, self).exec(), "Comparison failed",
        )

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if any(url.isLocalFile() and url.toLocalFile().lower().endswith(".oder") for url in urls):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls()
                 if url.isLocalFile() and url.toLocalFile().lower().endswith(".oder")]
        if paths:
            event.acceptProposedAction()
            self._import_profile_package(paths[0])
        else:
            super().dropEvent(event)

    def _confirm_package_import(self, path, info):
        conflicts = find_conflicts(info)
        dialog = ImportDirectoryDialog(info, conflicts, self)
        if not dialog.exec():
            return
        policy, target_id = dialog.selected_policy()
        if policy == "replace":
            with self._crawl_status_lock:
                running = self._crawl_status.get(target_id, {}).get("running")
            if running:
                QMessageBox.warning(
                    self, "Directory is updating",
                    "Stop this directory's active crawl before replacing it from a package.",
                )
                return
        self._start_package_task(
            "Importing directory package…",
            lambda: import_directory(path, conflict_policy=policy, replace_profile_id=target_id),
            self._import_package_finished,
            "Import failed",
        )

    def _import_package_finished(self, result):
        profile = result.profile
        select_key = f"site:{profile['id']}"
        self._reload_tabs(select_key=select_key if select_key in self._pages else None)
        self._open_site_tab(profile["id"])
        applog.log(f"directory imported: {profile['name']} ({profile['base_url']})")
        action = "replaced" if result.replaced else "imported"
        cache_text = (
            " The cached index is ready to browse." if result.cache_imported
            else " Update the directory when you want to build its local index."
        )
        QMessageBox.information(
            self, "Import complete", f'"{profile["name"]}" was {action}.{cache_text}'
        )

    # ---------- profiles ----------

    def _current_site_profile(self):
        if not self._current_key or not self._current_key.startswith("site:"):
            return None
        return get_profile(self._current_key.split(":", 1)[1])

    def _add_profile(self):
        dlg = ProfileDialog(self)
        if dlg.exec():
            data = dlg.result_data()
            if not data["base_url"]:
                QMessageBox.warning(self, "Missing URL", "Please enter a base URL.")
                return
            profile = create_profile(data["name"] or data["base_url"], data["base_url"])
            update_profile(profile["id"], settings=data["settings"])
            applog.log(f"Site added: {profile['name']} ({profile['base_url']})")
            self._reload_tabs()
            self._open_site_tab(profile["id"])

    def _edit_profile(self):
        profile = self._current_site_profile()
        if not profile:
            return
        dlg = ProfileDialog(self, profile=profile)
        if dlg.exec():
            data = dlg.result_data()
            update_profile(profile["id"], name=data["name"] or profile["name"],
                           base_url=data["base_url"], settings=data["settings"])
            applog.log(f"Site edited: {data['name'] or profile['name']} ({data['base_url']})")
            self._reload_tabs(select_key=f"site:{profile['id']}")

    def _remove_profile(self):
        profile = self._current_site_profile()
        if not profile:
            return
        confirm = QMessageBox.question(
            self, "Remove site",
            f'Remove "{profile["name"]}"? Its cached listing will be removed from the app, but downloaded files are kept.'
        )
        if confirm == QMessageBox.Yes:
            key = f"site:{profile['id']}"
            applog.log(f"Site removed: {profile['name']}")
            delete_profile(profile["id"], delete_files=False)
            self._remove_page(key)
            self.home.refresh(load_profiles())
            self._select_key("home")

    def _optimize_cache(self, profile_id):
        profile = get_profile(profile_id)
        if not profile:
            return
        self._start_package_task(
            f"Repairing and compacting {profile['name']}…",
            lambda: cache.optimize_database(profile_id),
            lambda result: self._storage_operation_finished(
                f"{profile['name']} is healthy and compacted. Integrity check: {result.get('integrity', 'unknown')}."
            ),
            "Storage repair failed",
        )

    def _storage_operation_finished(self, message):
        if self.storage is not None:
            self.storage.refresh()
        QMessageBox.information(self, "Storage manager", message)

    def _clear_cache(self, profile_id):
        profile = get_profile(profile_id)
        if not profile:
            return
        with self._crawl_status_lock:
            running = self._crawl_status.get(profile_id, {}).get("running")
        if running:
            QMessageBox.warning(self, "Directory is updating", "Stop its active update before clearing the cached index.")
            return
        answer = QMessageBox.question(
            self, "Clear cached index",
            f"Clear the offline index for “{profile['name']}”? Downloaded files and the directory definition are kept.",
        )
        if answer != QMessageBox.Yes:
            return
        cache.clear_database(profile_id, profile["base_url"])
        crawl_state.mark_completed(profile_id, 0)
        browser = self._pages.get(f"site:{profile_id}")
        if isinstance(browser, BrowserWidget):
            browser.refresh_cache()
        self.home.refresh(load_profiles())
        if self.storage is not None:
            self.storage.refresh()
        QMessageBox.information(self, "Cache cleared", "The cached index was cleared. Downloaded files were not changed.")

    # ---------- crawling ----------

    def _start_folder_crawl_for(self, profile_id, folder_url, grow=False):
        profile = get_profile(profile_id)
        if not profile or not folder_url:
            return
        with self._crawl_status_lock:
            if self._crawl_status.get(profile_id, {}).get("running"):
                self.statusBar().showMessage("This directory is already updating · Open Activity for details")
                return
            self._crawl_status[profile_id] = {"running": True, "crawled": 0, "current": folder_url,
                                              "error": None, "started_at": __import__("time").time(),
                                              "elapsed": 0.0, "folders_discovered": cache.count_dirs(profile_id),
                                              "files_discovered": cache.count_files(profile_id), "queued": 0,
                                              "rate": 0.0, "mode": "grow" if grow else "folder",
                                              "folder_url": folder_url}
            self._crawl_stop_events[profile_id] = threading.Event()

        def progress_cb(p):
            with self._crawl_status_lock:
                st = self._crawl_status.setdefault(profile_id, {})
                st.update(p)
                st["running"] = not p.get("done") and not p.get("error")
                st["last_update"] = __import__("time").time()

        def run():
            try:
                crawl_folder(profile, folder_url, progress_cb=progress_cb, log=applog.log,
                             stop_check=self._crawl_stop_events[profile_id].is_set,
                             grow_one_level=grow)
            finally:
                with self._crawl_status_lock:
                    self._crawl_status.setdefault(profile_id, {})["running"] = False
                self._crawl_stop_events.pop(profile_id, None)

        action = "Growing" if grow else "Updating"
        applog.log(f"{action} folder: {profile['name']} — {folder_url}")
        threading.Thread(target=run, daemon=True).start()
        self.statusBar().showMessage(f"{action} {folder_url}…")

    def _start_crawl_for(self, profile_id, mode="resume"):
        profile = get_profile(profile_id)
        if not profile:
            return
        mode = mode if mode in {"resume", "incremental", "full"} else "resume"
        if mode == "full" and load_settings().get("confirm_full_updates", True):
            answer = QMessageBox.question(
                self, "Rebuild entire site",
                f"Re-scan every cached folder in “{profile['name']}”? This can take a long time on large directories.",
            )
            if answer != QMessageBox.Yes:
                return
        with self._crawl_status_lock:
            if self._crawl_status.get(profile_id, {}).get("running"):
                self.statusBar().showMessage("This directory is already updating · Open Activity for details")
                return
            self._crawl_status[profile_id] = {"running": True, "crawled": 0, "current": None, "error": None,
                                              "started_at": __import__("time").time(), "elapsed": 0.0,
                                              "folders_discovered": 0, "files_discovered": 0, "queued": 0,
                                              "rate": 0.0, "mode": mode}
            self._crawl_stop_events[profile_id] = threading.Event()

        def progress_cb(p):
            with self._crawl_status_lock:
                st = self._crawl_status.setdefault(profile_id, {})
                st.update(p)
                st["running"] = not p.get("done") and not p.get("error")
                st["last_update"] = __import__("time").time()

        def run():
            try:
                crawl_profile(profile, progress_cb=progress_cb, log=applog.log,
                              stop_check=self._crawl_stop_events[profile_id].is_set, mode=mode)
            finally:
                with self._crawl_status_lock:
                    self._crawl_status.setdefault(profile_id, {})["running"] = False
                self._crawl_stop_events.pop(profile_id, None)

        applog.log(f"{mode.title()} crawl started: {profile['name']} ({profile['base_url']})")
        threading.Thread(target=run, daemon=True).start()
        self.statusBar().showMessage(f"Updating {profile['name']}…")

    def _resume_startup_crawls(self):
        for profile, _state in crawl_state.resumable(load_profiles()):
            self._start_crawl_for(profile["id"], "resume")

    def _stop_crawl_for(self, profile_id):
        event = self._crawl_stop_events.get(profile_id)
        if event:
            event.set()
            profile = get_profile(profile_id)
            applog.log(f"Crawl stop requested: {profile['name'] if profile else profile_id}")
            self.statusBar().showMessage("Stopping crawl after the current request…")

    def _refresh_activity(self):
        if self.activity is None:
            return
        profiles = load_profiles()
        with self._crawl_status_lock:
            statuses = {k: dict(v) for k, v in self._crawl_status.items()}
        self.activity.refresh(profiles, statuses)

    # ---------- periodic refresh ----------

    def _tick(self):
        if self.downloads is not None:
            self.downloads.refresh()
        if self.logs is not None:
            self.logs.poll_new()
        with self._crawl_status_lock:
            statuses = {k: dict(v) for k, v in self._crawl_status.items()}
        if self.activity is not None:
            self.activity.refresh(load_profiles(), statuses)
        for key, widget in list(self._pages.items()):
            if not key.startswith("site:"):
                continue
            pid = key.split(":", 1)[1]
            st = statuses.get(pid, {})
            if (st.get("done") or st.get("stopped") or st.get("error")) and not st.get("_consumed"):
                self._crawl_status[pid]["_consumed"] = True
                widget.refresh_cache()
                self.home.refresh(load_profiles())
                profile = widget.profile
                if st.get("error"):
                    self.statusBar().showMessage(f"Crawl failed for {profile['name']}: {st['error']}")
                elif st.get("stopped"):
                    self.statusBar().showMessage(f"Crawl stopped for {profile['name']} after {st.get('crawled', 0):,} folders")
                else:
                    self.statusBar().showMessage(f"Cache update complete for {profile['name']}")
                changes = st.get("changes") or {}
                changed_total = sum(int(changes.get(key, 0)) for key in ("new_count", "removed_count", "changed_count"))
                if changed_total and load_settings().get("notify_directory_changes", True):
                    tray = getattr(self, "tray_icon", None)
                    if tray is not None:
                        tray.showMessage(
                            "Directory changed",
                            f"{profile['name']}: {changes.get('new_count', 0)} new, "
                            f"{changes.get('removed_count', 0)} removed, {changes.get('changed_count', 0)} changed.",
                            msecs=6000,
                        )
                if self.changes is not None:
                    self.changes.refresh_profiles()
                if self.storage is not None:
                    self.storage.refresh()
            elif st.get("running"):
                self.statusBar().showMessage(f"Updating {widget.profile['name']}… {st.get('crawled', 0):,} folders · {st.get('rate', 0):.1f}/s · {st.get('workers', 1)} workers · {st.get('queued', 0):,} queued")

    def _refresh_current(self):
        widget = self._pages.get(self._current_key)
        if isinstance(widget, BrowserWidget):
            if widget.profile and widget.current_url:
                self._start_folder_crawl_for(widget.profile["id"], widget.current_url, False)
        elif self._current_key == "downloads" and self.downloads is not None:
            self.downloads.refresh()
        elif self._current_key == "search" and self.search_page is not None:
            self._run_search_now()
        else:
            self.home.refresh(load_profiles())

    def _full_refresh_current(self):
        widget = self._pages.get(self._current_key)
        if isinstance(widget, BrowserWidget) and widget.profile:
            self._start_crawl_for(widget.profile["id"], "full")

    def _go_back(self):
        widget = self._pages.get(self._current_key)
        if isinstance(widget, BrowserWidget):
            widget.go_back()

    def _go_forward(self):
        widget = self._pages.get(self._current_key)
        if isinstance(widget, BrowserWidget):
            widget.go_forward()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        tray = getattr(self, "tray_icon", None)
        if tray is not None:
            tray.showMessage(
                "ODeR",
                "Still running in the background. Right-click the tray icon to quit.",
                msecs=2500,
            )
