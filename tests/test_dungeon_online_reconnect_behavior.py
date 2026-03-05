import os
import sys

import pytest
from PySide6.QtCore import QPointF, Qt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dungeon_applet import (
    DungeonAppletWidget,
    ONLINE_MODE_LOCAL_DM,
    ONLINE_MODE_PLAYER,
)
from dungeon_items import EntityItem
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


def test_player_actions_remain_blocked_until_first_snapshot_after_hello_ack(dungeon_widget):
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_name = "Mira"

    dungeon_widget._on_client_hello_ack("player-1")

    assert dungeon_widget._player_connection_ready is False
    assert dungeon_widget._awaiting_player_snapshot is True
    assert dungeon_widget._player_network_actions_available() is False

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
        "players": {"player-1": "Mira"},
        "loot_pool": [],
        "initiative_state": {
            "active": False,
            "collapsed": False,
            "player_entries": {},
            "entity_entries": {},
        },
    }
    dungeon_widget._on_client_snapshot_received(snapshot)

    assert dungeon_widget._player_connection_ready is True
    assert dungeon_widget._awaiting_player_snapshot is False


def test_disconnect_after_hello_ack_keeps_player_mode_and_reconnects(dungeon_widget):
    controller = ClientSessionController(dungeon_widget)
    controller.disconnected.connect(dungeon_widget._on_client_disconnected)
    controller._connect_host = "127.0.0.1"
    controller._connect_port = 8765
    controller._connect_name = "Mira"
    dungeon_widget._client_controller = controller
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_name = "Mira"

    dungeon_widget._on_client_hello_ack("player-1")
    controller._on_disconnected()

    assert dungeon_widget._online_mode == ONLINE_MODE_PLAYER
    assert controller._manual_disconnect is False
    assert controller._reconnect_timer.isActive()


def test_first_player_snapshot_does_not_auto_push_pending_character_overrides(dungeon_widget):
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"

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

    assert dungeon_widget._pending_player_state_update is None


def test_player_snapshot_triggers_managed_linked_artifact_cleanup(dungeon_widget, monkeypatch):
    cleanup_calls = []
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    monkeypatch.setattr(
        dungeon_widget,
        "_cleanup_unlinked_managed_character_artifacts",
        lambda: cleanup_calls.append(True),
    )

    snapshot = {
        "collection_name": "Remote Collection",
        "active_dungeon_id": "d-1",
        "players_dungeon_id": "d-1",
        "dungeons": [
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
                            "linked_inventory": {"inventory": []},
                            "pos": [0.0, 0.0],
                        }
                    ],
                    "fog": {"path": []},
                },
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

    assert cleanup_calls == [True]


def test_snapshot_with_newer_local_linked_character_prompts_conflict_instead_of_auto_push(
    dungeon_widget, monkeypatch
):
    pushed = []
    prompted = []

    class _ClientStub:
        def send_command(self, action, payload, request_id=None):
            pushed.append((action, dict(payload), request_id))
            return True

        def disconnect(self):
            return None

    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._player_connection_ready = True
    dungeon_widget._client_controller = _ClientStub()
    monkeypatch.setattr(
        dungeon_widget,
        "_resolve_local_sheet_sync_payload",
        lambda _identifier: {
            "sheet_id": "sheet-1",
            "sheet_name": "Hero",
            "character_id": "character-1",
            "save_revision": 5,
            "last_saved_at": "",
            "content_hash": "local-hash",
            "inventory": {"inventory": [{"item_id": "item-local", "quantity": 1}]},
            "stats": {"name": "Hero"},
        },
    )
    monkeypatch.setattr(
        dungeon_widget,
        "_prompt_linked_character_conflict",
        lambda conflict, **_kwargs: prompted.append(dict(conflict)),
    )

    snapshot = {
        "collection_name": "Remote Collection",
        "active_dungeon_id": "d-1",
        "players_dungeon_id": "d-1",
        "dungeons": [
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
                            "linked_sheet_name": "Hero",
                            "linked_character_id": "character-1",
                            "linked_save_revision": 2,
                            "linked_content_hash": "host-hash",
                            "linked_inventory": {"inventory": [{"item_id": "item-host", "quantity": 1}]},
                            "pos": [0.0, 0.0],
                        }
                    ],
                    "fog": {"path": []},
                },
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

    assert pushed == []
    assert len(prompted) == 1
    assert prompted[0]["character_id"] == "character-1"


def test_reconnect_keeps_unresolved_link_conflict_blocked(dungeon_widget, monkeypatch):
    sent_commands = []

    class _ClientStub:
        def send_command(self, action, payload, request_id=None):
            sent_commands.append((action, dict(payload), request_id))
            return True

        def disconnect(self):
            return None

    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._local_player_name = "Mira"
    dungeon_widget._player_connection_ready = True
    dungeon_widget._client_controller = _ClientStub()

    monkeypatch.setattr("player_sheets.character_id_for_sheet_id", lambda _sheet_id: "character-1")
    monkeypatch.setattr("player_sheets.inventory_payload_for_sheet_id", lambda _sheet_id: {"inventory": []})
    monkeypatch.setattr(
        dungeon_widget,
        "_resolve_local_sheet_sync_payload",
        lambda _character_id: {
            "sheet_id": "sheet-1",
            "sheet_name": "Hero",
            "character_id": "character-1",
            "save_revision": 5,
            "last_saved_at": "",
            "content_hash": "local-hash",
            "inventory": {"inventory": [{"item_id": "item-local", "quantity": 1}]},
            "stats": {"name": "Hero"},
            "archive_b64": "",
        },
    )

    conflict = {
        "conflict_key": "d1::entity-1::character-1",
        "dungeon_id": "d1",
        "entity_id": "entity-1",
        "character_id": "character-1",
        "sheet_id": "sheet-1",
        "sheet_name": "Hero",
        "save_revision": 2,
        "last_saved_at": "",
        "content_hash": "host-hash",
        "inventory": {"inventory": [{"item_id": "item-host", "quantity": 1}]},
        "allow_force_push": True,
        "requires_local_create": False,
    }
    conflict_key = str(conflict["conflict_key"])
    dungeon_widget._pending_link_conflicts[conflict_key] = dict(conflict)
    dungeon_widget._suppressed_link_conflicts[conflict_key] = (
        dungeon_widget._linked_character_conflict_signature(conflict)
    )

    dungeon_widget._on_client_disconnected()
    dungeon_widget._on_client_hello_ack("player-local")

    prompts = []
    monkeypatch.setattr(
        dungeon_widget,
        "_prompt_linked_character_conflict",
        lambda payload, force=False: prompts.append((dict(payload), bool(force))),
    )

    snapshot = {
        "players": {"player-local": "Mira"},
        "players_dungeon_id": "d1",
        "active_dungeon_id": "d1",
        "dungeons": [
            {
                "id": "d1",
                "name": "Players",
                "state": {
                    "items": [
                        {
                            "type": "entity",
                            "entity_id": "entity-1",
                            "owner_player_id": "player-local",
                            "linked_sheet_id": "sheet-1",
                            "linked_sheet_name": "Hero",
                            "linked_character_id": "character-1",
                            "linked_save_revision": 2,
                            "linked_content_hash": "host-hash",
                            "linked_inventory": {"inventory": [{"item_id": "item-host", "quantity": 1}]},
                        }
                    ],
                    "fog": {"path": []},
                },
            }
        ],
    }

    dungeon_widget._on_client_snapshot_received(snapshot)

    assert prompts == []
    dungeon_widget._on_external_character_inventory_saved(
        "sheet-1",
        {"inventory": [{"item_id": "item-local", "quantity": 1}]},
    )

    assert sent_commands == []


def test_player_disconnect_redacts_scene_until_snapshot(dungeon_widget):
    class _ClientStub:
        def consume_terminal_disconnect_message(self):
            return ""

        def send_command(self, _action, _payload, request_id=None):
            _ = request_id
            return False

        def disconnect(self):
            return None

    dungeon_widget.canvas._place_entity(QPointF(32.0, 32.0))
    assert any(isinstance(item, EntityItem) for item in dungeon_widget.canvas.scene().items())

    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._player_connection_ready = True
    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._on_client_disconnected()

    assert not any(isinstance(item, EntityItem) for item in dungeon_widget.canvas.scene().items())

    snapshot = {
        "players": {"player-1": "Mira"},
        "players_dungeon_id": "players-dungeon",
        "active_dungeon_id": "players-dungeon",
        "dungeons": [
            {
                "id": "players-dungeon",
                "name": "Players",
                "state": {
                    "items": [
                        {
                            "type": "entity",
                            "entity_id": "entity-1",
                            "label": "Visible Again",
                            "pos": [64.0, 64.0],
                        }
                    ],
                    "fog": {"path": []},
                },
            }
        ],
    }
    dungeon_widget._on_client_snapshot_received(snapshot)

    assert any(isinstance(item, EntityItem) for item in dungeon_widget.canvas.scene().items())


def test_reconnect_dialog_retry_button_stays_disabled_until_auto_retries_exhausted(
    dungeon_widget, qtbot
):
    retry_calls = []

    class _ClientStub:
        def retry_reconnect(self):
            retry_calls.append(True)
            return True

        def disconnect(self):
            return None

    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._client_controller = _ClientStub()

    dungeon_widget._on_client_reconnect_state_changed(
        {
            "status": "scheduled",
            "attempt": 1,
            "max_attempts": 5,
            "next_delay_ms": 1200,
            "manual_retry_budget": 2,
            "manual_retry_available": False,
        }
    )

    retry_button = dungeon_widget._reconnect_retry_button
    assert retry_button is not None
    assert retry_button.isEnabled() is False

    dungeon_widget._on_client_reconnect_state_changed(
        {
            "status": "paused",
            "attempt": 5,
            "max_attempts": 5,
            "next_delay_ms": 0,
            "manual_retry_budget": 2,
            "manual_retry_available": True,
        }
    )

    retry_button = dungeon_widget._reconnect_retry_button
    assert retry_button is not None
    assert retry_button.isEnabled() is True
    qtbot.mouseClick(retry_button, Qt.MouseButton.LeftButton)
    assert retry_calls == [True]


def test_reconnect_dialog_waiting_message_animates_dot_suffix(dungeon_widget):
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER

    dungeon_widget._on_client_reconnect_state_changed(
        {
            "status": "attempting",
            "attempt": 1,
            "max_attempts": 5,
            "next_delay_ms": 0,
            "manual_retry_budget": -1,
            "manual_retry_available": False,
        }
    )

    label = dungeon_widget._reconnect_status_label
    assert label is not None
    text_a = label.text()
    dungeon_widget._on_reconnect_status_animation_tick()
    text_b = label.text()
    dungeon_widget._on_reconnect_status_animation_tick()
    text_c = label.text()
    dungeon_widget._on_reconnect_status_animation_tick()
    text_d = label.text()

    assert text_a.endswith(".")
    assert text_b.endswith("..")
    assert text_c.endswith("...")
    assert text_d.endswith(".")
