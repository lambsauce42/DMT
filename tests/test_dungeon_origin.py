import pytest
import sys
import os
from PySide6.QtCore import QPointF, Qt

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dungeon_applet import DungeonAppletWidget


class _WheelDeltaStub:
    def __init__(self, y_value: int) -> None:
        self._y_value = y_value

    def y(self) -> int:
        return self._y_value


class _WheelEventStub:
    def __init__(self, *, delta: int, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
        self._delta = delta
        self._modifiers = modifiers
        self.accepted = False

    def modifiers(self) -> Qt.KeyboardModifier:
        return self._modifiers

    def angleDelta(self) -> _WheelDeltaStub:
        return _WheelDeltaStub(self._delta)

    def accept(self) -> None:
        self.accepted = True

def test_manual_centering(qtbot):
    """Verify that centering the canvas on (0,0) updates the coord label correctly."""
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    widget.show()
    widget.resize(1000, 600)
    qtbot.waitExposed(widget)
    
    # Manually center on 0,0
    widget.canvas.centerOn(0, 0)
    
    # Wait for the label to update to 0,0 (centerOn triggers scrollContentsBy)
    qtbot.wait_until(lambda: widget.coord_label.text() == "X: 0, Y: 0", timeout=5000)

def test_origin_button(qtbot):
    """Verify that the 'Go to Origin' button centers the view on (0,0)."""
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    
    # Pan away
    widget.canvas.centerOn(1000, 1000)
    
    # Click origin button
    widget.btn_origin.click()
    
    # Check the label
    qtbot.wait_until(lambda: widget.coord_label.text() == "X: 0, Y: 0", timeout=1000)
    
    # Debug actual center again
    rect = widget.canvas.viewport().rect()
    center_scene = widget.canvas.mapToScene(rect).boundingRect().center()
    print(f"Final scene center: {center_scene.x()}, {center_scene.y()}")
    
    h_bar = widget.canvas.horizontalScrollBar()
    v_bar = widget.canvas.verticalScrollBar()
    print(f"Scrollbars: H={h_bar.value()} (range {h_bar.minimum()} to {h_bar.maximum()}), V={v_bar.value()} (range {v_bar.minimum()} to {v_bar.maximum()})")


def test_canvas_plain_wheel_zooms_when_ctrl_requirement_is_disabled(qtbot, monkeypatch):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)

    calls = []
    monkeypatch.setattr("dungeon_applet.is_ctrl_mouse_wheel_zoom_enabled", lambda: False)
    monkeypatch.setattr(
        widget.canvas,
        "zoom_in",
        lambda *, anchor_under_mouse=False: calls.append(anchor_under_mouse),
    )

    event = _WheelEventStub(delta=120)
    widget.canvas.wheelEvent(event)

    assert calls == [True]
    assert event.accepted is True
