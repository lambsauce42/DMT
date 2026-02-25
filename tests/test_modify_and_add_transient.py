import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PySide6.QtWidgets import QApplication

from encounter_engine import Monster
from ui.encounter_edit_dialog import ModifyMonsterDialog


class ModifyAndAddTransientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_modify_dialog_creates_transient(self) -> None:
        base = Monster(
            id="base",
            name="Base",
            cr="1/4",
            cr_value=0.25,
            xp=50,
            hp=7,
            ac=13,
            actions="Hit",
            description="",
            tags=("test",),
            source="SRD",
        )
        dialog = ModifyMonsterDialog(base, count=2)
        dialog._name.setText("Modified")
        dialog._xp.setValue(60)
        dialog.accept()

        result = dialog.result_monster()
        self.assertIsNotNone(result)
        self.assertTrue(result.transient)
        self.assertTrue(result.id.startswith("transient:"))
        self.assertEqual(result.name, "Modified")
        self.assertEqual(result.xp, 60)
        self.assertEqual(base.name, "Base")


if __name__ == "__main__":
    unittest.main()
