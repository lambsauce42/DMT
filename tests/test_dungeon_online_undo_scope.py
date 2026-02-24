import os
import sys

import pytest
from PyQt6.QtCore import QPointF

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dungeon_applet import DungeonAppletWidget, ONLINE_MODE_DM_HOST, ONLINE_MODE_PLAYER
from dungeon_commands import MoveItemsCommand
from dungeon_constants import ROLE_ENTITY_ID, ROLE_LABEL, ROLE_OWNER_PLAYER_ID
from dungeon_items import EntityItem


class _HostControllerStub:
    def __init__(self, player_widget: DungeonAppletWidget):
        self.players = {"player-1": "Alice"}
        self._player_widget = player_widget
        self.results = []

    def send_command_result(self, player_id, **kwargs):
        self.results.append((player_id, kwargs))

    def send_snapshot_to(self, player_id, snapshot):
        assert player_id == "player-1"
        self._player_widget._on_client_snapshot_received(snapshot)

    def send_icon_asset(self, player_id, **kwargs):
        return None

    def stop(self):
        return None


class _ClientControllerStub:
    def __init__(self, host_widget: DungeonAppletWidget):
        self._host_widget = host_widget

    def send_command(self, action, payload, request_id=None):
        self._host_widget._on_host_command_received(
            "player-1",
            {
                "action": action,
                "payload": payload,
                "request_id": request_id,
            },
        )

    def disconnect(self):
        return None


def _entity_positions(widget: DungeonAppletWidget) -> dict[str, QPointF]:
    result = {}
    for item in widget.canvas.scene().items():
        if isinstance(item, EntityItem):
            entity_id = str(item.data(ROLE_ENTITY_ID) or "")
            if entity_id:
                result[entity_id] = QPointF(item.pos())
    return result


@pytest.fixture
def online_host_and_player(qtbot):
    host = DungeonAppletWidget()
    player = DungeonAppletWidget()
    qtbot.addWidget(host)
    qtbot.addWidget(player)
    host.show()
    player.show()
    qtbot.wait(20)

    host._set_online_mode(ONLINE_MODE_DM_HOST)
    player._set_online_mode(ONLINE_MODE_PLAYER)
    player._local_player_id = "player-1"
    player._player_connection_ready = True

    host._players_dungeon_id = host._active_dungeon_id
    scene = host.canvas.scene()
    dm_entity = EntityItem(QPointF(0.0, 0.0))
    dm_entity.setData(ROLE_ENTITY_ID, "dm-entity")
    dm_entity.setData(ROLE_LABEL, "DM")
    dm_entity.setData(ROLE_OWNER_PLAYER_ID, "")
    scene.addItem(dm_entity)

    player_entity = EntityItem(QPointF(58.0, 0.0))
    player_entity.setData(ROLE_ENTITY_ID, "player-entity")
    player_entity.setData(ROLE_LABEL, "Player")
    player_entity.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    scene.addItem(player_entity)

    host._save_active_dungeon_state()
    host._host_controller = _HostControllerStub(player)
    player._client_controller = _ClientControllerStub(host)

    player._on_client_snapshot_received(host._build_online_snapshot(for_player_id="player-1"))
    return host, player


def test_player_undo_only_reverts_player_actions_and_syncs(online_host_and_player, qtbot):
    host, player = online_host_and_player
    player_entity = player._find_entity_by_id("player-entity")
    dm_entity = player._find_entity_by_id("dm-entity")
    assert player_entity is not None
    assert dm_entity is not None

    start_player_pos = QPointF(player_entity.pos())
    start_dm_pos = QPointF(dm_entity.pos())

    moved_player_pos = QPointF(start_player_pos.x() + 58.0, start_player_pos.y() + 58.0)
    player_entity.setPos(moved_player_pos)
    player.canvas.undo_stack.push(MoveItemsCommand([player_entity], {player_entity: start_player_pos}))
    qtbot.wait(30)

    host_positions_after_move = _entity_positions(host)
    assert host_positions_after_move["player-entity"] == moved_player_pos
    assert host_positions_after_move["dm-entity"] == start_dm_pos

    player.canvas.undo()
    qtbot.wait(30)

    host_positions_after_undo = _entity_positions(host)
    player_positions_after_undo = _entity_positions(player)
    assert host_positions_after_undo["player-entity"] == start_player_pos
    assert host_positions_after_undo["dm-entity"] == start_dm_pos
    assert player_positions_after_undo["player-entity"] == start_player_pos
    assert player_positions_after_undo["dm-entity"] == start_dm_pos


def test_dm_undo_only_reverts_dm_actions_and_syncs(online_host_and_player, qtbot):
    host, player = online_host_and_player
    dm_entity = host._find_entity_by_id("dm-entity")
    player_entity = host._find_entity_by_id("player-entity")
    assert dm_entity is not None
    assert player_entity is not None

    start_dm_pos = QPointF(dm_entity.pos())
    start_player_pos = QPointF(player_entity.pos())
    moved_dm_pos = QPointF(start_dm_pos.x() + 58.0, start_dm_pos.y() + 58.0)

    dm_entity.setPos(moved_dm_pos)
    host.canvas.undo_stack.push(MoveItemsCommand([dm_entity], {dm_entity: start_dm_pos}))
    qtbot.wait(30)

    player_positions_after_dm_move = _entity_positions(player)
    assert player_positions_after_dm_move["dm-entity"] == moved_dm_pos
    assert player_positions_after_dm_move["player-entity"] == start_player_pos

    host.canvas.undo()
    qtbot.wait(30)

    host_positions_after_undo = _entity_positions(host)
    player_positions_after_undo = _entity_positions(player)
    assert host_positions_after_undo["dm-entity"] == start_dm_pos
    assert host_positions_after_undo["player-entity"] == start_player_pos
    assert player_positions_after_undo["dm-entity"] == start_dm_pos
    assert player_positions_after_undo["player-entity"] == start_player_pos
