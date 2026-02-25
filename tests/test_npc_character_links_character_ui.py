import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QDialog


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import player_sheets
from npc_database import NPCEntry
from player_sheets import PlayerSheetEntry, PlayerSheetsWidget


def _make_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")


def _seed_character_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    monkeypatch.setattr(player_sheets, "PDFIUM_VIEW_AVAILABLE", False)
    entries = [
        PlayerSheetEntry(
            name="Hero One",
            pdf_path=str(player_sheets.character_sheet_pdf_path("Hero_One")),
            world="World A",
            campaign="Campaign A",
            group="Group A",
        ),
        PlayerSheetEntry(
            name="Hero Two",
            pdf_path=str(player_sheets.character_sheet_pdf_path("Hero_Two")),
            world="World B",
            campaign="Campaign B",
            group="Group B",
        ),
    ]
    for entry in entries:
        _make_pdf(Path(entry.pdf_path))
    player_sheets.save_entries_to_storage(entries)
    return entries


def test_character_list_shows_linked_npc_summary_line(tmp_path, qtbot, monkeypatch):
    _seed_character_entries(tmp_path, monkeypatch)
    monkeypatch.setattr(
        player_sheets,
        "_linked_npc_names_by_sheet_id",
        lambda: {"Hero_One": ["Guard", "Merchant", "Wizard"]},
    )

    widget = PlayerSheetsWidget()
    qtbot.addWidget(widget)
    text = widget._sheet_list.item(0).text()
    assert "NPCs: Guard, Merchant (+1)" in text


def test_character_header_shows_linked_npc_summary(tmp_path, qtbot, monkeypatch):
    _seed_character_entries(tmp_path, monkeypatch)
    monkeypatch.setattr(
        player_sheets,
        "_linked_npc_names_by_sheet_id",
        lambda: {"Hero_One": ["Guard", "Merchant", "Wizard"]},
    )

    widget = PlayerSheetsWidget()
    qtbot.addWidget(widget)
    widget._sheet_list.setCurrentRow(0)
    assert "| NPCs: Guard, Merchant (+1)" in widget._header_name.text()


def test_manage_npc_links_applies_selected_ids(tmp_path, qtbot, monkeypatch):
    _seed_character_entries(tmp_path, monkeypatch)

    monkeypatch.setattr(
        player_sheets,
        "_load_npcs_for_linking",
        lambda: [
            NPCEntry(id="npc_1", name="Guard", linked_sheet_id="Hero_One"),
            NPCEntry(id="npc_2", name="Merchant", linked_sheet_id=""),
        ],
    )
    monkeypatch.setattr(
        player_sheets.PlayerSheetsWidget,
        "_select_npc_links_for_sheet",
        lambda self, *_args, **_kwargs: {"npc_2"},
    )
    applied: dict[str, object] = {}

    def _apply(sheet_id: str, selected_ids: set[str]):
        applied["sheet_id"] = sheet_id
        applied["selected_ids"] = set(selected_ids)
        return (1, 1)

    monkeypatch.setattr(player_sheets, "_set_links_for_sheet", _apply)
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

    widget = PlayerSheetsWidget()
    qtbot.addWidget(widget)
    widget._sheet_list.setCurrentRow(0)
    widget._open_manage_npc_links_dialog()

    assert applied["sheet_id"] == "Hero_One"
    assert applied["selected_ids"] == {"npc_2"}
