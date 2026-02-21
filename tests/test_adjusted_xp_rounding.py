import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from encounter_engine import EncounterEntry, Monster, compute_adjusted_xp


class AdjustedXpRoundingTests(unittest.TestCase):
    def test_adjusted_xp_rounding_half_up(self) -> None:
        table = [(1, None, 1.5, 1.5, 1.5)]
        monster = Monster(
            id="m",
            name="Test",
            cr="1",
            cr_value=1.0,
            xp=101,
            hp=5,
            ac=10,
            actions="",
            description="",
            tags=(),
            source="",
        )
        entry = EncounterEntry(monster=monster, count=1)
        with patch("encounter_engine.load_multiplier_table", return_value=table):
            raw_xp, multiplier, adjusted = compute_adjusted_xp([entry], party_size=4)
        self.assertEqual(raw_xp, 101)
        self.assertEqual(multiplier, 1.5)
        self.assertEqual(adjusted, 152)


if __name__ == "__main__":
    unittest.main()
