import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QLineEdit

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from ui.encounter_panel import EncounterPanel, SuggestDialog
from encounter_engine import Monster

@pytest.fixture
def encounter_panel(qtbot):
    with patch("ui.encounter_panel.load_monsters") as mock_load:
        mock_load.return_value = [
            Monster(
                id="goblin", name="Goblin", cr="1/4", cr_value=0.25, xp=50, 
                hp=7, ac=15, actions="", description="", tags=("humanoid", "goblinoid"), 
                source="SRD"
            ),
            Monster(
                id="orc", name="Orc", cr="1/2", cr_value=0.5, xp=100, 
                hp=15, ac=13, actions="", description="", tags=("humanoid", "orc"), 
                source="SRD"
            ),
        ]
        with patch("ui.encounter_panel.load_difficulty_table"), \
             patch("ui.encounter_panel.load_multiplier_table"):
            panel = EncounterPanel()
            qtbot.addWidget(panel)
            return panel

def test_encounter_panel_search(encounter_panel, qtbot):
    """Test searching for monsters in the encounter panel."""
    # Based on reading encounter_panel.py, it's self._search
    search_input = encounter_panel._search
    assert search_input is not None
    
    # Type "Goblin"
    qtbot.keyClicks(search_input, "Goblin")
    
    # Wait for the search debounce timer (200ms)
    qtbot.wait(300)
    
    # Verify _filtered_monsters
    assert len(encounter_panel._filtered_monsters) == 1
    assert encounter_panel._filtered_monsters[0].name == "Goblin"

def test_suggest_dialog_initialization(qtbot):
    """Verify SuggestDialog has expected controls."""
    dialog = SuggestDialog()
    qtbot.addWidget(dialog)
    
    assert dialog.windowTitle() == "Suggest Monsters"
    assert dialog.max_monsters() == 10
    assert dialog.method() == "greedy"

def test_add_monster_to_encounter(encounter_panel, qtbot):
    """Smoke test for adding a monster to the active encounter list."""
    monster = encounter_panel._monsters[0] # Goblin
    encounter_panel._add_monster(monster, 1)
    
    assert len(encounter_panel._encounter_entries) == 1
    assert encounter_panel._encounter_entries[0].monster.name == "Goblin"
    assert encounter_panel._encounter_entries[0].count == 1

if __name__ == "__main__":
    pytest.main([__file__])
