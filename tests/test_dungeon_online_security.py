import base64
import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dungeon_applet import (
    DungeonAppletWidget,
    ONLINE_MODE_DM_HOST,
    ONLINE_MODE_LOCAL_DM,
    ONLINE_MODE_PLAYER,
)
from save_paths import dnd_saves_dir


@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    return widget


def test_player_state_update_only_merges_owned_entities(dungeon_widget, monkeypatch):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    broadcasts = []
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: broadcasts.append(True))

    dungeon_widget._dungeons = [
        {
            "id": "players-dungeon",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "owned-1",
                        "owner_player_id": "player-1",
                        "pos": [1.0, 1.0],
                        "hp": 10,
                    },
                    {
                        "type": "entity",
                        "entity_id": "other-1",
                        "owner_player_id": "player-2",
                        "pos": [2.0, 2.0],
                        "hp": 10,
                    },
                    {"type": "room", "floor_path": [], "pos": [0.0, 0.0]},
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]
    dungeon_widget._players_dungeon_id = "players-dungeon"
    dungeon_widget._active_dungeon_id = "players-dungeon"

    dungeon_widget._on_host_command_received(
        "player-1",
        {
            "action": "state_update",
            "request_id": "req-owned",
            "payload": {
                "dungeon_id": "players-dungeon",
                "state": {
                    "items": [
                        {
                            "type": "entity",
                            "entity_id": "owned-1",
                            "owner_player_id": "player-1",
                            "pos": [7.0, 8.0],
                            "hp": 21,
                        },
                        {
                            "type": "entity",
                            "entity_id": "other-1",
                            "owner_player_id": "player-2",
                            "pos": [99.0, 99.0],
                            "hp": 1,
                        },
                    ],
                    "fog": {"path": []},
                },
            },
        },
    )

    items = dungeon_widget._dungeons[0]["state"]["items"]
    owned = next(item for item in items if isinstance(item, dict) and item.get("entity_id") == "owned-1")
    other = next(item for item in items if isinstance(item, dict) and item.get("entity_id") == "other-1")
    room = next(item for item in items if isinstance(item, dict) and item.get("type") == "room")

    assert owned["pos"] == [7.0, 8.0]
    assert owned["hp"] == 21
    assert other["pos"] == [2.0, 2.0]
    assert other["hp"] == 10
    assert room["type"] == "room"
    assert broadcasts == [True]
    assert dungeon_widget._host_controller.results[-1][1]["ok"] is True


def test_player_state_update_syncs_only_player_owned_strokes(dungeon_widget, monkeypatch):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    broadcasts = []
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: broadcasts.append(True))

    dungeon_widget._dungeons = [
        {
            "id": "players-dungeon",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "stroke",
                        "stroke_id": "stroke-owned-1",
                        "owner_player_id": "player-1",
                        "layer": "foreground",
                        "pos": [1.0, 1.0],
                            "path": [{"type": 0, "x": 0.0, "y": 0.0}, {"type": 1, "x": 5.0, "y": 5.0}],
                        "pen_color": "#ffffff",
                        "pen_width": 2.0,
                        "z": 305.0,
                    },
                    {
                        "type": "stroke",
                        "stroke_id": "stroke-owned-2",
                        "owner_player_id": "player-1",
                        "layer": "foreground",
                        "pos": [2.0, 2.0],
                            "path": [{"type": 0, "x": 1.0, "y": 1.0}, {"type": 1, "x": 6.0, "y": 6.0}],
                        "pen_color": "#ffffff",
                        "pen_width": 2.0,
                        "z": 305.0,
                    },
                    {
                        "type": "stroke",
                        "stroke_id": "stroke-other",
                        "owner_player_id": "player-2",
                        "layer": "foreground",
                        "pos": [10.0, 10.0],
                            "path": [{"type": 0, "x": 0.0, "y": 0.0}, {"type": 1, "x": 9.0, "y": 9.0}],
                        "pen_color": "#00ff00",
                        "pen_width": 2.0,
                        "z": 305.0,
                    },
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]
    dungeon_widget._players_dungeon_id = "players-dungeon"
    dungeon_widget._active_dungeon_id = "players-dungeon"

    dungeon_widget._on_host_command_received(
        "player-1",
        {
            "action": "state_update",
            "request_id": "req-strokes",
            "payload": {
                "dungeon_id": "players-dungeon",
                "state": {
                    "items": [
                        {
                            "type": "stroke",
                            "stroke_id": "stroke-owned-1",
                            "owner_player_id": "player-1",
                            "layer": "foreground",
                            "pos": [22.0, 33.0],
                            "path": [{"type": 0, "x": 0.0, "y": 0.0}, {"type": 1, "x": 12.0, "y": 12.0}],
                            "pen_color": "#ff00ff",
                            "pen_width": 3.0,
                            "z": 305.0,
                        },
                        {
                            "type": "stroke",
                            "stroke_id": "stroke-new",
                            "owner_player_id": "player-1",
                            "layer": "foreground",
                            "pos": [44.0, 55.0],
                            "path": [{"type": 0, "x": 2.0, "y": 2.0}, {"type": 1, "x": 8.0, "y": 8.0}],
                            "pen_color": "#123456",
                            "pen_width": 4.0,
                            "z": 305.0,
                        },
                        {
                            "type": "stroke",
                            "stroke_id": "stroke-other",
                            "owner_player_id": "player-2",
                            "layer": "foreground",
                            "pos": [999.0, 999.0],
                            "path": [{"type": 0, "x": 0.0, "y": 0.0}, {"type": 1, "x": 1.0, "y": 1.0}],
                            "pen_color": "#ff0000",
                            "pen_width": 9.0,
                            "z": 305.0,
                        },
                    ],
                    "fog": {"path": []},
                },
            },
        },
    )

    items = dungeon_widget._dungeons[0]["state"]["items"]
    by_id = {
        str(item.get("stroke_id") or item.get("entity_id") or ""): item
        for item in items
        if isinstance(item, dict) and item.get("type") == "stroke"
    }
    assert "stroke-owned-1" in by_id
    assert "stroke-new" in by_id
    assert "stroke-owned-2" not in by_id
    assert by_id["stroke-owned-1"]["pos"] == [22.0, 33.0]
    assert by_id["stroke-owned-1"]["pen_color"] == "#ff00ff"
    assert by_id["stroke-new"]["owner_player_id"] == "player-1"
    assert by_id["stroke-other"]["owner_player_id"] == "player-2"
    assert by_id["stroke-other"]["pos"] == [10.0, 10.0]
    assert broadcasts == [True]
    assert dungeon_widget._host_controller.results[-1][1]["ok"] is True


def test_player_state_update_rejects_non_players_dungeon(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._players_dungeon_id = "players-dungeon"
    dungeon_widget._dungeons = [
        {"id": "players-dungeon", "name": "Players", "state": {"items": [], "fog": {"path": []}}},
        {"id": "dm-dungeon", "name": "DM", "state": {"items": [], "fog": {"path": []}}},
    ]

    dungeon_widget._on_host_command_received(
        "player-1",
        {
            "action": "state_update",
            "request_id": "req-denied",
            "payload": {"dungeon_id": "dm-dungeon", "state": {"items": [], "fog": {"path": []}}},
        },
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is False
    assert "assigned players dungeon" in result["message"]


def test_player_cannot_update_dm_entity_initiative_rows(dungeon_widget, monkeypatch):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._connected_players = {"player-1": "Alice"}
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {},
        "entity_entries": {"npc-1": {"name": "Goblin", "initiative": 5}},
    }
    monkeypatch.setattr(dungeon_widget, "_render_initiative_overlay", lambda: None)
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: None)

    print("[debug] initiative_before", dungeon_widget._initiative_state["entity_entries"]["npc-1"])
    dungeon_widget._handle_host_initiative_update(
        "player-1",
        {"kind": "entity", "id": "npc-1", "initiative": 20},
        request_id="req-initiative-entity",
    )
    print("[debug] initiative_after", dungeon_widget._initiative_state["entity_entries"]["npc-1"])
    result = dungeon_widget._host_controller.results[-1][1]
    print("[debug] initiative_result", result)

    assert result["ok"] is False
    assert "not owned" in str(result.get("message") or "").lower()
    assert dungeon_widget._initiative_state["entity_entries"]["npc-1"]["initiative"] == 5


def test_player_can_update_own_assigned_entity_initiative_row(dungeon_widget, monkeypatch):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._connected_players = {"player-1": "Alice"}
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {
            "player-1:entity-1": {
                "player_id": "player-1",
                "entity_id": "entity-1",
                "name": "Alice - Ranger",
                "initiative": 7,
            }
        },
        "entity_entries": {},
    }
    monkeypatch.setattr(dungeon_widget, "_render_initiative_overlay", lambda: None)
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: None)

    print("[debug] own_row_before", dungeon_widget._initiative_state["player_entries"]["player-1:entity-1"])
    dungeon_widget._handle_host_initiative_update(
        "player-1",
        {"kind": "player", "id": "player-1:entity-1", "initiative": 19},
        request_id="req-initiative-own",
    )
    print("[debug] own_row_after", dungeon_widget._initiative_state["player_entries"]["player-1:entity-1"])
    result = dungeon_widget._host_controller.results[-1][1]
    print("[debug] own_row_result", result)

    assert result["ok"] is True
    assert dungeon_widget._initiative_state["player_entries"]["player-1:entity-1"]["initiative"] == 19


def test_player_cannot_update_other_players_assigned_entity_initiative_row(dungeon_widget, monkeypatch):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._connected_players = {"player-1": "Alice", "player-2": "Bob"}
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {
            "player-2:entity-9": {
                "player_id": "player-2",
                "entity_id": "entity-9",
                "name": "Bob - Fighter",
                "initiative": 11,
            }
        },
        "entity_entries": {},
    }
    monkeypatch.setattr(dungeon_widget, "_render_initiative_overlay", lambda: None)
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: None)

    print("[debug] other_row_before", dungeon_widget._initiative_state["player_entries"]["player-2:entity-9"])
    dungeon_widget._handle_host_initiative_update(
        "player-1",
        {"kind": "player", "id": "player-2:entity-9", "initiative": 3},
        request_id="req-initiative-other",
    )
    print("[debug] other_row_after", dungeon_widget._initiative_state["player_entries"]["player-2:entity-9"])
    result = dungeon_widget._host_controller.results[-1][1]
    print("[debug] other_row_result", result)

    assert result["ok"] is False
    assert "not owned" in str(result.get("message") or "").lower()
    assert dungeon_widget._initiative_state["player_entries"]["player-2:entity-9"]["initiative"] == 11


def test_host_snapshot_request_sends_only_players_dungeon_to_player(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.snapshots = []

        def send_snapshot_to(self, player_id, snapshot):
            self.snapshots.append((player_id, snapshot))

        def send_icon_asset(self, player_id, **kwargs):
            return None

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._connected_players = {"player-1": "Alice", "player-2": "Bob"}
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {
            "player-1:e1": {"player_id": "player-1", "name": "Alice", "initiative": 12},
            "player-2:e2": {"player_id": "player-2", "name": "Bob", "initiative": 11},
        },
        "entity_entries": {"npc-1": {"name": "Goblin", "initiative": 5}},
    }
    dungeon_widget._dungeons = [
        {"id": "dm-dungeon", "name": "DM", "state": {"items": [], "fog": {"path": []}}},
        {
            "id": "players-dungeon",
            "name": "Players",
            "state": {"items": [{"type": "entity", "entity_id": "e1"}], "fog": {"path": []}},
        },
    ]
    dungeon_widget._active_dungeon_id = "dm-dungeon"
    dungeon_widget._players_dungeon_id = "players-dungeon"

    dungeon_widget._on_host_snapshot_requested("player-1")

    assert dungeon_widget._host_controller.snapshots
    _, snapshot = dungeon_widget._host_controller.snapshots[-1]
    assert snapshot["active_dungeon_id"] == "players-dungeon"
    assert snapshot["players_dungeon_id"] == "players-dungeon"
    assert len(snapshot["dungeons"]) == 1
    assert snapshot["dungeons"][0]["id"] == "players-dungeon"
    assert "player-1:e1" in snapshot["initiative_state"]["player_entries"]
    assert "player-2:e2" not in snapshot["initiative_state"]["player_entries"]
    assert snapshot["initiative_state"]["entity_entries"] == {}


def test_failed_join_disconnect_restores_local_mode(dungeon_widget):
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._player_connection_ready = False
    dungeon_widget._local_player_id = None

    dungeon_widget._on_client_disconnected()

    assert dungeon_widget._online_mode == ONLINE_MODE_LOCAL_DM
    assert dungeon_widget._player_connection_ready is False


def test_debug_log_defaults_to_disabled_and_stays_in_save_data(monkeypatch, qtbot):
    monkeypatch.delenv("DMT_ONLINE_DEBUG_LOG", raising=False)
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)

    assert widget._debug_log_enabled is False
    expected_root = dnd_saves_dir() / "cache" / "logs"
    assert str(widget._debug_log_path).startswith(str(expected_root))


def test_close_event_removes_global_app_event_filter(dungeon_widget):
    app = QApplication.instance()
    assert app is not None
    assert dungeon_widget._app is app

    dungeon_widget.close()

    assert dungeon_widget._app is None


def test_player_state_update_cannot_set_arbitrary_icon_path(dungeon_widget, tmp_path):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.assets = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_icon_asset(self, **kwargs):
            self.assets.append(dict(kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(dict(snapshot))

        @property
        def players(self):
            return {}

        def stop(self):
            return None

    host = _HostStub()
    dungeon_widget._host_controller = host
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dm = dungeon_widget._create_dungeon_entry("DM", state={"items": [], "fog": {"path": []}})
    players = dungeon_widget._create_dungeon_entry(
        "Players",
        state={
            "items": [
                {
                    "type": "entity",
                    "entity_id": "entity-1",
                    "owner_player_id": "player-1",
                    "icon_path": "",
                    "pos": [0.0, 0.0],
                }
            ],
            "fog": {"path": []},
        },
    )
    dungeon_widget._dungeons = [dm, players]
    dungeon_widget._active_dungeon_id = dm["id"]
    dungeon_widget._players_dungeon_id = players["id"]

    secret_file = tmp_path / "host_secret.txt"
    secret_file.write_text("host-data-that-must-not-leak", encoding="utf-8")
    original_icon = str(players["state"]["items"][0].get("icon_path") or "")

    dungeon_widget._on_host_command_received(
        "player-1",
        {
            "action": "state_update",
            "request_id": "req-icon-path",
            "payload": {
                "dungeon_id": players["id"],
                "state": {
                    "items": [
                        {
                            "type": "entity",
                            "entity_id": "entity-1",
                            "owner_player_id": "player-1",
                            "icon_path": str(secret_file),
                        }
                    ],
                    "fog": {"path": []},
                },
            },
        },
    )

    result = host.results[-1][1]
    assert result["ok"] is True
    assert players["state"]["items"][0].get("icon_path") == original_icon
    assert host.assets == []


def test_player_upload_icon_cannot_claim_unowned_entity(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.assets = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_icon_asset(self, **kwargs):
            self.assets.append(dict(kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(dict(snapshot))

        @property
        def players(self):
            return {}

        def stop(self):
            return None

    host = _HostStub()
    dungeon_widget._host_controller = host
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dm = dungeon_widget._create_dungeon_entry("DM", state={"items": [], "fog": {"path": []}})
    players = dungeon_widget._create_dungeon_entry(
        "Players",
        state={
            "items": [
                {
                    "type": "entity",
                    "entity_id": "entity-unowned",
                    "owner_player_id": "",
                    "icon_path": "",
                    "pos": [0.0, 0.0],
                }
            ],
            "fog": {"path": []},
        },
    )
    dungeon_widget._dungeons = [dm, players]
    dungeon_widget._active_dungeon_id = dm["id"]
    dungeon_widget._players_dungeon_id = players["id"]

    dungeon_widget._on_host_command_received(
        "player-1",
        {
            "action": "upload_icon",
            "request_id": "req-upload-claim",
            "payload": {
                "entity_id": "entity-unowned",
                "filename": "token.png",
                "content_b64": base64.b64encode(b"player-icon").decode("ascii"),
                "owner_player_id": "player-1",
                "dungeon_id": players["id"],
            },
        },
    )

    result = host.results[-1][1]
    assert result["ok"] is False
    assert "owner" in str(result.get("message") or "").lower()
    assert players["state"]["items"][0].get("owner_player_id") == ""
    assert host.assets == []


def test_player_disconnect_releases_loot_claim_reservations(dungeon_widget):
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._connected_players = {"player-1": "Alice"}
    dungeon_widget._session_loot_pool = [
        {"entry_id": "loot-1", "type": "item", "item_id": "item-a", "title": "Item A"}
    ]
    dungeon_widget._loot_claim_reservations = {
        "claim-1": {
            "claim_id": "claim-1",
            "player_id": "player-1",
            "sheet_id": "sheet-1",
            "claimed_entries": [{"entry_id": "loot-1"}],
            "entry_ids": ["loot-1"],
            "created_monotonic": 0.0,
        }
    }
    dungeon_widget._loot_claim_entry_reservations = {"loot-1": "claim-1"}

    dungeon_widget._update_connected_players({})

    assert dungeon_widget._loot_claim_reservations == {}
    assert dungeon_widget._loot_claim_entry_reservations == {}
