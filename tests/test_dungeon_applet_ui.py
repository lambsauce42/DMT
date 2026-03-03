import sys
import os
import pytest
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import QEvent, Qt

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dungeon_applet import DungeonAppletWidget, ToolType, FloatingToolPanel, ToolButton

@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    return widget

def test_dungeon_applet_has_tool_panel(dungeon_widget):
    """Verify that the DungeonAppletWidget has a FloatingToolPanel."""
    assert hasattr(dungeon_widget, "tool_panel")
    assert isinstance(dungeon_widget.tool_panel, FloatingToolPanel)

def test_tool_panel_buttons(dungeon_widget):
    """Verify that the tool panel has the expected number of buttons."""
    buttons = dungeon_widget.tool_panel.findChildren(ToolButton)
    # Select, Free Draw, Rect, Circle, Polygon, Entity, Eraser = 7 buttons
    # Select, Free Draw, Rect, Circle, Polygon, Entity, Eraser = 7
    # + Encounter = 1
    # + Fog Brush, Fog Eraser = 2
    # + Ping, Image = 2
    # Total = 12
    assert len(buttons) == 12

def test_tool_selection_changes_canvas_tool(dungeon_widget, qtbot):
    """Verify that clicking a tool button changes the tool in the canvas."""
    buttons = dungeon_widget.tool_panel.findChildren(ToolButton)
    
    # Find the Eraser button
    eraser_btn = next(btn for btn in buttons if btn.tool_type == ToolType.ERASER)
    
    # Click it
    qtbot.mouseClick(eraser_btn, Qt.MouseButton.LeftButton)
    
    assert dungeon_widget.canvas.current_tool == ToolType.ERASER

def test_tool_selection_is_exclusive(dungeon_widget, qtbot):
    """Verify that only one tool can be selected at a time."""
    buttons = dungeon_widget.tool_panel.findChildren(ToolButton)
    
    # Initially SELECT should be checked
    select_btn = next(btn for btn in buttons if btn.tool_type == ToolType.SELECT)
    assert select_btn.isChecked()
    
    # Click Rectangle
    rect_btn = next(btn for btn in buttons if btn.tool_type == ToolType.RECTANGLE)
    qtbot.mouseClick(rect_btn, Qt.MouseButton.LeftButton)
    
    assert rect_btn.isChecked()
    assert not select_btn.isChecked()


def test_event_filter_ignores_deleted_loot_pool_list(dungeon_widget, qtbot):
    loot_list = dungeon_widget._loot_pool_list
    loot_list.deleteLater()
    QApplication.processEvents()

    result = dungeon_widget.eventFilter(
        dungeon_widget,
        QEvent(QEvent.Type.Leave),
    )

    assert isinstance(result, bool)


def test_refresh_dungeon_list_handles_reentrant_refresh_request(dungeon_widget, monkeypatch):
    original_render_state_preview = dungeon_widget._render_state_preview
    refresh_requested = {"value": False}

    def _render_state_preview_with_reentry(state, size):
        if not refresh_requested["value"]:
            refresh_requested["value"] = True
            dungeon_widget._refresh_dungeon_list(preserve_selection=True)
        return original_render_state_preview(state, size)

    monkeypatch.setattr(
        dungeon_widget,
        "_render_state_preview",
        _render_state_preview_with_reentry,
    )

    dungeon_widget._refresh_dungeon_list(preserve_selection=True)

    assert dungeon_widget._dungeon_list.count() == len(dungeon_widget._dungeons)
