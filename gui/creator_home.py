"""A focused start workspace for Creator; authoring tools live in the editor."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.creator_state import recent_projects


class CreatorHomePage(QWidget):
    create_from_folder = Signal()
    open_project = Signal()
    blank_project = Signal()
    recent_project = Signal(str)
    resume_project = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("creatorHome")
        # Only typography and spacing are local; colors come from the app theme.
        self.setStyleSheet("""
            QLabel#creatorHomeHeading { font-size: 34px; font-weight: 700; }
            QLabel#creatorHomeEyebrow { font-size: 12px; font-weight: 600; }
            QTreeWidget#creatorRecentProjects::item { padding: 11px 8px; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        surface = QWidget()
        surface_layout = QHBoxLayout(surface)
        surface_layout.setContentsMargins(32, 34, 32, 28)
        content = QWidget()
        content.setMaximumWidth(1120)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        surface_layout.addStretch(1)
        surface_layout.addWidget(content, 30)
        surface_layout.addStretch(1)
        scroll.setWidget(surface)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(20)

        eyebrow = QLabel("ODeR Creator / Home")
        eyebrow.setObjectName("creatorHomeEyebrow")
        root.addWidget(eyebrow)
        heading = QLabel("Your next library starts here.")
        heading.setObjectName("creatorHomeHeading")
        heading.setWordWrap(True)
        root.addWidget(heading)
        description = QLabel("Choose your files, make it yours, and create something to share.")
        description.setObjectName("mutedLabel")
        description.setWordWrap(True)
        root.addWidget(description)

        actions = QHBoxLayout()
        actions.setSpacing(14)
        folder_card, self.folder_button = self._action_card(
            "Start with your files", "Bring a folder and its subfolders into a new library.",
            "Create from folder…", self.create_from_folder.emit, primary=True,
        )
        open_card, self.open_button = self._action_card(
            "Continue a project", "Open a saved Creator project and pick up where you left off.",
            "Open project…", self.open_project.emit,
        )
        blank_card, self.blank_button = self._action_card(
            "Build your own", "Start empty and add files or online sources as you go.",
            "Blank library", self.blank_project.emit,
        )
        actions.addWidget(folder_card, 1)
        actions.addWidget(open_card, 1)
        actions.addWidget(blank_card, 1)
        root.addLayout(actions)

        self.resume_card = QFrame()
        self.resume_card.setObjectName("card")
        resume_layout = QHBoxLayout(self.resume_card)
        resume_layout.setContentsMargins(18, 14, 18, 14)
        resume_text = QVBoxLayout()
        resume_heading = QLabel("CURRENT PROJECT")
        resume_heading.setObjectName("mutedLabel")
        resume_text.addWidget(resume_heading)
        self.current_project_label = QLabel()
        self.current_project_label.setObjectName("cardTitle")
        self.current_project_label.setTextFormat(Qt.PlainText)
        self.current_project_label.setWordWrap(True)
        resume_text.addWidget(self.current_project_label)
        resume_layout.addLayout(resume_text, 1)
        self.resume_button = QPushButton("Resume project")
        self.resume_button.clicked.connect(self.resume_project.emit)
        resume_layout.addWidget(self.resume_button)
        root.addWidget(self.resume_card)
        self.set_current_project(None)

        recent_heading = QLabel("Recent projects")
        recent_heading.setObjectName("pageTitle")
        root.addWidget(recent_heading)
        self.empty_recent = QLabel("Your saved projects will appear here. Start with a folder or open an existing project.")
        self.empty_recent.setWordWrap(True)
        self.empty_recent.setObjectName("mutedLabel")
        root.addWidget(self.empty_recent)
        self.recent_hint = QLabel("Double-click a project to open it.")
        self.recent_hint.setObjectName("mutedLabel")
        root.addWidget(self.recent_hint)
        self.recent_list = QTreeWidget()
        self.recent_list.setObjectName("creatorRecentProjects")
        self.recent_list.setHeaderLabels(["Project", "Folder"])
        self.recent_list.setRootIsDecorated(False)
        self.recent_list.setAlternatingRowColors(True)
        self.recent_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.recent_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.recent_list.setUniformRowHeights(True)
        self.recent_list.setMinimumHeight(180)
        self.recent_list.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.recent_list.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.recent_list.setColumnWidth(0, 280)
        self.recent_list.itemActivated.connect(self._open_recent)
        root.addWidget(self.recent_list, 1)
        root.addStretch(1)
        self.refresh_recent()

    @staticmethod
    def _action_card(title, description, button_text, callback, *, primary=False):
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumWidth(190)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        label = QLabel(title)
        label.setObjectName("cardTitle")
        label.setWordWrap(True)
        layout.addWidget(label)
        hint = QLabel(description)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        button = QPushButton(button_text)
        if primary:
            button.setObjectName("accentButton")
        button.clicked.connect(callback)
        layout.addWidget(button)
        return card, button

    def set_current_project(self, name: str | None):
        self.current_project_label.setText(name or "")
        self.resume_card.setVisible(name is not None)

    def refresh_recent(self):
        self.recent_list.clear()
        projects = recent_projects()
        for path in projects:
            available = os.path.isfile(path)
            filename = os.path.basename(path)
            item = QTreeWidgetItem([
                filename if available else f"{filename} — unavailable",
                os.path.dirname(path),
            ])
            item.setData(0, Qt.UserRole, path)
            item.setToolTip(0, path if available else f"Project not found at this location:\n{path}")
            item.setToolTip(1, os.path.dirname(path))
            if not available:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable)
            self.recent_list.addTopLevelItem(item)
        self.empty_recent.setVisible(not projects)
        self.recent_hint.setVisible(bool(projects))
        self.recent_list.setVisible(bool(projects))

    def _open_recent(self, item, _column):
        if item.flags() & Qt.ItemIsEnabled:
            path = item.data(0, Qt.UserRole)
            if path:
                self.recent_project.emit(path)
