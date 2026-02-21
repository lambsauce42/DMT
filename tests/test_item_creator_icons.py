import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt6.QtWidgets import QApplication

import item_creator


class ItemCreatorIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_icon_grid_populates(self) -> None:
        widget = item_creator.ItemCreatorWidget()
        try:
            self.assertGreater(len(widget._icon_grid_buttons), 0)
            widget._reflow_icon_grid()
            self.assertGreater(widget._icon_grid.count(), 0)
            self.assertEqual(widget._icon_grid.count(), len(widget._icon_grid_buttons))
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
