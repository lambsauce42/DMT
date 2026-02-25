import os
import sys

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtGui import QPixmap
from PySide6.QtCore import QSize

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dungeon_applet import DungeonTileWidget


def test_dungeon_tile_paint_exception_does_not_emit_active_painter_warning(qtbot):
    print("[DEBUG] setting up message capture for active painter warning")
    messages: list[str] = []

    def _handler(_mode, _context, message) -> None:
        text = str(message)
        if "QBackingStore::endPaint() called with active painter" in text:
            messages.append(text)

    previous_handler = qInstallMessageHandler(_handler)
    try:
        tile = DungeonTileWidget("tile-1", "Dungeon 1", QPixmap(), QSize(96, 96))
        qtbot.addWidget(tile)
        tile.resize(160, 120)
        tile.show()
        qtbot.wait(20)

        print("[DEBUG] forcing paint path exception to verify painter cleanup")
        tile.preview_frame = None  # triggers AttributeError inside paintEvent
        try:
            tile.repaint()
            qtbot.wait(20)
        except Exception:
            pass
    finally:
        qInstallMessageHandler(previous_handler)

    print(f"[DEBUG] captured active painter warnings: {len(messages)}")
    assert not messages
