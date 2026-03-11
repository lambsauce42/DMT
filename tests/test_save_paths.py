import unittest
import os
import sys
import base64
from pathlib import Path
from unittest.mock import patch
import tempfile

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import save_paths

_PNG_1X1_BYTES = (
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4////fwAJ+wP9KobjigAAAABJRU5ErkJggg=="
    )
)

class TestSavePaths(unittest.TestCase):
    def test_in_test_env(self):
        """Check that _in_test_env returns True when running tests."""
        self.assertTrue(save_paths._in_test_env())

    def test_default_dnd_save_dir_test_mode(self):
        """In test environment, save dir should point to tests/test_saves/DMT."""
        with patch.dict(os.environ, {"DMT_TEST_SAVE_DIR": ""}, clear=False):
            save_dir = save_paths.default_dnd_save_dir()
            expected = str(Path.cwd() / "tests" / "test_saves" / "DMT")
            self.assertEqual(save_dir, expected)

    def test_default_dnd_save_dir_test_mode_override(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"DMT_TEST_SAVE_DIR": td}, clear=False):
                save_dir = save_paths.default_dnd_save_dir()
            self.assertEqual(save_dir, td)

    @patch("save_paths._in_test_env")
    @patch("os.path.expanduser")
    @patch("os.path.exists")
    def test_default_dnd_save_dir_production(self, mock_exists, mock_expanduser, mock_in_test):
        """Test production path resolution without migration."""
        mock_in_test.return_value = False
        mock_expanduser.return_value = "/home/user"
        mock_exists.return_value = True # Primary exists
        
        save_dir = save_paths.default_dnd_save_dir()
        self.assertEqual(Path(save_dir), Path("/home/user/Documents/DMT"))

    @patch("save_paths._in_test_env", return_value=False)
    def test_debug_profile_dir_is_persistent_between_calls(self, _mock_in_test):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            debug_root = home / "Documents" / "DEBUG1_DMT"
            marker = debug_root / "marker.txt"
            debug_root.mkdir(parents=True, exist_ok=True)
            marker.write_text("keep", encoding="utf-8")
            with patch("os.path.expanduser", return_value=str(home)):
                with patch("os.path.exists", return_value=True):
                    with patch.dict(os.environ, {"DMT_SAVE_PROFILE": "DEBUG1"}, clear=False):
                        first_dir = Path(save_paths.default_dnd_save_dir())
                        second_dir = Path(save_paths.default_dnd_save_dir())

            self.assertEqual(first_dir, debug_root)
            self.assertEqual(second_dir, debug_root)
            self.assertTrue(marker.exists())

    @patch("save_paths._in_test_env", return_value=False)
    @patch("save_paths.default_dnd_save_dir")
    def test_derived_paths(self, mock_base, _mock_in_test):
        """Test paths derived from the canonical base save directory."""
        with tempfile.TemporaryDirectory() as td:
            mock_base.return_value = td
            saves_dir = save_paths.dnd_saves_dir()
            self.assertEqual(saves_dir, Path(td))

            trash_path = save_paths.trash_json_path()
            self.assertEqual(trash_path, str(Path(td) / "trash.json"))

    @patch("save_paths.default_dnd_save_dir")
    def test_clear_all_online_icon_caches_removes_cache_folders(self, mock_base):
        with tempfile.TemporaryDirectory() as td:
            mock_base.return_value = td
            session_cache = Path(td) / "online_sessions" / "sess-1" / "cache" / "icons"
            session_cache.mkdir(parents=True, exist_ok=True)
            (session_cache / "token.png").write_bytes(_PNG_1X1_BYTES)

            save_paths.clear_all_online_icon_caches()

            self.assertFalse(session_cache.exists())

    @patch("save_paths.default_dnd_save_dir")
    def test_clear_online_icon_cache_removes_single_session_cache(self, mock_base):
        with tempfile.TemporaryDirectory() as td:
            mock_base.return_value = td
            cache_a = Path(td) / "online_sessions" / "sess-a" / "cache" / "icons"
            cache_b = Path(td) / "online_sessions" / "sess-b" / "cache" / "icons"
            cache_a.mkdir(parents=True, exist_ok=True)
            cache_b.mkdir(parents=True, exist_ok=True)
            (cache_a / "a.png").write_bytes(_PNG_1X1_BYTES)
            (cache_b / "b.png").write_bytes(_PNG_1X1_BYTES)

            save_paths.clear_online_icon_cache("sess-a")

            self.assertFalse(cache_a.exists())
            self.assertTrue(cache_b.exists())

    @patch("save_paths.default_dnd_save_dir")
    def test_clear_online_loot_item_cache_removes_single_session_cache(self, mock_base):
        with tempfile.TemporaryDirectory() as td:
            mock_base.return_value = td
            cache_a = Path(td) / "cache" / "online_loot_items" / "sess-a"
            cache_b = Path(td) / "cache" / "online_loot_items" / "sess-b"
            cache_a.mkdir(parents=True, exist_ok=True)
            cache_b.mkdir(parents=True, exist_ok=True)
            (cache_a / "a.dmtitem").write_text("{}", encoding="utf-8")
            (cache_b / "b.dmtitem").write_text("{}", encoding="utf-8")

            save_paths.clear_online_loot_item_cache("sess-a")

            self.assertFalse(cache_a.exists())
            self.assertTrue(cache_b.exists())

    @patch("save_paths.default_dnd_save_dir")
    def test_clear_all_online_runtime_caches_removes_icon_and_loot_caches(self, mock_base):
        with tempfile.TemporaryDirectory() as td:
            mock_base.return_value = td
            icon_cache = Path(td) / "online_sessions" / "sess-1" / "cache" / "icons"
            loot_cache = Path(td) / "cache" / "online_loot_items" / "sess-1"
            icon_cache.mkdir(parents=True, exist_ok=True)
            loot_cache.mkdir(parents=True, exist_ok=True)
            (icon_cache / "token.png").write_bytes(_PNG_1X1_BYTES)
            (loot_cache / "item.dmtitem").write_text("{}", encoding="utf-8")

            save_paths.clear_all_online_runtime_caches()

            self.assertFalse(icon_cache.exists())
            self.assertFalse(loot_cache.exists())

    @patch("save_paths.default_dnd_save_dir")
    def test_clear_all_online_runtime_caches_preserves_unrelated_cache_dirs(self, mock_base):
        with tempfile.TemporaryDirectory() as td:
            mock_base.return_value = td
            root_cache = Path(td) / "cache"
            logs_cache = root_cache / "logs"
            unrelated_cache = root_cache / "item_icons"
            logs_cache.mkdir(parents=True, exist_ok=True)
            unrelated_cache.mkdir(parents=True, exist_ok=True)
            (logs_cache / "online_debug.log").write_text("debug", encoding="utf-8")
            (unrelated_cache / "cached.png").write_bytes(_PNG_1X1_BYTES)

            save_paths.clear_all_online_runtime_caches()

            self.assertTrue(root_cache.exists())
            self.assertTrue(logs_cache.exists())
            self.assertTrue(unrelated_cache.exists())

    @patch("save_paths.default_dnd_save_dir")
    def test_clear_character_metadata_caches_preserves_cached_sheet_pdfs(self, mock_base):
        with tempfile.TemporaryDirectory() as td:
            mock_base.return_value = td
            character_cache = Path(td) / "cache" / "characters"
            index_path = character_cache / "character_sheets.json"
            linked_items = character_cache / "linked_items" / "hero"
            cached_pdf = character_cache / "hero.pdf"
            linked_items.mkdir(parents=True, exist_ok=True)
            index_path.write_text("[]", encoding="utf-8")
            (linked_items / "item.dmtitem").write_text("{}", encoding="utf-8")
            cached_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

            save_paths.clear_character_metadata_caches()

            self.assertFalse(index_path.exists())
            self.assertFalse((character_cache / "linked_items").exists())
            self.assertTrue(cached_pdf.exists())

    @patch("save_paths.default_dnd_save_dir")
    def test_clear_all_disposable_caches_removes_safe_caches_but_keeps_logs_and_character_pdfs(self, mock_base):
        with tempfile.TemporaryDirectory() as td:
            mock_base.return_value = td
            root_cache = Path(td) / "cache"
            character_cache = root_cache / "characters"
            item_icons = root_cache / "item_icons"
            attachments = root_cache / "session_attachments" / "session-a"
            logs = root_cache / "logs"
            cached_pdf = character_cache / "hero.pdf"
            index_path = character_cache / "character_sheets.json"
            linked_items = character_cache / "linked_items" / "hero"

            linked_items.mkdir(parents=True, exist_ok=True)
            item_icons.mkdir(parents=True, exist_ok=True)
            attachments.mkdir(parents=True, exist_ok=True)
            logs.mkdir(parents=True, exist_ok=True)

            cached_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            index_path.write_text("[]", encoding="utf-8")
            (linked_items / "item.dmtitem").write_text("{}", encoding="utf-8")
            (item_icons / "cached.png").write_bytes(_PNG_1X1_BYTES)
            (attachments / "file.bin").write_bytes(b"payload")
            (logs / "dmt_app_crash.log").write_text("log", encoding="utf-8")

            save_paths.clear_all_disposable_caches()

            self.assertTrue(cached_pdf.exists())
            self.assertFalse(index_path.exists())
            self.assertFalse((character_cache / "linked_items").exists())
            self.assertFalse(item_icons.exists())
            self.assertFalse((root_cache / "session_attachments").exists())
            self.assertTrue((logs / "dmt_app_crash.log").exists())

    def test_collection_icon_assets_dir_is_related_to_collection_file(self):
        path = Path("My Collection.json")
        assets_dir = save_paths.collection_icon_assets_dir(path)
        self.assertEqual(assets_dir, Path("My Collection_assets/icons"))

    def test_collection_image_assets_dir_is_related_to_collection_file(self):
        path = Path("My Collection.json")
        assets_dir = save_paths.collection_image_assets_dir(path)
        self.assertEqual(assets_dir, Path("My Collection_assets/images"))

if __name__ == "__main__":
    unittest.main()
