import os
import sys
from pathlib import Path


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import npc_database
import player_sheets
from npc_database import NPCEntry


def _make_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")


def test_npc_entry_round_trip_persists_linked_sheet_id() -> None:
    entry = NPCEntry(
        id="npc_1",
        name="Innkeeper",
        linked_sheet_id="Hero_One",
    )
    payload = npc_database.entry_to_dict(entry)
    loaded = npc_database.entry_from_dict(payload)
    assert loaded is not None
    assert loaded.linked_sheet_id == "Hero_One"


def test_set_links_for_sheet_and_rename_and_unlink(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(npc_database, "default_sheet_save_dir", lambda: str(tmp_path))

    npc_database.save_npc_entries_to_storage(
        [
            NPCEntry(id="npc_1", name="Guard", linked_sheet_id=""),
            NPCEntry(id="npc_2", name="Merchant", linked_sheet_id="other_sheet"),
            NPCEntry(id="npc_3", name="Wizard", linked_sheet_id="target_sheet"),
        ]
    )

    linked_count, unlinked_count = npc_database.set_links_for_sheet(
        "target_sheet",
        {"npc_1", "npc_2"},
    )
    assert linked_count == 2
    assert unlinked_count == 1

    by_id = {entry.id: entry for entry in npc_database.load_npc_entries_from_storage()}
    assert by_id["npc_1"].linked_sheet_id == "target_sheet"
    assert by_id["npc_2"].linked_sheet_id == "target_sheet"
    assert by_id["npc_3"].linked_sheet_id == ""

    migrated = npc_database.retarget_links_for_sheet_rename(
        "target_sheet",
        "renamed_sheet",
    )
    assert migrated == 2
    by_id = {entry.id: entry for entry in npc_database.load_npc_entries_from_storage()}
    assert by_id["npc_1"].linked_sheet_id == "renamed_sheet"
    assert by_id["npc_2"].linked_sheet_id == "renamed_sheet"

    cleared = npc_database.unlink_links_for_sheet("renamed_sheet")
    assert cleared == 2
    by_id = {entry.id: entry for entry in npc_database.load_npc_entries_from_storage()}
    assert by_id["npc_1"].linked_sheet_id == ""
    assert by_id["npc_2"].linked_sheet_id == ""


def test_linked_name_map_auto_unlinks_orphans(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(npc_database, "default_sheet_save_dir", lambda: str(tmp_path))
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))

    valid_entry = player_sheets.PlayerSheetEntry(
        name="Valid Hero",
        pdf_path=str(player_sheets.character_sheet_pdf_path("Valid_Hero")),
    )
    _make_pdf(Path(valid_entry.pdf_path))
    player_sheets.save_entries_to_storage([valid_entry])

    npc_database.save_npc_entries_to_storage(
        [
            NPCEntry(id="npc_1", name="Valid Link", linked_sheet_id="Valid_Hero"),
            NPCEntry(id="npc_2", name="Orphan Link", linked_sheet_id="Missing_Hero"),
        ]
    )

    linked_map = npc_database.linked_npc_names_by_sheet_id()
    assert linked_map == {"Valid_Hero": ["Valid Link"]}

    by_id = {entry.id: entry for entry in npc_database.load_npc_entries_from_storage()}
    assert by_id["npc_1"].linked_sheet_id == "Valid_Hero"
    assert by_id["npc_2"].linked_sheet_id == ""
