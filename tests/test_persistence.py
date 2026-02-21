import unittest
import json
import os
import tempfile
from pathlib import Path
from dataclasses import asdict

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from session_creator import SessionManager, Session, SessionLogEntry
from npc_database import NPCEntry, entry_to_dict, entry_from_dict
from maps_applet import MapAsset, entry_to_dict as map_to_dict, entry_from_dict as map_from_dict

class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_path = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_session_persistence(self):
        """Test that Session objects can be saved and loaded correctly."""
        # Patch session_storage_path to redirect session storage root to our temp dir.
        import session_creator
        original_path_func = session_creator.session_storage_path
        session_creator.session_storage_path = lambda: self.test_path / "sessions.json"

        try:
            manager = SessionManager()
            session = Session(
                id="test_session",
                name="Test Session",
                session_date="2023-10-27",
                notes="Some notes",
                logs=[SessionLogEntry(timestamp="12:00", event_type="Test", description="Event")]
            )
            manager.sessions.append(session)
            manager.save()
            session_files = list(self.test_path.glob("*.dmtsession"))
            self.assertEqual(len(session_files), 1)
            self.assertEqual(session_files[0].name, "test_session.dmtsession")

            # Load in a new manager
            new_manager = SessionManager()
            self.assertEqual(len(new_manager.sessions), 1)
            loaded = new_manager.sessions[0]
            self.assertEqual(loaded.id, "test_session")
            self.assertEqual(loaded.name, "Test Session")
            self.assertEqual(len(loaded.logs), 1)
            self.assertEqual(loaded.logs[0].event_type, "Test")
        finally:
            session_creator.session_storage_path = original_path_func

    def test_npc_persistence(self):
        """Test NPCEntry serialization and deserialization."""
        npc = NPCEntry(
            id="npc_1",
            name="Gandalf",
            role="Wizard",
            location="Middle Earth",
            tags=["wizard", "maiur"],
            description="A wise wizard",
            created_at="2023-10-27T10:00:00"
        )
        
        data = entry_to_dict(npc)
        loaded_npc = entry_from_dict(data)
        
        self.assertIsNotNone(loaded_npc)
        self.assertEqual(loaded_npc.id, npc.id)
        self.assertEqual(loaded_npc.name, npc.name)
        self.assertEqual(loaded_npc.tags, npc.tags)
        self.assertEqual(loaded_npc.role, npc.role)

    def test_map_asset_persistence(self):
        """Test MapAsset serialization and deserialization."""
        map_asset = MapAsset(
            id="map_1",
            name="Dungeon Floor 1",
            image_path="/path/to/image.png",
            tags=["dungeon", "level1"],
            notes="Very dark"
        )
        
        data = map_to_dict(map_asset)
        loaded_map = map_from_dict(data)
        
        self.assertIsNotNone(loaded_map)
        self.assertEqual(loaded_map.id, map_asset.id)
        self.assertEqual(loaded_map.name, map_asset.name)
        self.assertEqual(loaded_map.image_path, map_asset.image_path)
        self.assertEqual(loaded_map.tags, map_asset.tags)

if __name__ == "__main__":
    unittest.main()
