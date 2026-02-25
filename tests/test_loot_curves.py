import os
import sys
import unittest

from PySide6.QtWidgets import QApplication

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import loot_applet
from loot_applet import RARITY_ORDER, RARITY_CURVES

app = QApplication.instance() or QApplication(sys.argv)

class TestLootCurves(unittest.TestCase):
    def setUp(self):
        self.widget = loot_applet.LootAppletWidget()

    def tearDown(self):
        self.widget.close()

    def test_all_curves_produce_valid_weights(self):
        for curve in RARITY_CURVES:
            self.widget._curve_combo.setCurrentText(curve)
            
            for luck_val in [1, 50, 100]:
                self.widget._luck_slider.setValue(luck_val * loot_applet.LUCK_SLIDER_SCALE)
                weights = self.widget._calculate_weights()
                
                # Check all rarities are present
                for r in RARITY_ORDER:
                    self.assertIn(r, weights, f"Curve {curve} at luck {luck_val} missing {r}")
                    self.assertGreaterEqual(weights[r], 0.0, f"Curve {curve} negative weight")
                
                total = sum(weights.values())
                self.assertAlmostEqual(total, 100.0, delta=0.01, msg=f"Curve {curve} sums to {total}")

    def test_flat_curve_is_flat(self):
        self.widget._curve_combo.setCurrentText("Flat")
        weights = self.widget._calculate_weights()
        
        # Artifact is special case (added on top), but core rarities should be equal *before* normalization?
        # _flat_weights returns 1.0 for all core.
        # _calculate_weights adds artifact weight based on sum.
        # Then normalizes.
        
        # Check core rarities are roughly equal
        core = [r for r in RARITY_ORDER if r != "artifact"]
        first = weights[core[0]]
        for r in core[1:]:
            self.assertAlmostEqual(weights[r], first, delta=0.01)

    def test_inverted_curve(self):
        self.widget._curve_combo.setCurrentText("Inverted")
        self.widget._luck_slider.setValue(100 * loot_applet.LUCK_SLIDER_SCALE)
        weights = self.widget._calculate_weights()
        
        # Legendary should be > Common at high luck (Inverted logic: Common is low, Legendary is high)
        self.assertGreater(weights["legendary"], weights["common"])

    def test_linear_steep_vs_linear(self):
        luck_val = 1 * loot_applet.LUCK_SLIDER_SCALE # Low luck
        self.widget._luck_slider.setValue(luck_val)
        
        self.widget._curve_combo.setCurrentText("Linear")
        w_linear = self.widget._calculate_weights()
        
        self.widget._curve_combo.setCurrentText("Linear (Steep)")
        w_steep = self.widget._calculate_weights()
        
        # Steep should punish high rarities more at low luck
        # So Legendary weight in Steep should be lower than Normal Linear
        self.assertLess(w_steep["legendary"], w_linear["legendary"])

    def test_bell_curve_variants(self):
        # Luck = 50% (Norm 0.5) -> Peak at Rare (index 2)
        self.widget._luck_slider.setValue(50 * loot_applet.LUCK_SLIDER_SCALE)
        
        self.widget._curve_combo.setCurrentText("Bell Curve (Narrow)")
        w_narrow = self.widget._calculate_weights()
        
        self.widget._curve_combo.setCurrentText("Bell Curve (Wide)")
        w_wide = self.widget._calculate_weights()
        
        # At peak (rare), Narrow should have higher relative weight (after normalization) 
        # But wait, weights are normalized to sum to 100.
        # Narrow: Peak is high, tails are near zero. Sum is dominated by peak.
        # Wide: Peak is high, tails are high. Sum is larger.
        # Normalized:
        # Narrow: Rare % should be higher.
        # Wide: Rare % should be lower (more spread to others).
        
        self.assertGreater(w_narrow["rare"], w_wide["rare"])
        
        # Check tails (Common)
        # Narrow: Common should be very low.
        # Wide: Common should be higher.
        self.assertLess(w_narrow["common"], w_wide["common"])

if __name__ == "__main__":
    unittest.main()
