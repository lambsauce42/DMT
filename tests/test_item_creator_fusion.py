import sys
import os
import pytest
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QToolButton, QMessageBox, QFileDialog, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from item_creator import ItemCreatorWidget
from item_renderer import ItemCardSpec

@pytest.fixture
def item_widget(qtbot, monkeypatch):
    # Mock message boxes and dialogs
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "exec", lambda *args: QMessageBox.StandardButton.Yes)
    
    # PREVENT HANG: Mock update_preview to stop the recursive timer loop
    monkeypatch.setattr(ItemCreatorWidget, "update_preview", lambda self: None)
    monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
    
    # Mock render_item_card
    monkeypatch.setattr("item_creator.render_item_card", lambda *args, **kwargs: type("Rendered", (), {"image": None, "hitboxes": {}}))
    
    widget = ItemCreatorWidget()
    qtbot.addWidget(widget)
    return widget

def test_fusion_ui_presence(item_widget):
    assert hasattr(item_widget, "fuse_stats_check")
    assert isinstance(item_widget.fuse_stats_check, QCheckBox)
    assert item_widget.fuse_stats_check.text() == "Fuse Stats and Effects"

def test_fusion_logic_enable_disable(item_widget, qtbot):
    # Initially, _seed_stats adds 2 rows
    assert item_widget.stats_table.rowCount() > 0
    # Trigger UI update
    item_widget._update_ui_states()
    # Fuse button should be disabled because there are stats
    assert not item_widget.fuse_stats_check.isEnabled()
    
    # Clear stats
    item_widget.stats_table.setRowCount(0)
    # Trigger UI update
    item_widget._update_ui_states()
    
    # Fuse button should now be enabled
    assert item_widget.fuse_stats_check.isEnabled()
    
    # Check it
    qtbot.mouseClick(item_widget.fuse_stats_check, Qt.MouseButton.LeftButton)
    assert item_widget.fuse_stats_check.isChecked()
    
    # Stats UI should be disabled
    assert not item_widget.stats_table.isEnabled()
    assert not item_widget.add_stat_btn.isEnabled()
    
    # Uncheck it
    qtbot.mouseClick(item_widget.fuse_stats_check, Qt.MouseButton.LeftButton)
    assert not item_widget.fuse_stats_check.isChecked()
    assert item_widget.stats_table.isEnabled()
    assert item_widget.add_stat_btn.isEnabled()

def test_fusion_persistence(item_widget, qtbot):
    # Prepare fused state
    item_widget.stats_table.setRowCount(0)
    item_widget._update_ui_states()
    item_widget.fuse_stats_check.setChecked(True)
    
    spec = item_widget._current_spec()
    assert spec.fused_stats_effects is True
    
    # Apply new spec with fusion enabled
    new_spec = ItemCardSpec(
        title="Fused Item",
        stats=[],
        effects=["Effect 1"],
        fused_stats_effects=True
    )
    item_widget._apply_spec(new_spec)
    assert item_widget.fuse_stats_check.isChecked()
    assert not item_widget.stats_table.isEnabled()
    
    # Apply spec with stats - should disable fusion even if spec says True
    new_spec_with_stats = ItemCardSpec(
        title="Stat Item",
        stats=[("+1", "STR")],
        effects=["Effect 1"],
        fused_stats_effects=True
    )
    item_widget._apply_spec(new_spec_with_stats)
    # Logic in _update_ui_states should have unchecked and disabled it
    assert not item_widget.fuse_stats_check.isChecked()
    assert not item_widget.fuse_stats_check.isEnabled()
    assert item_widget.stats_table.isEnabled()
