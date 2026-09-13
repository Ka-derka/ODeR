"""Dialogs and background worker used by .oder import/export flows."""
from __future__ import annotations

import os
import hashlib
from datetime import datetime

from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QRadioButton, QTableWidget, QTableWidgetItem, QHeaderView, QVBoxLayout,
    QGridLayout, QWidget,
)

from core.library_metadata import decode_artwork_data_uri, normalize_library_metadata


_COVER_PALETTES = (
    ("#4C1D95", "#7C3AED"),
    ("#075985", "#0EA5E9"),
    ("#14532D", "#22C55E"),
    ("#7C2D12", "#F97316"),
    ("#831843", "#EC4899"),
    ("#1E3A8A", "#6366F1"),
)


def format_number(value) -> str:
    return f"{int(value or 0):,}".replace(",", "'")


def format_bytes(value: int) -> str:
    size = float(max(0, int(value or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_library_datetime(value) -> str:
    if not value:
        return "Not updated"
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return f"{parsed.year}/{parsed.month}/{parsed.day} {parsed.hour:02d}:{parsed.minute:02d}"
    except (TypeError, ValueError):
        return text


def library_version(profile) -> str:
    metadata = normalize_library_metadata((profile or {}).get("metadata"))
    version = str(metadata.get("version") or (profile or {}).get("version") or "").strip()
    return version[1:] if version.lower().startswith("v") else version


def _single_library_link(profile):
    metadata = normalize_library_metadata((profile or {}).get("metadata"))
    if "links" in metadata:
        links = [str(value).strip() for value in metadata["links"] if str(value).strip()]
    elif isinstance((profile or {}).get("links"), (list, tuple)):
        links = [str(value).strip() for value in profile["links"] if str(value).strip()]
    else:
        base_url = str((profile or {}).get("base_url") or "").strip()
        links = [base_url] if base_url else []
    return links[0] if len(links) == 1 else None


def format_made_with(name, version) -> str:
    name = str(name or "").strip() or "Unknown builder"
    version = str(version or "").strip()
    if not version or version.casefold() == "unknown":
        return f"{name} (version unknown)"
    prefix = "v" if name.casefold() == "oder" and not version.lower().startswith("v") else ""
    return f"{name} {prefix}{version}"


def library_artwork_pixmap(profile, width=160, height=100):
    metadata = normalize_library_metadata((profile or {}).get("metadata"))
    raw_artwork = (profile or {}).get("_artwork_bytes")
    artwork_path = str((profile or {}).get("odrlib_artwork_path") or "")
    if raw_artwork or (artwork_path and os.path.isfile(artwork_path)):
        source = QPixmap()
        loaded = source.loadFromData(bytes(raw_artwork)) if raw_artwork else source.load(artwork_path)
        if loaded:
            scaled = source.scaled(
                width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            left = max(0, (scaled.width() - width) // 2)
            top = max(0, (scaled.height() - height) // 2)
            return scaled.copy(left, top, width, height)
    artwork = metadata.get("artwork_data_uri")
    if artwork:
        try:
            _mime_type, data = decode_artwork_data_uri(artwork)
            source = QPixmap()
            if source.loadFromData(data):
                scaled = source.scaled(
                    width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                )
                left = max(0, (scaled.width() - width) // 2)
                top = max(0, (scaled.height() - height) // 2)
                return scaled.copy(left, top, width, height)
        except ValueError:
            pass

    pixmap = QPixmap(width, height)
    digest = hashlib.sha256(
        f"{(profile or {}).get('id', '')}:{(profile or {}).get('name', '')}".encode(
            "utf-8", "replace"
        )
    ).digest()
    start, end = _COVER_PALETTES[digest[0] % len(_COVER_PALETTES)]
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0, QColor(start))
    gradient.setColorAt(1, QColor(end))
    painter.fillRect(pixmap.rect(), gradient)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor("white"))
    font = painter.font()
    font.setPointSize(30)
    font.setBold(True)
    painter.setFont(font)
    initial = (str((profile or {}).get("name") or "L").strip()[:1] or "L").upper()
    painter.drawText(pixmap.rect(), Qt.AlignCenter, initial)
    painter.end()
    return pixmap


def library_detail_rows(profile, *, cached, index_source, last_updated, made_with):
    metadata = normalize_library_metadata((profile or {}).get("metadata"))
    rows = [("Name", str((profile or {}).get("name") or "Unnamed library"))]
    link = _single_library_link(profile)
    if link:
        rows.append(("Link", link))
    rows.extend((
        ("Creator/Curator", metadata.get("creator") or "Not provided"),
        ("Category", metadata.get("category") or "Not provided"),
        ("Tags", " · ".join(metadata.get("tags") or []) or "Not provided"),
    ))
    version = library_version(profile)
    if version:
        rows.append(("Version", version))
    extensions = [
        str(value).strip() for value in ((profile or {}).get("odrlib") or {}).get("extensions", [])
        if str(value).strip()
    ]
    if extensions:
        rows.append(("Extensions", " · ".join(extensions)))
    update_key = ((profile or {}).get("odrlib") or {}).get("update_key")
    if update_key and ((profile or {}).get("odrlib") or {}).get("update_protocol") == "U1.1":
        rows.append(("Publisher fingerprint", str(update_key.get("key_id", "Unknown"))))
        rows.append(("Update security", "U1.1 · Explicit publisher trust required before online updates"))
    rows.extend((
        ("Cached", cached),
        ("Index Source", index_source),
        ("Last updated", format_library_datetime(last_updated)),
        ("Made with", made_with),
    ))
    return rows


class LibrarySummaryWidget(QWidget):
    """Shared artwork-and-details block used by import and information dialogs."""

    def __init__(self, heading, profile, rows, parent=None, *, compact=False):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        artwork_width, artwork_height = ((132, 84) if compact else (160, 100))
        root.setSpacing(12 if compact else 16)
        artwork = QLabel()
        artwork.setObjectName("librarySummaryArtwork")
        artwork.setFixedSize(artwork_width, artwork_height)
        artwork.setAlignment(Qt.AlignCenter)
        artwork.setPixmap(library_artwork_pixmap(profile, artwork_width, artwork_height))
        artwork.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(artwork, 0, Qt.AlignTop)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(6 if compact else 9)
        title = QLabel(heading)
        title.setObjectName("pageTitle")
        content.addWidget(title)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(3 if compact else 5)
        self.value_labels = {}
        for row, (label, value) in enumerate(rows):
            key = QLabel(f"{label}:")
            key.setObjectName("libraryDetailKey")
            key.setAlignment(Qt.AlignTop | Qt.AlignRight)
            text = QLabel(str(value))
            text.setObjectName("libraryDetailValue")
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(key, row, 0)
            grid.addWidget(text, row, 1)
            self.value_labels[label] = text
        grid.setColumnStretch(1, 1)
        content.addLayout(grid)
        description = normalize_library_metadata((profile or {}).get("metadata")).get("description")
        if description:
            description_label = QLabel(description)
            description_label.setObjectName("mutedLabel")
            description_label.setWordWrap(True)
            content.addWidget(description_label)
        root.addLayout(content, 1)


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
            f"{format_number(entries)} cached entries · {format_number(folders)} folders · "
            f"{format_number(files)} files · {format_bytes(size)} on disk. "
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
        self.setWindowTitle("Import ODeR Library")
        self.setMinimumWidth(720)
        self._conflicts = list(conflicts)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        scope_label = "Folder subtree" if info.scope == "subtree" else "Full library"
        if info.has_cache:
            cached = (
                f"{format_number(info.cache_entries)} entries · "
                f"{format_number(info.cache_folders)} folders · "
                f"{format_number(info.cache_files)} files · {format_bytes(info.cache_size)}"
            )
            index_source = f"{scope_label} .oder package"
        else:
            cached = "Not included"
            index_source = "Library definition only"
        cache_state = info.profile.get("cache_state") or {}
        rows = library_detail_rows(
            info.profile,
            cached=cached,
            index_source=index_source,
            last_updated=cache_state.get("last_crawled") or info.profile.get("last_crawled"),
            made_with=format_made_with(info.app_name, info.app_version),
        )
        summary = LibrarySummaryWidget("Import ODeR Library?", info.profile, rows)
        summary.setToolTip(os.path.basename(info.path))
        root.addWidget(summary)

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


class ImportOdrLibDialog(QDialog):
    """Preview a fully validated curated library and choose conflict handling."""

    def __init__(self, preview, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import ODeR Library")
        self.setMinimumWidth(740)
        self._conflicts = list(preview.conflicts)
        info = preview.package
        profile = preview.profile
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        cached = (
            f"{format_number(info.item_count)} files · "
            f"{format_number(info.collection_count)} folders · "
            f"{format_number(info.artifact_count)} downloads · "
            f"{format_bytes(info.embedded_bytes)} bundled"
        )
        rows = library_detail_rows(
            profile,
            cached=cached,
            index_source="Curated .odrlib package",
            last_updated=info.library.get("updated_at") or info.created_at,
            made_with=format_made_with(info.created_by_name, info.created_by_version),
        )
        summary = LibrarySummaryWidget("Import ODeR Library?", profile, rows)
        summary.setToolTip(os.path.basename(info.path))
        root.addWidget(summary)

        self.conflict_choice = QComboBox()
        if self._conflicts:
            warning = QLabel(
                "This curated library is already installed. Importing a separate copy is safest; "
                "replacing updates the installed catalog and preserves downloaded files."
            )
            warning.setObjectName("mutedLabel")
            warning.setWordWrap(True)
            root.addWidget(warning)
            self.conflict_choice.addItem("Import as a separate copy", ("copy", None))
            for existing in self._conflicts:
                current = existing.get("odrlib") or {}
                self.conflict_choice.addItem(
                    f"Replace {existing.get('name', 'installed library')} "
                    f"(revision {current.get('revision', '?')} → {info.revision})",
                    ("replace", existing.get("id")),
                )
            root.addWidget(self.conflict_choice)
        else:
            self.conflict_choice.addItem("Import library", ("error", None))
            self.conflict_choice.hide()

        validation = QLabel(
            "The package layout, required capabilities, catalog references, sizes, and SHA-256 "
            "checksums have been validated. Files are never run automatically."
        )
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


class LibraryInformationDialog(QDialog):
    def __init__(self, profile, counts, index_source, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ODeR Library Information")
        self.setMinimumWidth(620)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        items = max(0, int((counts or {}).get("entries", 0)) - 1)
        cached = (
            f"{format_number(items)} items · "
            f"{format_number((counts or {}).get('folders', 0))} folders · "
            f"{format_number((counts or {}).get('files', 0))} files"
        )
        created_with = profile.get("created_with") or {"name": "ODeR", "version": ""}
        rows = library_detail_rows(
            profile,
            cached=cached,
            index_source=index_source,
            last_updated=profile.get("last_crawled"),
            made_with=format_made_with(created_with.get("name"), created_with.get("version")),
        )
        self.summary = LibrarySummaryWidget("ODeR Library Information", profile, rows, compact=True)
        root.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


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
            f"Added: {format_number(comparison.new_count)} · Removed: {format_number(comparison.removed_count)} · "
            f"Changed: {format_number(comparison.changed_count)} · "
            f"Unchanged: {format_number(max(0, comparison.left.cache_entries - comparison.removed_count - comparison.changed_count))}"
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
