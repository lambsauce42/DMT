import os
import sys
import unittest
from pathlib import Path
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt6.QtWidgets import QApplication

from player_sheets import (
    PlayerSheetEntry,
    PlayerSheetsWidget,
)


class PlayerSheetsEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_external_inventory_saved_updates_entry_and_refreshes_current_sheet(self) -> None:
        # Bypass full widget initialization to keep this test deterministic/offscreen-safe.
        widget = PlayerSheetsWidget.__new__(PlayerSheetsWidget)
        entry = PlayerSheetEntry(name="Event Test", pdf_path="")
        widget._manager = types.SimpleNamespace(entries=[entry])
        widget._current_entry = entry
        refreshed = {"count": 0}
        widget._set_inventory = lambda _entry: refreshed.__setitem__("count", refreshed["count"] + 1)

        payload = {
            "inventory": [str(Path("tmp") / "item_1.json")],
            "inventory_notes": "Custom line",
            "equipment": {"weapon_1": str(Path("tmp") / "weapon_1.json")},
            "gold": 7,
            "silver": 8,
            "copper": 9,
        }

        widget._on_external_inventory_saved("Event_Test", payload)

        self.assertEqual(entry.inventory, [payload["inventory"][0]])
        self.assertEqual(entry.inventory_notes, "Custom line")
        self.assertEqual(entry.equipment.get("weapon_1"), payload["equipment"]["weapon_1"])
        self.assertEqual(entry.gold, 7)
        self.assertEqual(entry.silver, 8)
        self.assertEqual(entry.copper, 9)
        self.assertEqual(refreshed["count"], 1)


if __name__ == "__main__":
    unittest.main()
