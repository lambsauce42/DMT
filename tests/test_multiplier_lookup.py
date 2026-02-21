import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from encounter_engine import lookup_multiplier


class MultiplierLookupTests(unittest.TestCase):
    def test_lookup_across_ranges(self) -> None:
        table = [
            (1, 1, 1.5, 1.0, 0.5),
            (2, 2, 2.0, 1.5, 1.0),
            (3, 6, 2.5, 2.0, 1.5),
            (7, 10, 3.0, 2.5, 2.0),
            (11, 14, 4.0, 3.0, 2.5),
            (15, None, 5.0, 4.0, 3.0),
        ]
        with patch("encounter_engine.load_multiplier_table", return_value=table):
            self.assertEqual(lookup_multiplier(1, 1), 1.5)
            self.assertEqual(lookup_multiplier(2, 4), 1.5)
            self.assertEqual(lookup_multiplier(8, 6), 2.0)
            self.assertEqual(lookup_multiplier(16, 6), 3.0)


if __name__ == "__main__":
    unittest.main()
