import os
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from npc_database import NPCEntry, matches_filters, filter_entries, _split_search
from dmt_package import read_dmt_package_info, write_dmt_package

class TestNPCDatabaseLogic(unittest.TestCase):
    def test_split_search(self):
        self.assertEqual(_split_search("hello world"), ["hello", "world"])
        self.assertEqual(_split_search("  extra   spaces  "), ["extra", "spaces"])
        self.assertEqual(_split_search("comma,separated"), ["comma", "separated"])
        self.assertEqual(_split_search(""), [])

    def test_matches_filters_basic(self):
        entry = NPCEntry(
            id="1",
            name="Bob",
            role="Blacksmith",
            world="Faerun",
            campaign="Strahd",
            group="Heroes",
            tags=["friendly", "strong"]
        )
        
        # Test exact matches
        self.assertTrue(matches_filters(entry, "Faerun", "Strahd", "Heroes", "", ""))
        self.assertFalse(matches_filters(entry, "Greyhawk", None, None, "", ""))
        
        # Test tag query
        self.assertTrue(matches_filters(entry, None, None, None, "friendly", ""))
        self.assertTrue(matches_filters(entry, None, None, None, "friendly strong", ""))
        self.assertFalse(matches_filters(entry, None, None, None, "hostile", ""))

    def test_matches_filters_search_query(self):
        entry = NPCEntry(
            id="1",
            name="Bob the Bold",
            role="Guard",
            location="North Gate",
            description="A very brave man",
            tags=["loyal"]
        )
        
        # Search in name
        self.assertTrue(matches_filters(entry, None, None, None, "", "Bob"))
        # Search in role
        self.assertTrue(matches_filters(entry, None, None, None, "", "Guard"))
        # Search in location
        self.assertTrue(matches_filters(entry, None, None, None, "", "Gate"))
        # Search in description
        self.assertTrue(matches_filters(entry, None, None, None, "", "brave"))
        # Search in tags
        self.assertTrue(matches_filters(entry, None, None, None, "", "loyal"))
        # Multiple tokens (AND logic)
        self.assertTrue(matches_filters(entry, None, None, None, "", "Bob brave"))
        self.assertFalse(matches_filters(entry, None, None, None, "", "Bob coward"))

    def test_filter_entries(self):
        entries = [
            NPCEntry(id="1", name="Alice", world="W1"),
            NPCEntry(id="2", name="Bob", world="W1"),
            NPCEntry(id="3", name="Charlie", world="W2"),
        ]
        
        results = filter_entries(entries, world="W1")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].name, "Alice")
        self.assertEqual(results[1].name, "Bob")
        
        results = filter_entries(entries, search_query="Charlie")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Charlie")

    def test_save_preserves_unknown_format_packages(self):
        import npc_database

        with TemporaryDirectory() as tmpdir:
            original_sheet_save_dir = npc_database.default_sheet_save_dir
            npc_database.default_sheet_save_dir = lambda: str(Path(tmpdir))
            try:
                root = npc_database.npc_storage_dir()
                root.mkdir(parents=True, exist_ok=True)
                unknown_file = root / "future_format.dmtnpc"
                write_dmt_package(
                    unknown_file,
                    info={
                        "format": "dmtnpc.v999",
                        "object_type": "npc",
                        "object_id": "future",
                        "payload": {"id": "future", "name": "Future NPC"},
                    },
                )
                npc_database.save_npc_entries_to_storage([])
                self.assertTrue(unknown_file.exists())
            finally:
                npc_database.default_sheet_save_dir = original_sheet_save_dir

    def test_save_npc_assigns_long_object_id_in_package(self):
        import npc_database

        with TemporaryDirectory() as tmpdir:
            original_sheet_save_dir = npc_database.default_sheet_save_dir
            original_now_timestamp = npc_database._now_timestamp
            npc_database.default_sheet_save_dir = lambda: str(Path(tmpdir))
            npc_database._now_timestamp = lambda: "2026-02-26T12:00:00"
            try:
                entry = NPCEntry(id="", name="Bob")
                npc_database.save_npc_entries_to_storage([entry])

                self.assertTrue(entry.id.startswith("Bob_"))
                self.assertIn("_npc_", entry.id)

                path = npc_database.npc_file_path(entry.name)
                payload = read_dmt_package_info(path)
                self.assertIsInstance(payload, dict)
                self.assertEqual(path.name, "Bob.dmtnpc")
                self.assertEqual(payload["object_id"], entry.id)
            finally:
                npc_database._now_timestamp = original_now_timestamp
                npc_database.default_sheet_save_dir = original_sheet_save_dir

if __name__ == "__main__":
    unittest.main()
