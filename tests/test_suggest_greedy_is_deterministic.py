import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from encounter_engine import Monster, suggest_monsters


class SuggestGreedyDeterminismTests(unittest.TestCase):
    def test_suggest_is_deterministic(self) -> None:
        monsters = [
            Monster(
                id="a",
                name="Alpha",
                cr="1",
                cr_value=1.0,
                xp=100,
                hp=10,
                ac=12,
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
                ac=12,
                actions="",
                description="",
                tags=(),
                source="",
            ),
            Monster(
                id="c",
                name="Gamma",
                cr="1",
                cr_value=1.0,
                xp=25,
                hp=10,
                ac=12,
                actions="",
                description="",
                tags=(),
                source="",
            ),
        ]
        result_one = suggest_monsters(180, monsters, max_monsters=4)
        result_two = suggest_monsters(180, monsters, max_monsters=4)
        self.assertEqual(
            [(entry.monster.id, entry.count) for entry in result_one],
            [(entry.monster.id, entry.count) for entry in result_two],
        )


if __name__ == "__main__":
    unittest.main()
