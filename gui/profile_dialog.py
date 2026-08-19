from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QSpinBox, QCheckBox,
    QDialogButtonBox, QVBoxLayout, QLabel
)


class ProfileDialog(QDialog):
    """Add or edit a profile. Pass `profile` (a dict) to edit; omit to create new."""

    def __init__(self, parent=None, profile=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Site" if profile else "Add Site")
        self.setMinimumWidth(420)
        self._profile = profile

        settings = (profile or {}).get("settings", {})

        self.name_edit = QLineEdit((profile or {}).get("name", ""))
        self.url_edit = QLineEdit((profile or {}).get("base_url", ""))
        self.url_edit.setPlaceholderText("https://example.com/files/")

        self.auto_detect = QCheckBox("Auto-detect existing index before crawling")
        self.auto_detect.setChecked(settings.get("auto_detect_index", True))

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

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Base URL", self.url_edit)
        form.addRow(self.auto_detect)
        form.addRow(QLabel("<b>Crawl settings</b>"))
        form.addRow("Delay per worker request", self.crawl_delay)
        form.addRow("Concurrent folder requests", self.crawl_concurrency)
        form.addRow("Backoff if blocked/rate-limited", self.retry_backoff)
        form.addRow("Max retries before giving up", self.max_retries)
        form.addRow(QLabel("<b>Download settings</b>"))
        form.addRow("Delay between download starts", self.download_delay)
        form.addRow("Max concurrent downloads", self.max_concurrent)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def result_data(self):
        return {
            "name": self.name_edit.text().strip(),
            "base_url": self.url_edit.text().strip(),
            "settings": {
                "auto_detect_index": self.auto_detect.isChecked(),
                "crawl_delay_seconds": self.crawl_delay.value(),
                "crawl_concurrency": self.crawl_concurrency.value(),
                "crawl_retry_on_block_seconds": self.retry_backoff.value(),
                "max_crawl_retries": self.max_retries.value(),
                "download_delay_seconds": self.download_delay.value(),
                "max_concurrent_downloads": self.max_concurrent.value(),
            },
        }
