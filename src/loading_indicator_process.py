from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QWidget


class CircularLoadingSpinner(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self.setFixedSize(18, 18)
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def _advance(self) -> None:
        self._angle = (self._angle + 24) % 360
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#58a6ff"))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        arc_rect = self.rect().adjusted(2, 2, -2, -2)
        painter.drawArc(arc_rect, int(-self._angle * 16), int(120 * 16))


class LoadingIndicatorWindow(QWidget):
    def __init__(self, message: str, heartbeat_path: str = "") -> None:
        super().__init__(None)
        self._heartbeat_path = Path(heartbeat_path) if heartbeat_path else None
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet("background-color: rgba(13, 17, 23, 120);")

        self._card = QFrame(self)
        self._card.setStyleSheet(
            """
            QFrame {
                background-color: rgba(22, 27, 34, 230);
                border: 1px solid #3b424b;
                border-radius: 10px;
            }
            """
        )
        card_layout = QHBoxLayout(self._card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(8)

        spinner = CircularLoadingSpinner(self._card)
        label = QLabel(str(message or "Loading applet..."), self._card)
        label.setStyleSheet("color: #c9d1d9; font-size: 12px; font-weight: 500;")
        card_layout.addWidget(spinner)
        card_layout.addWidget(label)

        if self._heartbeat_path is not None:
            self._heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_heartbeat("start")
            self._heartbeat_timer = QTimer(self)
            self._heartbeat_timer.setInterval(50)
            self._heartbeat_timer.timeout.connect(lambda: self._write_heartbeat("tick"))
            self._heartbeat_timer.start()
        else:
            self._heartbeat_timer = None

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._position_card()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_card()

    def _position_card(self) -> None:
        card_size = self._card.sizeHint()
        x = max(0, (self.width() - card_size.width()) // 2)
        y = max(0, (self.height() - card_size.height()) // 2)
        self._card.setGeometry(x, y, card_size.width(), card_size.height())

    def _write_heartbeat(self, kind: str) -> None:
        if self._heartbeat_path is None:
            return
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with self._heartbeat_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{kind} {ts}\n")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--message", default="Loading applet...")
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=160)
    parser.add_argument("--heartbeat-path", default=os.environ.get("DMT_LOADING_INDICATOR_HEARTBEAT_PATH", ""))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    app = QApplication(sys.argv[:1])
    window = LoadingIndicatorWindow(str(args.message or "Loading applet..."), str(args.heartbeat_path or ""))
    window.setGeometry(int(args.x), int(args.y), max(1, int(args.width)), max(1, int(args.height)))
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
