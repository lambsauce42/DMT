import unittest
import json
import os
import tempfile
from pathlib import Path
from dataclasses import asdict
from datetime import datetime

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dmt_package import read_dmt_package_asset, read_dmt_package_info
from session_creator import SessionManager, Session, SessionAttachment, SessionLogEntry
from npc_database import NPCEntry, entry_to_dict, entry_from_dict, npc_storage_dir
from maps_applet import MapAsset, entry_to_dict as map_to_dict, entry_from_dict as map_from_dict
from navigation_storage import (
    save_navigation_world_data,
    navigation_objects_dir,
    WORLD_EXTENSION,
)
import player_sheets

class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_path = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def _debug_log(self, message: str) -> None:
        path = Path(__file__).resolve().parents[1] / "debug" / "session_persistence_audit.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            ts = datetime.now().isoformat(timespec="seconds")
            handle.write(f"[{ts}] {message}\n")

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

    def test_session_save_does_not_delete_unreadable_or_future_format_files(self):
        import session_creator
        from dmt_package import write_dmt_package

        original_path_func = session_creator.session_storage_path
        session_creator.session_storage_path = lambda: self.test_path / "sessions.dmtindex"
        try:
            future_file = self.test_path / "future_format.dmtsession"
            write_dmt_package(
                future_file,
                info={
                    "format": "dmtsession.v999",
                    "object_type": "session",
                    "object_id": "future",
                    "payload": {
                        "id": "future",
                        "name": "Future Session",
                        "session_date": "2099-01-01",
                    },
                },
            )
            self._debug_log(f"created foreign session package at {future_file}")

            manager = SessionManager()
            self._debug_log(
                f"loaded SessionManager sessions={len(manager.sessions)} last_error={manager.last_error!r}"
            )
            manager.save()
            self._debug_log("called SessionManager.save() after loading foreign-format file")

            self.assertTrue(
                future_file.exists(),
                "Saving sessions should not delete unreadable/unknown-format session files.",
            )
        finally:
            session_creator.session_storage_path = original_path_func

    def test_navigation_save_preserves_unknown_format_packages(self):
        from dmt_package import write_dmt_package

        worlds_dir = navigation_objects_dir(base_dir=self.test_path) / "worlds"
        worlds_dir.mkdir(parents=True, exist_ok=True)
        unknown_world = worlds_dir / f"future{WORLD_EXTENSION}"
        write_dmt_package(
            unknown_world,
            info={
                "format": "dmtworld.v999",
                "object_type": "world",
                "object_id": "future",
                "name": "Future World",
            },
        )
        save_navigation_world_data([], base_dir=self.test_path)
        self.assertTrue(unknown_world.exists())

if __name__ == "__main__":
    unittest.main()
