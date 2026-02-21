import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from encounter_engine import EncounterDataError, compute_target_xp


class TargetXpSumTests(unittest.TestCase):
    def test_target_xp_sums_by_level(self) -> None:
        table = {
            1: {"easy": 25, "medium": 50, "hard": 75, "deadly": 100},
            2: {"easy": 50, "medium": 100, "hard": 150, "deadly": 200},
        }
        with patch("encounter_engine.load_difficulty_table", return_value=table):
            total = compute_target_xp([1, 2, 2], "medium")
        self.assertEqual(total, 250)

    def test_invalid_difficulty_raises(self) -> None:
        table = {1: {"easy": 25}}
        with patch("encounter_engine.load_difficulty_table", return_value=table):
            with self.assertRaises(EncounterDataError):
                compute_target_xp([1], "hard")


if __name__ == "__main__":
    unittest.main()
