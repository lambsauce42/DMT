import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QGraphicsPathItem

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dungeon_applet import (
    DungeonAppletWidget,
    ONLINE_MODE_DM_HOST,
    ONLINE_MODE_PLAYER,
    ToolType,
)
from dungeon_constants import ROLE_KIND, ROLE_OWNER_PLAYER_ID
from item_file_format import build_item_document, write_item_document


pytestmark = pytest.mark.tier2


@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    return widget


def test_player_inventory_save_does_not_forward_while_link_conflict_pending(
    dungeon_widget, monkeypatch
):
    calls = []

    class _ClientStub:
        def send_command(self, action, payload, request_id=None):
            calls.append((action, dict(payload), request_id))
            return True

        def disconnect(self):
            return None

    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._player_connection_ready = True
    dungeon_widget._pending_link_conflicts["d1::entity-1::character-1"] = {
        "character_id": "character-1",
    }

    monkeypatch.setattr("player_sheets.character_id_for_sheet_id", lambda _sheet_id: "character-1")
    monkeypatch.setattr("player_sheets.inventory_payload_for_sheet_id", lambda _sheet_id: {"inventory": []})

    dungeon_widget._on_external_character_inventory_saved(
        "sheet-1",
        {"inventory": [{"item_id": "item-1", "quantity": 1}]},
    )

    assert calls == []


def test_host_sync_character_inventory_rejects_invalid_archive_payload(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-1",
                        "linked_inventory": {"inventory": []},
                        "pos": [0.0, 0.0],
                    }
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]

    dungeon_widget._handle_host_sync_character_inventory(
        "player-1",
        {
            "sheet_id": "sheet-1",
            "character_id": "character-1",
            "inventory": {"inventory": []},
            "stats": {"name": "Hero"},
            "archive_b64": "%%%not-base64%%%",
        },
        request_id="invalid-archive-sync",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is False
    assert "archive payload is invalid" in str(result.get("message") or "").lower()


def test_conflicting_known_item_definition_enters_review_before_sync(
    dungeon_widget, monkeypatch, tmp_path
):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    review_calls = []

    monkeypatch.setattr("dungeon_applet.items_dir", lambda: tmp_path)

    existing_item_path = tmp_path / "existing_item.dmtitem"
    write_item_document(
        existing_item_path,
        build_item_document(
            {"item_id": "item_x", "title": "DM Sword", "rarity": "common"},
            None,
        ),
    )

    def _review(**kwargs):
        entries = kwargs.get("entries") or []
        review_calls.append([dict(entry) for entry in entries if isinstance(entry, dict)])
        return {
            "action": "import",
            "selected_item_ids": [str(entry.get("item_id") or "") for entry in entries],
            "signature": "reviewed",
        }

    monkeypatch.setattr(dungeon_widget, "_review_unknown_linked_items", _review)

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._broadcast_snapshot_if_host = lambda: None
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-1",
                        "linked_inventory": {},
                        "pos": [0.0, 0.0],
                    }
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]

    dungeon_widget._handle_host_sync_character_inventory(
        "player-1",
        {
            "sheet_id": "sheet-1",
            "character_id": "character-1",
            "inventory": {
                "inventory": ["item_x"],
                "item_documents": {
                    "item_x": {
                        "format": "dmtitem.v2",
                        "payload": {"item_id": "item_x", "title": "Player Sword", "rarity": "rare"},
                    }
                },
            },
            "stats": {"name": "Hero"},
        },
        request_id="review-conflict",
    )

    assert review_calls
    assert review_calls[0][0]["item_id"] == "item_x"
    assert review_calls[0][0]["conflicts_with_authority"] is True
    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is True
    linked_inventory = dungeon_widget._dungeons[0]["state"]["items"][0]["linked_inventory"]
    assert linked_inventory["item_documents"]["item_x"]["payload"]["title"] == "DM Sword"


def test_player_mode_collection_autosave_is_suspended(dungeon_widget, tmp_path):
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._autosave_enabled = True
    dungeon_widget._collection_dirty = True
    dungeon_widget._collection_path = tmp_path / "campaign.dmtcollection"

    dungeon_widget._run_collection_autosave()

    assert not (tmp_path / "campaign_autosave.dmtcollection").exists()


def test_join_online_session_clears_previous_collection_path(dungeon_widget):
    class _ClientStub:
        def __init__(self):
            self.disconnected = False
            self.connect_args = None

        def disconnect(self):
            self.disconnected = True

        def connect_to_host(self, host, port, name, persistent_player_id=None):
            self.connect_args = (host, port, name, persistent_player_id)

    client_stub = _ClientStub()
    dungeon_widget._client_controller = client_stub
    dungeon_widget._collection_path = Path("C:/tmp/existing_collection.dmtcollection")

    dungeon_widget.join_online_session("192.168.1.10", 8765, "Mira")

    assert client_stub.disconnected is True
    assert dungeon_widget._collection_path is None


def test_player_eraser_only_deletes_local_player_strokes(dungeon_widget):
    own_stroke = QGraphicsPathItem()
    own_path = own_stroke.path()
    own_path.moveTo(20.0, 20.0)
    own_path.lineTo(30.0, 20.0)
    own_stroke.setPath(own_path)
    own_stroke.setData(ROLE_KIND, "stroke")
    own_stroke.setData(ROLE_OWNER_PLAYER_ID, "player-local")

    other_stroke = QGraphicsPathItem()
    other_path = other_stroke.path()
    other_path.moveTo(0.0, 0.0)
    other_path.lineTo(10.0, 0.0)
    other_stroke.setPath(other_path)
    other_stroke.setData(ROLE_KIND, "stroke")
    other_stroke.setData(ROLE_OWNER_PLAYER_ID, "player-other")

    scene = dungeon_widget.canvas.scene()
    scene.addItem(own_stroke)
    scene.addItem(other_stroke)

    dungeon_widget.canvas.set_stroke_owner_player_id("player-local")
    eraser_state = dungeon_widget.canvas._states[ToolType.ERASER]

    eraser_state._erase_at(QPointF(5.0, 0.0))
    assert other_stroke.scene() is scene

    eraser_state._erase_at(QPointF(25.0, 20.0))
    assert own_stroke.scene() is None
