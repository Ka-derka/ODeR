"""A lightweight, resolution-independent startup card for ODeR Creator."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from core.version import CREATOR_NAME, CREATOR_VERSION


class CreatorSplashScreen(QSplashScreen):
    """Report real startup stages without holding the application open."""

    WIDTH = 660
    HEIGHT = 388

    def __init__(self):
        screen = QApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen else 1.0
        canvas = QPixmap(round(self.WIDTH * ratio), round(self.HEIGHT * ratio))
        canvas.setDevicePixelRatio(ratio)
        canvas.fill(QColor("#17171c"))
        painter = QPainter(canvas)
        try:
            self._paint_card(painter)
        finally:
            painter.end()
        super().__init__(canvas)
        self.setWindowTitle(CREATOR_NAME)
        self.setAccessibleName(f"{CREATOR_NAME} startup")
        self.setAccessibleDescription(f"{CREATOR_NAME} {CREATOR_VERSION}")

    @staticmethod
    def _font(size, weight=QFont.Weight.Normal):
        font = QApplication.font()
        font.setPixelSize(size)
        font.setWeight(weight)
        return font

    def _paint_card(self, painter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # All artwork is drawn in logical pixels, so the startup card stays
        # sharp on high-DPI displays without shipping a separate image asset.
        art = QLinearGradient(360, 0, self.WIDTH, self.HEIGHT)
        art.setColorAt(0, QColor("#29203f"))
        art.setColorAt(1, QColor("#11111a"))
        painter.fillRect(QRectF(366, 0, 294, self.HEIGHT), art)
        painter.save()
        painter.setClipRect(QRectF(366, 0, 294, self.HEIGHT))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for radius, alpha in ((158, 30), (114, 45), (72, 65)):
            painter.setPen(QPen(QColor(179, 151, 250, alpha), 1))
            painter.drawEllipse(QRectF(525 - radius, 186 - radius, radius * 2, radius * 2))

        for x, y, angle, color in (
            (422, 96, -17, "#554278"),
            (438, 114, -5, "#7956ba"),
            (452, 132, 8, "#a080ef"),
        ):
            painter.save()
            painter.translate(x, y)
            painter.rotate(angle)
            face = QLinearGradient(0, 0, 130, 150)
            face.setColorAt(0, QColor(color).lighter(115))
            face.setColorAt(1, QColor(color).darker(135))
            painter.setPen(QPen(QColor(229, 219, 255, 55), 1))
            painter.setBrush(face)
            painter.drawRoundedRect(QRectF(0, 0, 132, 154), 12, 12)
            painter.setPen(QPen(QColor(247, 240, 255, 140), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            folder = QPainterPath()
            folder.moveTo(29, 56)
            folder.lineTo(29, 98)
            folder.quadTo(29, 103, 34, 103)
            folder.lineTo(98, 103)
            folder.quadTo(103, 103, 103, 98)
            folder.lineTo(103, 62)
            folder.quadTo(103, 57, 98, 57)
            folder.lineTo(65, 57)
            folder.lineTo(58, 49)
            folder.lineTo(34, 49)
            folder.quadTo(29, 49, 29, 56)
            painter.drawPath(folder)
            painter.restore()
        painter.restore()

        painter.setPen(QPen(QColor("#45404f"), 1))
        painter.setBrush(QColor("#282032"))
        painter.drawRoundedRect(QRectF(34, 32, 43, 43), 9, 9)
        painter.setPen(QColor("#c5a7ff"))
        painter.setFont(self._font(21, QFont.Weight.DemiBold))
        painter.drawText(QRectF(34, 32, 43, 43), Qt.AlignmentFlag.AlignCenter, "Cr")
        painter.setPen(QColor("#aaa6b3"))
        painter.setFont(self._font(11, QFont.Weight.DemiBold))
        painter.drawText(QRectF(90, 33, 230, 42), Qt.AlignmentFlag.AlignVCenter, "THE ODeR CREATIVE WORKSPACE")

        painter.setPen(QColor("#f6f3fb"))
        painter.setFont(self._font(39, QFont.Weight.DemiBold))
        painter.drawText(QRectF(32, 111, 315, 57), "ODeR Creator")
        painter.setPen(QColor("#b8b3c2"))
        painter.setFont(self._font(16))
        painter.drawText(QRectF(34, 180, 280, 61), "Shape your library.\nShare what matters.")

        painter.setPen(QPen(QColor("#36313f"), 1))
        painter.drawLine(34, 293, 329, 293)
        painter.setPen(QColor("#8f899b"))
        painter.setFont(self._font(11))
        painter.drawText(QRectF(34, 351, 290, 19), f"Version {CREATOR_VERSION}")
        painter.setPen(QPen(QColor("#3b3348"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(0.5, 0.5, self.WIDTH - 1, self.HEIGHT - 1))

    def drawContents(self, painter):
        painter.setPen(QColor("#c4b8d7"))
        painter.setFont(self._font(12))
        painter.drawText(QRectF(34, 309, 296, 27), Qt.AlignmentFlag.AlignVCenter, self.message())

    def set_status(self, text):
        """Paint the next real startup step before its synchronous work starts."""
        self.setAccessibleDescription(f"{CREATOR_NAME} {CREATOR_VERSION}. {text}")
        self.showMessage(text)
        QApplication.processEvents()
