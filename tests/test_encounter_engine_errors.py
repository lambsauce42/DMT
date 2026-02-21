import os
import sys
import unittest
import tempfile
import csv
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from encounter_engine import load_monsters, EncounterDataError

class TestEncounterEngineErrors(unittest.TestCase):
    def test_load_monsters_missing_file(self):
        with self.assertRaises(EncounterDataError):
            load_monsters(Path("non_existent_file.csv"))

    def test_load_monsters_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(EncounterDataError) as cm:
                load_monsters(tmp_path)
            self.assertIn("no headers", str(cm.exception))
        finally:
            tmp_path.unlink()

    def test_load_monsters_missing_columns(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
            writer = csv.DictWriter(tmp, fieldnames=["id", "name"]) # missing xp, hp, etc
            writer.writeheader()
            writer.writerow({"id": "1", "name": "Test"})
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(EncounterDataError) as cm:
                load_monsters(tmp_path)
            self.assertIn("missing required columns", str(cm.exception))
        finally:
            tmp_path.unlink()

    def test_load_monsters_invalid_data(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
            headers = ["id", "name", "cr", "xp", "hp", "ac", "actions", "description", "tags", "source"]
            writer = csv.DictWriter(tmp, fieldnames=headers)
            writer.writeheader()
            writer.writerow({
                "id": "1", "name": "Test", "cr": "1", 
                "xp": "not_an_int", # Invalid XP
                "hp": "10", "ac": "10", 
                "actions": "", "description": "", "tags": "", "source": ""
            })
            tmp_path = Path(tmp.name)
        try:
            with self.assertRaises(EncounterDataError) as cm:
                load_monsters(tmp_path)
            self.assertIn("Invalid xp value", str(cm.exception))
        finally:
            tmp_path.unlink()

if __name__ == "__main__":
    unittest.main()
