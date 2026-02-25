import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLineEdit, QListWidget, QListWidgetItem

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dmt_package import write_dmt_package
from dungeon_applet import DungeonAppletWidget
from item_creator import ItemCreatorWidget
from item_file_format import ITEM_FILE_EXTENSION, ITEM_FILE_FORMAT
from maps_applet import MapsWidget
from models import MapAsset
from npc_database import NPCDatabaseWidget, NPCEntry
from player_sheets import PlayerSheetEntry, PlayerSheetsWidget, sheet_id_for_entry
from ui.encounter_panel import EncounterPanel


def test_npc_open_linked_entry_selects_target_across_active_filters(qtbot) -> None:
    widget = NPCDatabaseWidget()
    qtbot.addWidget(widget)

    widget._manager.entries = [
        NPCEntry(id="npc_other", name="Other", description="alpha"),
        NPCEntry(id="npc_target", name="Target", description="beta"),
    ]
    widget._apply_filters()
    widget._search_input.setText("other")
    assert widget._current_entry is not None
    assert widget._current_entry.id == "npc_other"

    ok = widget.open_linked_entry("npc_target")
    assert ok is True
    assert widget._current_entry is not None
    assert widget._current_entry.id == "npc_target"


def test_map_open_linked_entry_selects_target_across_active_filters(qtbot) -> None:
    widget = MapsWidget()
    qtbot.addWidget(widget)

    widget._manager.entries = [
        MapAsset(id="map_other", name="Other Map", image_path="", tags=["alpha"]),
        MapAsset(id="map_target", name="Target Map", image_path="", tags=["beta"]),
    ]
    widget._apply_filters()
    widget._tag_input.setText("alpha")
    assert widget._current_entry is not None
    assert widget._current_entry.id == "map_other"

    ok = widget.open_linked_entry("map_target")
    assert ok is True
    assert widget._current_entry is not None
    assert widget._current_entry.id == "map_target"


def test_dungeon_open_linked_dungeon_switches_collection_and_selects_dungeon(
    qtbot, tmp_path: Path
) -> None:
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)

    collection_a = tmp_path / "a.dmtcollection"
    collection_b = tmp_path / "b.dmtcollection"

    write_dmt_package(
        collection_a,
        info={
            "format": "dmtcollection.v1",
            "object_type": "collection",
            "object_id": "collection_a",
            "collection_name": "Collection A",
            "dungeons": [
                {"id": "dng_a", "name": "Dungeon A", "state": {"items": [], "fog": {"path": []}}},
            ],
        },
        assets={},
    )
    write_dmt_package(
        collection_b,
        info={
            "format": "dmtcollection.v1",
            "object_type": "collection",
            "object_id": "collection_b",
            "collection_name": "Collection B",
            "dungeons": [
                {"id": "dng_b", "name": "Dungeon B", "state": {"items": [], "fog": {"path": []}}},
            ],
        },
        assets={},
    )

    assert widget.open_linked_dungeon(str(collection_a), "dng_a") is True
    assert widget._active_dungeon_id == "dng_a"

    assert widget.open_linked_dungeon(str(collection_b), "dng_b") is True
    assert widget._active_dungeon_id == "dng_b"
    assert widget._collection_path is not None
    assert widget._collection_path.resolve() == collection_b.resolve()


def test_character_open_linked_sheet_selects_target_across_active_filters(qtbot) -> None:
    e1 = PlayerSheetEntry(name="Alpha", pdf_path="")
    e1.world = "W1"
    e2 = PlayerSheetEntry(name="Beta", pdf_path="")
    e2.world = "W2"
    e3 = PlayerSheetEntry(name="Gamma", pdf_path="")
    e3.world = "W3"

    class _CharacterHost:
        def __init__(self) -> None:
            self._world_combo = QComboBox()
            self._campaign_combo = QComboBox()
            self._group_combo = QComboBox()
            self._tag_input = QLineEdit()
            self._sheet_list = QListWidget()
            self._current_entry = None
            self._selection_guard = False
            self._entries = [e1, e2, e3]

            for combo in (self._world_combo, self._campaign_combo, self._group_combo):
                combo.addItem("All")

            self._world_combo.addItem("W1")
            self._world_combo.addItem("W2")
            self._world_combo.addItem("W3")

        def _set_details(self, entry) -> None:
            self._current_entry = entry

        def _apply_filters(self) -> None:
            selected_world = self._world_combo.currentText()
            self._sheet_list.clear()
            visible = self._entries
            if selected_world and selected_world != "All":
                visible = [entry for entry in self._entries if entry.world == selected_world]
            for entry in visible:
                item = QListWidgetItem(entry.name)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self._sheet_list.addItem(item)

    host = _CharacterHost()
    qtbot.addWidget(host._world_combo)
    qtbot.addWidget(host._campaign_combo)
    qtbot.addWidget(host._group_combo)
    qtbot.addWidget(host._tag_input)
    qtbot.addWidget(host._sheet_list)

    host._apply_filters()
    idx = host._world_combo.findText("W1")
    if idx >= 0:
        host._world_combo.setCurrentIndex(idx)
    host._apply_filters()
    assert host._sheet_list.count() == 1

    ok = PlayerSheetsWidget.open_linked_sheet(host, "gamma")
    assert ok is True
    assert host._current_entry is not None
    assert sheet_id_for_entry(host._current_entry).casefold() == "gamma"


def test_item_open_linked_item_loads_by_item_id(qtbot, tmp_path: Path, monkeypatch) -> None:
    items_root = tmp_path / "items"
    items_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("save_paths.items_dir", lambda: items_root)

    payload = {
        "title": "Steel Sword",
        "rarity": "rare",
        "classes": [],
        "stats": [],
        "effects": [],
        "flavor_text": "",
        "icon_path": "",
        "tags": [],
        "level": 3,
        "fused_stats_effects": False,
        "show_level": True,
        "show_rarity": True,
        "show_icon_padding": True,
    }
    path = items_root / f"steel_sword{ITEM_FILE_EXTENSION}"
    path.write_text(
        json.dumps({"format": ITEM_FILE_FORMAT, "payload": payload}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    widget = ItemCreatorWidget()
    qtbot.addWidget(widget)

    ok = widget.open_linked_item("steel_sword")
    assert ok is True
    assert widget.title_edit.text() == "Steel Sword"


def test_encounter_open_linked_encounter_loads_by_id(qtbot, tmp_path: Path, monkeypatch) -> None:
    encounters_dir = tmp_path / "encounters"
    encounters_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("ui.encounter_panel.dnd_saves_dir", lambda: tmp_path)

    write_dmt_package(
        encounters_dir / "other.dmtencounter",
        info={
            "format": "dmtencounter.v1",
            "object_type": "encounter",
            "object_id": "enc_other",
            "name": "Other",
            "difficulty": "Easy",
            "party_levels": [1],
            "monsters": [{"id": "m1", "name": "Wolf", "cr": "1/4", "xp": 50, "count": 1}],
        },
        assets={},
    )
    write_dmt_package(
        encounters_dir / "target.dmtencounter",
        info={
            "format": "dmtencounter.v1",
            "object_type": "encounter",
            "object_id": "enc_target",
            "name": "Target",
            "difficulty": "Medium",
            "party_levels": [3, 3],
            "monsters": [{"id": "m2", "name": "Goblin", "cr": "1/4", "xp": 50, "count": 2}],
        },
        assets={},
    )

    widget = EncounterPanel()
    qtbot.addWidget(widget)

    ok = widget.open_linked_encounter("enc_target")
    assert ok is True
    assert widget._encounter_id == "enc_target"
    assert widget._encounter_entries
    assert widget._encounter_entries[0].monster.name == "Goblin"
