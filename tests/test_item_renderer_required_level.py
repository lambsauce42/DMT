import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from item_renderer import ItemCardSpec, spec_from_dict, spec_to_dict


class ItemRendererClassesTests(unittest.TestCase):
    def test_classes_round_trip(self) -> None:
        # classes is now a List[str]
        spec = ItemCardSpec(title="Test Relic", rarity="rare", classes=["Wizard", "Fighter"])
        data = spec_to_dict(spec)
        self.assertEqual(data["classes"], ["Wizard", "Fighter"])

        loaded = spec_from_dict(data)
        self.assertEqual(loaded.classes, ["Wizard", "Fighter"])

    def test_classes_default(self) -> None:
        # Empty list means "All Classes"
        loaded = spec_from_dict({"title": "Default Classes"})
        self.assertEqual(loaded.classes, [])
    
    def test_classes_legacy_string_format(self) -> None:
        # Backwards compatibility: old saved items may have string format
        loaded = spec_from_dict({"title": "Legacy", "classes": "Wizard, Fighter"})
        self.assertEqual(loaded.classes, ["Wizard", "Fighter"])


if __name__ == "__main__":
    unittest.main()
