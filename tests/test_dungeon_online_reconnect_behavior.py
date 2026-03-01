import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dungeon_applet import (
    DungeonAppletWidget,
    ONLINE_MODE_LOCAL_DM,
    ONLINE_MODE_PLAYER,
)
from online_session.controllers import ClientSessionController


@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    return widget


def test_failed_join_disconnect_stops_reconnect_loop(dungeon_widget):
    controller = ClientSessionController(dungeon_widget)
    controller.disconnected.connect(dungeon_widget._on_client_disconnected)
    controller._connect_host = "127.0.0.1"
    controller._connect_port = 8765
    controller._connect_name = "Mira"
    dungeon_widget._client_controller = controller
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._player_connection_ready = False

    controller._on_disconnected()

    assert dungeon_widget._online_mode == ONLINE_MODE_LOCAL_DM
    assert not controller._reconnect_timer.isActive()
    assert controller._manual_disconnect is True


def test_snapshot_is_ignored_outside_player_mode(dungeon_widget):
    dungeon_widget._online_mode = ONLINE_MODE_LOCAL_DM
    dungeon_widget._collection_name = "Local Collection"
    local = dungeon_widget._create_dungeon_entry(
        "Local Dungeon",
        state={"items": [], "fog": {"path": []}},
    )
    dungeon_widget._dungeons = [local]
    dungeon_widget._active_dungeon_id = local["id"]
    dungeon_widget._players_dungeon_id = local["id"]

    snapshot = {
        "collection_name": "Remote Collection",
        "active_dungeon_id": "remote-1",
        "players_dungeon_id": "remote-1",
        "dungeons": [
            {
                "id": "remote-1",
                "name": "Remote Dungeon",
                "state": {"items": [], "fog": {"path": []}},
            }
        ],
        "players": {"player-1": "Alice"},
        "loot_pool": [],
        "initiative_state": {
            "active": False,
            "collapsed": False,
            "player_entries": {},
            "entity_entries": {},
        },
    }

    dungeon_widget._on_client_snapshot_received(snapshot)

    assert dungeon_widget._collection_name == "Local Collection"
    assert dungeon_widget._active_dungeon_id == local["id"]
    assert dungeon_widget._players_dungeon_id == local["id"]
    assert len(dungeon_widget._dungeons) == 1
    assert dungeon_widget._dungeons[0]["id"] == local["id"]


def test_first_player_snapshot_runs_pending_override_sync(dungeon_widget, monkeypatch):
    calls = []
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._pending_join_character_override_sync = True
    monkeypatch.setattr(
        dungeon_widget,
        "_push_local_character_overrides_to_host",
        lambda **_kwargs: calls.append("called") or 0,
    )

    snapshot = {
        "collection_name": "Remote Collection",
        "active_dungeon_id": "d-1",
        "players_dungeon_id": "d-1",
        "dungeons": [
            {
                "id": "d-1",
                "name": "Players",
                "state": {"items": [], "fog": {"path": []}},
            }
        ],
        "players": {"player-local": "Mira"},
        "loot_pool": [],
        "initiative_state": {
            "active": False,
            "collapsed": False,
            "player_entries": {},
            "entity_entries": {},
        },
    }

    dungeon_widget._on_client_snapshot_received(snapshot)

    assert calls == ["called"]
    assert dungeon_widget._pending_join_character_override_sync is False


def test_push_local_character_overrides_uses_linked_character_id_lookup(dungeon_widget, monkeypatch):
    sent = []

    class _ClientStub:
        def send_command(self, action, payload, request_id=None):
            sent.append((action, dict(payload), request_id))

        def disconnect(self):
            return None

    lookup_calls = []
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._player_connection_ready = True
    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._active_dungeon_id = "d-1"
    dungeon_widget._dungeons = [
        {
            "id": "d-1",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-1",
                        "owner_player_id": "player-local",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-1",
                    }
                ],
                "fog": {"path": []},
            },
        }
    ]

    def _resolve(identifier):
        lookup_calls.append(identifier)
        if identifier != "character-1":
            return None
        return {
            "sheet_id": "sheet-1",
            "sheet_name": "Hero",
            "character_id": "character-1",
            "save_revision": 2,
            "last_saved_at": "",
            "content_hash": "hash-1",
            "inventory": {"inventory": []},
            "stats": {"name": "Hero"},
        }

    monkeypatch.setattr(dungeon_widget, "_resolve_local_sheet_sync_payload", _resolve)

    sent_count = dungeon_widget._push_local_character_overrides_to_host()

    assert lookup_calls == ["character-1"]
    assert sent_count == 1
    assert sent
    assert sent[-1][0] == "link_character_entity"
    assert sent[-1][1]["character_id"] == "character-1"
