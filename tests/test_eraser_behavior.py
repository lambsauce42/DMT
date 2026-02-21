import sys
import os
import pytest
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtWidgets import QGraphicsRectItem

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dungeon_applet import DungeonAppletWidget, ToolType
from dungeon_constants import ROLE_KIND, TOOL_ROOM

@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    return widget

def test_eraser_only_erases_strokes(dungeon_widget, qtbot):
    canvas = dungeon_widget.canvas
    scene = canvas.scene()
    
    # 1. Create a room-like item (but not a "stroke")
    # We'll just manually add a rect item with ROLE_KIND = TOOL_ROOM
    room_item = QGraphicsRectItem(0, 0, 100, 100)
    room_item.setData(ROLE_KIND, TOOL_ROOM)
    scene.addItem(room_item)
    
    # 2. Create a stroke item
    stroke_item = QGraphicsRectItem(200, 200, 50, 50)
    stroke_item.setData(ROLE_KIND, "stroke")
    scene.addItem(stroke_item)
    
    assert room_item in scene.items()
    assert stroke_item in scene.items()
    
    # 3. Switch to Eraser tool
    canvas.current_tool = ToolType.ERASER
    
    # 4. Try to erase the room item at (50, 50)
    # The eraser has a hit_radius of 5
    canvas._current_state._erase_at(QPointF(50, 50))
    
    # DESIRED BEHAVIOR: it should NOT be erased.
    
    # 5. Try to erase the stroke item at (225, 225)
    canvas._current_state._erase_at(QPointF(225, 225))
    
    # Check fixed behavior
    assert room_item in scene.items()
    assert stroke_item not in scene.items()
