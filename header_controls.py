"""Scalable header buttons and a resolution-independent video camera symbol."""
import re
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton


class HeaderButton(QPushButton):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self._header_size = 42
        self._header_style = ''
        self.setHeaderSize(42)

    def setStyleSheet(self, style):
        self._header_style = style
        self._apply_header_style()

    def setHeaderSize(self, size):
        self._header_size = int(size)
        self._apply_header_style()
        self.setFixedSize(size, size)

    def _apply_header_style(self):
        scale = self._header_size / 42
        defaults = ('QPushButton { padding:0; min-width:42px; min-height:42px; '
                    'border-radius:21px; font-size:20px; }')
        style = defaults + self._header_style
        style = re.sub(r'(font-size|border-radius|min-width|min-height)\s*:\s*([\d.]+)px',
                       lambda match: f'{match[1]}:{float(match[2]) * scale:.2f}px', style)
        # Qt stylesheet sizes describe the content box, excluding the border.
        borders = re.findall(r'border\s*:\s*([\d.]+)px', self._header_style)
        border = float(borders[0]) if borders else 1
        inner = max(1, self._header_size - 2 * border)
        dimensions = (f'QPushButton {{ min-width:{inner}px; max-width:{inner}px; '
                      f'min-height:{inner}px; max-height:{inner}px; }}')
        super().setStyleSheet(style + dimensions)


class VideoButton(HeaderButton):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(self.width() / 42, self.height() / 42)
        color = '#777777' if not self.isEnabled() else '#ff9b45' if self.isChecked() else '#ffffff'
        painter.setPen(QPen(QColor(color), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(-11, -7, 14, 14, 3, 3)
        lens = QPainterPath()
        lens.moveTo(3, -3)
        lens.lineTo(11, -7)
        lens.lineTo(11, 7)
        lens.lineTo(3, 3)
        painter.drawPath(lens)
        painter.end()
