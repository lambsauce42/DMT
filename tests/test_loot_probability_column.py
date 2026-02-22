import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import loot_applet
from loot_applet import LootItem, RARITY_ORDER

app = QApplication.instance() or QApplication(sys.argv)

class TestLootRelativeWeights(unittest.TestCase):
    @patch("loot_applet.LootAppletWidget._load_item_library")
    @patch("loot_applet.LootAppletWidget._load_presets")
    def setUp(self, mock_presets, mock_library):
        self.widget = loot_applet.LootAppletWidget()
        # Common and Legendary items
        self.legendary_item = LootItem(
            item_id="1", title="Legendary Sword", rarity="legendary",
            category_label="Weapon", categories={"weapon"}, level=1, tags=set()
        )
        self.common_item = LootItem(
            item_id="2", title="Common Sword", rarity="common",
            category_label="Weapon", categories={"weapon"}, level=1, tags=set()
        )
        
    def tearDown(self):
        self.widget.close()

    def test_prob_relative_weights_scenario(self):
        # User scenario:
        # Pool: Common, Legendary. (Others empty)
        # Weights: Common 1.0, Legendary 0.01 (Linear Steep Low Luck)
        # Old logic (Fallback): V (0.25) -> L. Prob L ~ 10%.
        # New logic (Relative): W(C)=1.0, W(L)=0.01. Norm: C=99%, L=1%.
        
        self.widget._item_library = [self.common_item, self.legendary_item]
        self.widget._item_by_id = {item.item_id: item for item in self.widget._item_library}
        self.widget._update_preview()
        
        # Configure Linear (Steep) at Low Luck
        self.widget._curve_combo.setCurrentText("Linear (Steep)")
        self.widget._luck_slider.setValue(1 * loot_applet.LUCK_SLIDER_SCALE)
        
        # Calculate base weights to verify assumptions
        base = self.widget._calculate_weights()
        # Norm weights sum to 100.
        # Check raw ratio roughly
        # We can't access raw internal values easily, but we know Linear Steep behavior.
        # C should be max, L should be min.
        
        self.widget._rolls_spin.setValue(1)
        self.widget._update_table()
        
        # Get displayed probabilities
        prob_c_str = self.widget._prob_value_labels["common"].text().replace("%", "")
        prob_l_str = self.widget._prob_value_labels["legendary"].text().replace("%", "")
        prob_c = float(prob_c_str)
        prob_l = float(prob_l_str)
        
        # With relative weights, L should be very small (~1%)
        # C should be very large (~99%)
        
        print(f"DEBUG: Prob Common: {prob_c}%, Prob Legendary: {prob_l}%")
        
        self.assertGreater(prob_c, 95.0)
        self.assertLess(prob_l, 5.0)
        
        # Ensure intermediate pools (Uncommon, Rare, Very Rare) are 0%
        for r in ["uncommon", "rare", "very rare"]:
            p = self.widget._prob_value_labels[r].text()
            self.assertEqual(p, "0.0%")

    def test_prob_sums_to_100_relative(self):
        # Basic check that non-empty pools sum to 100% prob for 1 roll
        self.widget._item_library = [self.common_item, self.legendary_item]
        self.widget._item_by_id = {item.item_id: item for item in self.widget._item_library}
        self.widget._update_preview()
        
        self.widget._rolls_spin.setValue(1)
        self.widget._update_table()
        
        total_prob = 0.0
        for r in RARITY_ORDER:
            txt = self.widget._prob_value_labels[r].text().replace("%", "")
            total_prob += float(txt)
            
        self.assertAlmostEqual(total_prob, 100.0, delta=0.5)

if __name__ == "__main__":
    unittest.main()
