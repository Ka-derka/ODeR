"""Read-only browser for installed ``.odrlib`` curated catalogs."""
from __future__ import annotations

from urllib.parse import urlsplit

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)
from PySide6.QtCore import QUrl

from core.odrlib import OdrLibError
from core.odrlib_store import load_profile_package
from gui.package_dialogs import format_bytes, format_number


class OdrLibBrowserWidget(QWidget):
    download_requested = Signal(object)
    information_requested = Signal()
    update_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = None
        self.package = None
        self._item_by_id = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(10)

        heading = QHBoxLayout()
        title_column = QVBoxLayout()
        self.title = QLabel("Curated library")
        self.title.setObjectName("heroTitle")
        title_column.addWidget(self.title)
        self.summary = QLabel()
        self.summary.setObjectName("mutedLabel")
        self.summary.setWordWrap(True)
        title_column.addWidget(self.summary)
        heading.addLayout(title_column, 1)
        self.info_button = QPushButton("Information")
        self.info_button.clicked.connect(self.information_requested.emit)
        self.update_button = QPushButton("Check for updates")
        self.update_button.clicked.connect(self.update_requested.emit)
        heading.addWidget(self.info_button, 0, Qt.AlignTop)
        heading.addWidget(self.update_button, 0, Qt.AlignTop)
        root.addLayout(heading)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search this curated library…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._rebuild_tree)
        root.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(("Name", "Version", "Platform", "Available from", "Size"))
        self.tree.header().setSectionResizeMode(QHeaderView.Interactive)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_args: self._download_selected())
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        root.addWidget(self.tree, 1)

        details_card = QFrame()
        details_card.setObjectName("card")
        details_layout = QVBoxLayout(details_card)
        details_layout.setContentsMargins(12, 10, 12, 10)
        self.details = QLabel("Select a file to see its description and sources.")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        details_layout.addWidget(self.details)
        root.addWidget(details_card)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.open_page_button = QPushButton("Open item page")
        self.open_page_button.clicked.connect(self._open_item_page)
        self.copy_link_button = QPushButton("Copy link")
        self.copy_link_button.clicked.connect(self._copy_link)
        self.download_button = QPushButton("Download")
        self.download_button.setObjectName("accentButton")
        self.download_button.clicked.connect(self._download_selected)
        actions.addWidget(self.open_page_button)
        actions.addWidget(self.copy_link_button)
        actions.addWidget(self.download_button)
        root.addLayout(actions)
        self._selection_changed()

    def set_profile(self, profile):
        self.profile = dict(profile or {})
        self.title.setText(self.profile.get("name") or "Curated library")
        try:
            self.package = load_profile_package(self.profile)
        except OdrLibError as exc:
            self.package = None
            self.summary.setText(str(exc))
            self.tree.clear()
            self.details.setText("The installed .odrlib package is unavailable or invalid.")
            self._selection_changed()
            return
        self._item_by_id = {item["id"]: item for item in self.package.items}
        curator = self.package.creator or "Unknown curator"
        version = self.package.version or "Unversioned"
        extensions = " · ".join(extension.badge for extension in self.package.extensions)
        self.summary.setText(
            f"{version} · revision {self.package.revision} · {curator}"
            f"{' · ' + extensions if extensions else ''}\n"
            f"{format_number(self.package.item_count)} files · "
            f"{format_number(self.package.collection_count)} folders · "
            f"{format_number(self.package.artifact_count)} downloads"
        )
        has_update_feed = bool(self.package.update_feed_url)
        self.update_button.setVisible(True)
        self.update_button.setToolTip(
            "Check the curator's HTTPS update feed."
            if has_update_feed else
            "This package does not contain an update-feed URL. Click for details."
        )
        self._rebuild_tree()

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    @staticmethod
    def _matches(item, query):
        if not query:
            return True
        text = " ".join((
            str(item.get("title") or ""), str(item.get("summary") or ""),
            str(item.get("description") or ""), str(item.get("creator") or ""),
            str(item.get("category") or ""), " ".join(item.get("tags") or []),
        )).casefold()
        return all(term in text for term in query.split())

    @staticmethod
    def _source_label(artifact):
        embedded = sum(source.get("type") == "embedded" for source in artifact.get("sources") or [])
        online = sum(source.get("type") == "https" for source in artifact.get("sources") or [])
        labels = []
        if embedded:
            labels.append("Bundled")
        if online:
            labels.append(f"HTTPS ×{online}" if online > 1 else "HTTPS")
        return " + ".join(labels) or "Unavailable"

    def _artifact_node(self, item, artifact, folder_name=""):
        name = item.get("title") or artifact.get("name") or "Untitled file"
        row = QTreeWidgetItem((
            name,
            str(item.get("version") or ""),
            " · ".join(value for value in (
                artifact.get("platform") or item.get("platform"),
                artifact.get("architecture") or item.get("architecture"),
            ) if value and value != "Any") or "Any",
            self._source_label(artifact),
            format_bytes(artifact.get("size")) if artifact.get("size") is not None else "—",
        ))
        row.setData(0, Qt.UserRole, {
            "item": item,
            "artifact": artifact,
            "folder": folder_name,
        })
        return row

    def _item_node(self, item, folder_name=""):
        artifacts = item.get("artifacts") or []
        if len(artifacts) == 1:
            return self._artifact_node(item, artifacts[0], folder_name)
        node = QTreeWidgetItem((
            item.get("title") or "Untitled file",
            str(item.get("version") or ""),
            str(item.get("platform") or "Any"),
            f"{format_number(len(artifacts))} variants" if artifacts else "No download",
            "",
        ))
        node.setData(0, Qt.UserRole, {"item": item, "artifact": None, "folder": folder_name})
        for artifact in artifacts:
            child = self._artifact_node(item, artifact, folder_name)
            child.setText(0, artifact.get("name") or artifact.get("filename") or "Download")
            node.addChild(child)
        node.setExpanded(True)
        return node

    def _rebuild_tree(self, *_args):
        self.tree.clear()
        if self.package is None:
            return
        query = self.search.text().strip().casefold()
        matching = {
            item["id"] for item in self.package.items if self._matches(item, query)
        }
        assigned = set()
        folders_root = QTreeWidgetItem((f"Folders ({format_number(self.package.collection_count)})", "", "", "", ""))
        folders_root.setFlags(folders_root.flags() & ~Qt.ItemIsSelectable)
        self.tree.addTopLevelItem(folders_root)
        for folder in self.package.collections:
            members = [
                self._item_by_id[item_id] for item_id in folder.get("item_ids") or []
                if item_id in matching and item_id in self._item_by_id and item_id not in assigned
            ]
            if query and not members and query not in str(folder.get("name") or "").casefold():
                continue
            folder_node = QTreeWidgetItem((folder.get("name") or "Untitled folder", "", "", "", ""))
            folder_node.setToolTip(0, folder.get("description") or folder.get("summary") or "")
            folders_root.addChild(folder_node)
            for item in members:
                folder_node.addChild(self._item_node(item, folder.get("name") or ""))
                assigned.add(item["id"])
            folder_node.setExpanded(True)
        unfiled = [item for item in self.package.items if item["id"] in matching and item["id"] not in assigned]
        files_root = QTreeWidgetItem((f"Files without a folder ({format_number(len(unfiled))})", "", "", "", ""))
        files_root.setFlags(files_root.flags() & ~Qt.ItemIsSelectable)
        self.tree.addTopLevelItem(files_root)
        for item in unfiled:
            files_root.addChild(self._item_node(item))
        folders_root.setExpanded(True)
        files_root.setExpanded(True)
        self.tree.resizeColumnToContents(1)
        self.tree.resizeColumnToContents(2)
        self.tree.resizeColumnToContents(3)
        self.tree.resizeColumnToContents(4)
        self._selection_changed()

    def _selection(self):
        current = self.tree.currentItem()
        value = current.data(0, Qt.UserRole) if current else None
        return value if isinstance(value, dict) else {}

    def _selection_changed(self, *_args):
        selected = self._selection()
        item = selected.get("item") or {}
        artifact = selected.get("artifact") or {}
        sources = artifact.get("sources") or []
        links = item.get("links") or []
        self.download_button.setEnabled(bool(sources))
        self.copy_link_button.setEnabled(any(source.get("type") == "https" for source in sources))
        self.open_page_button.setEnabled(bool(links))
        if not item:
            self.details.setText("Select a file to see its description and sources.")
            return
        description = item.get("description") or item.get("summary") or "No description provided."
        creator = item.get("creator") or "Unknown creator"
        license_name = (item.get("license") or {}).get("name") or "Unknown rights"
        source_text = self._source_label(artifact) if artifact else "Select a source variant below this file."
        self.details.setText(
            f"{item.get('title') or 'Untitled file'} · {creator} · {license_name}\n"
            f"{description}\nAvailable from: {source_text}"
        )

    def _choose_source(self, sources):
        if len(sources) == 1:
            return sources[0]
        menu = QMenu(self)
        mapping = {}
        for source in sources:
            if source.get("type") == "embedded":
                label = "Use bundled offline copy"
            else:
                host = urlsplit(source.get("url") or "").hostname or "HTTPS mirror"
                label = f"Download from {host}"
            action = menu.addAction(label)
            mapping[action] = source
        chosen = menu.exec(self.download_button.mapToGlobal(self.download_button.rect().topLeft()))
        return mapping.get(chosen)

    def _download_selected(self):
        selected = self._selection()
        artifact = selected.get("artifact") or {}
        sources = artifact.get("sources") or []
        if not sources:
            return
        source = self._choose_source(sources)
        if source:
            request = dict(selected)
            request["source"] = source
            self.download_requested.emit(request)

    def _copy_link(self):
        artifact = self._selection().get("artifact") or {}
        source = next((value for value in artifact.get("sources") or [] if value.get("type") == "https"), None)
        if source:
            QApplication.clipboard().setText(source.get("url") or "")

    def _open_item_page(self):
        item = self._selection().get("item") or {}
        link = next(iter(item.get("links") or []), "")
        if link and not QDesktopServices.openUrl(QUrl(link)):
            QMessageBox.warning(self, "Could not open link", link)

    def _context_menu(self, position):
        selected = self._selection()
        if not selected.get("item"):
            return
        menu = QMenu(self)
        download = menu.addAction("Download")
        download.setEnabled(bool((selected.get("artifact") or {}).get("sources")))
        copy_link = menu.addAction("Copy HTTPS link")
        copy_link.setEnabled(any(
            source.get("type") == "https"
            for source in (selected.get("artifact") or {}).get("sources") or []
        ))
        chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
        if chosen == download:
            self._download_selected()
        elif chosen == copy_link:
            self._copy_link()
