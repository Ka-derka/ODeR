"""Dialogs and background worker used by .oder import/export flows."""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QRadioButton, QTableWidget, QTableWidgetItem, QHeaderView, QVBoxLayout,
)


def format_bytes(value: int) -> str:
    size = float(max(0, int(value or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class PackageTask(QObject):
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, token, operation):
        super().__init__()
        self.token = token
        self.operation = operation

    @Slot()
    def run(self):
        try:
            result = self.operation()
        except Exception as exc:
            self.failed.emit(self.token, str(exc) or exc.__class__.__name__)
        else:
            self.finished.emit(self.token, result)


class ExportDirectoryDialog(QDialog):
    def __init__(self, profile, cache_stats, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export ODeR library")
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel(f"Export {profile['name']}")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        url = QLabel(profile.get("base_url", ""))
        url.setObjectName("mutedLabel")
        url.setWordWrap(True)
        root.addWidget(url)

        definition_card = QFrame()
        definition_card.setObjectName("card")
        definition_layout = QVBoxLayout(definition_card)
        self.definition = QRadioButton("Library definition only")
        definition_layout.addWidget(self.definition)
        definition_text = QLabel("URL, name, artwork, descriptive metadata, crawl settings, and download settings. The imported library must be indexed separately.")
        definition_text.setObjectName("mutedLabel")
        definition_text.setWordWrap(True)
        definition_layout.addWidget(definition_text)
        root.addWidget(definition_card)

        full_card = QFrame()
        full_card.setObjectName("card")
        full_layout = QVBoxLayout(full_card)
        self.full = QRadioButton("Include cached index")
        full_layout.addWidget(self.full)
        entries = int(cache_stats.get("entries", 0))
        folders = int(cache_stats.get("folders", 0))
        files = int(cache_stats.get("files", 0))
        size = int(cache_stats.get("size", 0))
        full_text = QLabel(
            f"{entries:,} cached entries · {folders:,} folders · {files:,} files · {format_bytes(size)} on disk. "
            "The imported library can be browsed immediately."
        )
        full_text.setObjectName("mutedLabel")
        full_text.setWordWrap(True)
        full_layout.addWidget(full_text)
        root.addWidget(full_card)

        has_cache = bool(cache_stats.get("available"))
        self.full.setEnabled(has_cache)
        self.full.setChecked(has_cache)
        self.definition.setChecked(not has_cache)
        if not has_cache:
            self.full.setToolTip("Update or progressively browse this library before exporting its cached index.")

        note = QLabel("The .oder file contains library metadata only; downloaded files are never included.")
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        export_button = buttons.addButton("Export .oder", QDialogButtonBox.AcceptRole)
        export_button.setObjectName("accentButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def include_cache(self):
        return self.full.isChecked() and self.full.isEnabled()


class ImportDirectoryDialog(QDialog):
    def __init__(self, info, conflicts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import ODeR library")
        self.setMinimumWidth(560)
        self._conflicts = list(conflicts)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("Import ODeR library")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        filename = QLabel(os.path.basename(info.path))
        filename.setObjectName("mutedLabel")
        root.addWidget(filename)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        name = QLabel(info.name)
        name.setObjectName("cardTitle")
        card_layout.addWidget(name)
        url = QLabel(info.base_url)
        url.setObjectName("cardMeta")
        url.setWordWrap(True)
        card_layout.addWidget(url)
        scope_label = "Folder subtree" if info.scope == "subtree" else "Full library"
        if info.has_cache:
            contents = (
                f"{scope_label} package · {info.cache_entries:,} entries · "
                f"{info.cache_folders:,} folders · {info.cache_files:,} files · {format_bytes(info.cache_size)}"
            )
        else:
            contents = "Library definition only · no cached index"
        details = QLabel(f"{contents}\nExported {info.created_at} with ODeR {info.app_version}")
        details.setObjectName("cardMeta")
        details.setWordWrap(True)
        card_layout.addWidget(details)
        root.addWidget(card)

        self.conflict_choice = QComboBox()
        if self._conflicts:
            warning = QLabel("A matching library already exists. Importing as a copy is the safe default; replacing keeps downloaded files and replaces the cached index only when this package includes one.")
            warning.setObjectName("mutedLabel")
            warning.setWordWrap(True)
            root.addWidget(warning)
            self.conflict_choice.addItem("Import as a separate copy", ("copy", None))
            for existing in self._conflicts:
                reason = existing.get("_conflict_reason", "matching library")
                self.conflict_choice.addItem(
                    f"Replace {existing.get('name', 'existing library')} ({reason})",
                    ("replace", existing.get("id")),
                )
            root.addWidget(self.conflict_choice)
        else:
            self.conflict_choice.addItem("Import library", ("error", None))
            self.conflict_choice.hide()

        validation = QLabel("The package manifest, checksums, layout, and SQLite index have been validated.")
        validation.setObjectName("mutedLabel")
        validation.setWordWrap(True)
        root.addWidget(validation)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        import_button = buttons.addButton("Import", QDialogButtonBox.AcceptRole)
        import_button.setObjectName("accentButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_policy(self):
        value = self.conflict_choice.currentData()
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return value[0], value[1]
        return "error", None


class PackageComparisonDialog(QDialog):
    def __init__(self, comparison, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compare ODeR packages")
        self.resize(850, 600)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        title = QLabel("Package comparison")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        summary = QLabel(
            f"{comparison.left.name}  ↔  {comparison.right.name}\n"
            f"Added: {comparison.new_count:,} · Removed: {comparison.removed_count:,} · "
            f"Changed: {comparison.changed_count:,} · "
            f"Unchanged: {max(0, comparison.left.cache_entries - comparison.removed_count - comparison.changed_count):,}"
        )
        summary.setWordWrap(True)
        root.addWidget(summary)
        if comparison.definition_differences:
            definition = QLabel("Definition differences: " + ", ".join(comparison.definition_differences))
            definition.setObjectName("mutedLabel")
            definition.setWordWrap(True)
            root.addWidget(definition)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Change", "Path", "Details"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        for change in comparison.changes:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(change.get("change_type", ""))))
            table.setItem(row, 1, QTableWidgetItem(str(change.get("url", ""))))
            details = f"{change.get('old_size') or '—'} → {change.get('new_size') or '—'}"
            table.setItem(row, 2, QTableWidgetItem(details))
        root.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
