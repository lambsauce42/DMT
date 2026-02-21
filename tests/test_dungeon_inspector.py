
import sys
import os
import pytest
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtWidgets import QApplication

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dungeon_applet import DungeonAppletWidget
from dungeon_items import EntityItem

def test_inspector_visibility(qtbot):
    # Setup application
    if not QApplication.instance():
        app = QApplication(sys.argv)
        
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    
    # Inspector should be hidden initially
    assert widget.inspector.isHidden()
    assert widget.inspector._entity is None
    
    # Create and add an entity
    scene = widget.canvas.scene()
    entity = EntityItem(QPointF(0, 0))
    scene.addItem(entity)
    
    # Select the entity programmatically
    entity.setSelected(True)
    
    # Process events to let signal propagate (wait briefly)
    qtbot.wait(50)
    
    # Check if inspector is shown and entity is set
    assert widget.inspector.isVisible()
    assert widget.inspector._entity == entity
    
    # Verify values match
    assert widget.inspector.hp_stat.curr_edit.value() == entity.hp
    assert widget.inspector.shield_widget.spin.value() == entity.ac
    
    # Deselect
    entity.setSelected(False)
    qtbot.wait(50)
    
    assert widget.inspector.isHidden()
    assert widget.inspector._entity is None
