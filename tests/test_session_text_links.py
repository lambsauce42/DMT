import json
import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dmt_package import write_dmt_package
from item_file_format import ITEM_FILE_EXTENSION, ITEM_FILE_FORMAT
from player_sheets import PlayerSheetEntry
from session_text_links import (
    build_markdown_link,
    detect_slash_trigger,
    find_markdown_link_at_position,
    load_link_suggestions,
)


def _write_character_base_dir_debug(lines: list[str]) -> None:
    debug_path = Path(ROOT) / "debug" / "session_text_links_character_base_dir.log"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_contextual_link_packages(base_dir: Path) -> None:
    npc_dir = base_dir / "npcs"
    maps_dir = base_dir / "maps"
    collections_dir = base_dir / "dungeon_collections"
    encounters_dir = base_dir / "encounters"
    npc_dir.mkdir(parents=True, exist_ok=True)
    maps_dir.mkdir(parents=True, exist_ok=True)
    collections_dir.mkdir(parents=True, exist_ok=True)
    encounters_dir.mkdir(parents=True, exist_ok=True)

    write_dmt_package(
        npc_dir / "npc_1.dmtnpc",
        info={
            "format": "dmtnpc.v1",
            "object_type": "npc",
            "object_id": "npc_1",
            "payload": {
                "id": "npc_1",
                "name": "Goblin Guide",
                "world": "Eldervale",
                "campaign": "Ashen Crown",
                "group": "Silver Lances",
            },
        },
        assets={},
    )
    write_dmt_package(
        npc_dir / "npc_2.dmtnpc",
        info={
            "format": "dmtnpc.v1",
            "object_type": "npc",
            "object_id": "npc_2",
            "payload": {
                "id": "npc_2",
                "name": "Goblin Wrong Context",
                "world": "Stormreach",
                "campaign": "Iron Meridian",
                "group": "Cinderwatch",
            },
        },
        assets={},
    )
    write_dmt_package(
        maps_dir / "map_1.dmtmap",
        info={
            "format": "dmtmap.v1",
            "object_type": "map",
            "object_id": "map_1",
            "payload": {
                "id": "map_1",
                "name": "Sewer Entrance",
                "image_path": "",
                "world": "Eldervale",
                "campaign": "Ashen Crown",
                "group": "Silver Lances",
            },
        },
        assets={},
    )
    write_dmt_package(
        collections_dir / "catacombs.dmtcollection",
        info={
            "format": "dmtcollection.v1",
            "object_type": "collection",
            "object_id": "collection_1",
            "collection_name": "Catacombs",
            "dungeons": [
                {"id": "dng_1", "name": "Catacombs Alpha", "state": {"items": [], "fog": {"path": []}}},
                {"id": "dng_2", "name": "Sewer Depths", "state": {"items": [], "fog": {"path": []}}},
            ],
        },
        assets={},
    )
    write_dmt_package(
        encounters_dir / "ambush.dmtencounter",
        info={
            "format": "dmtencounter.v1",
            "object_type": "encounter",
            "object_id": "enc_1",
            "name": "Goblin Ambush",
            "monsters": [],
        },
        assets={},
    )


@pytest.fixture
def contextual_link_base_dir(tmp_path: Path) -> Path:
    base_dir = tmp_path / "DMT"
    _write_contextual_link_packages(base_dir)
    return base_dir


def test_detects_supported_slash_commands() -> None:
    text = "/npc goblin"
    trigger = detect_slash_trigger(text, len(text))
    assert trigger is not None
    assert trigger.command == "npc"
    assert trigger.query == "goblin"

    text = "/map sewer"
    trigger = detect_slash_trigger(text, len(text))
    assert trigger is not None
    assert trigger.command == "map"
    assert trigger.query == "sewer"

    text = "/dungeon cat"
    trigger = detect_slash_trigger(text, len(text))
    assert trigger is not None
    assert trigger.command == "dungeon"
    assert trigger.query == "cat"

    text = "/item sword"
    trigger = detect_slash_trigger(text, len(text))
    assert trigger is not None
    assert trigger.command == "item"
    assert trigger.query == "sword"

    text = "/character mage"
    trigger = detect_slash_trigger(text, len(text))
    assert trigger is not None
    assert trigger.command == "character"
    assert trigger.query == "mage"

    text = "/encounter ambush"
    trigger = detect_slash_trigger(text, len(text))
    assert trigger is not None
    assert trigger.command == "encounter"
    assert trigger.query == "ambush"


def test_double_slash_disables_trigger() -> None:
    text = "//npc goblin"
    trigger = detect_slash_trigger(text, len(text))
    assert trigger is None


def test_markdown_link_roundtrip_with_collection_query() -> None:
    collection_path = "/tmp/test folder/my_collection.dmtcollection"
    markdown = build_markdown_link(
        kind="dungeon",
        target_id="dng_123",
        display_label="Dungeon: Catacombs",
        collection_path=collection_path,
    )
    assert markdown.startswith("[Dungeon: Catacombs](dmt://dungeon/dng_123")
    assert "collection=%2Ftmp%2Ftest%20folder%2Fmy_collection.dmtcollection" in markdown

    text = f"prefix {markdown} suffix"
    position = text.index("Catacombs")
    parsed = find_markdown_link_at_position(text, position)
    assert parsed is not None
    assert parsed.kind == "dungeon"
    assert parsed.target_id == "dng_123"
    assert parsed.collection_path == collection_path


def test_markdown_link_roundtrip_for_item_and_character() -> None:
    item_markdown = build_markdown_link(
        kind="item",
        target_id="steel_sword",
        display_label="Steel Sword",
    )
    item_text = f"x {item_markdown} y"
    item_parsed = find_markdown_link_at_position(item_text, item_text.index("Sword"))
    assert item_parsed is not None
    assert item_parsed.kind == "item"
    assert item_parsed.target_id == "steel_sword"

    char_markdown = build_markdown_link(
        kind="character",
        target_id="wizard_001",
        display_label="Alyra",
    )
    char_text = f"x {char_markdown} y"
    char_parsed = find_markdown_link_at_position(char_text, char_text.index("Alyra"))
    assert char_parsed is not None
    assert char_parsed.kind == "character"
    assert char_parsed.target_id == "wizard_001"

    encounter_markdown = build_markdown_link(
        kind="encounter",
        target_id="enc_001",
        display_label="Goblin Ambush",
    )
    encounter_text = f"x {encounter_markdown} y"
    encounter_parsed = find_markdown_link_at_position(encounter_text, encounter_text.index("Ambush"))
    assert encounter_parsed is not None
    assert encounter_parsed.kind == "encounter"
    assert encounter_parsed.target_id == "enc_001"


def test_npc_link_suggestions_filter_by_context(contextual_link_base_dir: Path) -> None:
    npc_suggestions = load_link_suggestions(
        "npc",
        "goblin",
        world="Eldervale",
        campaign="Ashen Crown",
        group="Silver Lances",
        base_dir=contextual_link_base_dir,
    )
    assert [s.target_id for s in npc_suggestions] == ["npc_1"]
    assert npc_suggestions[0].display_label == "Goblin Guide"


def test_map_link_suggestions_filter_by_context(contextual_link_base_dir: Path) -> None:
    map_suggestions = load_link_suggestions(
        "map",
        "sewer",
        world="Eldervale",
        campaign="Ashen Crown",
        group="Silver Lances",
        base_dir=contextual_link_base_dir,
    )
    assert [s.target_id for s in map_suggestions] == ["map_1"]
    assert map_suggestions[0].display_label == "Sewer Entrance"


def test_dungeon_link_suggestions_include_collection_path(contextual_link_base_dir: Path) -> None:
    dungeon_suggestions = load_link_suggestions(
        "dungeon",
        "alpha",
        base_dir=contextual_link_base_dir,
    )
    assert [s.target_id for s in dungeon_suggestions] == ["dng_1"]
    assert dungeon_suggestions[0].collection_path is not None
    assert dungeon_suggestions[0].collection_path.endswith("catacombs.dmtcollection")


def test_encounter_link_suggestions_use_matching_name(contextual_link_base_dir: Path) -> None:
    encounter_suggestions = load_link_suggestions(
        "encounter",
        "ambush",
        base_dir=contextual_link_base_dir,
    )
    assert [s.target_id for s in encounter_suggestions] == ["enc_1"]
    assert encounter_suggestions[0].display_label == "Goblin Ambush"


def test_dungeon_suggestions_scan_nested_collections(tmp_path: Path) -> None:
    base_dir = tmp_path / "DMT"
    nested_collections_dir = base_dir / "dungeon_collections" / "Act1"
    nested_collections_dir.mkdir(parents=True, exist_ok=True)

    write_dmt_package(
        nested_collections_dir / "crypts.dmtcollection",
        info={
            "format": "dmtcollection.v1",
            "object_type": "collection",
            "object_id": "collection_nested",
            "collection_name": "Act I Crypts",
            "dungeons": [
                {"id": "dng_nested", "name": "Lower Crypts", "state": {"items": [], "fog": {"path": []}}},
            ],
        },
        assets={},
    )

    suggestions = load_link_suggestions("dungeon", "lower", base_dir=base_dir)
    assert [s.target_id for s in suggestions] == ["dng_nested"]
    assert suggestions[0].collection_path is not None
    assert suggestions[0].collection_path.endswith("Act1/crypts.dmtcollection")


def test_item_suggestions_load_saved_items(tmp_path: Path) -> None:
    base_dir = tmp_path / "DMT"
    items_dir = base_dir / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    item_path = items_dir / f"steel_sword{ITEM_FILE_EXTENSION}"
    item_path.write_text(
        json.dumps(
            {
                "format": ITEM_FILE_FORMAT,
                "payload": {"title": "Steel Sword", "rarity": "rare"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    suggestions = load_link_suggestions("item", "steel", base_dir=base_dir)
    assert [s.target_id for s in suggestions] == ["steel_sword"]
    assert suggestions[0].display_label == "Steel Sword"


def test_suggestion_ranking_prefers_prefix_matches_over_plain_substring(tmp_path: Path) -> None:
    base_dir = tmp_path / "DMT"
    items_dir = base_dir / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    entries = [
        ("acat_blade", "Acat Blade"),
        ("cat_blade", "Cat Blade"),
        ("wildcat_blade", "Wildcat Blade"),
    ]
    for file_stem, title in entries:
        item_path = items_dir / f"{file_stem}{ITEM_FILE_EXTENSION}"
        item_path.write_text(
            json.dumps(
                {
                    "format": ITEM_FILE_FORMAT,
                    "payload": {"title": title, "rarity": "common"},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    suggestions = load_link_suggestions("item", "cat", base_dir=base_dir)
    labels = [suggestion.display_label for suggestion in suggestions]
    assert labels[0] == "Cat Blade"


def test_character_suggestions_include_all_saved_entries(monkeypatch) -> None:
    entries = [
        PlayerSheetEntry(name="Alyra", pdf_path=""),
        PlayerSheetEntry(name="Borin", pdf_path=""),
        PlayerSheetEntry(name="Cyra", pdf_path=""),
    ]
    monkeypatch.setattr("player_sheets.load_entries_from_storage", lambda: entries)

    suggestions = load_link_suggestions("character", "", base_dir=Path("."))
    assert [s.display_label for s in suggestions] == ["Alyra", "Borin", "Cyra"]


def test_character_suggestions_respect_explicit_base_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_dir = tmp_path / "env_saves"
    base_dir = tmp_path / "base_saves"
    for target_dir, hero_name in ((env_dir, "Env Hero"), (base_dir, "Base Hero")):
        cache_dir = target_dir / "cache" / "characters"
        cache_dir.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "name": hero_name,
                "pdf_path": "missing.pdf",
                "archive_path": "",
                "world": "",
                "campaign": "",
                "group": "",
                "tags": [],
                "inventory": [],
                "inventory_notes": "",
                "equipment": {},
                "gold": 0,
                "silver": 0,
                "copper": 0,
            }
        ]
        (cache_dir / "character_sheets.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    monkeypatch.setenv("DMT_TEST_MODE", "1")
    monkeypatch.setenv("DMT_TEST_SAVE_DIR", str(env_dir))
    suggestions = load_link_suggestions("character", "", base_dir=base_dir)
    labels = [suggestion.display_label for suggestion in suggestions]

    _write_character_base_dir_debug(
        [
            f"env_dir={env_dir}",
            f"base_dir={base_dir}",
            f"labels={labels}",
        ]
    )

    assert labels == ["Base Hero"]
