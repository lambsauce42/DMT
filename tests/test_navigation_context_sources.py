import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PySide6.QtWidgets import QApplication

from maps_applet import MapsWidget
import navigation_repository
from navigation_storage import save_navigation_world_data
from npc_database import NPCDatabaseWidget
from session_creator import SessionCreatorWidget


def _seed_navigation(base_dir: Path) -> str:
    save_navigation_world_data(
        [
            {
                "name": "Eldervale",
                "campaigns": [
                    {
                        "name": "Ashen Crown",
                        "groups": [{"name": "Silver Lances", "icon": "icon.png"}],
                    }
                ],
            }
        ],
        base_dir=base_dir,
    )
    return str(base_dir / "navigation.json")


class NavigationContextSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_session_creator_uses_navigation_storage_for_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            nav_path = _seed_navigation(Path(tmpdir))
            with patch.object(navigation_repository, "NAVIGATION_PATH", nav_path):
                widget = SessionCreatorWidget()
                self.addCleanup(widget.close)

                world_index = widget.world_combo.findText("Eldervale")
                self.assertNotEqual(world_index, -1)

                widget.world_combo.setCurrentIndex(world_index)
                widget._on_world_changed()
                campaign_index = widget.campaign_combo.findText("Ashen Crown")
                self.assertNotEqual(campaign_index, -1)

                widget.campaign_combo.setCurrentIndex(campaign_index)
                widget._on_campaign_changed()
                self.assertNotEqual(widget.group_combo.findText("Silver Lances"), -1)

    def test_session_creator_refreshes_navigation_context_after_tab_return(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            nav_path = _seed_navigation(base_dir)
            with patch.object(navigation_repository, "NAVIGATION_PATH", nav_path):
                widget = SessionCreatorWidget()
                self.addCleanup(widget.close)
                widget.show()
                self._app.processEvents()
                self.assertEqual(widget.world_combo.findText("Moonfall"), -1)

                save_navigation_world_data(
                    [
                        {
                            "name": "Moonfall",
                            "campaigns": [{"name": "Night Tide", "groups": []}],
                        }
                    ],
                    base_dir=base_dir,
                )

                widget.hide()
                self._app.processEvents()
                widget.show()
                self._app.processEvents()

                self.assertNotEqual(widget.world_combo.findText("Moonfall"), -1)

    def test_maps_widget_uses_navigation_storage_for_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            nav_path = _seed_navigation(Path(tmpdir))
            with patch.object(navigation_repository, "NAVIGATION_PATH", nav_path):
                widget = MapsWidget()
                self.addCleanup(widget.close)
                self.assertNotEqual(widget._world_combo.findText("Eldervale"), -1)

    def test_npc_widget_uses_navigation_storage_for_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            nav_path = _seed_navigation(Path(tmpdir))
            with patch.object(navigation_repository, "NAVIGATION_PATH", nav_path):
                widget = NPCDatabaseWidget()
                self.addCleanup(widget.close)
                self.assertNotEqual(widget._world_combo.findText("Eldervale"), -1)
