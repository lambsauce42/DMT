import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PySide6.QtWidgets import QApplication

import compact_nav_tree


class CompactNavDuplicateDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _build_widget(self, data: list[dict]) -> compact_nav_tree.CompactNavTree:
        with patch.object(compact_nav_tree, "load_navigation_data", return_value=data):
            with patch.object(compact_nav_tree, "load_trash", return_value=[]):
                with patch.object(compact_nav_tree, "save_navigation_data", lambda _: None):
                    with patch.object(compact_nav_tree, "save_trash", lambda _: None):
                        return compact_nav_tree.CompactNavTree()

    def test_remove_world_with_duplicate_name_removes_only_target(self) -> None:
        widget = self._build_widget(
            [
                {"name": "Dup", "campaigns": []},
                {"name": "Dup", "campaigns": []},
            ]
        )
        self.addCleanup(widget.close)

        widget._remove_world("Dup")
        self.assertEqual(len(widget._data), 1)
        self.assertEqual(len(widget._trash), 1)

    def test_remove_campaign_with_duplicate_name_removes_only_target(self) -> None:
        widget = self._build_widget(
            [
                {
                    "name": "World",
                    "campaigns": [
                        {"name": "Dup", "groups": []},
                        {"name": "Dup", "groups": []},
                    ],
                }
            ]
        )
        self.addCleanup(widget.close)

        widget._remove_campaign(0, "Dup")
        self.assertEqual(len(widget._data[0]["campaigns"]), 1)
        self.assertEqual(len(widget._trash), 1)

    def test_remove_group_with_duplicate_name_removes_only_target(self) -> None:
        widget = self._build_widget(
            [
                {
                    "name": "World",
                    "campaigns": [
                        {
                            "name": "Campaign",
                            "groups": [{"name": "Dup"}, {"name": "Dup"}],
                        }
                    ],
                }
            ]
        )
        self.addCleanup(widget.close)

        widget._remove_group(0, 0, "Dup")
        self.assertEqual(len(widget._data[0]["campaigns"][0]["groups"]), 1)
        self.assertEqual(len(widget._trash), 1)

