import sys
import os
import unittest
import importlib
import tempfile
from pathlib import Path
from unittest.mock import patch

# Ensure src is in path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

class AppletInitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create QApplication once
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Mock potentially file-system/noisy operations
        self.save_patcher = patch("navigate_widget.save_navigation_data")
        self.save_patcher.start()
        
        self.load_patcher = patch("navigate_widget.load_navigation_data", return_value=[])
        self.load_patcher.start()
        
        # Mock dnd_saves_dir to avoid touching real files
        self.path_patcher = patch("save_paths.dnd_saves_dir")
        self.mock_dir = self.path_patcher.start()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mock_dir.return_value = Path(self.temp_dir.name)


    def tearDown(self):
        self.save_patcher.stop()
        self.load_patcher.stop()
        self.path_patcher.stop()
        self.temp_dir.cleanup()

    def _load_class(self, module_name: str, class_name: str):
        module = importlib.import_module(module_name)
        return getattr(module, class_name)

    def _assert_widget_init(self, factory, label: str) -> None:
        widget = None
        try:
            widget = factory()
            self.assertIsNotNone(widget)
        except Exception as e:
            self.fail(f"{label} init failed: {e}")
        finally:
            if widget is not None:
                # Some widgets (notably DungeonAppletWidget) install a global app event
                # filter. Remove it explicitly before teardown to avoid cross-test stalls.
                remove_filter = getattr(widget, "_remove_app_event_filter", None)
                if callable(remove_filter):
                    remove_filter()
                widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
                widget.close()
                widget.deleteLater()
                QApplication.processEvents()

    def test_home_widget_init(self):
        """Test HomeWidget initialization"""
        HomeWidget = self._load_class("app", "HomeWidget")
        self._assert_widget_init(
            lambda: HomeWidget(
                applets=[],
                on_open=lambda x, y: None,
                world_data=[],
            ),
            "HomeWidget",
        )

    def test_encounter_panel_init(self):
        """Test EncounterPanel initialization"""
        EncounterPanel = self._load_class("ui.encounter_panel", "EncounterPanel")
        self._assert_widget_init(lambda: EncounterPanel(), "EncounterPanel")

    def test_npc_database_init(self):
        """Test NPCDatabaseWidget initialization"""
        NPCDatabaseWidget = self._load_class("npc_database", "NPCDatabaseWidget")
        self._assert_widget_init(lambda: NPCDatabaseWidget(), "NPCDatabaseWidget")

    def test_dungeon_applet_init(self):
        """Test DungeonAppletWidget initialization"""
        DungeonAppletWidget = self._load_class("dungeon_applet", "DungeonAppletWidget")
        self._assert_widget_init(lambda: DungeonAppletWidget(), "DungeonAppletWidget")

    def test_loot_applet_init(self):
        """Test LootAppletWidget initialization"""
        LootAppletWidget = self._load_class("loot_applet", "LootAppletWidget")
        self._assert_widget_init(lambda: LootAppletWidget(), "LootAppletWidget")

    def test_maps_widget_init(self):
        """Test MapsWidget initialization"""
        MapsWidget = self._load_class("maps_applet", "MapsWidget")
        self._assert_widget_init(lambda: MapsWidget(), "MapsWidget")

    def test_player_sheets_init(self):
        """Test PlayerSheetsWidget import availability (full init covered elsewhere)."""
        PlayerSheetsWidget = self._load_class("player_sheets", "PlayerSheetsWidget")
        self.assertTrue(callable(PlayerSheetsWidget))

    def test_session_creator_init(self):
        """Test SessionCreatorWidget initialization"""
        SessionCreatorWidget = self._load_class("session_creator", "SessionCreatorWidget")
        self._assert_widget_init(lambda: SessionCreatorWidget(), "SessionCreatorWidget")

if __name__ == "__main__":
    unittest.main()
