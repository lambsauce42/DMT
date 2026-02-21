import sys
import os
import pytest
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QToolButton, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, QTimer

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from item_creator import ItemCreatorWidget

@pytest.fixture
def item_widget(qtbot, monkeypatch, tmp_path):
    # Mock message boxes and dialogs
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    # CRITICAL: Mock exec methods to prevent hanging dialogs
    monkeypatch.setattr(QMessageBox, "exec", lambda *args: QMessageBox.StandardButton.Yes)
    
    item_path = tmp_path / "test_item.dmtitem"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(item_path), "DMT Item"))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(item_path), "DMT Item"))

    # CRITICAL: Mock os.path.exists to avoid "File Exists" dialog logic entirely
    # We only want to test the save flow, not the overwrite confirmation
    original_exists = os.path.exists
    def mock_exists(path):
        if "test_item" in path:
            return False
        return original_exists(path)
    monkeypatch.setattr(os.path, "exists", mock_exists)

    # Mock open for save
    # We can just catch exceptions in the slot if we don't mock open
    # Writes are redirected to the test temp directory via mocked file dialogs.
    
    # PREVENT HANG: Mock update_preview to stop the recursive timer loop
    monkeypatch.setattr(ItemCreatorWidget, "update_preview", lambda self: None)
    # Also stop the singleShot in init if possible, but mocking the target method is safer/easier
    monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
    
    # Mock render_item_card to avoid actual rendering which might hang or be slow
    monkeypatch.setattr("item_creator.render_item_card", lambda *args, **kwargs: None)
    monkeypatch.setattr("item_creator.save_item_card_pdf", lambda *args, **kwargs: None)
    
    widget = ItemCreatorWidget()
    qtbot.addWidget(widget)
    return widget

def test_item_toolbar_buttons(item_widget, qtbot, monkeypatch):
    """
    Click Save, Load, Export buttons.
    """
    # Mock render check to allow save attempt
    monkeypatch.setattr(item_widget, "_current_spec", lambda: type("Spec", (), {"title": "Test", "rarity": "common", "classes": [], "stats": [], "effects": [], "flavor_text": "", "icon_path": "", "tags": [], "level": 1}))
    monkeypatch.setattr(item_widget, "_set_dirty", lambda x: None)
    
    # Mock open for save
    # We can just catch exceptions in the slot if we don't mock open
    
    # Click Save
    qtbot.mouseClick(item_widget.save_button, Qt.MouseButton.LeftButton)
    
    # Click Save As
    qtbot.mouseClick(item_widget.save_to_button, Qt.MouseButton.LeftButton)
    
    # Click Load
    qtbot.mouseClick(item_widget.load_button, Qt.MouseButton.LeftButton)
    
    # Click Export (might fail due to renderer but shouldn't crash)
    qtbot.mouseClick(item_widget.export_button, Qt.MouseButton.LeftButton)

def test_item_toolbar_buttons_are_square(item_widget):
    for btn in (
        item_widget.load_button,
        item_widget.save_button,
        item_widget.save_to_button,
        item_widget.export_button,
    ):
        assert btn.width() == btn.height()
        assert btn.width() >= 36
        style = btn.styleSheet()
        assert "padding: 4px;" in style
        assert "min-width: 36px;" in style
        assert "max-width: 36px;" in style
        assert "min-height: 36px;" in style
        assert "max-height: 36px;" in style

def test_item_stats_buttons(item_widget, qtbot):
    """
    Click Add/Remove Stat buttons.
    """
    # Find add/remove buttons in the stats group
    # They are QToolButtons with specific icons or tooltips
    
    # We can find them by object name if they have unique ones, or by tooltip
    # Add Stat, Remove Selected Stat
    
    buttons = item_widget.findChildren(QToolButton)
    add_btn = next((b for b in buttons if b.toolTip() == "Add Stat"), None)
    remove_btn = next((b for b in buttons if b.toolTip() == "Remove Selected Stat"), None)
    
    assert add_btn is not None
    assert remove_btn is not None
    
    # Click Add
    row_count_before = item_widget.stats_table.rowCount()
    qtbot.mouseClick(add_btn, Qt.MouseButton.LeftButton)
    assert item_widget.stats_table.rowCount() == row_count_before + 1
    
    # Select row to remove
    item_widget.stats_table.selectRow(0)
    qtbot.mouseClick(remove_btn, Qt.MouseButton.LeftButton)
    assert item_widget.stats_table.rowCount() == row_count_before

def test_click_all_item_buttons(item_widget, qtbot):
    """
    Click all buttons.
    """
    all_buttons = item_widget.findChildren(QPushButton) + item_widget.findChildren(QToolButton)
    for btn in all_buttons:
        if btn.isVisible() and btn.isEnabled():
            qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
