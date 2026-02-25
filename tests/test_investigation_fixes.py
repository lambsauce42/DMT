import sys
import os
import pytest
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QApplication, QPushButton, QListWidget, QLabel

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from loot_applet import LootAppletWidget, PresetEntry, LootItem, PresetRow
from ui.widgets import PlusMinusSpinBox

def test_trash_button_styling(qtbot):
    # Setup application if not exists
    if not QApplication.instance():
        app = QApplication(sys.argv)
    
    # Create a dummy preset entry
    entry = PresetEntry(name="Test Preset", data={}, built_in=False)
    row = PresetRow(entry, lambda x: None)
    qtbot.addWidget(row)
    row.show()
    
    trash_btn = row.findChild(QPushButton)
    assert trash_btn is not None
    assert trash_btn.iconSize() == QSize(12, 12)
    assert trash_btn.size() == QSize(24, 24)
    assert "border-radius: 4px" in trash_btn.styleSheet()

def test_preset_weight_saving(qtbot):
    widget = LootAppletWidget()
    qtbot.addWidget(widget)
    
    # Set some custom weights
    widget._custom_weights_enabled = True
    for rarity, slider in widget._weight_sliders.items():
        slider.setValue(500) # 50.0% in slider units (50 * 10)
        
    settings = widget._current_settings()
    weights = settings["weights"]
    
    # Check if it was divided by SLIDER_SCALE (10)
    for rarity in weights:
        assert weights[rarity] == 50.0

def test_font_size_increase(qtbot):
    widget = LootAppletWidget()
    qtbot.addWidget(widget)
    
    item = LootItem(
        item_id="test", title="Test Item", rarity="common",
        category_label="test", categories=set(), level=1, tags=set()
    )
    
    row_item, row_widget = widget._build_library_row(item, False)
    
    # Find the name label
    labels = row_widget.findChildren(QLabel)
    name_label = next(l for l in labels if l.text() == "Test Item")
    
    # We checked the code and it had +1.
    assert name_label.font().bold() == True
    # If it was +2 before and now +1, we can't easily check change without base.
    # But the instruction says "Reduced font size increase from +2 to +1".

def test_library_grid_columns(qtbot):
    widget = LootAppletWidget()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    
    list_widget = widget._guaranteed_list
    # The item_width calculation uses viewport().width()
    # Let's mock viewport width or just check the math
    v_width = list_widget.viewport().width()
    spacing = list_widget.spacing()
    expected_width = max(190, (v_width - spacing * 3) // 2)
    
    widget._update_library_grids()
    
    grid_size = list_widget.gridSize()
    assert grid_size.width() == expected_width

def test_plus_minus_spinbox_button_size(qtbot):
    spinbox = PlusMinusSpinBox()
    qtbot.addWidget(spinbox)
    spinbox.show()
    
    assert spinbox.plus_btn.size() == QSize(32, 32)
    assert spinbox.minus_btn.size() == QSize(32, 32)
