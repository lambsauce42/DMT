import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from encounter_engine import Monster, parse_tags_text, sort_monsters_by_xp


class EncounterTagsAndSortTests(unittest.TestCase):
    def test_parse_tags_text(self) -> None:
        tags = parse_tags_text(" undead,  boss ; elite ")
        self.assertEqual(tags, ("undead", "boss", "elite"))

    def test_sort_monsters_by_xp(self) -> None:
        monsters = [
            Monster(
                id="a",
                name="Alpha",
                cr="1",
                cr_value=1.0,
                xp=200,
                hp=10,
                ac=10,
                actions="",
                description="",
                tags=(),
                source="",
            ),
            Monster(
                id="b",
                name="Beta",
                cr="1",
                cr_value=1.0,
                xp=50,
                hp=10,
                ac=10,
                actions="",
                description="",
                tags=(),
                source="",
            ),
        ]
        asc = sort_monsters_by_xp(monsters, "asc")
        desc = sort_monsters_by_xp(monsters, "desc")
        self.assertEqual([m.id for m in asc], ["b", "a"])
        self.assertEqual([m.id for m in desc], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
