"""A focused hand-off screen for a successfully published Creator library."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSizePolicy, QToolButton, QVBoxLayout,
)

from core.odrlib import BuildResult
from gui.package_dialogs import format_bytes, format_number


def sharing_instructions(result: BuildResult, *, source_folder: str = "") -> str:
    """Describe the actual build outputs, including the two distinct torrents."""
    package_name = os.path.basename(result.path)
    lines = [
        f"Sharing {result.package.name}",
        "",
        f"Share {package_name}. Recipients can open it in ODeR to add the library.",
    ]
    if result.torrent_path:
        lines.extend([
            "",
            f"File sharing: {os.path.basename(result.torrent_path)}",
            "Open this torrent in your torrent client and verify the existing original files before seeding.",
        ])
        if source_folder:
            source_folder = os.path.abspath(source_folder)
            lines.extend([
                f"Original source folder: {source_folder}",
                f"The torrent includes that folder's name. If the client asks for a save location, use its parent: {os.path.dirname(source_folder)}",
            ])
        else:
            lines.append("Use the original source folder selected in Creator, preserving its names and subfolders.")
        lines.append("Keep your torrent client running to share the files. The .odrlib alone does not seed them.")
    if result.feed_path:
        lines.extend([
            "",
            "Publishing online updates",
            f"Upload {package_name} to the package URL configured in this project.",
        ])
    if result.update_torrent_path:
        purpose = "This torrent shares the library package."
        if result.torrent_path:
            purpose += " The file-sharing torrent shares its catalog files."
        lines.extend([
            f"Upload {os.path.basename(result.update_torrent_path)} to the update torrent URL configured in this project.",
            f"Open {os.path.basename(result.update_torrent_path)} in your torrent client. Use the output folder as its save location: {os.path.dirname(os.path.abspath(result.path))}",
            f"Verify the existing {package_name} file, then keep it seeding. {purpose}",
        ])
    if result.feed_path:
        feed_url = result.package.update_feed_url
        destination = f" to {feed_url}" if feed_url else " to the feed URL configured in this project"
        lines.extend([
            f"Publish {os.path.basename(result.feed_path)}{destination} LAST, once the package and any update torrent are available.",
            "Readers can use Check for updates in ODeR to discover the new release.",
        ])
    lines.extend(["", f"Output folder: {os.path.dirname(os.path.abspath(result.path))}"])
    return "\n".join(lines)


def _label(text: str, *, style: str = "", selectable: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    if style:
        label.setObjectName(style)
    if selectable:
        label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
    return label


class PublishResultDialog(QDialog):
    """Show the useful next steps without putting technical details in the way."""

    def __init__(self, result: BuildResult, parent=None, *, source_folder: str = ""):
        super().__init__(parent)
        self.build_result = result
        self.source_folder = source_folder
        self.setWindowTitle("Library ready to share")
        self.setMinimumWidth(520)
        self.resize(650, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)

        layout.addWidget(_label("Your library is ready to share", style="pageTitle"))
        layout.addWidget(_label(result.package.name, style="cardTitle", selectable=True))
        layout.addWidget(_label(
            f"{format_number(result.package.item_count)} files · "
            f"{format_number(result.package.collection_count)} folders · {format_bytes(result.size)}",
            style="mutedLabel",
        ))

        files_card = QFrame()
        files_card.setObjectName("card")
        files_layout = QGridLayout(files_card)
        files_layout.setContentsMargins(16, 14, 16, 14)
        files_layout.setHorizontalSpacing(16)
        files_layout.setVerticalSpacing(12)
        files_layout.setColumnStretch(1, 1)
        outputs = [("Shareable library", result.path)]
        if result.feed_path:
            outputs.append(("Update feed", result.feed_path))
        if result.torrent_path:
            outputs.append(("File-sharing torrent", result.torrent_path))
        if result.update_torrent_path:
            outputs.append(("Library-update torrent", result.update_torrent_path))
        for row, (role, path) in enumerate(outputs):
            role_label = QLabel(role)
            role_label.setObjectName("mutedLabel")
            files_layout.addWidget(role_label, row, 0, Qt.AlignTop)
            files_layout.addWidget(_label(os.path.basename(path), selectable=True), row, 1)
        layout.addWidget(files_card)

        if result.feed_path:
            hint = "Publish the library and any update torrent first, then publish the update feed. Copy the sharing instructions for the full steps."
        elif result.torrent_path:
            hint = "Share the .odrlib and keep the original files seeding in your torrent client. Copy the sharing instructions for the full steps."
        else:
            hint = "Send the .odrlib to someone, or open it in ODeR to try your library."
        layout.addWidget(_label(hint, style="mutedLabel"))

        actions = QHBoxLayout()
        self.open_folder_button = QPushButton("Open output folder")
        self.open_folder_button.clicked.connect(self._open_output_folder)
        actions.addWidget(self.open_folder_button)
        self.copy_button = QPushButton("Copy sharing instructions")
        self.copy_button.clicked.connect(self._copy_instructions)
        actions.addWidget(self.copy_button)
        self.test_button = QPushButton("Test in ODeR")
        self.test_button.setToolTip("Open the library using its installed file association.")
        self.test_button.clicked.connect(self._test_in_oder)
        actions.addWidget(self.test_button)
        layout.addLayout(actions)

        self.action_status = _label("", style="mutedLabel")
        self.action_status.hide()
        layout.addWidget(self.action_status)

        self.details_toggle = QToolButton()
        self.details_toggle.setText("Technical details")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.details_toggle.setArrowType(Qt.RightArrow)
        self.details_toggle.toggled.connect(self._toggle_details)
        layout.addWidget(self.details_toggle)
        self.technical_details = _label(
            f"Package SHA-256\n{result.sha256}\n\nSaved to\n{os.path.abspath(result.path)}",
            style="mutedLabel", selectable=True,
        )
        self.technical_details.hide()
        layout.addWidget(self.technical_details)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.done_button = QPushButton("Done")
        self.done_button.setObjectName("accentButton")
        self.done_button.setDefault(True)
        self.done_button.clicked.connect(self.accept)
        footer.addWidget(self.done_button)
        layout.addLayout(footer)

    def _toggle_details(self, expanded: bool):
        self.details_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.technical_details.setVisible(expanded)
        self.adjustSize()

    def _copy_instructions(self):
        QApplication.clipboard().setText(sharing_instructions(
            self.build_result, source_folder=self.source_folder,
        ))
        self.action_status.setText("Sharing instructions copied.")
        self.action_status.show()

    def _open_output_folder(self):
        path = os.path.dirname(os.path.abspath(self.build_result.path))
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            QMessageBox.information(self, "Open output folder", f"Open this folder in your file manager:\n\n{path}")

    def _test_in_oder(self):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(self.build_result.path))):
            QMessageBox.information(
                self, "Open in ODeR",
                "No application could open this library. Install ODeR, or open ODeR and drag the .odrlib from the output folder into its window.",
            )
