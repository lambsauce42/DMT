
import sys
import os
import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtWidgets import QApplication

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


def test_inspector_pending_changes_clear_safely_on_state_reload(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)

    entity = EntityItem(QPointF(0, 0))
    widget.canvas.scene().addItem(entity)
    widget.inspector.set_entity(entity)

    widget.inspector._track_change("hp", max(0, entity.hp - 1))
    widget._load_dungeon_state(widget._blank_dungeon_state())

    assert widget.inspector._entity is None
    assert widget.inspector.isHidden()


def test_inspector_hp_current_allows_negative_values(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)

    entity = EntityItem(QPointF(0, 0))
    widget.canvas.scene().addItem(entity)
    widget.inspector.set_entity(entity)

    widget.inspector.hp_stat.curr_edit.setValue(-7)

    assert widget.inspector.hp_stat.curr_edit.minimum() < 0
    assert widget.inspector.hp_stat.curr_edit.value() == -7
    assert widget.inspector.hp_stat.bar.value() == 0


def test_inspector_hp_current_allows_values_above_max(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)

    entity = EntityItem(QPointF(0, 0), hp=120, max_hp=100)
    widget.canvas.scene().addItem(entity)
    widget.inspector.set_entity(entity)

    widget.inspector.hp_stat.curr_edit.setValue(135)

    assert widget.inspector.hp_stat.curr_edit.value() == 135
    assert widget.inspector.hp_stat.max_edit.value() == 100
    assert widget.inspector.hp_stat.bar.value() == 100
