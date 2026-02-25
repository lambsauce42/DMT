import sys
import os
import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPolygonF
from PySide6.QtWidgets import QApplication, QGraphicsPolygonItem

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dungeon_applet import DungeonCanvas, ToolType
from dungeon_items import RoomGroup, WallItem
from dungeon_constants import GRID_SIZE

def test_polygon_tool_creation(qtbot):
    # Setup canvas
    canvas = DungeonCanvas()
    qtbot.addWidget(canvas)
    canvas.show()
    qtbot.waitExposed(canvas)
    
    # Set tool to POLYGON
    canvas.current_tool = ToolType.POLYGON
    
    # Define points (off-grid by 5 pixels to test snapping)
    offset = 5 
    
    # Use mapFromScene to get viewport coordinates
    # Scene is centered on 0,0 by default init of DungeonCanvas
    
    # Point 1: 0,0 (snapped) -> input 5,5
    p1_scene = QPointF(0 + offset, 0 + offset)
    p1_view = canvas.mapFromScene(p1_scene)
    
    # Point 2: 2*GRID, 0 (snapped) -> input ..., 5
    p2_scene = QPointF(GRID_SIZE * 2 + offset, 0 + offset)
    p2_view = canvas.mapFromScene(p2_scene)
    
    # Point 3: GRID, 2*GRID (snapped) -> input ..., ...
    p3_scene = QPointF(GRID_SIZE + offset, GRID_SIZE * 2 + offset)
    p3_view = canvas.mapFromScene(p3_scene)
    
    # Simulate clicks
    qtbot.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=p1_view)
    qtbot.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=p2_view)
    qtbot.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=p3_view)
    
    # Double click to finish (at p3 or anywhere really, but usually p3 to close loop)
    qtbot.mouseDClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=p3_view)
    
    # Verify undo stack has command
    assert canvas.undo_stack.count() == 1
    
    # Verify items in scene
    items = canvas.scene().items()
    # Filter for RoomGroup
    room_groups = [i for i in items if isinstance(i, RoomGroup)]
    assert len(room_groups) == 1
    room = room_groups[0]
    
    # Check children of group
    child_items = room.childItems()
    
    # Expect: 1 Floor (Polygon) + 3 Walls (Lines)
    walls = [i for i in child_items if isinstance(i, WallItem)]
    assert len(walls) == 3
    
    floors = [i for i in child_items if isinstance(i, QGraphicsPolygonItem)]
    assert len(floors) == 1
    
    floor = floors[0]
    poly = floor.polygon()
    
    # Check snapping
    expected_p1 = QPointF(0, 0)
    expected_p2 = QPointF(GRID_SIZE * 2, 0)
    expected_p3 = QPointF(GRID_SIZE, GRID_SIZE * 2)
    
    # Check if polygon points match expected snapped values
    # QPolygonF is likely closed (4 points) or open (3 points)
    # The DrawingPolygonState logic creates it from self.points which has 3 points.
    
    assert poly.count() == 3
    assert poly[0] == expected_p1
    assert poly[1] == expected_p2
    assert poly[2] == expected_p3
    
    # Check walls start/end points
    # One wall should connect p1 and p2
    wall_1_2 = next((w for w in walls if w.line().p1() == expected_p1 and w.line().p2() == expected_p2), None)
    if not wall_1_2:
        # Check reverse selection order or construction order
         wall_1_2 = next((w for w in walls if w.line().p1() == expected_p2 and w.line().p2() == expected_p1), None)
         
    # Simply check that all wall endpoints are grid aligned
    for wall in walls:
        line = wall.line()
        assert line.p1().x() % GRID_SIZE == 0
        assert line.p1().y() % GRID_SIZE == 0
        assert line.p2().x() % GRID_SIZE == 0
        assert line.p2().y() % GRID_SIZE == 0
