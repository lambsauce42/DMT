import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QAbstractItemView, QApplication, QDialogButtonBox, QLabel, QLineEdit

import compact_nav_tree


class NavigationTrashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_load_navigation_data_reads_legacy_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            nav_path = Path(tmpdir) / "navigation.json"
            nav_path.write_text(
                json.dumps([{"name": "Legacy World", "campaigns": []}], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            original_path = compact_nav_tree.NAVIGATION_PATH
            try:
                compact_nav_tree.NAVIGATION_PATH = str(nav_path)
                loaded = compact_nav_tree.load_navigation_data()
            finally:
                compact_nav_tree.NAVIGATION_PATH = original_path
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].get("name"), "Legacy World")

    def test_trash_purges_old_entries(self) -> None:
        """Test that old trash entries are purged on widget initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trash_path = Path(tmpdir) / "navigation_trash.json"
            data_path = Path(tmpdir) / "navigation_data.json"
            
            # Create initial navigation data
            nav_data = [{"name": "World A", "campaigns": []}]
            data_path.write_text(
                json.dumps(nav_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            
            # Create trash with one old and one new entry
            old_date = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            new_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
            trash_data = [
                {
                    "type": "world",
                    "name": "Old World",
                    "payload": {"name": "Old World"},
                    "deleted_at": old_date,
                },
                {
                    "type": "world",
                    "name": "New World",
                    "payload": {"name": "New World"},
                    "deleted_at": new_date,
                },
            ]
            trash_path.write_text(
                json.dumps(trash_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            
            # Mock the path functions to use our temp directories
            with patch.object(compact_nav_tree, 'load_navigation_data', return_value=nav_data):
                with patch.object(compact_nav_tree, 'load_trash', return_value=trash_data.copy()):
                    # Mock save_trash to capture what was saved
                    saved_trash = []
                    def mock_save_trash(entries):
                        saved_trash.clear()
                        saved_trash.extend(entries)
                    
                    with patch.object(compact_nav_tree, 'save_trash', side_effect=mock_save_trash):
                        widget = compact_nav_tree.CompactNavTree()
                        
                        # The widget purges on init
                        # After purge, only the new entry should remain
                        self.assertEqual(len(widget._trash), 1)
                        self.assertEqual(widget._trash[0]["name"], "New World")
                        widget.close()

    def test_remove_and_revive_world(self) -> None:
        """Test that worlds can be removed to trash and revived."""
        nav_data = [{"name": "World A", "campaigns": []}]
        
        # Mock the module-level functions
        with patch.object(compact_nav_tree, 'load_navigation_data', return_value=nav_data.copy()):
            with patch.object(compact_nav_tree, 'load_trash', return_value=[]):
                saved_data = []
                saved_trash = []
                
                def mock_save_data(data):
                    saved_data.clear()
                    saved_data.extend(data)
                
                def mock_save_trash(entries):
                    saved_trash.clear()
                    saved_trash.extend(entries)
                
                with patch.object(compact_nav_tree, 'save_navigation_data', side_effect=mock_save_data):
                    with patch.object(compact_nav_tree, 'save_trash', side_effect=mock_save_trash):
                        widget = compact_nav_tree.CompactNavTree()
                        
                        # Verify initial data
                        self.assertEqual(len(widget._data), 1)
                        self.assertEqual(widget._data[0]["name"], "World A")
                        
                        # Remove world via the internal method
                        widget._remove_world("World A")
                        
                        self.assertEqual(len(widget._data), 0)
                        self.assertEqual(len(widget._trash), 1)
                        self.assertEqual(widget._trash[0]["name"], "World A")
                        
                        # Simulate revive by restoring the payload
                        trash_entry = widget._trash[0]
                        payload = trash_entry.get("payload", {})
                        widget._data.append(widget._normalize_world(payload))
                        widget._trash.remove(trash_entry)
                        widget._save_data()
                        widget._save_trash()
                        widget._rebuild_tree()
                        
                        self.assertEqual(len(widget._data), 1)
                        self.assertEqual(len(widget._trash), 0)
                        self.assertEqual(widget._data[0]["name"], "World A")
                        widget.close()

    def test_empty_tree_click_clears_selection(self) -> None:
        nav_data = [{"name": "World A", "campaigns": []}]

        with patch.object(compact_nav_tree, "load_navigation_data", return_value=nav_data.copy()):
            with patch.object(compact_nav_tree, "load_trash", return_value=[]):
                widget = compact_nav_tree.CompactNavTree()
                widget.resize(320, 420)
                widget.show()
                self._app.processEvents()

                first = widget._tree.topLevelItem(0)
                self.assertIsNotNone(first)
                self.assertEqual(
                    widget._tree.selectionMode(),
                    QAbstractItemView.SelectionMode.NoSelection,
                )
                widget._tree.setCurrentItem(first)
                first.setSelected(True)
                self.assertEqual(len(widget._tree.selectedItems()), 1)

                viewport = widget._tree.viewport()
                empty_pos = None
                for y in range(viewport.height() - 2, -1, -1):
                    point = QPoint(8, y)
                    if widget._tree.itemAt(point) is None:
                        empty_pos = point
                        break

                self.assertIsNotNone(empty_pos)
                changed = widget._clear_selection_if_empty_click(empty_pos)
                self.assertTrue(changed)
                self.assertEqual(len(widget._tree.selectedItems()), 0)
                self.assertIsNone(widget._tree.currentItem())
                widget.close()

    def test_left_click_toggle_does_not_select_item(self) -> None:
        nav_data = [{"name": "World A", "campaigns": []}]

        with patch.object(compact_nav_tree, "load_navigation_data", return_value=nav_data.copy()):
            with patch.object(compact_nav_tree, "load_trash", return_value=[]):
                widget = compact_nav_tree.CompactNavTree()
                world_item = widget._tree.topLevelItem(0)
                self.assertIsNotNone(world_item)
                self.assertFalse(world_item.isExpanded())

                widget._on_item_clicked(world_item, 0)

                self.assertTrue(world_item.isExpanded())
                self.assertEqual(len(widget._tree.selectedItems()), 0)
                widget.close()

    def test_add_campaign_expands_world_so_new_item_is_visible(self) -> None:
        nav_data = [{"name": "World A", "campaigns": []}]

        with patch.object(compact_nav_tree, "load_navigation_data", return_value=nav_data.copy()):
            with patch.object(compact_nav_tree, "load_trash", return_value=[]):
                widget = compact_nav_tree.CompactNavTree()
                world_item = widget._tree.topLevelItem(0)
                self.assertIsNotNone(world_item)
                self.assertFalse(world_item.isExpanded())
                with patch.object(
                    widget,
                    "_prompt_name_icon",
                    return_value=("Campaign A", widget._default_campaign_icon),
                ):
                    widget._add_campaign(0)

                world_item = widget._tree.topLevelItem(0)
                self.assertIsNotNone(world_item)
                self.assertTrue(world_item.isExpanded())
                self.assertEqual(world_item.childCount(), 1)
                self.assertEqual(world_item.child(0).text(0), "Campaign A")
                widget.close()

    def test_name_dialog_requires_name_with_inline_warning(self) -> None:
        dialog = compact_nav_tree.NameIconDialog(
            "New World",
            "World name:",
            [],
            default_name="",
        )
        dialog.show()
        self._app.processEvents()

        buttons = dialog.findChild(QDialogButtonBox)
        self.assertIsNotNone(buttons)
        assert buttons is not None
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertIsNotNone(ok_button)
        assert ok_button is not None
        ok_button.click()
        self._app.processEvents()

        self.assertTrue(dialog.isVisible())
        warning = dialog.findChild(QLabel, "NameValidationError")
        self.assertIsNotNone(warning)

        name_field = dialog.findChild(QLineEdit, "NameInputField")
        self.assertIsNotNone(name_field)
        assert name_field is not None
        name_field.setText("Valid Name")
        self._app.processEvents()
        ok_button.click()
        self._app.processEvents()
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.result(), int(dialog.DialogCode.Accepted))
        dialog.close()


if __name__ == "__main__":
    unittest.main()
