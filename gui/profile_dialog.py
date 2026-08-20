from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QSpinBox, QCheckBox,
    QDialogButtonBox, QVBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QFileDialog, QMessageBox, QHBoxLayout, QWidget, QTabWidget
)

from core.library_metadata import (
    MAX_ARTWORK_BYTES, artwork_data_uri, decode_artwork_data_uri,
    normalize_library_metadata,
)


class ProfileDialog(QDialog):
    """Add or edit a profile. Pass `profile` (a dict) to edit; omit to create new."""

    def __init__(self, parent=None, profile=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Library" if profile else "Add Library")
        self.setMinimumWidth(580)
        self.resize(640, 660)
        self._profile = profile

        settings = (profile or {}).get("settings", {})
        metadata = normalize_library_metadata((profile or {}).get("metadata"))
        self._artwork_data_uri = metadata.get("artwork_data_uri", "")

        self.name_edit = QLineEdit((profile or {}).get("name", ""))
        self.url_edit = QLineEdit((profile or {}).get("base_url", ""))
        self.url_edit.setPlaceholderText("https://example.com/files/")

        self.description_edit = QPlainTextEdit(metadata.get("description", ""))
        self.description_edit.setPlaceholderText("What this library contains and why it is useful")
        self.description_edit.setFixedHeight(90)
        self.creator_edit = QLineEdit(metadata.get("creator", ""))
        self.creator_edit.setPlaceholderText("Optional creator or curator")
        self.category_edit = QLineEdit(metadata.get("category", ""))
        self.category_edit.setPlaceholderText("For example: Software, Films, Books")
        self.tags_edit = QLineEdit(", ".join(metadata.get("tags") or []))
        self.tags_edit.setPlaceholderText("Comma-separated tags")

        artwork_controls = QWidget()
        artwork_layout = QHBoxLayout(artwork_controls)
        artwork_layout.setContentsMargins(0, 0, 0, 0)
        artwork_layout.setSpacing(8)
        choose_artwork = QPushButton("Choose image…")
        choose_artwork.clicked.connect(self._choose_artwork)
        self.remove_artwork = QPushButton("Remove")
        self.remove_artwork.clicked.connect(self._clear_artwork)
        artwork_layout.addWidget(choose_artwork)
        artwork_layout.addWidget(self.remove_artwork)
        artwork_layout.addStretch(1)
        self.artwork_preview = QLabel()
        self.artwork_preview.setFixedSize(220, 112)
        self.artwork_preview.setAlignment(Qt.AlignCenter)
        self.artwork_preview.setObjectName("libraryArtworkPreview")
        self._update_artwork_preview()

        self.auto_detect = QCheckBox("Auto-detect hosted .oder and other indexes before crawling")
        self.auto_detect.setChecked(settings.get("auto_detect_index", True))

        self.hosted_oder_url = QLineEdit(str(settings.get("hosted_oder_url") or ""))
        self.hosted_oder_url.setPlaceholderText("Optional: https://cdn.example.com/archive/index.oder")
        self.hosted_oder_url.setToolTip(
            "Exact URL of a full .oder package. Leave blank to discover index.oder or an advertised package."
        )
        hosted_help = QLabel(
            "Leave blank for automatic root/HTML discovery. Only validated full packages matching this Base URL are loaded."
        )
        hosted_help.setObjectName("mutedLabel")
        hosted_help.setWordWrap(True)

        self.crawl_delay = QDoubleSpinBox()
        self.crawl_delay.setRange(0.0, 60.0)
        self.crawl_delay.setSingleStep(0.5)
        self.crawl_delay.setSuffix(" s")
        self.crawl_delay.setValue(settings.get("crawl_delay_seconds", 1.5))


        self.crawl_concurrency = QSpinBox()
        self.crawl_concurrency.setRange(1, 32)
        self.crawl_concurrency.setValue(settings.get("crawl_concurrency", 8))
        self.crawl_concurrency.setToolTip("Number of directory listings fetched at the same time. Lower this if the server rate-limits you.")

        self.retry_backoff = QDoubleSpinBox()
        self.retry_backoff.setRange(1.0, 3600.0)
        self.retry_backoff.setSuffix(" s")
        self.retry_backoff.setValue(settings.get("crawl_retry_on_block_seconds", 60))

        self.max_retries = QSpinBox()
        self.max_retries.setRange(0, 20)
        self.max_retries.setValue(settings.get("max_crawl_retries", 3))

        self.download_delay = QDoubleSpinBox()
        self.download_delay.setRange(0.0, 60.0)
        self.download_delay.setSingleStep(0.5)
        self.download_delay.setSuffix(" s")
        self.download_delay.setValue(settings.get("download_delay_seconds", 2.0))

        self.max_concurrent = QSpinBox()
        self.max_concurrent.setRange(1, 20)
        self.max_concurrent.setValue(settings.get("max_concurrent_downloads", 1))

        library_tab = QWidget()
        library_form = QFormLayout(library_tab)
        library_form.addRow("Name", self.name_edit)
        library_form.addRow("Base URL", self.url_edit)
        library_form.addRow("Artwork", artwork_controls)
        library_form.addRow("", self.artwork_preview)
        library_form.addRow("Description", self.description_edit)
        library_form.addRow("Creator / curator", self.creator_edit)
        library_form.addRow("Category", self.category_edit)
        library_form.addRow("Tags", self.tags_edit)

        network_tab = QWidget()
        network_form = QFormLayout(network_tab)
        network_form.addRow(self.auto_detect)
        network_form.addRow("Hosted .oder URL", self.hosted_oder_url)
        network_form.addRow(hosted_help)
        network_form.addRow(QLabel("<b>Crawl settings</b>"))
        network_form.addRow("Delay per worker request", self.crawl_delay)
        network_form.addRow("Concurrent folder requests", self.crawl_concurrency)
        network_form.addRow("Backoff if blocked/rate-limited", self.retry_backoff)
        network_form.addRow("Max retries before giving up", self.max_retries)
        network_form.addRow(QLabel("<b>Download settings</b>"))
        network_form.addRow("Delay between download starts", self.download_delay)
        network_form.addRow("Max concurrent downloads", self.max_concurrent)

        tabs = QTabWidget()
        tabs.addTab(library_tab, "Library details")
        tabs.addTab(network_tab, "Indexing & downloads")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    @staticmethod
    def _encoded_jpeg(image):
        image = image.scaled(960, 640, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        for attempt in range(4):
            canvas = QImage(image.size(), QImage.Format_RGB32)
            canvas.fill(QColor("#20242C"))
            painter = QPainter(canvas)
            painter.drawImage(0, 0, image)
            painter.end()
            for quality in (88, 78, 66, 54):
                payload = QByteArray()
                buffer = QBuffer(payload)
                buffer.open(QIODevice.WriteOnly)
                saved = canvas.save(buffer, "JPEG", quality)
                buffer.close()
                data = bytes(payload)
                if saved and data and len(data) <= MAX_ARTWORK_BYTES:
                    return artwork_data_uri("image/jpeg", data)
            image = image.scaled(
                max(1, int(image.width() * 0.75)),
                max(1, int(image.height() * 0.75)),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        raise ValueError("The selected image could not be reduced below the 1 MiB artwork limit.")

    def _choose_artwork(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose library artwork",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)",
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "Artwork not loaded", "Choose a valid image file.")
            return
        try:
            self._artwork_data_uri = self._encoded_jpeg(image)
        except ValueError as exc:
            QMessageBox.warning(self, "Artwork not loaded", str(exc))
            return
        self._update_artwork_preview()

    def _clear_artwork(self):
        self._artwork_data_uri = ""
        self._update_artwork_preview()

    def _update_artwork_preview(self):
        self.remove_artwork.setEnabled(bool(self._artwork_data_uri))
        if not self._artwork_data_uri:
            self.artwork_preview.setPixmap(QPixmap())
            self.artwork_preview.setText("Generated cover will be used")
            return
        try:
            _mime_type, data = decode_artwork_data_uri(self._artwork_data_uri)
        except ValueError:
            self._artwork_data_uri = ""
            self.artwork_preview.setPixmap(QPixmap())
            self.artwork_preview.setText("Generated cover will be used")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self._artwork_data_uri = ""
            self.artwork_preview.setPixmap(QPixmap())
            self.artwork_preview.setText("Generated cover will be used")
            return
        self.artwork_preview.setText("")
        self.artwork_preview.setPixmap(
            pixmap.scaled(
                self.artwork_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

    def result_data(self):
        metadata = normalize_library_metadata({
            "description": self.description_edit.toPlainText(),
            "creator": self.creator_edit.text(),
            "category": self.category_edit.text(),
            "tags": self.tags_edit.text().split(","),
            "artwork_data_uri": self._artwork_data_uri,
        })
        return {
            "name": self.name_edit.text().strip(),
            "base_url": self.url_edit.text().strip(),
            "metadata": metadata,
            "settings": {
                "auto_detect_index": self.auto_detect.isChecked(),
                "hosted_oder_url": self.hosted_oder_url.text().strip(),
                "crawl_delay_seconds": self.crawl_delay.value(),
                "crawl_concurrency": self.crawl_concurrency.value(),
                "crawl_retry_on_block_seconds": self.retry_backoff.value(),
                "max_crawl_retries": self.max_retries.value(),
                "download_delay_seconds": self.download_delay.value(),
                "max_concurrent_downloads": self.max_concurrent.value(),
            },
        }
