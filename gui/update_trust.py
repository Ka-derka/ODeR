"""An explicit, local trust decision. Opening this dialog performs no network I/O."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class PublisherTrustDialog(QDialog):
    def __init__(self, fingerprint, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trust this library's publisher?")
        self.resize(540, 300)
        layout = QVBoxLayout(self)
        for text in (
            "ODeR has not independently verified this publisher's identity. Compare this fingerprint "
            "with one received from the curator through a trusted, separate channel.",
            fingerprint,
            "Trusting a key allows it to authorize future updates for this library. A signature protects "
            "the update's integrity; HTTP still exposes requests and downloads to the network. "
            "Importing alone does not grant trust. Files are never run automatically.",
        ):
            label = QLabel(text)
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(label)
        self.confirm = QCheckBox("I trust this key to publish updates for this library")
        layout.addWidget(self.confirm)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.trust_button = buttons.button(QDialogButtonBox.Ok)
        self.trust_button.setText("Trust publisher")
        self.trust_button.setEnabled(False)
        buttons.button(QDialogButtonBox.Cancel).setDefault(True)
        self.confirm.toggled.connect(self.trust_button.setEnabled)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
