import os
import sys
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import item_creator

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])

def test_icon_searching(app):
    widget = item_creator.ItemCreatorWidget()
    try:
        # Search for a specific icon name (e.g., 'amulett')
        widget.icon_search.setText("amulett")
        # Ensure only matching icons are visible
        visible_buttons = [btn for btn in widget._icon_grid_buttons if not btn.isHidden()]
        for btn in visible_buttons:
            assert "amulett" in btn.text().lower()
        
        # Clear search
        widget.icon_search.setText("")
        visible_buttons_cleared = [btn for btn in widget._icon_grid_buttons if not btn.isHidden()]
        assert len(visible_buttons_cleared) > len(visible_buttons)
    finally:
        widget.close()

def test_icon_category_filtering(app):
    widget = item_creator.ItemCreatorWidget()
    try:
        # Find 'Equipment' category in combo box
        eq_index = widget.icon_category_filter.findText("Equipment")
        if eq_index != -1:
            widget.icon_category_filter.setCurrentIndex(eq_index)
            # All visible buttons should be equipment
            visible_buttons = [btn for btn in widget._icon_grid_buttons if not btn.isHidden()]
            # Check a few
            for btn in visible_buttons:
                # Based on our discovery logic, icons in 'equipment' folder get 'Equipment' category
                matching_data = [d for d in widget._all_icon_data if d['button'] == btn]
                assert matching_data[0]['category'] == "Equipment"
        
        # Change to 'Consumables'
        cons_index = widget.icon_category_filter.findText("Consumables")
        if cons_index != -1:
            widget.icon_category_filter.setCurrentIndex(cons_index)
            visible_buttons = [btn for btn in widget._icon_grid_buttons if not btn.isHidden()]
            for btn in visible_buttons:
                matching_data = [d for d in widget._all_icon_data if d['button'] == btn]
                assert matching_data[0]['category'] == "Consumables"
    finally:
        widget.close()
