import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt6.QtWidgets import QApplication, QLabel
from ui.widgets.monster_card import MonsterCard
from encounter_engine import Monster

app = QApplication.instance() or QApplication(sys.argv)

class TestMonsterCardUI(unittest.TestCase):
    def setUp(self):
        self.monster = Monster(
            id="test-m",
            name="Testing Monster",
            cr="1",
            cr_value=1.0,
            xp=200,
            hp=50,
            ac=15,
            actions="Slash",
            description="Scary",
            tags=("undead",),
            source="Manual",
            strength=18,
            dexterity=10,
            constitution=14,
            intelligence=6,
            wisdom=8,
            charisma=5
        )
        self.on_add = MagicMock()
        self.on_modify = MagicMock()
        self.on_expand = MagicMock()
        self.card = MonsterCard(self.monster, self.on_add, self.on_modify, self.on_expand)

    def test_stats_display(self):
        # Find the label that shows HP and AC
        labels = self.card.findChildren(QLabel)
        hp_ac_text = f"HP {self.monster.hp} • AC {self.monster.ac}"
        found_hp_ac = any(hp_ac_text in l.text() for l in labels)
        self.assertTrue(found_hp_ac, f"Could not find HP/AC text: {hp_ac_text}")

        # Find the label that shows ability scores
        stats_text = (
            f"STR {self.monster.strength} DEX {self.monster.dexterity} CON {self.monster.constitution} "
            f"INT {self.monster.intelligence} WIS {self.monster.wisdom} CHA {self.monster.charisma}"
        )
        found_stats = any(stats_text in l.text() for l in labels)
        self.assertTrue(found_stats, f"Could not find ability stats text: {stats_text}")

    def test_add_button_calls_callback(self):
        self.card._count_spin.setValue(3)
        self.card._handle_add()
        self.on_add.assert_called_once_with(self.monster, 3)

if __name__ == "__main__":
    unittest.main()
