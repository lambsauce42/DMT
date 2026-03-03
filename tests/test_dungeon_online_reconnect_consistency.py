import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dungeon_applet import DungeonAppletWidget, ONLINE_MODE_DM_HOST, ONLINE_MODE_PLAYER


pytestmark = pytest.mark.tier2

_DEBUG_LOG = Path(ROOT) / "debug" / "test_dungeon_online_reconnect_consistency.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def _entity_state(*, hp: int, label: str) -> dict:
    return {
        "type": "entity",
        "entity_id": "entity-1",
        "owner_player_id": "player-1",
        "hp": hp,
        "label": label,
        "pos": [0.0, 0.0],
    }


def _players_dungeon(*, item: dict) -> list[dict]:
    return [
        {
            "id": "d1",
            "name": "Players",
            "state": {
                "items": [item],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]


class _HostControllerStub:
    def __init__(self):
        self.players = {"player-1": "Mira"}
        self.results = []

    def send_command_result(self, player_id, **kwargs):
        self.results.append((player_id, kwargs))

    def send_snapshot_to(self, player_id, snapshot):
        _debug_log(
            "host send_snapshot_to invoked "
            f"player_id={player_id!r} hp={snapshot['dungeons'][0]['state']['items'][0].get('hp')!r}"
        )

    def send_icon_asset(self, player_id, **kwargs):
        _debug_log(f"host send_icon_asset invoked player_id={player_id!r} kwargs={kwargs!r}")

    def stop(self):
        return None


class _PlayerClientStub:
    def __init__(self, host_widget: DungeonAppletWidget):
        self.host_widget = host_widget
        self.calls = []

    def send_command(self, action, payload, request_id=None):
        self.calls.append((action, dict(payload), request_id))
        _debug_log(
            "player send_command "
            f"action={action!r} request_id={request_id!r} "
            f"hp={payload.get('state', {}).get('items', [{}])[0].get('hp')!r}"
        )
        self.host_widget._on_host_command_received(
            "player-1",
            {
                "action": action,
                "payload": payload,
                "request_id": request_id,
            },
        )
        return True

    def disconnect(self):
        _debug_log("player client disconnect invoked")
        return None


def _build_online_widget(qtbot, *, mode: str, item: dict) -> DungeonAppletWidget:
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    widget._online_mode = mode
    widget._active_dungeon_id = "d1"
    widget._players_dungeon_id = "d1"
    widget._dungeons = _players_dungeon(item=item)
    return widget


def test_reconnect_snapshot_does_not_reapply_stale_player_state_to_host(qtbot):
    host = _build_online_widget(
        qtbot,
        mode=ONLINE_MODE_DM_HOST,
        item=_entity_state(hp=9, label="Host Newer"),
    )
    host._host_controller = _HostControllerStub()
    host._load_dungeon_state(host._dungeons[0]["state"])

    player = _build_online_widget(
        qtbot,
        mode=ONLINE_MODE_PLAYER,
        item=_entity_state(hp=5, label="Player Stale"),
    )
    player._client_controller = _PlayerClientStub(host)
    player._local_player_id = "player-1"
    player._player_connection_ready = True
    player._pending_player_state_update = {
        "dungeon_id": "d1",
        "state": {
            "items": [_entity_state(hp=5, label="Player Stale")],
            "fog": {"path": []},
        },
    }
    player._pending_player_state_update_request_id = "req-before-disconnect"

    _debug_log("disconnect phase: stale pending state should be dropped before reconnect")
    player._on_client_disconnected()
    assert player._pending_player_state_update is None
    assert player._pending_player_state_update_request_id == ""

    player._local_player_id = "player-1"
    player._awaiting_player_snapshot = True

    snapshot = host._build_online_snapshot(for_player_id="player-1")
    _debug_log(
        "snapshot phase: player receives host snapshot "
        f"hp={snapshot['dungeons'][0]['state']['items'][0].get('hp')!r} "
        f"label={snapshot['dungeons'][0]['state']['items'][0].get('label')!r}"
    )
    player._on_client_snapshot_received(snapshot)

    host_item = host._dungeons[0]["state"]["items"][0]
    _debug_log(
        "post snapshot host state "
        f"hp={host_item.get('hp')!r} label={host_item.get('label')!r}"
    )

    assert host_item["hp"] == 9
    assert host_item["label"] == "Host Newer"
