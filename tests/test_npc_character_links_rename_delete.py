import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QDialog, QInputDialog


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import player_sheets
from player_sheets import PlayerSheetEntry, PlayerSheetsWidget


def _make_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")


def _seed_single_entry(tmp_path, monkeypatch, name: str = "Hero One") -> None:
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    monkeypatch.setattr(player_sheets, "PDFIUM_VIEW_AVAILABLE", False)
    entry = PlayerSheetEntry(
        name=name,
        pdf_path=str(player_sheets.character_sheet_pdf_path(player_sheets.sanitize_filename(name))),
    )
    _make_pdf(Path(entry.pdf_path))
    player_sheets.save_entries_to_storage([entry])


def test_edit_sheet_name_retargets_npc_links(tmp_path, qtbot, monkeypatch):
    _seed_single_entry(tmp_path, monkeypatch, name="Hero One")

    class _FakeDialog:
        def __init__(self, *args, **kwargs):
            self._entry = player_sheets.PlayerSheetEntry(
                name="Hero Renamed",
                pdf_path=str(player_sheets.character_sheet_pdf_path("Hero_One")),
                archive_path=str(player_sheets.character_sheet_archive_path("Hero_Renamed")),
            )

        def exec(self):
            return QDialog.DialogCode.Accepted

        def entry(self):
            return self._entry

    monkeypatch.setattr(player_sheets, "PlayerSheetDialog", _FakeDialog)
    monkeypatch.setattr(player_sheets, "ensure_entry_archive", lambda _entry: True)
    retarget_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        player_sheets,
        "_retarget_npc_links_for_sheet_rename",
        lambda old, new: retarget_calls.append((old, new)) or 0,
    )

    widget = PlayerSheetsWidget()
    qtbot.addWidget(widget)
    widget._sheet_list.setCurrentRow(0)
    widget._open_edit_sheet_dialog()

    assert retarget_calls == [("Hero_One", "Hero_Renamed")]


def test_delete_unlinks_npc_links_for_sheet(tmp_path, qtbot, monkeypatch):
    _seed_single_entry(tmp_path, monkeypatch, name="Delete Hero")
    unlinked: list[str] = []
    monkeypatch.setattr(
        player_sheets,
        "_unlink_npc_links_for_sheet",
        lambda sheet_id: unlinked.append(sheet_id) or 0,
    )

    widget = PlayerSheetsWidget()
    qtbot.addWidget(widget)
    widget._sheet_list.setCurrentRow(0)
    widget._delete_current_sheet()

    assert unlinked == ["Delete_Hero"]


def test_disintegrate_unlinks_npc_links_for_sheet(tmp_path, qtbot, monkeypatch):
    _seed_single_entry(tmp_path, monkeypatch, name="Dust Hero")
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("DISINTEGRATE", True),
    )
    unlinked: list[str] = []
    monkeypatch.setattr(
        player_sheets,
        "_unlink_npc_links_for_sheet",
        lambda sheet_id: unlinked.append(sheet_id) or 0,
    )

    widget = PlayerSheetsWidget()
    qtbot.addWidget(widget)
    widget._sheet_list.setCurrentRow(0)
    widget._disintegrate_current_sheet()

    assert unlinked == ["Dust_Hero"]
