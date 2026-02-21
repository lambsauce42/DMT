import importlib.util
import sys
import unittest
from dataclasses import asdict
from pathlib import Path


_MODELS_PATH = Path(__file__).resolve().parents[1] / "src" / "models.py"
_SPEC = importlib.util.spec_from_file_location("dmt_models", _MODELS_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODELS = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODELS
_SPEC.loader.exec_module(_MODELS)

Campaign = _MODELS.Campaign
Dungeon = _MODELS.Dungeon
Group = _MODELS.Group
Item = _MODELS.Item
MapAsset = _MODELS.MapAsset
NPC = _MODELS.NPC
Session = _MODELS.Session
SessionLogEntry = _MODELS.SessionLogEntry
World = _MODELS.World


class TestModelsUnit(unittest.TestCase):
    def test_world_instantiation(self):
        world = World(id="1", name="Faerun", description="A high fantasy world")
        self.assertEqual(world.name, "Faerun")
        self.assertEqual(world.description, "A high fantasy world")
        self.assertEqual(world.campaign_ids, [])

    def test_campaign_instantiation(self):
        campaign = Campaign(id="1", world_id="1", name="Curse of Strahd")
        self.assertEqual(campaign.name, "Curse of Strahd")
        self.assertEqual(campaign.world_id, "1")
        self.assertEqual(campaign.group_ids, [])

    def test_group_instantiation(self):
        group = Group(id="1", campaign_id="1", name="The Heroes")
        self.assertEqual(group.name, "The Heroes")
        self.assertEqual(group.campaign_id, "1")

    def test_session_instantiation(self):
        session = Session(id="1", name="Episode 1", session_date="2023-01-01")
        self.assertEqual(session.name, "Episode 1")
        self.assertEqual(session.logs, [])
        self.assertEqual(session.group_ids, [])

    def test_map_asset_defaults(self):
        map_asset = MapAsset(id="m1", name="Town", image_path="town.png")
        self.assertEqual(map_asset.tags, [])
        self.assertIsNone(map_asset.thumbnail_path)
        self.assertEqual(map_asset.notes, "")

    def test_session_log_entry_round_trip(self):
        entry = SessionLogEntry(
            timestamp="2026-02-10T12:00:00",
            event_type="combat",
            description="Battle started",
        )
        payload = asdict(entry)
        self.assertEqual(payload["event_type"], "combat")
        self.assertEqual(payload["description"], "Battle started")

    def test_other_dataclass_defaults(self):
        dungeon = Dungeon(id="d1", name="Crypt", world_id="w1")
        item = Item(id="i1", name="Sword")
        npc = NPC(id="n1", name="Innkeeper", world_id="w1")
        self.assertIsNone(dungeon.json_path)
        self.assertEqual(item.required_level, 1)
        self.assertEqual(item.tags, [])
        self.assertEqual(npc.tags, [])

    def test_dataclass_conversion(self):
        world = World(id="1", name="Test World")
        data = asdict(world)
        self.assertEqual(data["name"], "Test World")


if __name__ == "__main__":
    unittest.main()
