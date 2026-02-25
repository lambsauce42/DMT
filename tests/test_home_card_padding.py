import sys
import os
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

# Ensure src is in path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import HomeCard

class HomeCardPaddingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_padding_consistency_narrow_tall(self):
        """Test that icon padding is consistent in narrow/tall viewports"""
        # Create a card with a narrow/tall geometry
        card = HomeCard(
            title="Test Applet",
            subtitle="Test Subtitle",
            icon_path=None,
            on_open=lambda x: None
        )
        card.show()
        
        # Force a narrow/tall size
        # available_width will be roughly 150, available_height roughly 400
        card.resize(200, 450)
        QApplication.processEvents()
        
        icon_label = card._icon_label
        geom = icon_label.geometry()
        
        padding_left = geom.left()
        padding_top = geom.top()
        padding_bottom = card.height() - geom.bottom() - 1
        
        print(f"\nNarrow tall geometry: {card.width()}x{card.height()}")
        print(f"Icon geometry: {geom.width()}x{geom.height()} at ({geom.x()}, {geom.y()})")
        print(f"Padding - Left: {padding_left}, Top: {padding_top}, Bottom: {padding_bottom}")
        
        # The user wants "the same distance to the outside card box on the left and up and down"
        # Since we haven't fixed it yet, this should fail if the bug is present.
        # Allowing some small tolerance for rounding
        self.assertAlmostEqual(padding_left, padding_top, delta=2, msg="Horizontal and vertical padding should be consistent")
        self.assertAlmostEqual(padding_top, padding_bottom, delta=2, msg="Top and bottom padding should be consistent")

    def test_padding_consistency_wide_short(self):
        """Test that icon padding is consistent in wide/short viewports"""
        card = HomeCard(
            title="Test Applet",
            subtitle="Test Subtitle",
            icon_path=None,
            on_open=lambda x: None
        )
        card.show()
        
        card.resize(600, 150)
        QApplication.processEvents()
        
        icon_label = card._icon_label
        geom = icon_label.geometry()
        
        padding_left = geom.left()
        padding_top = geom.top()
        padding_bottom = card.height() - geom.bottom() - 1
        
        print(f"\nWide short geometry: {card.width()}x{card.height()}")
        print(f"Icon geometry: {geom.width()}x{geom.height()} at ({geom.x()}, {geom.y()})")
        print(f"Padding - Left: {padding_left}, Top: {padding_top}, Bottom: {padding_bottom}")
        
        self.assertAlmostEqual(padding_left, padding_top, delta=2, msg="Horizontal and vertical padding should be consistent")
        self.assertAlmostEqual(padding_top, padding_bottom, delta=2, msg="Top and bottom padding should be consistent")

if __name__ == "__main__":
    unittest.main()
