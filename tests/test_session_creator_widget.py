import os
import sys
import tempfile
import unittest
import copy
import json
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextListFormat
from PySide6.QtWidgets import QApplication

from dmt_package import read_dmt_package_info, write_dmt_package
import session_creator
from session_creator import SessionCreatorWidget


TEST_WORLD_DATA = [
    {
        "id": "world_eldervale",
        "name": "Eldervale",
        "campaigns": [
            {
                "id": "campaign_ashen_crown",
                "name": "Ashen Crown",
                "groups": [
                    {"id": "group_silver_lances", "name": "Silver Lances"},
                    {"id": "group_gilded_tide", "name": "The Gilded Tide"},
                ],
            },
            {
                "id": "campaign_hollow_pact",
                "name": "Hollow Pact",
                "groups": [
                    {"id": "group_night_cartel", "name": "Night Cartel"},
                    {"id": "group_dawn_wardens", "name": "Dawn Wardens"},
                ],
            },
        ],
    },
    {
        "id": "world_stormreach",
        "name": "Stormreach",
        "campaigns": [
            {
                "id": "campaign_iron_meridian",
                "name": "Iron Meridian",
                "groups": [
                    {"id": "group_cinderwatch", "name": "Cinderwatch"},
                    {"id": "group_glass_harbor", "name": "Glass Harbor"},
                ],
            },
            {
                "id": "campaign_verdant_rift",
                "name": "Verdant Rift",
                "groups": [
                    {"id": "group_stone_hounds", "name": "Stone Hounds"},
                    {"id": "group_riftwalkers", "name": "Riftwalkers"},
                ],
            },
        ],
    },
]


class SessionCreatorWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._original_world_data = session_creator.WORLD_DATA
        session_creator.WORLD_DATA = copy.deepcopy(TEST_WORLD_DATA)

    def tearDown(self) -> None:
        session_creator.WORLD_DATA = self._original_world_data

    @staticmethod
    def _context_token(world_id: str = "", campaign_id: str = "", group_id: str = "") -> str:
        payload = {}
        if world_id:
            payload["world_id"] = world_id
        if campaign_id:
            payload["campaign_id"] = campaign_id
        if group_id:
            payload["group_id"] = group_id
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _saved_sessions_in_dir(storage_root: Path) -> list[dict]:
        sessions: list[dict] = []
        for path in sorted(storage_root.glob("*.dmtsession")):
            info = read_dmt_package_info(path)
            if not isinstance(info, dict):
                continue
            payload = info.get("payload")
            if not isinstance(payload, dict):
                continue
            normalized = dict(payload)
            normalized["attachments"] = list(info.get("attachments") or [])
            sessions.append(normalized)
        return sessions

    @staticmethod
    def _write_sessions_to_dir(storage_root: Path, sessions: list[dict]) -> None:
        storage_root.mkdir(parents=True, exist_ok=True)
        for session_payload in sessions:
            normalized = dict(session_payload)
            session_id = str(normalized.get("id") or "session")
            attachments = list(normalized.pop("attachments", []))
            path = storage_root / f"{session_id}.dmtsession"
            write_dmt_package(
                path,
                info={
                    "format": session_creator.SESSION_FILE_FORMAT,
                    "object_type": "session",
                    "object_id": session_id,
                    "updated_at": "2026-01-01T00:00:00",
                    "payload": normalized,
                    "attachments": attachments,
                },
                assets={},
            )

    def test_new_session_inline_name_edit(self) -> None:
        widget = SessionCreatorWidget()
        self.addCleanup(widget.close)

        initial_count = widget.session_list.count()
        widget._create_session()

        self.assertEqual(widget.session_list.count(), initial_count + 1)
        item = widget.session_list.currentItem()
        self.assertIsNotNone(item)
        self.assertTrue(bool(item.flags() & Qt.ItemFlag.ItemIsEditable))

        item.setText("Renamed Session")
        self.assertEqual(widget._current_session.name, "Renamed Session")
        self.assertIn("Renamed Session", widget.session_title_label.text())

    def test_plan_tab_text_import_and_save(self) -> None:
        widget = SessionCreatorWidget()
        self.addCleanup(widget.close)

        tab_names = [widget.ref_tabs.tabText(i) for i in range(widget.ref_tabs.count())]
        self.assertEqual(tab_names, ["Plan", "Files", "Transcript", "Recap"])
        self.assertNotIn("Maps", tab_names)
        self.assertFalse(widget.load_plan_btn.icon().isNull())
        self.assertEqual(
            widget.plan_editor.placeholderText(),
            "Load a text file to import a session plan or start typing...",
        )
        self.assertEqual(widget.load_plan_btn.width(), widget.load_plan_btn.height())
        self.assertEqual(widget.load_plan_btn.height(), widget.plan_bold_btn.height())

        widget._create_session()
        with tempfile.TemporaryDirectory() as tmp_dir:
            md_path = Path(tmp_dir) / "plan.md"
            md_path.write_text("# Session Plan", encoding="utf-8")

            widget._current_session.document_path = str(md_path)
            widget._load_plan_text_file(str(md_path))
            self.assertIn("Session Plan", widget.plan_editor.toPlainText())

            widget.plan_editor.setPlainText("Updated Plan\n- test")
            self.assertIn("*", widget.session_title_label.text())

            widget._save_current_session()
            self.assertNotIn("*", widget.session_title_label.text())
            self.assertIn("Updated Plan", md_path.read_text(encoding="utf-8"))

    def test_plan_text_persists_without_imported_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "sessions.dmtindex"
            original_path_func = session_creator.session_storage_path
            session_creator.session_storage_path = lambda: storage_path
            try:
                widget = SessionCreatorWidget()
                self.addCleanup(widget.close)
                widget._create_session()
                self.assertIsNotNone(widget._current_session)
                session_id = widget._current_session.id
                self.assertFalse(widget._current_session.document_path)

                widget.plan_editor.setPlainText("Inline-only plan text")
                widget._save_now()

                payload = self._saved_sessions_in_dir(Path(tmp_dir))
                stored = next(entry for entry in payload if entry["id"] == session_id)
                self.assertEqual(stored.get("plan_text"), "Inline-only plan text")
                self.assertFalse(stored.get("document_path"))

                reopened = SessionCreatorWidget()
                self.addCleanup(reopened.close)
                match_row = None
                for row in range(reopened.session_list.count()):
                    item = reopened.session_list.item(row)
                    if item.data(Qt.ItemDataRole.UserRole) == session_id:
                        match_row = row
                        break
                self.assertIsNotNone(match_row)

                reopened.session_list.setCurrentRow(match_row)
                reopened._load_selected_session()
                self.assertEqual(reopened.plan_editor.toPlainText(), "Inline-only plan text")
                self.assertEqual(reopened.plan_path_label.text(), "No text file loaded")
            finally:
                session_creator.session_storage_path = original_path_func

    def test_renaming_session_persists_pending_scratchpad_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "sessions.dmtindex"
            original_path_func = session_creator.session_storage_path
            session_creator.session_storage_path = lambda: storage_path
            try:
                widget = SessionCreatorWidget()
                self.addCleanup(widget.close)
                widget._create_session()
                self.assertIsNotNone(widget._current_session)
                session_id = widget._current_session.id

                widget.scratchpad.setPlainText("Scratchpad text should survive rename")
                self.assertIn("*", widget.session_title_label.text())

                item = widget.session_list.currentItem()
                self.assertIsNotNone(item)
                item.setText("Renamed Session")

                payload = self._saved_sessions_in_dir(Path(tmp_dir))
                stored = next(entry for entry in payload if entry["id"] == session_id)
                self.assertEqual(stored.get("name"), "Renamed Session")
                self.assertIn(
                    "Scratchpad text should survive rename",
                    str(stored.get("notes") or ""),
                )
            finally:
                session_creator.session_storage_path = original_path_func

    def test_plan_toolbar_formatting_actions(self) -> None:
        widget = SessionCreatorWidget()
        self.addCleanup(widget.close)

        widget._create_session()
        widget.plan_editor.setPlainText("Line item")

        # Bold toggle
        widget._toggle_plan_bold()
        self.assertEqual(widget.plan_editor.textCursor().charFormat().fontWeight(), QFont.Weight.Bold)

        # Underline toggle
        widget._toggle_plan_underline()
        self.assertTrue(widget.plan_editor.textCursor().charFormat().fontUnderline())

        # Bullet list toggle
        widget._toggle_plan_bullet_list()
        current_list = widget.plan_editor.textCursor().currentList()
        self.assertIsNotNone(current_list)
        self.assertEqual(current_list.format().style(), QTextListFormat.Style.ListDisc)

        # Indent / outdent in list
        widget._indent_plan_text()
        current_list = widget.plan_editor.textCursor().currentList()
        self.assertIsNotNone(current_list)
        self.assertGreaterEqual(current_list.format().indent(), 2)

        widget._outdent_plan_text()
        current_list = widget.plan_editor.textCursor().currentList()
        self.assertIsNotNone(current_list)
        self.assertEqual(current_list.format().indent(), 1)

        # Font size control
        widget._set_plan_font_size(18)
        self.assertEqual(int(widget.plan_editor.textCursor().charFormat().fontPointSize()), 18)

        # Undo/Redo controls were intentionally removed from the plan toolbar.
        self.assertFalse(hasattr(widget, "plan_undo_btn"))
        self.assertFalse(hasattr(widget, "plan_redo_btn"))
        self.assertIsNotNone(widget.plan_font_spin)
        self.assertIsNotNone(widget.plan_font_up_btn)
        self.assertIsNotNone(widget.plan_font_down_btn)

    def test_ctrl_s_saves_current_session(self) -> None:
        widget = SessionCreatorWidget()
        self.addCleanup(widget.close)

        widget._create_session()
        with tempfile.TemporaryDirectory() as tmp_dir:
            md_path = Path(tmp_dir) / "plan.txt"
            widget._current_session.document_path = str(md_path)
            widget._load_plan_text_file(str(md_path))

            widget.plan_editor.setPlainText("# CtrlS Save")
            self.assertIn("*", widget.session_title_label.text())

            widget.save_shortcut.activated.emit()

            self.assertTrue(md_path.exists())
            self.assertIn("CtrlS Save", md_path.read_text(encoding="utf-8"))
            self.assertNotIn("*", widget.session_title_label.text())

    def test_context_combo_fields_have_uniform_height(self) -> None:
        widget = SessionCreatorWidget()
        self.addCleanup(widget.close)

        self.assertEqual(widget.world_combo.height(), 32)
        self.assertEqual(widget.campaign_combo.height(), 32)
        self.assertEqual(widget.group_combo.height(), 32)
        self.assertEqual(len(widget._context_reset_buttons), 3)
        for btn in widget._context_reset_buttons:
            self.assertEqual(btn.width(), 32)
            self.assertEqual(btn.height(), 32)

    def test_auto_selects_most_recent_session_on_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "sessions.dmtindex"
            self._write_sessions_to_dir(
                Path(tmp_dir),
                [
                    {
                        "id": "old_session",
                        "name": "Old Session",
                        "session_date": "2026-01-01",
                    },
                    {
                        "id": "new_session",
                        "name": "New Session",
                        "session_date": "2026-02-01",
                    },
                ],
            )

            original_path_func = session_creator.session_storage_path
            session_creator.session_storage_path = lambda: storage_path
            try:
                widget = SessionCreatorWidget()
                self.addCleanup(widget.close)

                current_item = widget.session_list.currentItem()
                self.assertIsNotNone(current_item)
                self.assertEqual(
                    current_item.data(Qt.ItemDataRole.UserRole),
                    "new_session",
                )
                self.assertIsNotNone(widget._current_session)
                self.assertEqual(widget._current_session.id, "new_session")
            finally:
                session_creator.session_storage_path = original_path_func

    def test_linked_context_filters_sessions_by_restrictions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "sessions.dmtindex"
            self._write_sessions_to_dir(
                Path(tmp_dir),
                [
                    {
                        "id": "session_eld",
                        "name": "Eldervale Session",
                        "session_date": "2026-02-05",
                        "group_ids": [self._context_token("world_eldervale", "campaign_ashen_crown", "group_silver_lances")],
                    },
                    {
                        "id": "session_storm",
                        "name": "Stormreach Session",
                        "session_date": "2026-02-04",
                        "group_ids": [self._context_token("world_stormreach", "campaign_iron_meridian", "group_cinderwatch")],
                    },
                ],
            )

            original_path_func = session_creator.session_storage_path
            session_creator.session_storage_path = lambda: storage_path
            try:
                widget = SessionCreatorWidget()
                self.addCleanup(widget.close)

                widget.world_combo.setCurrentIndex(0)
                self.assertEqual(widget.session_list.count(), 2)

                eld_index = widget.world_combo.findText("Eldervale")
                self.assertGreaterEqual(eld_index, 0)
                widget.world_combo.setCurrentIndex(eld_index)

                self.assertEqual(widget.session_list.count(), 1)
                current_item = widget.session_list.currentItem()
                self.assertIsNotNone(current_item)
                self.assertEqual(current_item.data(Qt.ItemDataRole.UserRole), "session_eld")

                widget.world_combo.setCurrentIndex(0)
                self.assertEqual(widget.session_list.count(), 2)
            finally:
                session_creator.session_storage_path = original_path_func

    def test_context_filtering_does_not_overwrite_session_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "sessions.dmtindex"
            self._write_sessions_to_dir(
                Path(tmp_dir),
                [
                    {
                        "id": "session_eld",
                        "name": "Eldervale Session",
                        "session_date": "2026-02-05",
                        "group_ids": [self._context_token("world_eldervale", "campaign_ashen_crown", "group_silver_lances")],
                    },
                    {
                        "id": "session_storm",
                        "name": "Stormreach Session",
                        "session_date": "2026-02-06",
                        "group_ids": [self._context_token("world_stormreach", "campaign_iron_meridian", "group_cinderwatch")],
                    },
                ],
            )

            original_path_func = session_creator.session_storage_path
            session_creator.session_storage_path = lambda: storage_path
            try:
                widget = SessionCreatorWidget()
                self.addCleanup(widget.close)

                self.assertIsNotNone(widget._current_session)
                self.assertEqual(widget._current_session.id, "session_storm")

                eld_index = widget.world_combo.findText("Eldervale")
                self.assertGreaterEqual(eld_index, 0)
                widget.world_combo.setCurrentIndex(eld_index)
                self.assertEqual(widget.session_list.count(), 1)

                payload = self._saved_sessions_in_dir(Path(tmp_dir))
                storm_entry = next(entry for entry in payload if entry["id"] == "session_storm")
                self.assertEqual(
                    storm_entry.get("group_ids"),
                    [self._context_token("world_stormreach", "campaign_iron_meridian", "group_cinderwatch")],
                )
            finally:
                session_creator.session_storage_path = original_path_func

    def test_save_and_load_session_preserves_linked_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "sessions.dmtindex"
            self._write_sessions_to_dir(
                Path(tmp_dir),
                [
                    {
                        "id": "seed_session",
                        "name": "Seed Session",
                        "session_date": "2026-01-01",
                        "group_ids": [self._context_token("world_eldervale", "campaign_ashen_crown", "group_silver_lances")],
                    }
                ],
            )
            original_path_func = session_creator.session_storage_path
            session_creator.session_storage_path = lambda: storage_path
            try:
                widget = SessionCreatorWidget()
                self.addCleanup(widget.close)

                widget._create_session()
                self.assertIsNotNone(widget._current_session)
                session_id = widget._current_session.id

                world_index = widget.world_combo.findText("Eldervale")
                self.assertGreaterEqual(world_index, 0)
                widget.world_combo.setCurrentIndex(world_index)

                campaign_index = widget.campaign_combo.findText("Ashen Crown")
                self.assertGreaterEqual(campaign_index, 0)
                widget.campaign_combo.setCurrentIndex(campaign_index)

                group_index = widget.group_combo.findText("Silver Lances")
                self.assertGreaterEqual(group_index, 0)
                widget.group_combo.setCurrentIndex(group_index)

                widget._save_now()

                payload = self._saved_sessions_in_dir(Path(tmp_dir))
                stored = next(entry for entry in payload if entry["id"] == session_id)
                self.assertEqual(
                    stored.get("group_ids"),
                    [self._context_token("world_eldervale", "campaign_ashen_crown", "group_silver_lances")],
                )

                reopened = SessionCreatorWidget()
                self.addCleanup(reopened.close)
                match_row = None
                for row in range(reopened.session_list.count()):
                    item = reopened.session_list.item(row)
                    if item.data(Qt.ItemDataRole.UserRole) == session_id:
                        match_row = row
                        break
                self.assertIsNotNone(match_row)
                reopened.session_list.setCurrentRow(match_row)
                reopened._load_selected_session()

                self.assertEqual(reopened.world_combo.currentText(), "Eldervale")
                self.assertEqual(reopened.campaign_combo.currentText(), "Ashen Crown")
                self.assertEqual(reopened.group_combo.currentText(), "Silver Lances")
            finally:
                session_creator.session_storage_path = original_path_func

    def test_loading_session_uses_stable_context_ids_after_navigation_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "sessions.dmtindex"
            self._write_sessions_to_dir(
                Path(tmp_dir),
                [
                    {
                        "id": "renamed_context_session",
                        "name": "Renamed Context Session",
                        "session_date": "2026-02-07",
                        "group_ids": [
                            self._context_token(
                                "world_eldervale",
                                "campaign_ashen_crown",
                                "group_silver_lances",
                            )
                        ],
                    }
                ],
            )
            original_path_func = session_creator.session_storage_path
            original_world_data = copy.deepcopy(session_creator.WORLD_DATA)
            session_creator.session_storage_path = lambda: storage_path
            try:
                renamed_world_data = copy.deepcopy(TEST_WORLD_DATA)
                renamed_world_data[0]["name"] = "Eldervale Renamed"
                renamed_world_data[0]["campaigns"][0]["name"] = "Ashen Crown Renamed"
                renamed_world_data[0]["campaigns"][0]["groups"][0]["name"] = "Silver Lances Renamed"
                session_creator.WORLD_DATA = renamed_world_data

                widget = SessionCreatorWidget()
                self.addCleanup(widget.close)

                target_row = None
                for row in range(widget.session_list.count()):
                    item = widget.session_list.item(row)
                    if item.data(Qt.ItemDataRole.UserRole) == "renamed_context_session":
                        target_row = row
                        break
                self.assertIsNotNone(target_row)

                widget.session_list.setCurrentRow(target_row)
                widget._load_selected_session()

                self.assertEqual(widget.world_combo.currentText(), "Eldervale Renamed")
                self.assertEqual(widget.campaign_combo.currentText(), "Ashen Crown Renamed")
                self.assertEqual(widget.group_combo.currentText(), "Silver Lances Renamed")
            finally:
                session_creator.WORLD_DATA = original_world_data
                session_creator.session_storage_path = original_path_func

    def test_loading_session_applies_linked_context_restrictions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "sessions.dmtindex"
            self._write_sessions_to_dir(
                Path(tmp_dir),
                [
                    {
                        "id": "session_eld_a",
                        "name": "Eldervale A",
                        "session_date": "2026-02-05",
                        "group_ids": [self._context_token("world_eldervale", "campaign_ashen_crown", "group_silver_lances")],
                    },
                    {
                        "id": "session_eld_b",
                        "name": "Eldervale B",
                        "session_date": "2026-02-04",
                        "group_ids": [self._context_token("world_eldervale", "campaign_ashen_crown", "group_gilded_tide")],
                    },
                    {
                        "id": "session_storm",
                        "name": "Stormreach",
                        "session_date": "2026-02-03",
                        "group_ids": [self._context_token("world_stormreach", "campaign_iron_meridian", "group_cinderwatch")],
                    },
                ],
            )

            original_path_func = session_creator.session_storage_path
            session_creator.session_storage_path = lambda: storage_path
            try:
                widget = SessionCreatorWidget()
                self.addCleanup(widget.close)
                widget.world_combo.setCurrentIndex(0)
                self.assertEqual(widget.session_list.count(), 3)

                target_row = None
                for row in range(widget.session_list.count()):
                    item = widget.session_list.item(row)
                    if item.data(Qt.ItemDataRole.UserRole) == "session_storm":
                        target_row = row
                        break
                self.assertIsNotNone(target_row)

                widget.session_list.setCurrentRow(target_row)
                widget._load_selected_session()

                self.assertEqual(widget.world_combo.currentText(), "Stormreach")
                self.assertEqual(widget.campaign_combo.currentText(), "Iron Meridian")
                self.assertEqual(widget.group_combo.currentText(), "Cinderwatch")
                self.assertEqual(widget.session_list.count(), 1)
                self.assertEqual(
                    widget.session_list.currentItem().data(Qt.ItemDataRole.UserRole),
                    "session_storm",
                )
            finally:
                session_creator.session_storage_path = original_path_func


if __name__ == "__main__":
    unittest.main()
