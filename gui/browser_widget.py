from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
    QTreeWidget, QTreeWidgetItem, QToolButton, QHeaderView, QFrame,
    QMenu, QApplication, QStyle, QComboBox, QStyledItemDelegate,
    QStyleOptionButton, QStyleOptionViewItem
)
from PySide6.QtCore import Qt, Signal, QSize, QRect, QEvent
from html import escape

from core import cache, downloader, library
from core import applog
from core.settings import load_settings


class FileActionDelegate(QStyledItemDelegate):
    """Paint lightweight file actions without creating widgets for every row."""

    BUTTON_WIDTH = 76
    BUTTON_HEIGHT = 24
    BUTTON_GAP = 6
    RIGHT_INSET = 8
    download_requested = Signal(str, str)
    copy_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        viewport = parent.viewport() if parent is not None else None
        self._download_style = QPushButton("Download", viewport)
        self._copy_style = QPushButton("Copy link", viewport)
        for button in (self._download_style, self._copy_style):
            button.setObjectName("rowActionButton")
            button.hide()

    @classmethod
    def button_rects(cls, cell_rect):
        total_width = cls.BUTTON_WIDTH * 2 + cls.BUTTON_GAP
        left = max(cell_rect.left(), cell_rect.right() - cls.RIGHT_INSET - total_width + 1)
        top = cell_rect.top() + max(0, (cell_rect.height() - cls.BUTTON_HEIGHT) // 2)
        download_rect = QRect(left, top, cls.BUTTON_WIDTH, cls.BUTTON_HEIGHT)
        copy_rect = QRect(
            left + cls.BUTTON_WIDTH + cls.BUTTON_GAP,
            top,
            cls.BUTTON_WIDTH,
            cls.BUTTON_HEIGHT,
        )
        return download_rect, copy_rect

    @staticmethod
    def _file_details(index):
        source = index.sibling(index.row(), 0)
        if bool(source.data(Qt.UserRole + 1)):
            return None, None
        return source.data(Qt.UserRole), source.data(Qt.DisplayRole)

    def paint(self, painter, option, index):
        base_option = QStyleOptionViewItem(option)
        self.initStyleOption(base_option, index)
        style = option.widget.style() if option.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, base_option, painter, option.widget)
        url, _name = self._file_details(index)
        if not url:
            return
        for text, rect, template in zip(
            ("Download", "Copy link"),
            self.button_rects(option.rect),
            (self._download_style, self._copy_style),
        ):
            button_option = QStyleOptionButton()
            button_option.initFrom(template)
            button_option.rect = rect
            button_option.text = text
            button_option.state |= QStyle.State_Enabled
            template.style().drawControl(QStyle.CE_PushButton, button_option, painter, template)

    def editorEvent(self, event, model, option, index):
        if event.type() != QEvent.MouseButtonRelease or event.button() != Qt.LeftButton:
            return False
        url, name = self._file_details(index)
        if not url:
            return False
        download_rect, copy_rect = self.button_rects(option.rect)
        if download_rect.contains(event.position().toPoint()):
            self.download_requested.emit(url, name or "download")
            return True
        if copy_rect.contains(event.position().toPoint()):
            self.copy_requested.emit(url)
            return True
        return False

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        return QSize(max(hint.width(), 166), max(hint.height(), 37))


class BrowserWidget(QWidget):
    navigate_requested = Signal(str)
    update_folder_requested = Signal(str)
    grow_level_requested = Signal(str)
    full_update_requested = Signal()
    incremental_update_requested = Signal()
    resume_update_requested = Signal()
    export_subtree_requested = Signal(str)
    download_folder_requested = Signal(str)
    favorite_added = Signal()
    open_downloads_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = None
        self.current_url = None
        self.history = []
        self.history_index = -1
        self._visible_urls = []
        self.page_offset = 0
        self.page_size = max(50, int(load_settings().get("browser_page_size", 500)))

        style = QApplication.style()
        self.back_btn = QToolButton()
        self.back_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.back_btn.setToolTip("Back (Alt+Left)")
        self.back_btn.clicked.connect(self.go_back)

        self.forward_btn = QToolButton()
        self.forward_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.forward_btn.setToolTip("Forward (Alt+Right)")
        self.forward_btn.clicked.connect(self.go_forward)

        self.up_btn = QToolButton()
        self.up_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.up_btn.setToolTip("Parent folder")
        self.up_btn.clicked.connect(self.go_up)

        self.grow_btn = QPushButton("Grow 1 level")
        self.grow_btn.setToolTip("Fetch this folder and the next level of subfolders, then save them locally.")
        self.grow_btn.clicked.connect(self._grow_level)

        self.update_btn = QPushButton("Update folder")
        self.update_btn.setObjectName("accentButton")
        self.update_btn.setToolTip("Refetch only the folder you are currently viewing.")
        self.update_btn.clicked.connect(self._update_folder)

        self.full_update_btn = QPushButton("More")
        self.full_update_btn.setObjectName("tableButton")
        self.full_update_btn.setFixedSize(78, 27)
        self.full_update_btn.setToolTip("More update options")
        menu = QMenu(self)
        menu.addAction("Resume unfinished update", lambda: self.resume_update_requested.emit())
        menu.addAction("Update stale folders", lambda: self.incremental_update_requested.emit())
        menu.addAction("Rebuild entire site", lambda: self.full_update_requested.emit())
        menu.addSeparator()
        menu.addAction("Export current folder…", self._export_current)
        self.full_update_btn.setMenu(menu)
        

        self.download_selected_btn = QPushButton("Download selected")
        self.download_selected_btn.clicked.connect(self._download_selected)
        self.download_selected_btn.setEnabled(False)

        self.breadcrumb_label = QLabel("No site selected")
        self.breadcrumb_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.breadcrumb_label.setTextFormat(Qt.RichText)
        self.breadcrumb_label.linkActivated.connect(self._navigate)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search this directory…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._filter_changed)

        self.sort_box = QComboBox()
        self.sort_box.addItem("Name", "name")
        self.sort_box.addItem("Name (Z–A)", "name_desc")
        self.sort_box.addItem("Size", "size")
        self.sort_box.addItem("Type", "type")
        self.sort_box.setToolTip("Sort cached entries")
        self.sort_box.currentIndexChanged.connect(self._filter_changed)

        self.prev_page_btn = QPushButton("Previous")
        self.prev_page_btn.clicked.connect(self._previous_page)
        self.next_page_btn = QPushButton("Next")
        self.next_page_btn.clicked.connect(self._next_page)
        self.page_label = QLabel("")
        self.page_label.setObjectName("mutedLabel")

        self.status_label = QLabel("")
        self.status_label.setObjectName("mutedLabel")

        self.list_widget = QTreeWidget()
        self.list_widget.setObjectName("browserFileList")
        self.list_widget.setHeaderLabels(["Name", "Size", "Type", "Actions"])
        self.list_widget.setRootIsDecorated(False)
        self.list_widget.setAlternatingRowColors(False)
        self.list_widget.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.list_widget.setSortingEnabled(False)
        self.list_widget.setSelectionBehavior(QTreeWidget.SelectRows)
        header = self.list_widget.header()
        # Content columns stay user-resizable. The trailing Actions section
        # absorbs remaining width so its controls stay against the right edge.
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setMinimumSectionSize(70)
        header.resizeSection(0, 430)
        header.resizeSection(1, 100)
        header.resizeSection(2, 110)
        header.resizeSection(3, 174)
        header.setSectionsClickable(True)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.itemSelectionChanged.connect(self._update_selection_state)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._context_menu)
        self.action_delegate = FileActionDelegate(self.list_widget)
        self.action_delegate.download_requested.connect(self._download)
        self.action_delegate.copy_requested.connect(self._copy_link)
        self.list_widget.setItemDelegateForColumn(3, self.action_delegate)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(5)
        nav_row.addWidget(self.back_btn)
        nav_row.addWidget(self.forward_btn)
        nav_row.addWidget(self.up_btn)
        nav_row.addSpacing(6)
        breadcrumb = QFrame()
        breadcrumb.setObjectName("breadcrumbBar")
        breadcrumb_layout = QHBoxLayout(breadcrumb)
        breadcrumb_layout.setContentsMargins(8, 3, 8, 3)
        breadcrumb_layout.addWidget(self.breadcrumb_label, 1)
        self.breadcrumb_label.setObjectName("breadcrumbLabel")
        nav_row.addWidget(breadcrumb, 1)
        nav_row.addWidget(self.download_selected_btn)
        nav_row.addWidget(self.grow_btn)
        nav_row.addWidget(self.update_btn)
        nav_row.addWidget(self.full_update_btn)

        search_row = QHBoxLayout()
        search_row.addWidget(self.search_box, 1)
        search_row.addWidget(QLabel("Sort:"))
        search_row.addWidget(self.sort_box)
        search_row.addWidget(self.prev_page_btn)
        search_row.addWidget(self.page_label)
        search_row.addWidget(self.next_page_btn)
        hint = QLabel("Cached only · no network request")
        hint.setObjectName("mutedLabel")
        search_row.addWidget(hint)

        header = QFrame()
        header.setObjectName("pageHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(8)
        header_layout.addLayout(nav_row)
        header_layout.addLayout(search_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.status_label)
        self.status_label.setContentsMargins(16, 8, 16, 8)

        self._update_nav_state()

    def set_profile(self, profile):
        self.profile = profile
        self.history = []
        self.history_index = -1
        if profile:
            cache.migrate_json_if_needed(profile["id"], profile["base_url"])
            base = cache.get_base_url(profile["id"]) or profile["base_url"]
            self.current_url = base if base.endswith("/") else base + "/"
            self._push_history(self.current_url)
        else:
            self.current_url = None
        self.search_box.clear()
        self.page_offset = 0
        self.render_current()

    def refresh_cache(self):
        if self.profile:
            cache.migrate_json_if_needed(self.profile["id"], self.profile["base_url"])
            base = cache.get_base_url(self.profile["id"]) or self.profile["base_url"]
            if not self.current_url or not cache.get_node(self.profile["id"], self.current_url):
                self.current_url = base if base.endswith("/") else base + "/"
        self.render_current()

    def navigate_to_url(self, url):
        if not self.profile:
            return False
        if not cache.get_node(self.profile["id"], url):
            return False
        self._set_url(url)
        return True

    def focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    def _push_history(self, url):
        if self.history_index >= 0 and self.history[self.history_index] == url:
            return
        self.history = self.history[: self.history_index + 1]
        self.history.append(url)
        self.history_index = len(self.history) - 1

    def _set_url(self, url, record=True):
        if record:
            self._push_history(url)
        self.current_url = url
        self.page_offset = 0
        self.search_box.clear()
        self.render_current()

    def go_back(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.current_url = self.history[self.history_index]
            self.page_offset = 0
            self.render_current()

    def go_forward(self):
        if self.history_index + 1 < len(self.history):
            self.history_index += 1
            self.current_url = self.history[self.history_index]
            self.page_offset = 0
            self.render_current()

    def go_up(self):
        if not self.profile or not self.current_url:
            return
        node = cache.get_node(self.profile["id"], self.current_url)
        if node and node.get("parent_url"):
            self._set_url(node["parent_url"])

    def render_current(self):
        self.list_widget.clear()
        self._visible_urls = []
        self._update_nav_state()
        if not self.profile:
            self.breadcrumb_label.setText("No site selected")
            self.status_label.setText("")
            return
        if not self.current_url:
            return
        node = cache.get_node(self.profile["id"], self.current_url)
        if not node:
            self.breadcrumb_label.setText(self.profile["name"])
            self.status_label.setText("No cached data yet — use Update cache to create an offline listing.")
            return

        base = cache.get_base_url(self.profile["id"]) or self.profile["base_url"]
        rel = self.current_url[len(base):].rstrip("/") if self.current_url.startswith(base) else ""
        parts = [p for p in rel.split("/") if p]
        crumbs = [f'<a href="{escape(base)}">root</a>']
        acc = base
        for part in parts:
            acc += part + "/"
            crumbs.append(f'<a href="{escape(acc)}">{escape(part)}</a>')
        self.breadcrumb_label.setText("  /  ".join(crumbs))

        filter_text = self.search_box.text().strip()
        sort_mode = self.sort_box.currentData()
        total_children = cache.child_count(self.profile["id"], self.current_url, filter_text)
        if total_children and self.page_offset >= total_children:
            self.page_offset = max(0, ((total_children - 1) // self.page_size) * self.page_size)
        children = cache.get_children(
            self.profile["id"], self.current_url, filter_text, sort_mode,
            limit=self.page_size, offset=self.page_offset,
        )

        style = QApplication.style()
        folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        file_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        for child in children:
            url = child["url"]
            kind = "Folder" if child["is_dir"] else self._file_type(child["name"])
            item = QTreeWidgetItem([child["name"], child.get("size") or "", kind, ""])
            item.setData(0, Qt.UserRole, url)
            item.setData(0, Qt.UserRole + 1, bool(child["is_dir"]))
            item.setIcon(0, folder_icon if child["is_dir"] else file_icon)
            item.setSizeHint(0, QSize(0, 37))
            self.list_widget.addTopLevelItem(item)
            self._visible_urls.append(url)

        shown = len(children)
        first = self.page_offset + 1 if shown else 0
        last = self.page_offset + shown
        pages = max(1, (total_children + self.page_size - 1) // self.page_size)
        page = min(pages, self.page_offset // self.page_size + 1)
        self.page_label.setText(f"Page {page:,} of {pages:,}")
        self.prev_page_btn.setEnabled(self.page_offset > 0)
        self.next_page_btn.setEnabled(last < total_children)
        suffix = f" · showing {first:,}–{last:,} of {total_children:,}" if total_children else ""
        last_stats = self.profile.get("last_crawl_stats") or {}
        cache_source = "Hosted .oder cache" if last_stats.get("update_mode") == "hosted" else "Offline cache"
        self.status_label.setText(
            f"{shown:,} item{'s' if shown != 1 else ''}{suffix} · {cache_source} · Select files and use Download selected"
        )
        self._update_selection_state()

    def _filter_changed(self, *_args):
        self.page_offset = 0
        self.render_current()

    def _previous_page(self):
        self.page_offset = max(0, self.page_offset - self.page_size)
        self.render_current()

    def _next_page(self):
        self.page_offset += self.page_size
        self.render_current()

    def _export_current(self):
        if self.current_url:
            self.export_subtree_requested.emit(self.current_url)

    @staticmethod
    def _file_type(name):
        lower = name.lower()
        for ext, kind in ((".zip", "Archive"), (".7z", "Archive"), (".rar", "Archive"),
                          (".tar", "Archive"), (".gz", "Archive"), (".exe", "Application"),
                          (".msi", "Installer"), (".deb", "Package"), (".rpm", "Package"),
                          (".iso", "Disk image"), (".pdf", "Document"), (".txt", "Text"),
                          (".json", "Data"), (".jpg", "Image"), (".jpeg", "Image"),
                          (".png", "Image"), (".mp4", "Video")):
            if lower.endswith(ext):
                return kind
        return "File"

    def _update_nav_state(self):
        self.back_btn.setEnabled(self.history_index > 0)
        self.forward_btn.setEnabled(self.history_index + 1 < len(self.history))
        self.up_btn.setEnabled(bool(self.profile and self.current_url and cache.get_node(self.profile["id"], self.current_url) and cache.get_node(self.profile["id"], self.current_url).get("parent_url")))
        enabled = bool(self.profile and self.current_url and cache.get_node(self.profile["id"], self.current_url) and cache.get_node(self.profile["id"], self.current_url).get("is_dir"))
        self.update_btn.setEnabled(enabled)
        self.grow_btn.setEnabled(enabled)
        self.full_update_btn.setEnabled(bool(self.profile))

    def _update_selection_state(self):
        selected_files = 0
        for item in self.list_widget.selectedItems():
            url = item.data(0, Qt.UserRole)
            node = cache.get_node(self.profile["id"], url) if self.profile else None
            if node and not node.get("is_dir"):
                selected_files += 1
        self.download_selected_btn.setEnabled(selected_files > 0)
        if selected_files:
            self.status_label.setText(f"{selected_files} file{'s' if selected_files != 1 else ''} selected · Download selected")

    def _navigate(self, url):
        self._set_url(url)

    def _copy_link(self, url):
        QApplication.clipboard().setText(url)
        self.status_label.setText(f"Copied link: {url}")
        applog.log(f"copied link: {url}")

    def _on_item_double_clicked(self, item, _col):
        url = item.data(0, Qt.UserRole)
        node = cache.get_node(self.profile["id"], url) if self.profile else None
        if node and node["is_dir"]:
            self._set_url(url)
        elif node:
            self._download(url, node["name"])

    def _update_folder(self):
        if self.profile and self.current_url:
            self.update_folder_requested.emit(self.current_url)

    def _grow_level(self):
        if self.profile and self.current_url:
            self.grow_level_requested.emit(self.current_url)

    def _download_selected(self):
        selected = []
        for item in self.list_widget.selectedItems():
            url = item.data(0, Qt.UserRole)
            node = cache.get_node(self.profile["id"], url) if self.profile else None
            if node and not node.get("is_dir"):
                selected.append({
                    "url": url,
                    "name": node["name"],
                    "rel_path": self._relative_to_current(
                        node.get("parent_url") or self.current_url
                    ),
                })
        group = downloader.new_group(f"{self.profile['name']} — selected files") if selected else None
        if selected:
            downloader.enqueue_many(
                self.profile["id"], self.profile["name"], selected,
                group_id=group["id"], group_name=group["name"],
            )
            self.open_downloads_requested.emit()

    def _context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item or not self.profile:
            return
        url = item.data(0, Qt.UserRole)
        node = cache.get_node(self.profile["id"], url)
        if not node:
            return
        menu = QMenu(self)
        if node.get("is_dir"):
            open_action = menu.addAction("Open folder")
            update_folder = menu.addAction("Update this folder")
            grow_level = menu.addAction("Grow 1 level")
            download_folder = menu.addAction("Download folder")
            favorite_folder = menu.addAction("Add folder to favorites")
            export_folder = menu.addAction("Export this folder…")
            copy_local = None
        else:
            open_action = None
            update_folder = None
            grow_level = None
            download_folder = None
            download = menu.addAction("Download")
            copy_local = menu.addAction("Copy expected local path")
        copy_action = menu.addAction("Copy source URL")
        chosen = menu.exec(self.list_widget.viewport().mapToGlobal(pos))
        if chosen == open_action:
            self._set_url(url)
        elif chosen == update_folder:
            self.update_folder_requested.emit(url)
        elif chosen == grow_level:
            self.grow_level_requested.emit(url)
        elif chosen == download_folder:
            self._download_folder(url)
        elif node.get("is_dir") and chosen == favorite_folder:
            library.add_folder(self.profile["id"], url, f"{self.profile['name']} — {node.get('name') or 'root'}")
            self.favorite_added.emit()
            self.status_label.setText("Folder added to Favorites")
        elif node.get("is_dir") and chosen == export_folder:
            self.export_subtree_requested.emit(url)
        elif not node.get("is_dir") and chosen == download:
            self._download(url, node["name"])
        elif not node.get("is_dir") and chosen == copy_local:
            QApplication.clipboard().setText(downloader.destination_preview(self.profile["name"], self._relative_to_current(node.get("parent_url") or self.current_url), node["name"]))
        elif chosen == copy_action:
            QApplication.clipboard().setText(url)

    def _relative_to_current(self, parent_url):
        base = cache.get_base_url(self.profile["id"]) or self.profile["base_url"]
        if parent_url and parent_url.startswith(base):
            return parent_url[len(base):].rstrip("/")
        return ""

    def _download_folder(self, folder_url):
        if not self.profile:
            return
        # Descendant expansion and the single batch queue write run outside
        # the UI thread in MainWindow so very large folders do not freeze the
        # browser while they are being prepared.
        self.download_folder_requested.emit(folder_url)

    def _download(self, url, name, open_after=True, group=None):
        if not self.profile:
            return
        base = cache.get_base_url(self.profile["id"]) or self.profile["base_url"]
        parent = cache.get_node(self.profile["id"], url)
        rel_parent = parent.get("parent_url") if parent else self.current_url
        rel = self._relative_to_current(rel_parent)
        downloader.enqueue(self.profile["id"], self.profile["name"], url, name, rel,
                           group_id=group["id"] if group else None,
                           group_name=group["name"] if group else None)
        if open_after:
            self.open_downloads_requested.emit()
