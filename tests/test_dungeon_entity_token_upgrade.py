import json
import os
import sys

from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QGraphicsScene

# Adjust import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dungeon_applet import DungeonAppletWidget
from dungeon_constants import ROLE_KIND, ROLE_LABEL
from dungeon_items import EntityItem
from encounter_engine import EncounterEntry, Monster
from ui.encounter_panel import EncounterPanel


def _monster_with_icon(icon_path: str) -> Monster:
    return Monster(
        id="m1",
        name="Boss",
        cr="5",
        cr_value=5.0,
        xp=1800,
        hp=95,
        ac=16,
        actions="",
        description="",
        tags=(),
        source="tests",
        icon_path=icon_path,
    )


def test_entity_serialize_deserialize_custom_token_fields(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)

    entity = EntityItem(
        QPointF(120, 180),
        hp=45,
        max_hp=70,
        ac=18,
        icon_path="token://boss_icon.png",
        size_w_cells=3,
        size_h_cells=2,
        lock_square=False,
    )
    entity.setData(ROLE_KIND, "entity")
    entity.setData(ROLE_LABEL, "Boss Hydra")
    widget.canvas.scene().addItem(entity)

    state = widget._serialize_scene()
    entity_payloads = [item for item in state["items"] if item.get("type") == "entity"]
    assert entity_payloads
    payload = entity_payloads[0]
    assert payload["icon_path"] == "token://boss_icon.png"
    assert payload["size_w_cells"] == 3
    assert payload["size_h_cells"] == 2
    assert payload["lock_square"] is False

    scene = QGraphicsScene()
    widget._populate_scene(scene, state, include_fog=False)
    reloaded = [item for item in scene.items() if isinstance(item, EntityItem)]
    assert len(reloaded) == 1
    reloaded_entity = reloaded[0]
    assert reloaded_entity.icon_path == "token://boss_icon.png"
    assert reloaded_entity.size_w_cells == 3
    assert reloaded_entity.size_h_cells == 2
    assert reloaded_entity.lock_square is False


def test_spawn_encounter_entities_inherits_icon_path(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)

    widget.canvas._spawn_encounter_entities(
        QPointF(0, 0),
        [
            {
                "name": "Orc Chief",
                "count": 1,
                "hp": 20,
                "ac": 14,
                "icon_path": "token://orc_chief.png",
            }
        ],
    )

    entities = [item for item in widget.canvas.scene().items() if isinstance(item, EntityItem)]
    assert entities
    assert entities[0].icon_path == "token://orc_chief.png"


def test_encounter_icon_path_round_trip(qtbot, tmp_path):
    panel = EncounterPanel()
    qtbot.addWidget(panel)

    icon_path = "token://encounter_default.png"
    panel._encounter_entries = [EncounterEntry(monster=_monster_with_icon(icon_path), count=2)]
    payload = panel._serialize_encounter("icon-test")
    assert payload["monsters"][0]["icon_path"] == icon_path

    save_path = tmp_path / "encounter_icon_roundtrip.json"
    save_path.write_text(json.dumps(payload), encoding="utf-8")

    panel.load_encounter(save_path)
    assert panel._encounter_entries
    assert panel._encounter_entries[0].monster.icon_path == icon_path
