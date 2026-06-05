
import sys
import os
import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainterPath, QPen, QColor
from PySide6.QtWidgets import QApplication, QGraphicsPathItem

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dungeon_applet import DungeonAppletWidget, ToolType
from dungeon_items import FogItem
from dungeon_constants import ROLE_KIND, ROLE_LAYER, LAYER_BG

def test_fog_of_war_tools(qtbot):
    # Setup application
    if not QApplication.instance():
        app = QApplication(sys.argv)
        
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    
    # 1. Check if Fog Tools exist in panel
    assert widget.tool_panel.btn_fow is not None
    assert widget.tool_panel.btn_fow_eraser is not None
    assert widget.tool_panel.btn_fill_fog is not None
    
    # 2. Test "Fill Fog" action
    # Initially no fog item
    assert widget.canvas.fog_item is None
    
    # Click Fill Fog
    widget.tool_panel.btn_fill_fog.click()
    
    # Needs to process Fog Item creation
    qtbot.wait(50)
    
    assert widget.canvas.fog_item is not None
    assert isinstance(widget.canvas.fog_item, FogItem)
    assert widget.canvas.fog_item.scene() == widget.canvas.scene()
    
    # Check if path is not empty (filled)
    assert not widget.canvas.fog_item.path().isEmpty()
    
    # 3. Test View Toggle
    # Start as DM (opacity 0.5)
    assert str(widget.canvas.fog_item._view_mode) == "dm"
    assert widget.canvas.fog_item.opacity() == 0.5
    
    # Toggle to Player
    widget.tool_panel.btn_view_toggle.click()
    assert str(widget.canvas.fog_item._view_mode) == "player"
    assert widget.canvas.fog_item.opacity() == 1.0
    
    # Toggle back
    widget.tool_panel.btn_view_toggle.click()
    assert str(widget.canvas.fog_item._view_mode) == "dm"
    
    # 4. Test Fog Brush Tool Selection
    widget.tool_panel.btn_fow.click()
    assert widget.canvas.current_tool == ToolType.FOW_BRUSH
    assert isinstance(widget.canvas._current_state, type(widget.canvas._states[ToolType.FOW_BRUSH]))

    # 5. Test Fog Eraser Tool Selection
    widget.tool_panel.btn_fow_eraser.click()
    assert widget.canvas.current_tool == ToolType.FOW_ERASER


def test_fog_overlay_covers_strokes_after_state_reload(qtbot):
    if not QApplication.instance():
        app = QApplication(sys.argv)

    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)

    widget.tool_panel.btn_fill_fog.click()
    qtbot.wait(50)
    assert isinstance(widget.canvas.fog_item, FogItem)

    stroke_path = QPainterPath()
    stroke_path.moveTo(QPointF(0, 0))
    stroke_path.lineTo(QPointF(40, 40))
    stroke = QGraphicsPathItem(stroke_path)
    stroke.setPen(QPen(QColor("#ffffff"), 6))
    stroke.setData(ROLE_KIND, "stroke")
    stroke.setData(ROLE_LAYER, LAYER_BG)
    stroke.setZValue(-95)
    widget.canvas.scene().addItem(stroke)

    state = widget._serialize_scene()
    widget._load_dungeon_state(state)

    loaded_fog = widget.canvas.fog_item
    loaded_strokes = [
        item
        for item in widget.canvas.scene().items()
        if isinstance(item, QGraphicsPathItem) and item.data(ROLE_KIND) == "stroke"
    ]
    assert loaded_fog is not None
    assert loaded_strokes
    assert loaded_strokes[0].zValue() < loaded_fog.zValue()


def test_fog_overlay_normalizes_old_above_fog_strokes_on_reload(qtbot):
    if not QApplication.instance():
        app = QApplication(sys.argv)

    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)

    move_to = int(QPainterPath.ElementType.MoveToElement.value)
    line_to = int(QPainterPath.ElementType.LineToElement.value)
    state = {
        "items": [
            {
                "type": "stroke",
                "path": [
                    {"type": move_to, "x": 0.0, "y": 0.0},
                    {"type": line_to, "x": 40.0, "y": 40.0},
                ],
                "pen_color": "#ffffff",
                "pen_width": 6,
                "layer": LAYER_BG,
                "z": 305.0,
            }
        ],
        "fog": {
            "path": [
                {"type": move_to, "x": -100.0, "y": -100.0},
                {"type": line_to, "x": 100.0, "y": -100.0},
                {"type": line_to, "x": 100.0, "y": 100.0},
                {"type": line_to, "x": -100.0, "y": 100.0},
                {"type": line_to, "x": -100.0, "y": -100.0},
            ]
        },
    }

    widget._load_dungeon_state(state)

    loaded_fog = widget.canvas.fog_item
    loaded_strokes = [
        item
        for item in widget.canvas.scene().items()
        if isinstance(item, QGraphicsPathItem) and item.data(ROLE_KIND) == "stroke"
    ]
    assert loaded_fog is not None
    assert loaded_strokes
    assert loaded_strokes[0].zValue() < loaded_fog.zValue()
