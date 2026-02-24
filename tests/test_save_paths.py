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
        save_dir = save_paths.default_dnd_save_dir()
        expected = str(Path.cwd() / "tests" / "test_saves" / "DMT")
        self.assertEqual(save_dir, expected)

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
    def test_clear_all_online_runtime_caches_removes_root_cache_dir(self, mock_base):
        with tempfile.TemporaryDirectory() as td:
            mock_base.return_value = td
            root_cache = Path(td) / "cache"
            logs_cache = root_cache / "logs"
            logs_cache.mkdir(parents=True, exist_ok=True)
            (logs_cache / "online_debug.log").write_text("debug", encoding="utf-8")

            save_paths.clear_all_online_runtime_caches()

            self.assertFalse(root_cache.exists())

    def test_collection_icon_assets_dir_is_related_to_collection_file(self):
        path = Path("My Collection.json")
        assets_dir = save_paths.collection_icon_assets_dir(path)
        self.assertEqual(assets_dir, Path("My Collection_assets/icons"))

if __name__ == "__main__":
    unittest.main()
