import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from player_sheets import (
    sanitize_filename,
    parse_tag_query,
    normalize_tags,
    entry_to_dict,
    entry_from_dict,
    list_campaigns,
    PlayerSheetEntry,
    EQUIPMENT_SLOTS_MISC,
)

class TestPlayerSheetsUtils(unittest.TestCase):
    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("Hello World!"), "Hello_World")
        self.assertEqual(sanitize_filename("  spaces  "), "spaces")
        self.assertEqual(sanitize_filename("invalid/path?"), "invalid_path")
        self.assertEqual(sanitize_filename("..."), "character_sheet")
        self.assertEqual(sanitize_filename(""), "character_sheet")

    def test_parse_tag_query(self):
        self.assertEqual(parse_tag_query("Tag1, Tag2"), ["tag1", "tag2"])
        self.assertEqual(parse_tag_query("Tag1 Tag2"), ["tag1", "tag2"])
        self.assertEqual(parse_tag_query(""), [])

    def test_normalize_tags(self):
        self.assertEqual(normalize_tags([" Tag1 ", "TAG2", "tag1"]), ["tag1", "tag2"])

    def test_serialization(self):
        entry = PlayerSheetEntry(
            name="Grog",
            pdf_path="grog.pdf",
            sheet_id="Grog_sheet_20260226120000_deadbeefcafebabe",
            world="Exandria",
            campaign="Vox Machina",
            group="Bells Hells",
            tags=["goliath", "barbarian"],
            inventory=["Axe", "Beer"],
            inventory_notes="Lantern oil, antitoxin",
        )
        
        as_dict = entry_to_dict(entry)
        self.assertEqual(as_dict["name"], "Grog")
        self.assertEqual(as_dict["sheet_id"], "Grog_sheet_20260226120000_deadbeefcafebabe")
        self.assertEqual(as_dict["tags"], ["goliath", "barbarian"])
        
        back = entry_from_dict(as_dict)
        self.assertEqual(back.name, entry.name)
        self.assertEqual(back.pdf_path, entry.pdf_path)
        self.assertEqual(back.sheet_id, entry.sheet_id)
        self.assertEqual(back.world, entry.world)
        self.assertEqual(back.tags, entry.tags)
        self.assertEqual(back.inventory, entry.inventory)
        self.assertEqual(back.inventory_notes, entry.inventory_notes)

    def test_entry_from_dict_invalid(self):
        self.assertIsNone(entry_from_dict(None))
        self.assertIsNone(entry_from_dict({}))
        self.assertIsNone(entry_from_dict({"name": "Only Name"}))

    def test_entry_from_dict_adds_new_misc_slots_with_none_defaults(self):
        payload = {
            "name": "Legacy",
            "pdf_path": "legacy.pdf",
            "equipment": {"head": "helmet_item_id"},
        }
        entry = entry_from_dict(payload)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.equipment.get("head"), "helmet_item_id")
        for slot_id, _ in EQUIPMENT_SLOTS_MISC:
            self.assertIn(slot_id, entry.equipment)
            self.assertIsNone(entry.equipment[slot_id])

    def test_list_campaigns_aggregates_all_matching_duplicate_world_names(self):
        world_data = [
            {"name": "Dup", "campaigns": [{"name": "Camp One"}]},
            {"name": "Dup", "campaigns": [{"name": "Camp Two"}]},
        ]

        self.assertEqual(list_campaigns(world_data, "Dup"), ["Camp One", "Camp Two"])

if __name__ == "__main__":
    unittest.main()
