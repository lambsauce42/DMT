from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Property
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget


class EncounterProgressBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._base_width = 0
        self._adjusted_xp = 0
        self._target_xp = 0
        self._animation = QPropertyAnimation(self, b"value")
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(18)

        self._track_color = QColor("#2b3138")
        self._green = QColor("#3fb950")
        self._red = QColor("#f85149")
        self._marker = QColor("#e6edf3")

    def resizeEvent(self, event) -> None:
        self._base_width = max(1, self.width())
        super().resizeEvent(event)

    def get_value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        value = max(0.0, value)
        self._animation.stop()
        self._animation.setStartValue(self._value)
        self._animation.setEndValue(value)
        self._animation.start()

    def _set_value(self, value: float) -> None:
        self._value = value
        self.update()

    def set_target_values(self, adjusted_xp: int, target_xp: int) -> None:
        self._adjusted_xp = max(0, adjusted_xp)
        self._target_xp = max(0, target_xp)
        self.update()

    value = Property(float, fget=get_value, fset=_set_value)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        base_width = self._base_width or self.width()
        total_width = self.width()
        height = self.height()

        painter.fillRect(0, 0, total_width, height, self._track_color)

        effective_total = max(self._value, 100.0)
        marker_x = int(base_width * (100.0 / effective_total))
        green_width = int(base_width * (min(self._value, 100.0) / effective_total))
        if green_width > 0:
            painter.fillRect(0, 0, green_width, height, self._green)

        if self._value > 100:
            red_width = int(base_width * ((self._value - 100.0) / effective_total))
            painter.fillRect(marker_x, 0, red_width, height, self._red)

        if self._target_xp > 0:
            marker_x = max(0, min(total_width - 2, marker_x - 1))
            painter.fillRect(marker_x, 0, 2, height, self._marker)
        painter.end()
