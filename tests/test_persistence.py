import unittest
import json
import os
import tempfile
from pathlib import Path
from dataclasses import asdict

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dmt_package import read_dmt_package_asset, read_dmt_package_info
from session_creator import SessionManager, Session, SessionAttachment, SessionLogEntry
from npc_database import NPCEntry, entry_to_dict, entry_from_dict, npc_storage_dir
from maps_applet import MapAsset, entry_to_dict as map_to_dict, entry_from_dict as map_from_dict
import player_sheets

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
        session_creator.session_storage_path = lambda: self.test_path / "sessions.dmtindex"

        try:
            manager = SessionManager()
            attachment = SessionAttachment(
                id="att_notes",
                name="notes.txt",
                asset_path="assets/files/att_notes/notes.txt",
                mime="text/plain",
                is_text=True,
            )
            session = Session(
                id="test_session",
                name="Test Session",
                session_date="2023-10-27",
                notes="Some notes",
                logs=[SessionLogEntry(timestamp="12:00", event_type="Test", description="Event")],
                attachments=[attachment],
            )
            manager.sessions.append(session)
            manager.set_attachment_bytes(session.id, attachment.id, b"hello attachment")
            manager.save()
            session_files = list(self.test_path.glob("*.dmtsession"))
            self.assertEqual(len(session_files), 1)
            self.assertEqual(session_files[0].name, "test_session.dmtsession")
            info = read_dmt_package_info(session_files[0])
            self.assertIsInstance(info, dict)
            self.assertEqual(info.get("format"), "dmtsession.v2")
            attachments = info.get("attachments") or []
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get("name"), "notes.txt")
            asset_path = str(attachments[0].get("asset_path") or "")
            self.assertTrue(asset_path)
            asset_payload = read_dmt_package_asset(session_files[0], asset_path)
            self.assertEqual(asset_payload, b"hello attachment")

            # Load in a new manager
            new_manager = SessionManager()
            self.assertEqual(len(new_manager.sessions), 1)
            loaded = new_manager.sessions[0]
            self.assertEqual(loaded.id, "test_session")
            self.assertEqual(loaded.name, "Test Session")
            self.assertEqual(len(loaded.logs), 1)
            self.assertEqual(loaded.logs[0].event_type, "Test")
            self.assertEqual(len(loaded.attachments), 1)
            self.assertEqual(loaded.attachments[0].name, "notes.txt")
            self.assertEqual(
                new_manager.get_attachment_bytes(loaded.id, loaded.attachments[0].id),
                b"hello attachment",
            )
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

    def test_character_and_npc_storage_directory_names(self):
        import npc_database

        original_sheet_save_dir = player_sheets.default_sheet_save_dir
        original_npc_sheet_save_dir = npc_database.default_sheet_save_dir
        player_sheets.default_sheet_save_dir = lambda: str(self.test_path)
        npc_database.default_sheet_save_dir = lambda: str(self.test_path)
        try:
            self.assertEqual(player_sheets.character_sheets_dir(), self.test_path / "characters")
            self.assertEqual(player_sheets.character_sheet_cache_dir(), self.test_path / "cache" / "characters")
            self.assertEqual(npc_storage_dir(), self.test_path / "npcs")
        finally:
            player_sheets.default_sheet_save_dir = original_sheet_save_dir
            npc_database.default_sheet_save_dir = original_npc_sheet_save_dir

if __name__ == "__main__":
    unittest.main()
