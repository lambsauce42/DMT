import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication

# Setup path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import loot_applet
from loot_applet import LootItem, RARITY_ORDER

app = QApplication.instance() or QApplication(sys.argv)

class TestLootProbabilityColumn(unittest.TestCase):
    @patch("loot_applet.LootAppletWidget._load_item_library")
    @patch("loot_applet.LootAppletWidget._load_presets")
    def setUp(self, mock_presets, mock_library):
        self.widget = loot_applet.LootAppletWidget()
        # Populate library with some dummy items
        self.legendary_item = LootItem(
            item_id="1", title="Legendary Sword", rarity="legendary",
            category_label="Weapon", categories={"weapon"}, level=1, tags=set()
        )
        self.common_item = LootItem(
            item_id="2", title="Common Sword", rarity="common",
            category_label="Weapon", categories={"weapon"}, level=1, tags=set()
        )
        self.widget._item_library = [self.legendary_item, self.common_item]
        self.widget._item_by_id = {item.item_id: item for item in self.widget._item_library}
        
        # Ensure filters allow these
        # By default category checks might be empty if _load_item_library was mocked and not called
        # But _apply_filters handles empty checks by allowing all
        
        # Force update to populate filtered_pool
        self.widget._update_preview()

    def tearDown(self):
        self.widget.close()

    def test_prob_zero_if_pool_empty(self):
        # Empty pool for "rare"
        # Ensure filtered pool has no "rare" items (it only has legendary and common)
        
        # Set weights such that "rare" has non-zero probability
        # We can force custom weights
        self.widget._custom_weights_enabled = True
        self.widget._weight_sliders["rare"].setValue(500) # 50.0%
        self.widget._weight_sliders["common"].setValue(500) # 50.0%
        # Others 0
        for r in RARITY_ORDER:
            if r not in ("rare", "common"):
                self.widget._weight_sliders[r].setValue(0)
        
        self.widget._rolls_spin.setValue(10)
        
        self.widget._update_table()
        
        # Rare pool is empty (count 0)
        # Prob should be 0.0% despite high weight
        self.assertEqual(self.widget._prob_value_labels["rare"].text(), "0.0%")

    def test_prob_calculation(self):
        # Legendary in pool.
        # Set legendary weight to 50%
        self.widget._custom_weights_enabled = True
        for r in RARITY_ORDER:
            self.widget._weight_sliders[r].setValue(0)
        self.widget._weight_sliders["legendary"].setValue(500) # 50%
        self.widget._weight_sliders["common"].setValue(500) # 50%
        
        # 1 Roll
        self.widget._rolls_spin.setValue(1)
        self.widget._update_table()
        # P = 0.5. Prob >= 1 = 50.0%
        self.assertEqual(self.widget._prob_value_labels["legendary"].text(), "50.0%")
        
        # 2 Rolls
        self.widget._rolls_spin.setValue(2)
        self.widget._update_table()
        # P = 1 - (0.5)^2 = 0.75 -> 75.0%
        self.assertEqual(self.widget._prob_value_labels["legendary"].text(), "75.0%")

    def test_prob_100_percent(self):
        # Legendary weight 100%
        self.widget._custom_weights_enabled = True
        for r in RARITY_ORDER:
            self.widget._weight_sliders[r].setValue(0)
        self.widget._weight_sliders["legendary"].setValue(1000)
        
        self.widget._rolls_spin.setValue(1)
        self.widget._update_table()
        
        self.assertEqual(self.widget._prob_value_labels["legendary"].text(), "100.0%")

    def test_prob_sums_to_100_with_fallback(self):
        # Setup:
        # Common: Has items. Weight 50%.
        # Rare: Empty pool. Weight 50%.
        # Others: Empty pool. Weight 0%.
        
        # Rare should fall back to Common (eventually).
        # Rare (index 2).
        # Offset 1: Uncommon (1), Very Rare (3). Both empty? 
        # We need to ensure intermediate pools are empty too.
        
        # Clear library and set up just Common item.
        self.widget._item_library = [self.common_item] # Only Common
        self.widget._item_by_id = {item.item_id: item for item in self.widget._item_library}
        self.widget._update_preview() # Refresh filtered pool
        
        self.widget._custom_weights_enabled = True
        for r in RARITY_ORDER:
            self.widget._weight_sliders[r].setValue(0)
            
        self.widget._weight_sliders["common"].setValue(500) # 50%
        self.widget._weight_sliders["rare"].setValue(500)   # 50%
        
        self.widget._rolls_spin.setValue(1)
        self.widget._update_table()
        
        # Rare is empty, so prob should be 0.0%
        self.assertEqual(self.widget._prob_value_labels["rare"].text(), "0.0%")
        
        # Common should absorb Rare's weight -> 100%
        # (Rare falls back to Uncommon -> Common)
        self.assertEqual(self.widget._prob_value_labels["common"].text(), "100.0%")
