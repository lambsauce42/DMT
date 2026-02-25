import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt6.QtWidgets import QApplication

from maps_applet import MapDialog
from npc_database import NPCDialog


WORLD_DATA_WITH_OBJECT_GROUPS = [
    {
        "name": "Eldervale",
        "campaigns": [
            {
                "name": "Ashen Crown",
                "groups": [{"name": "Silver Lances", "icon": "group.png"}],
            }
        ],
    }
]


class NavigationGroupShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_map_dialog_accepts_object_group_shape(self) -> None:
        dialog = MapDialog(world_data=WORLD_DATA_WITH_OBJECT_GROUPS)
        self.addCleanup(dialog.close)

        world_index = dialog._world_combo.findText("Eldervale")
        self.assertNotEqual(world_index, -1)
        dialog._world_combo.setCurrentIndex(world_index)
        dialog._on_world_changed()

        campaign_index = dialog._campaign_combo.findText("Ashen Crown")
        self.assertNotEqual(campaign_index, -1)
        dialog._campaign_combo.setCurrentIndex(campaign_index)
        dialog._on_campaign_changed()

        self.assertNotEqual(dialog._group_combo.findText("Silver Lances"), -1)

    def test_npc_dialog_accepts_object_group_shape(self) -> None:
        dialog = NPCDialog(world_data=WORLD_DATA_WITH_OBJECT_GROUPS)
        self.addCleanup(dialog.close)

        world_index = dialog._world_combo.findText("Eldervale")
        self.assertNotEqual(world_index, -1)
        dialog._world_combo.setCurrentIndex(world_index)
        dialog._on_world_changed()

        campaign_index = dialog._campaign_combo.findText("Ashen Crown")
        self.assertNotEqual(campaign_index, -1)
        dialog._campaign_combo.setCurrentIndex(campaign_index)
        dialog._on_campaign_changed()

        self.assertNotEqual(dialog._group_combo.findText("Silver Lances"), -1)

