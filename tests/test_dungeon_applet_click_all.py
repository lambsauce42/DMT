import sys
import os
import pytest
from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Qt

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dungeon_applet import DungeonAppletWidget, ToolType, ToolButton

@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    return widget

def test_click_all_tool_buttons(dungeon_widget, qtbot):
    """
    Literally try to click all tool buttons and see whether they do what they should.
    """
    buttons = dungeon_widget.tool_panel.findChildren(ToolButton)
    
    # Map tool types to their buttons for easy access
    tool_map = {btn.tool_type: btn for btn in buttons}
    
    expected_tools = [
        ToolType.SELECT,
        ToolType.FREE_DRAW,
        ToolType.ERASER,
        ToolType.RECTANGLE,
        ToolType.CIRCLE,
        ToolType.POLYGON,
        ToolType.ENTITY
    ]
    
    for tool_type in expected_tools:
        btn = tool_map.get(tool_type)
        assert btn is not None, f"Button for {tool_type} not found"
        
        # Click the button
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
        
        # Verify button is checked
        assert btn.isChecked(), f"Button for {tool_type} should be checked after click"
        
        # Verify canvas tool state changed
        assert dungeon_widget.canvas.current_tool == tool_type, \
            f"Canvas tool should be {tool_type} after clicking its button"
            
        # Verify other buttons are unchecked (exclusivity check)
        for other_type, other_btn in tool_map.items():
            if other_type != tool_type:
                assert not other_btn.isChecked(), \
                    f"Button for {other_type} should be unchecked when {tool_type} is selected"

def test_click_zoom_buttons(dungeon_widget, qtbot):
    """
    Click zoom in/out buttons and verify zoom changes.
    """
    initial_zoom = dungeon_widget.canvas._current_zoom
    initial_label = dungeon_widget.zoom_label.text()
    initial_transform_zoom = dungeon_widget.canvas.transform().m11()
    assert initial_transform_zoom == pytest.approx(1.2)
    
    # Find Zoom In button (it has the plus icon)
    # Since we don't have direct public accessors easily without inspecting children or relying on member names:
    # We can access them via the member variables directly as they are public in python class
    btn_zoom_in = dungeon_widget.btn_zoom_in
    btn_zoom_out = dungeon_widget.btn_zoom_out
    
    # Click Zoom In
    qtbot.mouseClick(btn_zoom_in, Qt.MouseButton.LeftButton)
    
    new_zoom = dungeon_widget.canvas._current_zoom
    assert new_zoom > initial_zoom, "Zoom level should increase after clicking Zoom In"
    assert dungeon_widget.canvas.transform().m11() > initial_transform_zoom
    assert dungeon_widget.zoom_label.text() != initial_label, "Zoom label should update"
    
    # Click Zoom Out
    qtbot.mouseClick(btn_zoom_out, Qt.MouseButton.LeftButton)
    
    # Depending on floating point math, might not be exactly initial, but should be less than the zoomed in state
    assert dungeon_widget.canvas._current_zoom < new_zoom, "Zoom level should decrease after clicking Zoom Out"

def test_click_origin_button(dungeon_widget, qtbot):
    """
    Click origin button and verify view reset.
    """
    # Pan/Zoom away first
    dungeon_widget.canvas.scale(2.0, 2.0)
    dungeon_widget.canvas.centerOn(1000, 1000)
    
    # Verify we are not at default
    assert dungeon_widget.canvas._current_zoom != 1.0 or \
           dungeon_widget.canvas.horizontalScrollBar().value() != 0 or \
           dungeon_widget.canvas.verticalScrollBar().value() != 0
           
    # Click Origin Button
    btn_origin = dungeon_widget.btn_origin
    qtbot.mouseClick(btn_origin, Qt.MouseButton.LeftButton)
    
    # Verify reset
    assert dungeon_widget.canvas._current_zoom == 1.0, "Zoom should reset to 1.0"
    assert dungeon_widget.canvas.transform().m11() == pytest.approx(1.2)
    
    # centerOn(0,0) ensures the scene center is in view. 
    # Exact scrollbar values depend on viewport size, but we can check internal zoom state.
    # We can also check if the zoom label reset
    assert dungeon_widget.zoom_label.text() == "100%"
