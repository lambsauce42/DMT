import sys
import os
import pytest
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QToolButton, QMessageBox, QFileDialog, QDialog
)
from PySide6.QtCore import Qt, QTimer

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from ui.encounter_panel import EncounterPanel, EncounterEntry, Monster

@pytest.fixture
def encounter_panel(qtbot, monkeypatch, tmp_path):
    # Mock file dialogs and message boxes
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    encounter_path = tmp_path / "test_encounter.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(encounter_path), "JSON"))
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected) # Default reject to avoid stuck dialogs

    widget = EncounterPanel()
    qtbot.addWidget(widget)
    return widget

def test_click_toolbar_buttons(encounter_panel, qtbot):
    """
    Click the 4 toolbar buttons: Suggest, Save, Export, Clear.
    """
    # Find all tool buttons in the panel
    buttons = encounter_panel.findChildren(QToolButton)
    assert len(buttons) >= 4, f"Should have at least 4 toolbar buttons, found {len(buttons)}"

    for btn in buttons:
        if btn.isVisible() and btn.isEnabled():
            qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

def test_add_and_remove_entry(encounter_panel, qtbot):
    """
    Manually add an entry, then find the 'Modify' button in the tree.
    Also test removal by setting count to 0.
    """
    # Create a dummy monster
    monster = Monster(
        id="test_id", name="Test Goblin", cr="1/4", cr_value=0.25, xp=50,
        hp=7, ac=15, strength=8, dexterity=14, constitution=10, 
        intelligence=10, wisdom=8, charisma=8, actions="", tags=[], source="", transient=False, description=""
    )
    
    # Add to panel
    encounter_panel._add_monster(monster, 1)
    
    # Verify it's in the tree
    tree = encounter_panel._encounter_tree
    assert tree.rowCount() == 2
    
    # Find the Modify button in the tree item
    widget = tree.cellWidget(1, 4) # Column 4 is Modify
    assert isinstance(widget, QWidget)
    modify_btn = widget.findChild(QPushButton)
    assert isinstance(modify_btn, QPushButton)
    assert modify_btn.text() == "Modify"
    
    # Test removal by setting count to 0
    # First get the spinbox
    count_widget = tree.cellWidget(1, 0)
    # The PlusMinusSpinBox might not be a direct QSpinBox, let's just call _update_count
    entry = encounter_panel._encounter_entries[0]
    encounter_panel._update_count(entry, 0)
    
    # Verify removal
    assert tree.rowCount() == 1
    assert len(encounter_panel._encounter_entries) == 0

def test_click_all_buttons_recursively(encounter_panel, qtbot, monkeypatch):
    """
    Find ALL buttons in the panel and click them.
    Including the ones in the party panel (PlusMinusSpinBox buttons).
    """
    # Force add a monster so we have tree buttons too
    monster = Monster(
        id="test_id", name="Test Goblin", cr="1/4", cr_value=0.25, xp=50,
        hp=7, ac=15, strength=8, dexterity=14, constitution=10, 
        intelligence=10, wisdom=8, charisma=8, actions="", tags=[], source="", transient=False, description=""
    )
    encounter_panel._add_monster(monster, 1)
    
    # Find all buttons
    push_buttons = encounter_panel.findChildren(QPushButton)
    tool_buttons = encounter_panel.findChildren(QToolButton)
    all_buttons = push_buttons + tool_buttons
    
    for btn in all_buttons:
        if not btn.isVisible():
            continue
            
        # Skip if it's disabled
        if not btn.isEnabled():
            continue

        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
