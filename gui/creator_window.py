"""Power-user authoring interface for ODeR Library projects."""
from __future__ import annotations

from copy import deepcopy
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
    QStatusBar, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.odrlib import (
    OdrLibError, build_library, import_folder_selection, load_project, new_artifact,
    new_collection, new_item, new_project, normalize_project, save_project,
    scan_folder, validate_project,
)
from core.settings import load_settings
from core.version import CREATOR_NAME, CREATOR_VERSION
from gui.main_window import THEME_PRESETS, _render_theme_qss
from gui.package_dialogs import format_bytes, format_number


PLATFORMS = ("Any", "Windows", "Linux", "macOS", "Android", "Web", "Other")
ARCHITECTURES = ("Any", "x86-64", "x86", "ARM64", "ARM", "Universal", "Other")


def _csv_values(text):
    values = []
    seen = set()
    for raw in str(text or "").split(","):
        value = raw.strip()
        if value and value.casefold() not in seen:
            values.append(value)
            seen.add(value.casefold())
    return values


def _line_values(text):
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _set_combo(combo, value):
    index = combo.findText(str(value or ""), Qt.MatchFixedString)
    if index < 0:
        combo.addItem(str(value or "Other"))
        index = combo.count() - 1
    combo.setCurrentIndex(index)


class PathPicker(QWidget):
    def __init__(self, caption, file_filter, parent=None):
        super().__init__(parent)
        self.caption = caption
        self.file_filter = file_filter
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Optional local file")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.edit.clear)
        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)
        layout.addWidget(clear)

    def _browse(self):
        path, _selected = QFileDialog.getOpenFileName(self, self.caption, self.edit.text(), self.file_filter)
        if path:
            self.edit.setText(path)

    def text(self):
        return self.edit.text().strip()

    def setText(self, value):
        self.edit.setText(str(value or ""))


class NewFileDialog(QDialog):
    """Create one user-facing file and choose its folder and sources together."""

    def __init__(self, folders=(), default_folder_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add file")
        self.resize(640, 610)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        title = QLabel("Add a file")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        hint = QLabel("Choose its folder now, then add a bundled file, online mirrors, or both. ODeR never runs files automatically.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        self.name = QLineEdit()
        self.folder = QComboBox()
        self.folder.addItem("No folder", None)
        for folder in folders:
            self.folder.addItem(folder.get("name") or "Untitled folder", folder.get("id"))
        folder_index = self.folder.findData(default_folder_id)
        self.folder.setCurrentIndex(max(0, folder_index))
        self.filename = QLineEdit()
        self.filename.setPlaceholderText("Displayed download filename")
        self.embedded = PathPicker("Choose a local source file", "All files (*)")
        self.embedded.edit.textChanged.connect(self._embedded_changed)
        self.bundle = QCheckBox("Bundle this file inside the .odrlib")
        self.bundle.setChecked(False)
        self.torrent = QCheckBox("Include this file in the generated T1 torrent")
        self.torrent.setChecked(True)
        self.urls = QPlainTextEdit()
        self.urls.setPlaceholderText("One HTTPS URL per line\nhttps://example.org/download/file.zip")
        self.urls.setFixedHeight(90)
        self.media_type = QLineEdit()
        self.media_type.setPlaceholderText("Automatic from filename when empty")
        self.platform = QComboBox()
        self.platform.addItems(PLATFORMS)
        self.architecture = QComboBox()
        self.architecture.addItems(ARCHITECTURES)
        self.size = QLineEdit()
        self.size.setPlaceholderText("Optional for online-only files")
        self.checksum = QLineEdit()
        self.checksum.setPlaceholderText("Optional SHA-256 for online-only files")
        form.addRow("Name", self.name)
        form.addRow("Folder", self.folder)
        form.addRow("Filename", self.filename)
        form.addRow("Local source", self.embedded)
        form.addRow("", self.bundle)
        form.addRow("", self.torrent)
        form.addRow("HTTPS mirrors", self.urls)
        form.addRow("Media type", self.media_type)
        form.addRow("Platform", self.platform)
        form.addRow("Architecture", self.architecture)
        form.addRow("Expected size", self.size)
        form.addRow("Expected SHA-256", self.checksum)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _embedded_changed(self, path):
        basename = os.path.basename(str(path or "").strip())
        if not basename:
            return
        if not self.filename.text().strip():
            self.filename.setText(basename)
        if not self.name.text().strip():
            self.name.setText(os.path.splitext(basename)[0])

    def _accept_checked(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "File name needed", "Give this file a display name.")
            return
        if not self.embedded.text() and not _line_values(self.urls.toPlainText()):
            QMessageBox.warning(self, "Source needed", "Choose a local file or enter at least one HTTPS source.")
            return
        if (self.bundle.isChecked() or self.torrent.isChecked()) and not self.embedded.text():
            QMessageBox.warning(self, "Local file needed", "Choose a local file for bundling or torrent sharing.")
            return
        checksum = self.checksum.text().strip().casefold()
        if checksum and (len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum)):
            QMessageBox.warning(self, "Invalid checksum", "SHA-256 must contain exactly 64 hexadecimal characters.")
            return
        if self.size.text().strip():
            try:
                if int(self.size.text()) < 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Invalid size", "Expected size must be a non-negative number of bytes.")
                return
        self.accept()

    def result_data(self):
        item = new_item(title=self.name.text().strip())
        item["platform"] = self.platform.currentText()
        item["architecture"] = self.architecture.currentText()
        artifact = new_artifact(name=self.name.text().strip())
        artifact.update({
            "name": self.name.text().strip(),
            "filename": self.filename.text().strip(),
            "media_type": self.media_type.text().strip(),
            "platform": self.platform.currentText(),
            "architecture": self.architecture.currentText(),
            "size": int(self.size.text()) if self.size.text().strip() else None,
            "sha256": self.checksum.text().strip().casefold(),
            "sources": [],
        })
        if self.embedded.text() and self.bundle.isChecked():
            artifact["sources"].append({"type": "embedded", "source_path": self.embedded.text()})
        if self.embedded.text() and self.torrent.isChecked():
            artifact["sources"].append({
                "type": "torrent", "source_path": self.embedded.text(),
                "relative_path": os.path.basename(self.embedded.text()),
            })
        artifact["sources"].extend({"type": "https", "url": url} for url in _line_values(self.urls.toPlainText()))
        item["artifacts"] = [artifact]
        return item, self.folder.currentData()


class FolderImportDialog(QDialog):
    """Let curators choose catalog, bundle, and torrent inclusion in one pass."""

    def __init__(self, folder, records, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.records = [dict(record) for record in records]
        self.setWindowTitle("Import folder into ODeR Creator")
        self.resize(900, 650)
        root = QVBoxLayout(self)
        title = QLabel("Choose what the library will publish")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        hint = QLabel(
            "Checked files become catalog entries. Torrent is selected by default; bundling is opt-in "
            "because it makes the .odrlib itself larger. Folder structure is preserved."
        )
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)
        path = QLabel(folder)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(path)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(("Include file", "Size", "Bundle", "Torrent"))
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        for index, record in enumerate(self.records):
            item = QTreeWidgetItem([
                record["relative_path"], format_bytes(record["size"]), "", ""
            ])
            item.setData(0, Qt.UserRole, index)
            item.setCheckState(0, Qt.Checked if record.get("include", True) else Qt.Unchecked)
            item.setCheckState(2, Qt.Checked if record.get("bundle", False) else Qt.Unchecked)
            item.setCheckState(3, Qt.Checked if record.get("torrent", True) else Qt.Unchecked)
            self.tree.addTopLevelItem(item)
        self.tree.setColumnWidth(0, 560)
        self.tree.setColumnWidth(1, 100)
        root.addWidget(self.tree, 1)
        choices = QHBoxLayout()
        all_button = QPushButton("Select all")
        none_button = QPushButton("Select none")
        bundle_button = QPushButton("Bundle selected")
        torrent_button = QPushButton("Torrent selected")
        all_button.clicked.connect(lambda: self._set_column(0, Qt.Checked))
        none_button.clicked.connect(lambda: self._set_column(0, Qt.Unchecked))
        bundle_button.clicked.connect(lambda: self._copy_selected_to(2))
        torrent_button.clicked.connect(lambda: self._copy_selected_to(3))
        choices.addWidget(all_button)
        choices.addWidget(none_button)
        choices.addStretch(1)
        choices.addWidget(bundle_button)
        choices.addWidget(torrent_button)
        root.addLayout(choices)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Add files")
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _set_column(self, column, state):
        for index in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(index).setCheckState(column, state)

    def _copy_selected_to(self, column):
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            item.setCheckState(column, item.checkState(0))

    def _accept_checked(self):
        selected = 0
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.checkState(0) == Qt.Checked:
                selected += 1
                if item.checkState(2) != Qt.Checked and item.checkState(3) != Qt.Checked:
                    QMessageBox.warning(
                        self, "Choose a source",
                        f"{item.text(0)} is selected but is neither bundled nor in the torrent.",
                    )
                    return
        if not selected:
            QMessageBox.information(self, "Nothing selected", "Select at least one file to add.")
            return
        self.accept()

    def selections(self):
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            record = self.records[item.data(0, Qt.UserRole)]
            record["include"] = item.checkState(0) == Qt.Checked
            record["bundle"] = item.checkState(2) == Qt.Checked
            record["torrent"] = item.checkState(3) == Qt.Checked
        return self.records


class CreatorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = new_project()
        self.project_path = None
        self.dirty = False
        self._loading = False
        self._current_node = ("library", None)
        self._loaded_folder_id = None
        self._last_build = None
        self.setAcceptDrops(True)
        self.setMinimumSize(1050, 680)
        self.resize(1380, 850)
        self._build_actions()
        self._build_ui()
        self._apply_theme()
        self._rebuild_tree(("library", None))
        self._update_preview()
        self._update_title()

    def _apply_theme(self):
        settings = load_settings()
        theme = settings.get("theme", "dark")
        colors = THEME_PRESETS.get(theme, THEME_PRESETS["dark"]).copy()
        if theme == "custom":
            colors = THEME_PRESETS["dark"].copy()
            colors.update(settings.get("custom_theme") or {})
        self.setStyleSheet(_render_theme_qss(colors))

    def _build_actions(self):
        self.new_action = QAction("New project", self, shortcut=QKeySequence.New, triggered=self.new_document)
        self.open_action = QAction("Open project…", self, shortcut=QKeySequence.Open, triggered=self.open_document)
        self.save_action = QAction("Save", self, shortcut=QKeySequence.Save, triggered=self.save_document)
        self.save_as_action = QAction("Save as…", self, shortcut=QKeySequence.SaveAs, triggered=self.save_document_as)
        self.import_folder_action = QAction("Import folder…", self, triggered=self.import_local_folder)
        self.validate_action = QAction("Validate project", self, shortcut="F6", triggered=self.validate_current_project)
        self.build_action = QAction("Build .odrlib…", self, shortcut="Ctrl+B", triggered=self.build_package)
        self.exit_action = QAction("Exit", self, triggered=self.close)
        self.add_file_action = QAction("Add file…", self, shortcut="Ctrl+I", triggered=self.add_file)
        self.add_folder_action = QAction("Add folder", self, triggered=self.add_folder)
        self.delete_action = QAction("Delete selected", self, shortcut=QKeySequence.Delete, triggered=self.delete_selected)

        file_menu = self.menuBar().addMenu("File")
        file_menu.addActions((self.new_action, self.open_action, self.save_action, self.save_as_action))
        file_menu.addSeparator()
        file_menu.addAction(self.import_folder_action)
        file_menu.addSeparator()
        file_menu.addActions((self.validate_action, self.build_action))
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)
        catalog_menu = self.menuBar().addMenu("Library")
        catalog_menu.addActions((self.add_file_action, self.add_folder_action, self.delete_action))

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

        navigation = QFrame()
        navigation.setObjectName("sidebar")
        navigation.setMinimumWidth(220)
        navigation.setMaximumWidth(340)
        nav_layout = QVBoxLayout(navigation)
        nav_layout.setContentsMargins(10, 12, 10, 10)
        logo = QLabel("ODeR Creator")
        logo.setObjectName("appLogo")
        nav_layout.addWidget(logo)
        version = QLabel(f"Library authoring · {CREATOR_VERSION}")
        version.setObjectName("mutedLabel")
        nav_layout.addWidget(version)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.currentItemChanged.connect(self._tree_changed)
        nav_layout.addWidget(self.tree, 1)
        splitter.addWidget(navigation)

        self.editors = QStackedWidget()
        self.library_editor = self._build_library_editor()
        self.item_editor = self._build_item_editor()
        self.collection_editor = self._build_collection_editor()
        self.editors.addWidget(self.library_editor)
        self.editors.addWidget(self.item_editor)
        self.editors.addWidget(self.collection_editor)
        splitter.addWidget(self.editors)

        inspector = QFrame()
        inspector.setObjectName("sidebar")
        inspector.setMinimumWidth(280)
        inspector.setMaximumWidth(390)
        inspect_layout = QVBoxLayout(inspector)
        inspect_layout.setContentsMargins(14, 14, 14, 12)
        heading = QLabel("Library preview")
        heading.setObjectName("pageTitle")
        inspect_layout.addWidget(heading)
        self.preview_artwork = QLabel("No artwork")
        self.preview_artwork.setObjectName("libraryArtworkPreview")
        self.preview_artwork.setFixedHeight(150)
        self.preview_artwork.setAlignment(Qt.AlignCenter)
        inspect_layout.addWidget(self.preview_artwork)
        self.preview_name = QLabel()
        self.preview_name.setObjectName("cardTitle")
        self.preview_name.setWordWrap(True)
        inspect_layout.addWidget(self.preview_name)
        self.preview_meta = QLabel()
        self.preview_meta.setObjectName("mutedLabel")
        self.preview_meta.setWordWrap(True)
        inspect_layout.addWidget(self.preview_meta)
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.HLine)
        inspect_layout.addWidget(divider)
        validation_heading = QLabel("Validation")
        validation_heading.setObjectName("sectionLabel")
        inspect_layout.addWidget(validation_heading)
        self.validation_list = QListWidget()
        self.validation_list.setWordWrap(True)
        self.validation_list.setSelectionMode(QAbstractItemView.NoSelection)
        inspect_layout.addWidget(self.validation_list, 1)
        validate_button = QPushButton("Validate project")
        validate_button.clicked.connect(self.validate_current_project)
        build_button = QPushButton("Build .odrlib")
        build_button.setObjectName("accentButton")
        build_button.clicked.connect(self.build_package)
        inspect_layout.addWidget(validate_button)
        inspect_layout.addWidget(build_button)
        splitter.addWidget(inspector)
        splitter.setSizes([260, 800, 320])

        status = QStatusBar()
        self.setStatusBar(status)
        self.statusBar().showMessage("Ready")

    def _scroll_form(self, title_text, subtitle_text):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        title = QLabel(title_text)
        title.setObjectName("heroTitle")
        layout.addWidget(title)
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("mutedLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        return page, layout

    def _card_form(self, parent_layout, title):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(10)
        layout.addLayout(form)
        parent_layout.addWidget(card)
        return form

    def _build_library_editor(self):
        page, layout = self._scroll_form(
            "Library", "Describe the library, its curator, and how future revisions are published."
        )
        form = self._card_form(layout, "Identity")
        self.library_name = QLineEdit()
        self.library_version = QLineEdit()
        self.library_revision = QSpinBox()
        self.library_revision.setRange(1, 2_147_483_647)
        self.library_creator = QLineEdit()
        self.library_category = QLineEdit()
        self.library_summary = QLineEdit()
        self.library_summary.setMaxLength(1000)
        self.library_description = QPlainTextEdit()
        self.library_description.setFixedHeight(120)
        self.library_tags = QLineEdit()
        self.library_tags.setPlaceholderText("Comma-separated")
        self.library_languages = QLineEdit()
        self.library_languages.setPlaceholderText("Comma-separated")
        self.library_links = QPlainTextEdit()
        self.library_links.setPlaceholderText("One HTTPS link per line")
        self.library_links.setFixedHeight(72)
        self.library_artwork = PathPicker("Choose library artwork", "Images (*.png *.jpg *.jpeg *.webp)")
        self.library_name.textChanged.connect(self._update_preview)
        self.library_version.textChanged.connect(self._update_preview)
        self.library_revision.valueChanged.connect(self._update_preview)
        self.library_artwork.edit.textChanged.connect(self._update_preview)
        form.addRow("Name", self.library_name)
        form.addRow("Version", self.library_version)
        form.addRow("Revision", self.library_revision)
        form.addRow("Creator / curator", self.library_creator)
        form.addRow("Category", self.library_category)
        form.addRow("Summary", self.library_summary)
        form.addRow("Description", self.library_description)
        form.addRow("Tags", self.library_tags)
        form.addRow("Languages", self.library_languages)
        form.addRow("Links", self.library_links)
        form.addRow("Artwork", self.library_artwork)

        rights = self._card_form(layout, "Rights and redistribution")
        self.library_license_name = QLineEdit()
        self.library_license_url = QLineEdit()
        self.library_license_url.setPlaceholderText("Optional HTTPS license page")
        rights.addRow("Default license", self.library_license_name)
        rights.addRow("License URL", self.library_license_url)

        publishing = self._card_form(layout, "Publishing and updates")
        self.feed_url = QLineEdit()
        self.feed_url.setPlaceholderText("https://example.org/library.odrlib-feed.json")
        self.update_channel = QComboBox()
        self.update_channel.setEditable(True)
        self.update_channel.addItems(("stable", "preview", "archive"))
        self.package_url = QLineEdit()
        self.package_url.setPlaceholderText("Public HTTPS URL of the exported .odrlib")
        self.release_notes = QPlainTextEdit()
        self.release_notes.setPlaceholderText("Shown when this revision is offered as an update")
        self.release_notes.setFixedHeight(90)
        publishing.addRow("Update feed URL", self.feed_url)
        publishing.addRow("Channel", self.update_channel)
        publishing.addRow("Package URL", self.package_url)
        publishing.addRow("Release notes", self.release_notes)

        torrent = self._card_form(layout, "T1 torrent sharing")
        self.torrent_root = QLineEdit()
        self.torrent_root.setReadOnly(True)
        # The standard picker selects files, so the recursive importer normally
        # fills this field. A dedicated folder button remains available here.
        self.torrent_root_button = QPushButton("Choose source folder…")
        self.torrent_root_button.clicked.connect(self._choose_torrent_root)
        self.torrent_trackers = QPlainTextEdit()
        self.torrent_trackers.setPlaceholderText("One HTTP, HTTPS, or UDP tracker per line")
        self.torrent_trackers.setFixedHeight(74)
        self.torrent_web_seeds = QPlainTextEdit()
        self.torrent_web_seeds.setPlaceholderText("Optional HTTP(S) web seed base URLs")
        self.torrent_web_seeds.setFixedHeight(64)
        self.torrent_private = QCheckBox("Private torrent (tracker-controlled peer discovery)")
        self.torrent_piece_size = QComboBox()
        for label, size in (("Automatic", 0), ("256 KiB", 256 * 1024), ("512 KiB", 512 * 1024),
                            ("1 MiB", 1024 * 1024), ("2 MiB", 2 * 1024 * 1024),
                            ("4 MiB", 4 * 1024 * 1024)):
            self.torrent_piece_size.addItem(label, size)
        self.torrent_comment = QLineEdit()
        self.torrent_comment.setPlaceholderText("Optional torrent comment")
        torrent.addRow("Source folder", self.torrent_root_button)
        torrent.addRow("Current folder", self.torrent_root)
        torrent.addRow("Trackers", self.torrent_trackers)
        torrent.addRow("Web seeds", self.torrent_web_seeds)
        torrent.addRow("", self.torrent_private)
        torrent.addRow("Piece size", self.torrent_piece_size)
        torrent.addRow("Comment", self.torrent_comment)
        layout.addStretch(1)
        return page

    def _choose_torrent_root(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the T1 source folder", self.torrent_root.text()
        )
        if folder:
            self.torrent_root.setText(folder)

    def _build_item_editor(self):
        page, layout = self._scroll_form(
            "File", "Describe a file, choose its folder, and provide a bundled copy, online mirrors, or both."
        )
        form = self._card_form(layout, "File details")
        self.item_title = QLineEdit()
        self.item_folder = QComboBox()
        self.item_version = QLineEdit()
        self.item_creator = QLineEdit()
        self.item_category = QLineEdit()
        self.item_summary = QLineEdit()
        self.item_description = QPlainTextEdit()
        self.item_description.setFixedHeight(110)
        self.item_tags = QLineEdit()
        self.item_platform = QComboBox()
        self.item_platform.addItems(PLATFORMS)
        self.item_architecture = QComboBox()
        self.item_architecture.addItems(ARCHITECTURES)
        self.item_links = QPlainTextEdit()
        self.item_links.setPlaceholderText("One HTTPS link per line")
        self.item_links.setFixedHeight(70)
        self.item_artwork = PathPicker("Choose item artwork", "Images (*.png *.jpg *.jpeg *.webp)")
        self.item_license_name = QLineEdit()
        self.item_license_url = QLineEdit()
        form.addRow("Name", self.item_title)
        form.addRow("Folder", self.item_folder)
        form.addRow("Version", self.item_version)
        form.addRow("Creator / publisher", self.item_creator)
        form.addRow("Category", self.item_category)
        form.addRow("Summary", self.item_summary)
        form.addRow("Description", self.item_description)
        form.addRow("Tags", self.item_tags)
        form.addRow("Platform", self.item_platform)
        form.addRow("Architecture", self.item_architecture)
        form.addRow("Links", self.item_links)
        form.addRow("Artwork", self.item_artwork)
        form.addRow("License", self.item_license_name)
        form.addRow("License URL", self.item_license_url)

        source_form = self._card_form(layout, "Download source")
        self.file_filename = QLineEdit()
        self.file_filename.setPlaceholderText("Displayed download filename")
        self.file_embedded = PathPicker("Choose a local source file", "All files (*)")
        self.file_bundle = QCheckBox("Bundle this file inside the .odrlib")
        self.file_torrent = QCheckBox("Include this file in the generated T1 torrent")
        self.file_urls = QPlainTextEdit()
        self.file_urls.setPlaceholderText("One HTTPS URL per line\nhttps://example.org/download/file.zip")
        self.file_urls.setFixedHeight(90)
        self.file_media_type = QLineEdit()
        self.file_media_type.setPlaceholderText("Automatic from filename when empty")
        self.file_size = QLineEdit()
        self.file_size.setPlaceholderText("Optional for online-only files")
        self.file_checksum = QLineEdit()
        self.file_checksum.setPlaceholderText("Optional SHA-256 for online-only files")
        self.file_variant_note = QLabel()
        self.file_variant_note.setObjectName("mutedLabel")
        self.file_variant_note.setWordWrap(True)
        self.file_variant_note.hide()
        source_form.addRow("Filename", self.file_filename)
        source_form.addRow("Local source", self.file_embedded)
        source_form.addRow("", self.file_bundle)
        source_form.addRow("", self.file_torrent)
        source_form.addRow("HTTPS mirrors", self.file_urls)
        source_form.addRow("Media type", self.file_media_type)
        source_form.addRow("Expected size", self.file_size)
        source_form.addRow("Expected SHA-256", self.file_checksum)
        source_form.addRow("", self.file_variant_note)
        layout.addStretch(1)
        return page

    def _build_collection_editor(self):
        page, layout = self._scroll_form(
            "Folder", "Name and describe a folder. Files choose their folder when they are created or edited."
        )
        form = self._card_form(layout, "Folder details")
        self.collection_name = QLineEdit()
        self.collection_summary = QLineEdit()
        self.collection_description = QPlainTextEdit()
        self.collection_description.setFixedHeight(110)
        form.addRow("Name", self.collection_name)
        form.addRow("Summary", self.collection_summary)
        form.addRow("Description", self.collection_description)
        hint = QLabel("Add a file from the Library menu and select this folder, or change a file's Folder field later.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _node_data(self, item):
        data = item.data(0, Qt.UserRole) if item else None
        return tuple(data) if isinstance(data, (list, tuple)) and len(data) == 2 else (None, None)

    def _rebuild_tree(self, selection=None):
        selection = selection or self._current_node
        if selection[0] == "item":
            selection = ("file", selection[1])
        elif selection[0] == "collection":
            selection = ("folder", selection[1])
        self._loading = True
        self.tree.clear()
        library_item = QTreeWidgetItem([self.project["library"]["name"]])
        library_item.setData(0, Qt.UserRole, ("library", None))
        self.tree.addTopLevelItem(library_item)
        folders_root = QTreeWidgetItem([f"Folders ({format_number(len(self.project['collections']))})"])
        folders_root.setData(0, Qt.UserRole, ("folders-root", None))
        folders_root.setFlags(folders_root.flags() & ~Qt.ItemIsSelectable)
        self.tree.addTopLevelItem(folders_root)
        assigned_ids = set()
        selected_item = library_item if selection == ("library", None) else None
        item_by_id = {item["id"]: item for item in self.project["items"]}
        for folder in self.project["collections"]:
            node = QTreeWidgetItem([folder["name"]])
            node.setData(0, Qt.UserRole, ("folder", folder["id"]))
            folders_root.addChild(node)
            if selection == ("folder", folder["id"]):
                selected_item = node
            for item_id in folder["item_ids"]:
                item = item_by_id.get(item_id)
                if not item or item_id in assigned_ids:
                    continue
                file_node = QTreeWidgetItem([item["title"]])
                file_node.setData(0, Qt.UserRole, ("file", item_id))
                node.addChild(file_node)
                assigned_ids.add(item_id)
                if selection == ("file", item_id):
                    selected_item = file_node
            node.setExpanded(True)
        unfiled = [item for item in self.project["items"] if item["id"] not in assigned_ids]
        files_root = QTreeWidgetItem([f"Files without a folder ({format_number(len(unfiled))})"])
        files_root.setData(0, Qt.UserRole, ("files-root", None))
        files_root.setFlags(files_root.flags() & ~Qt.ItemIsSelectable)
        self.tree.addTopLevelItem(files_root)
        for item in unfiled:
            node = QTreeWidgetItem([item["title"]])
            node.setData(0, Qt.UserRole, ("file", item["id"]))
            files_root.addChild(node)
            if selection == ("file", item["id"]):
                selected_item = node
        folders_root.setExpanded(True)
        files_root.setExpanded(True)
        self.tree.setCurrentItem(selected_item or library_item)
        self._loading = False
        self._current_node = self._node_data(selected_item or library_item)
        self._load_editor(self._current_node)

    def _find_item(self, item_id):
        return next((item for item in self.project["items"] if item["id"] == item_id), None)

    def _find_collection(self, collection_id):
        return next((collection for collection in self.project["collections"] if collection["id"] == collection_id), None)

    def _folder_for_item(self, item_id):
        folder = next((folder for folder in self.project["collections"] if item_id in folder["item_ids"]), None)
        return folder["id"] if folder else None

    def _assign_item_folder(self, item_id, folder_id):
        for folder in self.project["collections"]:
            folder["item_ids"] = [value for value in folder["item_ids"] if value != item_id]
        folder = self._find_collection(folder_id)
        if folder is not None:
            folder["item_ids"].append(item_id)

    def _load_folder_choices(self, selected_id=None):
        self.item_folder.clear()
        self.item_folder.addItem("No folder", None)
        for folder in self.project["collections"]:
            self.item_folder.addItem(folder["name"], folder["id"])
        index = self.item_folder.findData(selected_id)
        self.item_folder.setCurrentIndex(max(0, index))

    def _tree_changed(self, current, previous):
        if self._loading:
            return
        self._commit_editor()
        node = self._node_data(current)
        if node[0] in {"files-root", "folders-root"}:
            return
        self._current_node = node
        self._load_editor(node)

    def _load_editor(self, node):
        self._loading = True
        kind, identifier = node
        if kind == "library":
            library = self.project["library"]
            self.library_name.setText(library["name"])
            self.library_version.setText(library["version"])
            self.library_revision.setValue(library["revision"])
            self.library_creator.setText(library["creator"])
            self.library_category.setText(library["category"])
            self.library_summary.setText(library["summary"])
            self.library_description.setPlainText(library["description"])
            self.library_tags.setText(", ".join(library["tags"]))
            self.library_languages.setText(", ".join(library["languages"]))
            self.library_links.setPlainText("\n".join(library["links"]))
            self.library_artwork.setText(library["artwork_path"])
            self.library_license_name.setText(library["license"]["name"])
            self.library_license_url.setText(library["license"]["url"])
            self.feed_url.setText(library["update"]["feed_url"])
            _set_combo(self.update_channel, library["update"]["channel"])
            self.package_url.setText(self.project["publishing"]["package_url"])
            self.release_notes.setPlainText(self.project["publishing"]["release_notes"])
            torrent = self.project["torrent"]
            self.torrent_root.setText(torrent.get("root_path", ""))
            self.torrent_trackers.setPlainText("\n".join(torrent.get("trackers") or []))
            self.torrent_web_seeds.setPlainText("\n".join(torrent.get("web_seeds") or []))
            self.torrent_private.setChecked(bool(torrent.get("private")))
            piece_index = self.torrent_piece_size.findData(torrent.get("piece_size") or 0)
            self.torrent_piece_size.setCurrentIndex(max(0, piece_index))
            self.torrent_comment.setText(torrent.get("comment", ""))
            self.editors.setCurrentWidget(self.library_editor)
        elif kind == "file":
            item = self._find_item(identifier)
            if item:
                self.item_title.setText(item["title"])
                self._loaded_folder_id = self._folder_for_item(identifier)
                self._load_folder_choices(self._loaded_folder_id)
                self.item_version.setText(item["version"])
                self.item_creator.setText(item["creator"])
                self.item_category.setText(item["category"])
                self.item_summary.setText(item["summary"])
                self.item_description.setPlainText(item["description"])
                self.item_tags.setText(", ".join(item["tags"]))
                _set_combo(self.item_platform, item["platform"])
                _set_combo(self.item_architecture, item["architecture"])
                self.item_links.setPlainText("\n".join(item["links"]))
                self.item_artwork.setText(item["artwork_path"])
                self.item_license_name.setText(item["license"]["name"])
                self.item_license_url.setText(item["license"]["url"])
                artifact = item["artifacts"][0] if item["artifacts"] else new_artifact(name=item["title"])
                embedded = next((source for source in artifact["sources"] if source["type"] == "embedded"), None)
                torrent = next((source for source in artifact["sources"] if source["type"] == "torrent"), None)
                self.file_filename.setText(artifact.get("filename", ""))
                self.file_embedded.setText((embedded or torrent or {}).get("source_path", ""))
                self.file_bundle.setChecked(bool(embedded))
                self.file_torrent.setChecked(bool(torrent))
                self.file_urls.setPlainText("\n".join(
                    source.get("url", "") for source in artifact["sources"] if source["type"] == "https"
                ))
                self.file_media_type.setText(artifact.get("media_type", ""))
                self.file_size.setText("" if artifact.get("size") is None else str(artifact["size"]))
                self.file_checksum.setText(artifact.get("sha256", ""))
                extra_count = max(0, len(item["artifacts"]) - 1)
                self.file_variant_note.setVisible(bool(extra_count))
                self.file_variant_note.setText(
                    f"This older project contains {format_number(extra_count)} additional source variant(s). "
                    "Creator will preserve them; this screen edits the primary file."
                    if extra_count else ""
                )
                self.editors.setCurrentWidget(self.item_editor)
        elif kind == "folder":
            collection = self._find_collection(identifier)
            if collection:
                self.collection_name.setText(collection["name"])
                self.collection_summary.setText(collection["summary"])
                self.collection_description.setPlainText(collection["description"])
                self.editors.setCurrentWidget(self.collection_editor)
        self._loading = False
        self._update_preview()

    def _commit_editor(self):
        if self._loading:
            return
        before = deepcopy(self.project)
        kind, identifier = self._current_node
        if kind == "library":
            library = self.project["library"]
            library.update({
                "name": self.library_name.text().strip() or "Untitled Library",
                "version": self.library_version.text().strip() or "1",
                "revision": self.library_revision.value(),
                "creator": self.library_creator.text().strip(),
                "category": self.library_category.text().strip(),
                "summary": self.library_summary.text().strip(),
                "description": self.library_description.toPlainText().strip(),
                "tags": _csv_values(self.library_tags.text()),
                "languages": _csv_values(self.library_languages.text()),
                "links": _line_values(self.library_links.toPlainText()),
                "artwork_path": self.library_artwork.text(),
                "license": {"name": self.library_license_name.text().strip(), "url": self.library_license_url.text().strip()},
                "update": {"feed_url": self.feed_url.text().strip(), "channel": self.update_channel.currentText().strip() or "stable"},
            })
            self.project["publishing"] = {
                "package_url": self.package_url.text().strip(),
                "release_notes": self.release_notes.toPlainText().strip(),
            }
            self.project["torrent"] = {
                "root_path": self.torrent_root.text(),
                "trackers": _line_values(self.torrent_trackers.toPlainText()),
                "web_seeds": _line_values(self.torrent_web_seeds.toPlainText()),
                "private": self.torrent_private.isChecked(),
                "comment": self.torrent_comment.text().strip(),
                "piece_size": self.torrent_piece_size.currentData() or 0,
            }
        elif kind == "file":
            item = self._find_item(identifier)
            if item:
                try:
                    expected_size = int(self.file_size.text()) if self.file_size.text().strip() else None
                except ValueError:
                    expected_size = None
                item.update({
                    "title": self.item_title.text().strip() or "Untitled file",
                    "version": self.item_version.text().strip(),
                    "creator": self.item_creator.text().strip(),
                    "category": self.item_category.text().strip(),
                    "summary": self.item_summary.text().strip(),
                    "description": self.item_description.toPlainText().strip(),
                    "tags": _csv_values(self.item_tags.text()),
                    "platform": self.item_platform.currentText(),
                    "architecture": self.item_architecture.currentText(),
                    "links": _line_values(self.item_links.toPlainText()),
                    "artwork_path": self.item_artwork.text(),
                    "license": {"name": self.item_license_name.text().strip(), "url": self.item_license_url.text().strip()},
                })
                artifact = deepcopy(item["artifacts"][0]) if item["artifacts"] else new_artifact(name=item["title"])
                artifact.update({
                    "name": item["title"],
                    "filename": self.file_filename.text().strip(),
                    "media_type": self.file_media_type.text().strip(),
                    "platform": item["platform"],
                    "architecture": item["architecture"],
                    "size": expected_size,
                    "sha256": self.file_checksum.text().strip().casefold(),
                    "sources": [],
                })
                if self.file_embedded.text() and self.file_bundle.isChecked():
                    artifact["sources"].append({"type": "embedded", "source_path": self.file_embedded.text()})
                if self.file_embedded.text() and self.file_torrent.isChecked():
                    root = self.project["torrent"].get("root_path")
                    if not root:
                        root = os.path.dirname(os.path.abspath(self.file_embedded.text()))
                        self.project["torrent"]["root_path"] = root
                    resolved_root = root
                    if not os.path.isabs(resolved_root) and self.project_path:
                        resolved_root = os.path.join(os.path.dirname(self.project_path), resolved_root)
                    try:
                        relative = os.path.relpath(os.path.abspath(self.file_embedded.text()), resolved_root)
                    except ValueError:
                        relative = os.path.basename(self.file_embedded.text())
                    artifact["sources"].append({
                        "type": "torrent", "source_path": self.file_embedded.text(),
                        "relative_path": relative.replace("\\", "/"),
                    })
                artifact["sources"].extend(
                    {"type": "https", "url": url} for url in _line_values(self.file_urls.toPlainText())
                )
                if item["artifacts"]:
                    item["artifacts"][0] = artifact
                else:
                    item["artifacts"].append(artifact)
                selected_folder_id = self.item_folder.currentData()
                if selected_folder_id != self._loaded_folder_id:
                    self._assign_item_folder(item["id"], selected_folder_id)
                    self._loaded_folder_id = selected_folder_id
        elif kind == "folder":
            collection = self._find_collection(identifier)
            if collection:
                collection.update({
                    "name": self.collection_name.text().strip() or "Untitled folder",
                    "summary": self.collection_summary.text().strip(),
                    "description": self.collection_description.toPlainText().strip(),
                })
        self.project = normalize_project(self.project)
        if before != self.project:
            self._set_dirty(True)
            self._refresh_tree_labels()
        self._update_preview()

    def _refresh_tree_labels(self):
        selection = self._current_node
        self._rebuild_tree(selection)

    def _tree_menu(self, position):
        node = self._node_data(self.tree.itemAt(position))
        menu = QMenu(self)
        menu.addAction(self.add_file_action)
        menu.addAction(self.add_folder_action)
        if node[0] in {"file", "folder"}:
            menu.addSeparator()
            menu.addAction(self.delete_action)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def add_file(self):
        self._commit_editor()
        if self._current_node[0] == "folder":
            default_folder_id = self._current_node[1]
        elif self._current_node[0] == "file":
            default_folder_id = self._folder_for_item(self._current_node[1])
        else:
            default_folder_id = None
        dialog = NewFileDialog(self.project["collections"], default_folder_id, self)
        if dialog.exec() != QDialog.Accepted:
            return
        item, folder_id = dialog.result_data()
        for source in item["artifacts"][0]["sources"]:
            if source["type"] != "torrent":
                continue
            root = self.project["torrent"].get("root_path")
            if not root:
                root = os.path.dirname(os.path.abspath(source["source_path"]))
                self.project["torrent"]["root_path"] = root
            resolved_root = root
            if not os.path.isabs(resolved_root) and self.project_path:
                resolved_root = os.path.join(os.path.dirname(self.project_path), resolved_root)
            try:
                source["relative_path"] = os.path.relpath(
                    os.path.abspath(source["source_path"]), resolved_root
                ).replace("\\", "/")
            except ValueError:
                pass
        self.project["items"].append(item)
        self._assign_item_folder(item["id"], folder_id)
        self._set_dirty(True)
        self._rebuild_tree(("file", item["id"]))

    def add_folder(self):
        self._commit_editor()
        collection = new_collection(name="New folder")
        self.project["collections"].append(collection)
        self._set_dirty(True)
        self._rebuild_tree(("folder", collection["id"]))

    def delete_selected(self):
        kind, identifier = self._current_node
        if kind not in {"file", "folder"}:
            return
        label = (self._find_item(identifier) or self._find_collection(identifier) or {}).get("title") or (self._find_collection(identifier) or {}).get("name") or "selection"
        if QMessageBox.question(self, "Delete from project", f"Remove “{label}” from this project?") != QMessageBox.Yes:
            return
        if kind == "file":
            self.project["items"] = [item for item in self.project["items"] if item["id"] != identifier]
            for collection in self.project["collections"]:
                collection["item_ids"] = [item_id for item_id in collection["item_ids"] if item_id != identifier]
        else:
            self.project["collections"] = [collection for collection in self.project["collections"] if collection["id"] != identifier]
        self._set_dirty(True)
        self._rebuild_tree(("library", None))

    def import_local_folder(self):
        self._commit_editor()
        folder = QFileDialog.getExistingDirectory(self, "Import a folder of files")
        if not folder:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            records = scan_folder(folder)
        except OdrLibError as exc:
            QMessageBox.warning(self, "Folder not imported", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        if not records:
            QMessageBox.information(self, "Nothing imported", "The selected folder does not contain any files.")
            return
        dialog = FolderImportDialog(folder, records, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            project, added = import_folder_selection(
                self.project, folder, dialog.selections(), project_path=self.project_path
            )
        except OdrLibError as exc:
            QMessageBox.warning(self, "Folder not imported", str(exc))
            return
        self.project = project
        if added:
            self._set_dirty(True)
            self._rebuild_tree(("library", None))
            self.statusBar().showMessage(f"Imported {format_number(added)} files from {folder}", 8000)

    def _update_preview(self):
        library = self.project["library"]
        editing_library = self._current_node[0] == "library" and not self._loading
        preview_name = self.library_name.text().strip() if editing_library else library.get("name")
        preview_version = self.library_version.text().strip() if editing_library else library.get("version")
        preview_revision = self.library_revision.value() if editing_library else library.get("revision", 1)
        artwork = self.library_artwork.text() if self._current_node[0] == "library" and not self._loading else library.get("artwork_path", "")
        resolved = artwork
        if resolved and not os.path.isabs(resolved) and self.project_path:
            resolved = os.path.join(os.path.dirname(self.project_path), resolved)
        pixmap = QPixmap(resolved) if resolved else QPixmap()
        if not pixmap.isNull():
            self.preview_artwork.setText("")
            self.preview_artwork.setPixmap(pixmap.scaled(self.preview_artwork.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        else:
            self.preview_artwork.setPixmap(QPixmap())
            self.preview_artwork.setText((preview_name or "L")[:1].upper())
        self.preview_name.setText(preview_name or "Untitled Library")
        artifacts = sum(len(item["artifacts"]) for item in self.project["items"])
        embedded = sum(
            1 for item in self.project["items"] for artifact in item["artifacts"]
            if any(source["type"] == "embedded" for source in artifact["sources"])
        )
        extension_badges = []
        if (library.get("update") or {}).get("feed_url"):
            extension_badges.append("U1")
        torrent_count = sum(
            1 for item in self.project["items"] for artifact in item["artifacts"]
            if any(source["type"] == "torrent" for source in artifact["sources"])
        )
        if torrent_count:
            extension_badges.append("T1")
        extensions = " · ".join(extension_badges) or "Core only"
        self.preview_meta.setText(
            f"Version {preview_version or '—'} · revision {preview_revision}\n"
            f"{format_number(len(self.project['items']))} files · {format_number(len(self.project['collections']))} folders\n"
            f"{format_number(artifacts)} source variants · {format_number(embedded)} bundled\n"
            f"{format_number(torrent_count)} torrent files · Extensions: {extensions}"
        )

    def validate_current_project(self):
        self._commit_editor()
        issues = validate_project(self.project, self.project_path)
        self.validation_list.clear()
        for issue in issues:
            prefix = "Error" if issue.level == "error" else "Warning"
            self.validation_list.addItem(f"{prefix} · {issue.location}\n{issue.message}")
        if not issues:
            self.validation_list.addItem("Ready to build\nNo problems were found.")
            self.statusBar().showMessage("Project validation passed", 5000)
        else:
            errors = sum(issue.level == "error" for issue in issues)
            warnings = len(issues) - errors
            self.statusBar().showMessage(f"Validation found {errors} errors and {warnings} warnings", 8000)
        return issues

    def build_package(self):
        self._commit_editor()
        if not self.project_path and not self.save_document_as():
            return
        issues = self.validate_current_project()
        if any(issue.level == "error" for issue in issues):
            QMessageBox.warning(self, "Project needs attention", "Fix the validation errors before building this library.")
            return
        if issues:
            if QMessageBox.question(self, "Build with warnings?", f"The project has {len(issues)} warnings. Build it anyway?") != QMessageBox.Yes:
                return
        suggested = os.path.join(
            os.path.dirname(self.project_path),
            "".join(character for character in self.project["library"]["name"] if character not in '<>:"/\\|?*').strip() + ".odrlib",
        )
        destination, _selected = QFileDialog.getSaveFileName(self, "Build ODeR Library", suggested, "ODeR Libraries (*.odrlib)")
        if not destination:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = build_library(self.project, destination, project_path=self.project_path)
        except (OdrLibError, OSError) as exc:
            QMessageBox.critical(self, "Library build failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._last_build = result
        message = (
            f"Built {os.path.basename(result.path)}\n\n"
            f"{format_number(result.package.item_count)} files · "
            f"{format_number(result.package.collection_count)} folders · {format_bytes(result.size)}\n"
            f"SHA-256: {result.sha256}"
        )
        if result.feed_path:
            message += f"\n\nUpdate feed: {os.path.basename(result.feed_path)}"
        if result.torrent_path:
            message += f"\nTorrent: {os.path.basename(result.torrent_path)}"
        QMessageBox.information(self, "ODeR Library built", message)
        self.statusBar().showMessage(f"Built {result.path}", 10000)

    def _set_dirty(self, value):
        self.dirty = bool(value)
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self.project_path) if self.project_path else "Untitled project"
        marker = " *" if self.dirty else ""
        self.setWindowTitle(f"{name}{marker} — {CREATOR_NAME} {CREATOR_VERSION}")

    def _confirm_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self, "Unsaved Creator project", "Save your changes before continuing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return bool(self.save_document())
        return True

    def new_document(self):
        if not self._confirm_discard():
            return
        self.project = new_project()
        self.project_path = None
        self._set_dirty(False)
        self.validation_list.clear()
        self._rebuild_tree(("library", None))
        self.statusBar().showMessage("New Creator project")

    def open_document(self):
        if not self._confirm_discard():
            return
        path, _selected = QFileDialog.getOpenFileName(self, "Open Creator project", "", "ODeR Creator projects (*.odrproj)")
        if path:
            self.open_project_path(path, confirm=False)

    def open_project_path(self, path, *, confirm=True):
        if confirm and not self._confirm_discard():
            return False
        try:
            project = load_project(path)
        except (OdrLibError, OSError) as exc:
            QMessageBox.warning(self, "Project not opened", str(exc))
            return False
        self.project = project
        self.project_path = os.path.abspath(path)
        self._set_dirty(False)
        self.validation_list.clear()
        self._rebuild_tree(("library", None))
        self.statusBar().showMessage(f"Opened {self.project_path}", 7000)
        return True

    def save_document(self):
        self._commit_editor()
        if not self.project_path:
            return self.save_document_as()
        try:
            self.project = save_project(self.project_path, self.project)
        except (OdrLibError, OSError) as exc:
            QMessageBox.critical(self, "Project not saved", str(exc))
            return False
        self._set_dirty(False)
        self.statusBar().showMessage(f"Saved {self.project_path}", 5000)
        return True

    def save_document_as(self):
        self._commit_editor()
        suggested = self.project_path or os.path.join(os.getcwd(), "Untitled Library.odrproj")
        path, _selected = QFileDialog.getSaveFileName(self, "Save Creator project", suggested, "ODeR Creator projects (*.odrproj)")
        if not path:
            return False
        if not path.casefold().endswith(".odrproj"):
            path += ".odrproj"
        self.project_path = os.path.abspath(path)
        return self.save_document()

    def dragEnterEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if any(path.casefold().endswith(".odrproj") for path in paths):
            event.acceptProposedAction()

    def dropEvent(self, event):
        path = next((url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile() and url.toLocalFile().casefold().endswith(".odrproj")), None)
        if path and self.open_project_path(path):
            event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
