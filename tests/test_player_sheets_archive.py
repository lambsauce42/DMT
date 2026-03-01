import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DMT_TEST_MODE", "1")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from character_archive import (
    ARCHIVE_EXTENSION,
    INVENTORY_ENTRY_NAME,
    META_ENTRY_NAME,
    PDF_ENTRY_NAME,
    extract_character_pdf,
    read_character_inventory,
    write_character_archive,
)
import player_sheets


def test_character_sheet_pdf_runtime_path_uses_cache_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    runtime_pdf = player_sheets.character_sheet_pdf_path("hero")
    assert runtime_pdf == tmp_path / "cache" / "characters" / "hero.pdf"
    assert runtime_pdf.parent != player_sheets.character_sheets_dir()


def test_sync_entry_archive_does_not_create_sidecar_pdf_in_character_sheets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 source")
    entry = player_sheets.PlayerSheetEntry(name="Hero", pdf_path=str(source_pdf))

    assert player_sheets.sync_entry_archive(entry)
    sidecar_pdf = player_sheets.character_sheets_dir() / "Hero.pdf"
    assert not sidecar_pdf.exists()
    assert Path(entry.archive_path).exists()


def test_save_entries_writes_index_to_cache_not_save_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 source")
    entry = player_sheets.PlayerSheetEntry(name="Hero", pdf_path=str(source_pdf))
    assert player_sheets.ensure_entry_archive(entry)

    player_sheets.save_entries_to_storage([entry])

    cache_index = tmp_path / "cache" / "characters" / "character_sheets.json"
    root_index = tmp_path / "characters" / "character_sheets.json"
    assert cache_index.exists()
    assert not root_index.exists()


def test_load_entries_rebuilds_cache_index_from_archives_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 source")
    sheet_id = "Hero"
    archive_path = player_sheets.character_sheet_archive_path(sheet_id)
    write_character_archive(
        archive_path,
        pdf_path=source_pdf,
        inventory_payload={
            "inventory": ["rope"],
            "inventory_notes": "from archive",
            "equipment": {"head": "helm_1"},
            "gold": 5,
            "silver": 1,
            "copper": 0,
        },
        meta={
            "name": "Hero",
            "sheet_id": sheet_id,
            "world": "Eldervale",
            "campaign": "Ashen Crown",
            "group": "Silver Lances",
            "tags": ["fighter", "tank"],
        },
    )

    cache_index = tmp_path / "cache" / "characters" / "character_sheets.json"
    root_index = tmp_path / "characters" / "character_sheets.json"
    assert not cache_index.exists()
    assert not root_index.exists()

    entries = player_sheets.load_entries_from_storage()
    assert len(entries) == 1
    entry = entries[0]
    assert player_sheets.sheet_id_for_entry(entry) == sheet_id
    assert entry.name == "Hero"
    assert entry.world == "Eldervale"
    assert entry.campaign == "Ashen Crown"
    assert entry.group == "Silver Lances"
    assert sorted(entry.tags) == ["fighter", "tank"]
    assert Path(entry.archive_path).exists()
    assert cache_index.exists()
    assert not root_index.exists()


def test_load_entries_prefers_archive_over_stale_cache_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 source")
    sheet_id = "Hero"
    archive_path = player_sheets.character_sheet_archive_path(sheet_id)
    write_character_archive(
        archive_path,
        pdf_path=source_pdf,
        inventory_payload={
            "inventory": ["rope"],
            "inventory_notes": "from archive",
            "equipment": {"head": "helm_1"},
            "gold": 5,
            "silver": 1,
            "copper": 0,
        },
        meta={
            "name": "Hero",
            "sheet_id": sheet_id,
            "world": "Eldervale",
            "campaign": "Ashen Crown",
            "group": "Silver Lances",
            "tags": ["fighter", "tank"],
        },
    )

    cache_index = player_sheets.player_sheets_storage_path()
    cache_index.parent.mkdir(parents=True, exist_ok=True)
    cache_index.write_text(
        json.dumps(
            [
                {
                    "name": "Hero",
                    "pdf_path": str(tmp_path / "stale.pdf"),
                    "archive_path": str(archive_path),
                    "world": "Wrong World",
                    "campaign": "Wrong Campaign",
                    "group": "Wrong Group",
                    "tags": ["stale"],
                    "inventory": ["stale_item"],
                    "inventory_notes": "stale note",
                    "equipment": {"head": "stale_helm"},
                    "gold": 99,
                    "silver": 98,
                    "copper": 97,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    entries = player_sheets.load_entries_from_storage()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.world == "Eldervale"
    assert entry.campaign == "Ashen Crown"
    assert entry.group == "Silver Lances"
    assert sorted(entry.tags) == ["fighter", "tank"]
    assert entry.inventory == ["rope"]
    assert entry.inventory_notes == "from archive"
    assert entry.gold == 5
    assert entry.silver == 1
    assert entry.copper == 0

    persisted = json.loads(cache_index.read_text(encoding="utf-8"))
    assert persisted[0]["world"] == "Eldervale"
    assert persisted[0]["inventory"] == ["rope"]
    assert persisted[0]["gold"] == 5


def test_character_archive_round_trip_and_inventory_schema(tmp_path: Path) -> None:
    source_pdf = tmp_path / "sheet.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 test sheet")
    archive_path = tmp_path / f"hero{ARCHIVE_EXTENSION}"

    write_character_archive(
        archive_path,
        pdf_path=source_pdf,
        inventory_payload={
            "inventory": [" sword ", "", "shield"],
            "inventory_notes": "  found in cave ",
            "equipment": {"head": "helm", "neck": ""},
            "gold": "12",
            "silver": -5,
            "copper": "x",
            "hp": 42,  # Should not be persisted in inventory schema.
        },
        meta={"name": "Hero", "character_id": "character_hero_unique"},
    )

    assert archive_path.exists()
    with zipfile.ZipFile(archive_path, "r") as zf:
        names = set(zf.namelist())
        assert {PDF_ENTRY_NAME, INVENTORY_ENTRY_NAME, META_ENTRY_NAME}.issubset(names)
        raw_inventory = json.loads(zf.read(INVENTORY_ENTRY_NAME).decode("utf-8"))
        assert set(raw_inventory.keys()) == {
            "inventory",
            "inventory_notes",
            "equipment",
            "gold",
            "silver",
            "copper",
        }
        raw_meta = json.loads(zf.read(META_ENTRY_NAME).decode("utf-8"))
        assert raw_meta["name"] == "Hero"
        assert raw_meta["character_id"] == "character_hero_unique"

    payload = read_character_inventory(archive_path)
    assert payload["inventory"] == ["sword", "shield"]
    assert payload["inventory_notes"] == "  found in cave "
    assert payload["equipment"]["head"] == "helm"
    assert payload["equipment"]["neck"] is None
    assert payload["gold"] == 12
    assert payload["silver"] == 0
    assert payload["copper"] == 0
    assert "hp" not in payload

    extracted_pdf = tmp_path / "restored.pdf"
    assert extract_character_pdf(archive_path, extracted_pdf)
    assert extracted_pdf.read_bytes() == source_pdf.read_bytes()


def test_entries_with_same_name_get_distinct_stable_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    pdf_one = tmp_path / "one.pdf"
    pdf_two = tmp_path / "two.pdf"
    pdf_one.write_bytes(b"%PDF-1.4 one")
    pdf_two.write_bytes(b"%PDF-1.4 two")

    first = player_sheets.PlayerSheetEntry(name="Shared Hero", pdf_path=str(pdf_one))
    second = player_sheets.PlayerSheetEntry(name="Shared Hero", pdf_path=str(pdf_two))

    assert player_sheets.ensure_entry_archive(first)
    assert player_sheets.ensure_entry_archive(second)

    first_sheet_id = player_sheets.sheet_id_for_entry(first)
    second_sheet_id = player_sheets.sheet_id_for_entry(second)
    assert first_sheet_id
    assert second_sheet_id
    assert first_sheet_id != second_sheet_id
    assert first.character_id == first_sheet_id
    assert second.character_id == second_sheet_id
    assert Path(first.archive_path).exists()
    assert Path(second.archive_path).exists()


def test_legacy_character_sheet_entry_migrates_to_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    legacy_pdf = tmp_path / "legacy.pdf"
    legacy_pdf.write_bytes(b"%PDF-1.4 legacy")

    storage_path = player_sheets.player_sheets_storage_path()
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_text(
        json.dumps(
            [
                {
                    "name": "Legacy Hero",
                    "pdf_path": str(legacy_pdf),
                    "tags": ["fighter"],
                    "inventory": ["rope"],
                    "inventory_notes": "old note",
                    "equipment": {"head": "old_helm"},
                    "gold": 11,
                    "silver": 2,
                    "copper": 1,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    entries = player_sheets.load_entries_from_storage()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.name == "Legacy Hero"
    assert entry.archive_path
    archive_path = Path(entry.archive_path)
    assert archive_path.exists()

    inventory = read_character_inventory(archive_path)
    assert inventory["inventory"] == ["rope"]
    assert inventory["inventory_notes"] == "old note"
    assert inventory["gold"] == 11
    assert inventory["silver"] == 2
    assert inventory["copper"] == 1
    assert "hp" not in inventory
    assert "ac" not in inventory

    player_sheets.save_entries_to_storage(entries)
    persisted = json.loads(storage_path.read_text(encoding="utf-8"))
    assert persisted and isinstance(persisted, list)
    row = persisted[0]
    assert row["sheet_id"] == player_sheets.sheet_id_for_entry(entry)
    assert row["pdf_path"] == str(player_sheets.character_sheet_pdf_path(row["sheet_id"]))
    assert row["archive_path"] == str(archive_path)


def test_set_inventory_payload_for_sheet_id_persists_and_emits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    source_pdf = tmp_path / "hero.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 hero")
    entry = player_sheets.PlayerSheetEntry(name="Hero", pdf_path=str(source_pdf))
    assert player_sheets.ensure_entry_archive(entry)
    player_sheets.save_entries_to_storage([entry])
    sheet_id = player_sheets.sheet_id_for_entry(entry)

    events: list[tuple[str, dict]] = []
    handler = lambda emitted_sheet_id, payload: events.append((emitted_sheet_id, dict(payload)))
    player_sheets.PLAYER_SHEET_EVENTS.inventorySaved.connect(handler)
    try:
        ok, message, payload = player_sheets.set_inventory_payload_for_sheet_id(
            sheet_id,
            {
                "inventory": ["item_a", "item_b"],
                "inventory_notes": "loot stash",
                "equipment": {"head": "helm_1"},
                "gold": 12,
                "silver": 3,
                "copper": 1,
            },
            emit_event=True,
        )
    finally:
        player_sheets.PLAYER_SHEET_EVENTS.inventorySaved.disconnect(handler)

    assert ok, message
    assert isinstance(payload, dict)
    assert payload["inventory"] == ["item_a", "item_b"]
    assert payload["inventory_notes"] == "loot stash"
    assert payload["equipment"]["head"] == "helm_1"
    assert payload["gold"] == 12
    assert payload["silver"] == 3
    assert payload["copper"] == 1
    assert events and events[-1][0] == sheet_id

    archive_payload = read_character_inventory(Path(entry.archive_path))
    assert archive_payload["inventory"] == ["item_a", "item_b"]
    assert archive_payload["inventory_notes"] == "loot stash"
    assert archive_payload["gold"] == 12


def test_ensure_network_linked_sheet_entry_creates_local_sheet_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    sheet_id = "Hero_A_sheet_20260226120000_deadbeefcafebabe"

    ok, message, payload = player_sheets.ensure_network_linked_sheet_entry(
        sheet_id,
        "Hero A",
        {
            "inventory": ["item_a"],
            "inventory_notes": "synced",
            "equipment": {"head": "helm_a"},
            "gold": 3,
            "silver": 1,
            "copper": 0,
        },
        emit_event=False,
    )

    assert ok, message
    assert isinstance(payload, dict)
    assert payload["inventory"] == ["item_a"]
    assert payload["equipment"]["head"] == "helm_a"

    entries = player_sheets.load_entries_from_storage()
    assert len(entries) == 1
    entry = entries[0]
    assert player_sheets.sheet_id_for_entry(entry) == sheet_id
    assert entry.name == "Hero A"
    assert Path(entry.pdf_path).exists()
    assert Path(entry.archive_path).exists()


def test_load_entries_prunes_legacy_mock_character_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_sheets, "default_sheet_save_dir", lambda: str(tmp_path))
    hero_pdf = tmp_path / "hero.pdf"
    hero_pdf.write_bytes(b"%PDF-1.4 hero")

    storage_path = player_sheets.player_sheets_storage_path()
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_text(
        json.dumps(
            [
                {
                    "name": "Liora Sunfall",
                    "pdf_path": str(tmp_path / "Liora_Sunfall.pdf"),
                    "world": "Eldervale",
                    "campaign": "Ashen Crown",
                    "group": "Silver Lances",
                    "tags": ["cleric", "healer", "sun"],
                },
                {
                    "name": "Hero",
                    "pdf_path": str(hero_pdf),
                    "tags": ["fighter"],
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    entries = player_sheets.load_entries_from_storage()
    assert [entry.name for entry in entries] == ["Hero"]

    persisted = json.loads(storage_path.read_text(encoding="utf-8"))
    assert [row.get("name") for row in persisted] == ["Hero"]
