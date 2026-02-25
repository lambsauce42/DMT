import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QLineEdit

import navigate_widget
from navigate_widget import NavigateContentWidget, NavigateWidget


class NavigateWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.original_path = navigate_widget.NAVIGATION_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        navigate_widget.NAVIGATION_PATH = os.path.join(self.temp_dir.name, "nav.json")
        navigate_widget.save_navigation_data(
            [
                {
                    "name": "World A",
                    "icon": "",
                    "campaigns": [
                        {
                            "name": "Campaign A",
                            "icon": "",
                            "groups": [{"name": "Group A", "icon": ""}],
                        }
                    ],
                }
            ]
        )

    def tearDown(self) -> None:
        navigate_widget.NAVIGATION_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_worlds_section_expands(self) -> None:
        widget = NavigateWidget()
        section = widget._worlds_section
        section.set_expanded(True, animate=False)
        self.assertTrue(section.expanded)
        self.assertGreater(section.content_widget.maximumHeight(), 0)
        widget.close()

    def test_world_section_expands_campaigns(self) -> None:
        widget = NavigateWidget()
        world_section = widget._world_sections[0]
        world_section.set_expanded(True, animate=False)
        self.assertTrue(world_section.expanded)
        self.assertGreater(world_section.content_widget.maximumHeight(), 0)
        widget.close()

    def test_add_and_remove_world(self) -> None:
        widget = NavigateContentWidget(show_worlds_header=False)
        initial_count = len(widget._data)
        widget.add_world(name="Test World")
        self.assertEqual(len(widget._data), initial_count + 1)
        widget.remove_world(name="Test World")
        self.assertEqual(len(widget._data), initial_count)
        widget.close()

    def test_add_campaign_and_group(self) -> None:
        widget = NavigateContentWidget(show_worlds_header=False)
        widget._add_campaign(0, name="Test Campaign")
        campaigns = widget._data[0]["campaigns"]
        self.assertTrue(any(c["name"] == "Test Campaign" for c in campaigns))
        campaign_index = next(
            idx for idx, camp in enumerate(campaigns) if camp["name"] == "Test Campaign"
        )
        widget._add_group(0, campaign_index, name="Test Group")
        groups = campaigns[campaign_index]["groups"]
        self.assertTrue(any(group["name"] == "Test Group" for group in groups))
        widget.close()

    def test_add_campaign_and_group_persist_after_reload(self) -> None:
        widget = NavigateContentWidget(show_worlds_header=False)
        widget._add_campaign(0, name="Persistent Campaign")
        campaigns = widget._data[0]["campaigns"]
        campaign_index = next(
            idx for idx, camp in enumerate(campaigns) if camp["name"] == "Persistent Campaign"
        )
        widget._add_group(0, campaign_index, name="Persistent Group")
        widget.close()

        reloaded = NavigateContentWidget(show_worlds_header=False)
        reloaded_campaigns = reloaded._data[0]["campaigns"]
        self.assertTrue(any(c["name"] == "Persistent Campaign" for c in reloaded_campaigns))
        reloaded_campaign_index = next(
            idx for idx, camp in enumerate(reloaded_campaigns) if camp["name"] == "Persistent Campaign"
        )
        reloaded_groups = reloaded_campaigns[reloaded_campaign_index]["groups"]
        self.assertTrue(any(group["name"] == "Persistent Group" for group in reloaded_groups))
        reloaded.close()

    def test_edit_world_campaign_group(self) -> None:
        widget = NavigateContentWidget(show_worlds_header=False)
        original_world = widget._data[0]["name"]
        widget.edit_world(old_name=original_world, new_name="Renamed World")
        self.assertEqual(widget._data[0]["name"], "Renamed World")

        campaigns = widget._data[0]["campaigns"]
        original_campaign = campaigns[0]["name"]
        widget._edit_campaign(0, old_name=original_campaign, new_name="Renamed Campaign")
        self.assertEqual(campaigns[0]["name"], "Renamed Campaign")

        groups = campaigns[0]["groups"]
        original_group = groups[0]["name"]
        widget._edit_group(0, 0, old_name=original_group, new_name="Renamed Group")
        self.assertEqual(groups[0]["name"], "Renamed Group")
        widget.close()

    def test_trash_purges_expired_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trash_path = os.path.join(temp_dir, "trash.json")
            original_path = navigate_widget.TRASH_PATH
            try:
                navigate_widget.TRASH_PATH = trash_path
                expired_date = (datetime.now() - timedelta(days=31)).isoformat()
                with open(trash_path, "w", encoding="utf-8") as handle:
                    json.dump([{"deleted_at": expired_date}], handle)
                widget = NavigateContentWidget(show_worlds_header=False)
                self.assertEqual(widget._trash, [])
                widget.close()
            finally:
                navigate_widget.TRASH_PATH = original_path

    def test_disintegrate_world_removes_entry(self) -> None:
        widget = NavigateContentWidget(show_worlds_header=False)
        widget._confirm_disintegrate = lambda title, message: True
        target_name = widget._data[0]["name"]
        widget.disintegrate_world(name=target_name)
        self.assertTrue(all(world["name"] != target_name for world in widget._data))
        widget.close()

    def test_revive_world_from_trash(self) -> None:
        widget = NavigateContentWidget(show_worlds_header=False)
        target_name = widget._data[0]["name"]
        world_payload = widget._data[0]
        widget._trash = [
            {
                "type": "world",
                "name": target_name,
                "icon": world_payload.get("icon"),
                "payload": world_payload,
                "parent": {},
                "deleted_at": datetime.now().isoformat(),
            }
        ]
        widget._data = [world for world in widget._data if world["name"] != target_name]
        widget._save_trash = lambda: None
        widget.revive_world(name=target_name)
        self.assertTrue(any(world["name"] == target_name for world in widget._data))
        widget.close()

    def test_name_dialog_requires_name_with_inline_warning(self) -> None:
        dialog = navigate_widget.NameIconDialog(
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
