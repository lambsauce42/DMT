import os
import sys
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt6.QtWidgets import QApplication
import loot_applet

app = QApplication.instance() or QApplication(sys.argv)

class TestLootProbabilities(unittest.TestCase):
    @patch("loot_applet.LootAppletWidget._load_item_library")
    @patch("loot_applet.LootAppletWidget._load_presets")
    def setUp(self, mock_presets, mock_library):
        self.widget = loot_applet.LootAppletWidget()

    def tearDown(self):
        self.widget.close()

    def test_linear_weights_increase_with_luck(self):
        # Low luck
        self.widget._luck_spin.setValue(1)
        weights_low = self.widget._linear_weights(0.0)
        
        # High luck
        self.widget._luck_spin.setValue(100)
        weights_high = self.widget._linear_weights(1.0)
        
        # Artifact weight should be higher at high luck
        self.assertGreater(weights_high["very rare"], weights_low["very rare"])
        self.assertGreater(weights_high["rare"], weights_low["rare"])

    def test_weighted_choice_returns_valid_rarity(self):
        weights = {"common": 0.5, "uncommon": 0.3, "rare": 0.2}
        rng = MagicMock()
        # total is 1.0. roll = rng.random() * total
        # We want roll to be 0.9 to fall into "rare" (common 0.5 + uncommon 0.3 = 0.8)
        rng.random.return_value = 0.9
        
        choice = self.widget._weighted_choice(weights, rng)
        self.assertEqual(choice, "rare")

    def test_normalize_weights(self):
        weights = {"a": 10.0, "b": 10.0}
        norm = self.widget._normalize_weights(weights)
        self.assertAlmostEqual(norm["a"], 50.0)
        self.assertAlmostEqual(norm["b"], 50.0)

if __name__ == "__main__":
    unittest.main()
