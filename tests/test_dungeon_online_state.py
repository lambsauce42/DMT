import base64
import json
import math
import os
import sys
import types
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QGraphicsScene, QLabel, QLineEdit, QListWidget, QPushButton

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import dungeon_applet as dungeon_applet_module
from dungeon_applet import (
    DungeonAppletWidget,
    ONLINE_MODE_DM_HOST,
    ONLINE_MODE_LOCAL_DM,
    ONLINE_MODE_PLAYER,
    SESSION_ICON_PREFIX,
    ToolType,
)
from dungeon_commands import SpawnPingCommand
from dungeon_constants import (
    ROLE_ENTITY_ID,
    ROLE_ICON,
    ROLE_LINKED_CHARACTER_ID,
    ROLE_LABEL,
    ROLE_LINKED_SHEET_ID,
    ROLE_LINKED_SHEET_NAME,
    ROLE_OWNER_PLAYER_ID,
)
from dungeon_items import EntityItem
from dmt_package import read_dmt_package_info
from item_file_format import build_item_document, load_item_payload, write_item_document

_PNG_1X1_BYTES = (
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4////fwAJ+wP9KobjigAAAABJRU5ErkJggg=="
    )
)


@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    return widget


def test_entity_owner_and_network_id_round_trip(dungeon_widget):
    scene = dungeon_widget.canvas.scene()
    entity = EntityItem(QPointF(10, 10))
    entity.setData(ROLE_ENTITY_ID, "entity-1")
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    entity.setData(ROLE_ICON, "")
    scene.addItem(entity)

    state = dungeon_widget._serialize_scene()
    target_scene = QGraphicsScene()
    dungeon_widget._populate_scene(target_scene, state, include_fog=False)

    loaded = [item for item in target_scene.items() if isinstance(item, EntityItem)]
    assert len(loaded) == 1
    assert loaded[0].data(ROLE_ENTITY_ID) == "entity-1"
    assert loaded[0].data(ROLE_OWNER_PLAYER_ID) == "player-1"


def test_session_icon_reference_serializes_as_reference(dungeon_widget):
    scene = dungeon_widget.canvas.scene()
    entity = EntityItem(QPointF(15, 15))
    entity.setData(ROLE_ENTITY_ID, "entity-2")
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-2")
    entity.setData(ROLE_ICON, f"{SESSION_ICON_PREFIX}token.png")
    entity.icon_path = "not-a-real-file.png"
    scene.addItem(entity)

    state = dungeon_widget._serialize_scene()
    entries = [entry for entry in state.get("items", []) if entry.get("type") == "entity"]
    assert len(entries) == 1
    assert entries[0]["icon_path"] == f"{SESSION_ICON_PREFIX}token.png"


def test_spawn_ping_command_pushes_without_error(dungeon_widget):
    scene = dungeon_widget.canvas.scene()
    dungeon_widget.canvas.undo_stack.push(SpawnPingCommand(scene, QPointF(20, 20)))

    assert dungeon_widget.canvas.undo_stack.index() == 1


def test_host_mode_keeps_player_vision_toggle_available(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)

    assert not dungeon_widget.tool_panel.btn_view_toggle.isHidden()
    assert dungeon_widget.tool_panel.btn_view_toggle.isEnabled()

    dungeon_widget._on_view_mode_changed("player")
    assert dungeon_widget._view_mode == "player"

    dungeon_widget._on_view_mode_changed("dm")
    assert dungeon_widget._view_mode == "dm"


def test_online_bottom_panels_are_collapsible(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    assert dungeon_widget._session_bottom_panel.height() == 220

    dungeon_widget._set_session_panels_collapsed(True, animate=False)
    assert dungeon_widget._session_bottom_panel.height() == 0
    assert dungeon_widget._session_content.isHidden()

    dungeon_widget._set_session_panels_collapsed(False, animate=False)
    assert dungeon_widget._session_bottom_panel.height() == 220
    assert not dungeon_widget._session_content.isHidden()


def test_player_snapshot_uses_players_assigned_dungeon(dungeon_widget):
    snapshot = {
        "collection_name": "Online Test",
        "active_dungeon_id": "dm-dungeon",
        "players_dungeon_id": "players-dungeon",
        "dungeons": [
            {"id": "dm-dungeon", "name": "DM", "state": {"items": [], "fog": {"path": []}}},
            {
                "id": "players-dungeon",
                "name": "Players",
                "state": {
                    "items": [
                        {
                            "type": "entity",
                            "pos": [8.0, 8.0],
                            "entity_id": "players-entity",
                            "owner_player_id": "player-1",
                        }
                    ],
                    "fog": {"path": []},
                },
            },
        ],
        "players": {"player-1": "Mira"},
    }

    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._on_client_snapshot_received(snapshot)

    assert dungeon_widget._players_dungeon_id == "players-dungeon"
    assert dungeon_widget._active_dungeon_id == "players-dungeon"
    scene_entities = [
        item for item in dungeon_widget.canvas.scene().items() if isinstance(item, EntityItem)
    ]
    assert len(scene_entities) == 1
    assert scene_entities[0].data(ROLE_ENTITY_ID) == "players-entity"


def test_assign_players_to_dungeon_broadcasts_snapshot_in_host_mode(dungeon_widget, monkeypatch):
    first = dungeon_widget._create_dungeon_entry("A")
    second = dungeon_widget._create_dungeon_entry("B")
    dungeon_widget._dungeons = [first, second]
    dungeon_widget._active_dungeon_id = first["id"]
    dungeon_widget._players_dungeon_id = first["id"]
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST

    calls = []
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: calls.append("sent"))
    dungeon_widget._assign_players_to_dungeon(second["id"])

    assert dungeon_widget._players_dungeon_id == second["id"]
    assert calls == ["sent"]


def test_online_session_overlay_does_not_resize_canvas(dungeon_widget):
    dungeon_widget.resize(1280, 800)
    base_height = dungeon_widget.canvas.height()

    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    assert dungeon_widget.canvas.height() == base_height

    dungeon_widget._set_session_panels_collapsed(True, animate=False)
    assert dungeon_widget.canvas.height() == base_height

    dungeon_widget._set_session_panels_collapsed(False, animate=False)
    assert dungeon_widget.canvas.height() == base_height


def test_overlay_lift_is_zero_on_large_viewport(dungeon_widget):
    dungeon_widget.resize(1600, 1000)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._set_session_panels_collapsed(False, animate=False)

    assert dungeon_widget._required_session_overlay_lift() == 0


def test_overlay_lift_moves_zoom_and_tool_panel_when_needed(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget.resize(900, 420)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._set_session_panels_collapsed(True, animate=False)
    dungeon_widget._position_session_overlay()
    tool_collapsed_y = dungeon_widget.tool_panel.y()
    zoom_collapsed_y = dungeon_widget._br_hud.y()

    dungeon_widget._set_session_panels_collapsed(False, animate=False)
    dungeon_widget._position_session_overlay()
    required_lift = dungeon_widget._required_session_overlay_lift()

    assert required_lift > 0
    assert dungeon_widget.tool_panel.y() < tool_collapsed_y
    assert dungeon_widget._br_hud.y() < zoom_collapsed_y


def test_overlay_lift_moves_inspector_only_when_zoom_nearly_hits(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget.resize(1000, 1100)

    entity = EntityItem(QPointF(10, 10))
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget.inspector.set_entity(entity)
    assert dungeon_widget.inspector.isVisible()

    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._set_session_panels_collapsed(True, animate=False)
    dungeon_widget._position_session_overlay()
    inspector_collapsed_y = dungeon_widget.inspector.y()

    dungeon_widget._set_session_panels_collapsed(False, animate=False)
    dungeon_widget._position_session_overlay()

    assert dungeon_widget._required_session_overlay_lift() > 0
    inspector_bottom = inspector_collapsed_y + dungeon_widget.inspector.height()
    required_for_inspector = dungeon_widget._required_overlay_lift_for_bottom(inspector_bottom, padding=8)
    if required_for_inspector > 0:
        assert dungeon_widget.inspector.y() < inspector_collapsed_y
    else:
        assert dungeon_widget.inspector.y() == inspector_collapsed_y


def test_overlay_lift_keeps_inspector_in_place_if_move_would_hit_top_bound(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget.resize(640, 280)

    entity = EntityItem(QPointF(10, 10))
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget.inspector.set_entity(entity)
    assert dungeon_widget.inspector.isVisible()

    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._set_session_panels_collapsed(True, animate=False)
    dungeon_widget._position_session_overlay()
    inspector_collapsed_y = dungeon_widget.inspector.y()

    dungeon_widget._set_session_panels_collapsed(False, animate=False)
    dungeon_widget._position_session_overlay()

    assert dungeon_widget._required_session_overlay_lift() > 0
    assert dungeon_widget.inspector.y() <= inspector_collapsed_y
    assert dungeon_widget.inspector.y() >= 8


def test_inspector_overlay_rule_reapplies_after_resize(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget.resize(640, 280)

    entity = EntityItem(QPointF(10, 10))
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget.inspector.set_entity(entity)
    assert dungeon_widget.inspector.isVisible()

    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._set_session_panels_collapsed(False, animate=False)
    dungeon_widget._position_session_overlay()
    stuck_y = dungeon_widget.inspector.y()

    dungeon_widget.resize(1000, 1100)
    qtbot.wait(20)
    dungeon_widget._set_session_panels_collapsed(True, animate=False)
    collapsed_large_y = dungeon_widget.inspector.y()
    dungeon_widget._set_session_panels_collapsed(False, animate=False)
    expanded_large_y = dungeon_widget.inspector.y()
    inspector_h = max(
        int(dungeon_widget.inspector.minimumSizeHint().height()),
        int(dungeon_widget.inspector.sizeHint().height()),
    )
    inspector_base_y = int((dungeon_widget.height() - inspector_h) / 2)
    required_for_inspector = dungeon_widget._required_overlay_lift_for_bottom(
        inspector_base_y + inspector_h,
        padding=8,
    )
    expected_expanded_y = max(8, inspector_base_y - required_for_inspector)

    assert expanded_large_y != stuck_y
    assert expanded_large_y == expected_expanded_y


def test_player_mode_hides_disallowed_toolbar_buttons_and_shrinks(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_LOCAL_DM)
    dungeon_widget._apply_online_permissions()
    full_height = dungeon_widget.tool_panel.sizeHint().height()

    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._apply_online_permissions()

    rectangle_btn = dungeon_widget.tool_panel.button_for_tool(ToolType.RECTANGLE)
    free_draw_btn = dungeon_widget.tool_panel.button_for_tool(ToolType.FREE_DRAW)
    eraser_btn = dungeon_widget.tool_panel.button_for_tool(ToolType.ERASER)
    ping_btn = dungeon_widget.tool_panel.button_for_tool(ToolType.PING)
    assert rectangle_btn is not None and rectangle_btn.isHidden()
    assert free_draw_btn is not None and not free_draw_btn.isHidden()
    assert eraser_btn is not None and not eraser_btn.isHidden()
    assert ping_btn is not None and not ping_btn.isHidden()
    assert dungeon_widget.tool_panel.btn_fill_fog.isHidden()
    assert dungeon_widget.tool_panel.sizeHint().height() < full_height


def test_dm_host_toolbar_keeps_fog_buttons_and_shows_loot_tools(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._apply_online_permissions()

    assert not dungeon_widget.tool_panel.btn_fill_fog.isHidden()
    assert not dungeon_widget.tool_panel.btn_clear_fog.isHidden()
    assert not dungeon_widget.tool_panel.btn_loot_panel.isHidden()
    assert not dungeon_widget.tool_panel.btn_loot_add_items.isHidden()


def test_player_mode_shows_only_loot_panel_tool(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._apply_online_permissions()

    assert not dungeon_widget.tool_panel.btn_loot_panel.isHidden()
    assert dungeon_widget.tool_panel.btn_loot_add_items.isHidden()


def test_player_mode_places_loot_add_tool_directly_under_loot_pool_when_enabled(dungeon_widget):
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._player_connection_ready = True
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._apply_online_permissions()

    pool_btn = dungeon_widget.tool_panel.btn_loot_panel
    add_btn = dungeon_widget.tool_panel.btn_loot_add_items
    assert not pool_btn.isHidden()
    assert not dungeon_widget.tool_panel.btn_loot_add_items.isHidden()
    assert add_btn.x() == pool_btn.x()
    assert add_btn.y() > pool_btn.y()


def test_player_mode_hides_and_disables_top_selection_ui(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)

    assert dungeon_widget.selection_widget.isHidden()
    assert not dungeon_widget.selection_widget.isEnabled()
    assert dungeon_widget.selection_widget.text_container.isHidden()
    assert not dungeon_widget.selection_widget.text_container.isEnabled()
    assert dungeon_widget.selection_widget.carousel_container.isHidden()
    assert not dungeon_widget.selection_widget.carousel_container.isEnabled()
    assert dungeon_widget._dungeon_list.isHidden()
    assert not dungeon_widget._dungeon_list.isEnabled()

    dungeon_widget._set_online_mode(ONLINE_MODE_LOCAL_DM)
    assert not dungeon_widget.selection_widget.isHidden()
    assert dungeon_widget.selection_widget.isEnabled()
    assert not dungeon_widget.selection_widget.text_container.isHidden()
    assert dungeon_widget.selection_widget.text_container.isEnabled()
    assert not dungeon_widget._dungeon_list.isHidden()
    dungeon_widget.selection_widget.setExpandProgress(1.0)
    assert dungeon_widget.selection_widget.carousel_container.isEnabled()
    assert dungeon_widget._dungeon_list.isEnabled()


def test_player_owned_entity_stats_visibility_tracks_assignment(dungeon_widget):
    owned = EntityItem(QPointF(0, 0))
    owned.setData(ROLE_OWNER_PLAYER_ID, "player-local")
    unowned = EntityItem(QPointF(80, 0))
    unowned.setData(ROLE_OWNER_PLAYER_ID, "other-player")
    dungeon_widget.canvas.scene().addItem(owned)
    dungeon_widget.canvas.scene().addItem(unowned)

    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._apply_online_permissions()
    assert owned.player_stats_visible is True
    assert unowned.player_stats_visible is False

    owned.setData(ROLE_OWNER_PLAYER_ID, "")
    dungeon_widget._apply_online_permissions()
    assert owned.player_stats_visible is False

    unowned.setData(ROLE_OWNER_PLAYER_ID, "player-local")
    dungeon_widget._apply_online_permissions()
    assert unowned.player_stats_visible is True


def test_player_disconnect_disables_owned_entity_interactions(dungeon_widget):
    from online_session.controllers import ClientSessionController

    entity = EntityItem(QPointF(0, 0))
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-local")
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget._client_controller = ClientSessionController(dungeon_widget)
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._player_connection_ready = True
    dungeon_widget._apply_online_permissions()
    assert entity.flags() & entity.GraphicsItemFlag.ItemIsSelectable
    assert entity.flags() & entity.GraphicsItemFlag.ItemIsMovable
    assert dungeon_widget._loot_claim_btn.isEnabled()

    dungeon_widget._on_client_disconnected()

    assert not (entity.flags() & entity.GraphicsItemFlag.ItemIsSelectable)
    assert not (entity.flags() & entity.GraphicsItemFlag.ItemIsMovable)
    assert entity.player_stats_visible is False
    assert not dungeon_widget._loot_claim_btn.isEnabled()


def test_select_state_snaps_entities_to_cell_centers(dungeon_widget):
    entity = EntityItem(QPointF(13.0, 27.0))
    dungeon_widget.canvas.scene().addItem(entity)
    entity.setSelected(True)

    select_state = dungeon_widget.canvas._states[ToolType.SELECT]
    select_state.is_dragging = True
    select_state.drag_start_positions = {entity: QPointF(0.0, 0.0)}

    class _MouseReleaseEvent:
        def button(self):
            return Qt.MouseButton.LeftButton

        def modifiers(self):
            return Qt.KeyboardModifier.NoModifier

        def accept(self):
            return None

    select_state.mouseReleaseEvent(_MouseReleaseEvent(), QPointF(0.0, 0.0))

    grid = float(dungeon_widget.canvas.grid_size)
    half = grid / 2.0
    pos = entity.pos()
    assert math.isclose((pos.x() - half) % grid, 0.0, abs_tol=1e-6)
    assert math.isclose((pos.y() - half) % grid, 0.0, abs_tol=1e-6)


def test_select_state_tracks_movable_parent_for_non_movable_child_click(dungeon_widget, monkeypatch):
    from dungeon_items import RoomGroup

    room = RoomGroup()
    room.add_floor(QRectF(0.0, 0.0, 80.0, 80.0))
    dungeon_widget.canvas.scene().addItem(room)
    child = room.childItems()[0]
    assert not (child.flags() & child.GraphicsItemFlag.ItemIsMovable)

    monkeypatch.setattr(dungeon_widget.canvas.scene(), "itemAt", lambda *_args, **_kwargs: child)
    select_state = dungeon_widget.canvas._states[ToolType.SELECT]

    class _MousePressEvent:
        def button(self):
            return Qt.MouseButton.LeftButton

        def modifiers(self):
            return Qt.KeyboardModifier.NoModifier

        def accept(self):
            return None

    select_state.mousePressEvent(_MousePressEvent(), QPointF(40.0, 40.0))

    assert room in select_state.drag_start_positions
    assert child not in select_state.drag_start_positions


def test_host_scene_change_debounce_broadcasts_without_undo_push(dungeon_widget, qtbot, monkeypatch):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)

    calls: list[str] = []
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: calls.append("sent"))

    entity = EntityItem(QPointF(10.0, 10.0))
    dungeon_widget.canvas.scene().addItem(entity)
    QApplication.processEvents()
    qtbot.wait(220)
    calls.clear()

    undo_index_before = dungeon_widget.canvas.undo_stack.index()
    entity.setPos(QPointF(160.0, 180.0))
    QApplication.processEvents()
    qtbot.wait(560)

    assert dungeon_widget.canvas.undo_stack.index() == undo_index_before
    assert calls


def test_switching_back_to_local_mode_hides_online_panels(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._set_online_mode(ONLINE_MODE_LOCAL_DM)

    assert dungeon_widget._session_toggle_btn.isHidden()
    assert dungeon_widget._session_bottom_panel.isHidden()
    assert dungeon_widget._session_bottom_panel.height() == 0


def test_loot_pool_panel_opens_centered(dungeon_widget, qtbot):
    dungeon_widget.resize(1280, 800)
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)

    dungeon_widget._toggle_loot_pool_panel()
    assert dungeon_widget._loot_pool_panel.isVisible()
    panel_geom = dungeon_widget._loot_pool_panel.geometry()
    panel_center = panel_geom.center()
    assert abs(panel_center.x() - (dungeon_widget.width() // 2)) <= 4
    assert abs(panel_center.y() - (dungeon_widget.height() // 2)) <= 4


def test_loot_pool_has_collapse_button_and_larger_default_size(dungeon_widget, qtbot):
    dungeon_widget.resize(1280, 800)
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._toggle_loot_pool_panel()
    qtbot.wait(220)
    assert not dungeon_widget._loot_pool_panel.isHidden()
    assert dungeon_widget._loot_pool_panel.width() >= 364
    assert dungeon_widget._loot_pool_panel.height() >= 380
    assert dungeon_widget._loot_pool_collapse_btn.text() == "Collapse"
    dungeon_widget._loot_pool_collapse_btn.click()
    qtbot.wait(220)
    assert dungeon_widget._loot_pool_panel.isHidden()


def test_initiative_overlay_opens_centered_and_larger(dungeon_widget, qtbot):
    dungeon_widget.resize(1280, 800)
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {},
        "entity_entries": {},
    }

    dungeon_widget._show_initiative_overlay()
    qtbot.wait(220)
    assert not dungeon_widget._initiative_overlay.isHidden()
    panel_geom = dungeon_widget._initiative_overlay.geometry()
    panel_center = panel_geom.center()
    assert abs(panel_center.x() - (dungeon_widget.width() // 2)) <= 4
    assert abs(panel_center.y() - (dungeon_widget.height() // 2)) <= 4
    assert panel_geom.width() >= 399
    assert panel_geom.height() >= 290


def test_show_initiative_overlay_when_visible_recenters_without_reopen_animation(dungeon_widget, qtbot):
    dungeon_widget.resize(1280, 800)
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {},
        "entity_entries": {},
    }
    dungeon_widget._initiative_overlay.setGeometry(20, 40, 320, 220)
    dungeon_widget._initiative_overlay.show()

    dungeon_widget._show_initiative_overlay()

    assert dungeon_widget._initiative_overlay.geometry() == dungeon_widget._target_initiative_geometry()


def test_position_overlays_preserves_inspector_minimum_height(dungeon_widget, qtbot):
    dungeon_widget.resize(1280, 800)
    dungeon_widget.show()
    qtbot.wait(20)
    entity = EntityItem(QPointF(10, 10))
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget.inspector.set_entity(entity)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._position_floating_overlays()

    assert dungeon_widget.inspector.height() >= dungeon_widget.inspector.minimumSizeHint().height()


def test_online_loot_toolbar_buttons_use_bottom_two_column_layout(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)

    dm_pool_item = dungeon_widget.tool_panel.layout.itemAtPosition(8, 0)
    dm_add_item = dungeon_widget.tool_panel.layout.itemAtPosition(8, 1)
    assert dm_pool_item is not None
    assert dm_pool_item.widget() is dungeon_widget.tool_panel.btn_loot_panel
    assert dm_add_item is not None
    assert dm_add_item.widget() is dungeon_widget.tool_panel.btn_loot_add_items
    assert dungeon_widget.tool_panel.layout.itemAtPosition(4, 2) is None
    assert dungeon_widget.tool_panel.layout.itemAtPosition(5, 2) is None

    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    assert not dungeon_widget.tool_panel.btn_loot_panel.isHidden()
    assert dungeon_widget.tool_panel.btn_loot_add_items.isHidden()


def test_loot_add_items_routes_by_picker_source(dungeon_widget, monkeypatch):
    calls = []
    monkeypatch.setattr(dungeon_widget, "_choose_loot_add_source", lambda: "library")
    monkeypatch.setattr(dungeon_widget, "_on_loot_add_from_library", lambda: calls.append("library"))
    dungeon_widget._on_loot_add_items()
    assert calls == ["library"]

    calls.clear()
    monkeypatch.setattr(dungeon_widget, "_choose_loot_add_source", lambda: "tables")
    monkeypatch.setattr(dungeon_widget, "_on_loot_import_saved_results", lambda: calls.append("tables"))
    dungeon_widget._on_loot_add_items()
    assert calls == ["tables"]


def test_loot_add_items_routes_to_player_inventory_in_player_mode(dungeon_widget, monkeypatch):
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    calls = []
    monkeypatch.setattr(dungeon_widget, "_on_loot_add_from_player_inventory", lambda: calls.append("inventory"))
    dungeon_widget._on_loot_add_items()
    assert calls == ["inventory"]
    assert "Backpack + Equipment" in dungeon_widget.tool_panel.btn_loot_add_items.toolTip()
    assert "Backpack + Equipment" in dungeon_widget._loot_add_btn.toolTip()


def test_loot_add_source_picker_uses_combined_player_inventory_label(dungeon_widget, monkeypatch):
    captured_texts: list[str] = []

    def _fake_exec(dialog):
        for button in dialog.findChildren(QPushButton):
            captured_texts.append(str(button.text()))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", _fake_exec)
    selected = dungeon_widget._choose_loot_add_source()
    assert selected is None
    assert "Player Backpack + Equipment" in captured_texts


def test_inventory_loot_picker_shows_icons_for_backpack_and_equipment(dungeon_widget, monkeypatch):
    icon = QPixmap(6, 6)
    icon.fill(QColor("#ffffff"))
    monkeypatch.setattr(dungeon_widget, "_loot_pool_icon_for_entry", lambda _entry: QPixmap(icon))

    icon_null_states: list[bool] = []

    def _fake_exec(dialog):
        list_widget = dialog.findChild(QListWidget)
        assert list_widget is not None
        for idx in range(list_widget.count()):
            icon_null_states.append(list_widget.item(idx).icon().isNull())
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", _fake_exec)
    rows = [
        {
            "source_type": "backpack",
            "source_index": 0,
            "item_id": "item_a",
            "title": "Backpack Item",
            "path": "item_a.dmtitem",
            "item_document": {"item_id": "item_a", "title": "Backpack Item"},
            "label": "Backpack Item - Backpack",
        },
        {
            "source_type": "equipment",
            "source_slot": "head",
            "item_id": "item_b",
            "title": "Head Item",
            "path": "item_b.dmtitem",
            "item_document": {"item_id": "item_b", "title": "Head Item"},
            "label": "Head Item - Equipment: Head",
        },
    ]
    selected = dungeon_widget._choose_inventory_rows_for_loot(sheet_name="Hero", rows=rows)
    assert selected is None
    assert icon_null_states == [False, False]


def test_inventory_loot_rows_include_equipment_slots(monkeypatch, dungeon_widget):
    fake_module = types.SimpleNamespace(
        inventory_payload_for_sheet_id=lambda _sheet_id: {
            "inventory": ["backpack_item"],
            "equipment": {"head": "equipped_item"},
            "inventory_notes": "",
            "gold": 0,
            "silver": 0,
            "copper": 0,
        },
        EQUIPMENT_SLOT_LABELS={"head": "Head"},
        loot_item_path_for_id=lambda _item_id: None,
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)

    rows = dungeon_widget._inventory_loot_rows_for_sheet("sheet-1")

    source_types = {str(row.get("source_type") or "") for row in rows}
    assert "backpack" in source_types
    assert "equipment" in source_types
    equipment_rows = [row for row in rows if str(row.get("source_type") or "") == "equipment"]
    assert equipment_rows
    assert equipment_rows[0]["source_slot"] == "head"
    assert "Equipment: Head" in str(equipment_rows[0].get("label") or "")


def test_player_loot_add_from_inventory_sends_source_metadata(dungeon_widget, monkeypatch):
    class _ClientStub:
        def __init__(self):
            self.calls = []

        def send_command(self, action, payload, request_id=None):
            self.calls.append((action, payload, request_id))

        def disconnect(self):
            return None

    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._player_connection_ready = True
    monkeypatch.setattr(dungeon_widget, "_choose_sheet_for_claim", lambda: ("sheet-1", "Hero"))
    monkeypatch.setattr(
        dungeon_widget,
        "_inventory_loot_rows_for_sheet",
        lambda _sheet_id: [
            {"item_id": "item_a", "title": "Backpack Item", "source_type": "backpack", "source_index": 2},
            {"item_id": "item_b", "title": "Head Item", "source_type": "equipment", "source_slot": "head"},
        ],
    )
    monkeypatch.setattr(
        dungeon_widget,
        "_choose_inventory_rows_for_loot",
        lambda **_kwargs: [
            {"item_id": "item_a", "title": "Backpack Item", "source_type": "backpack", "source_index": 2},
            {"item_id": "item_b", "title": "Head Item", "source_type": "equipment", "source_slot": "head"},
        ],
    )

    dungeon_widget._on_loot_add_from_player_inventory()

    assert dungeon_widget._client_controller.calls
    action, payload, request_id = dungeon_widget._client_controller.calls[-1]
    assert action == "add_loot_from_inventory"
    assert payload["sheet_id"] == "sheet-1"
    sent_items = payload["items"]
    assert sent_items[0]["source"] == "backpack"
    assert sent_items[0]["source_index"] == 2
    assert sent_items[1]["source"] == "equipment"
    assert sent_items[1]["source_slot"] == "head"
    assert isinstance(request_id, str) and request_id


def test_local_loot_claim_runs_through_local_action_path(dungeon_widget, monkeypatch):
    captured = {}
    dungeon_widget._online_mode = ONLINE_MODE_LOCAL_DM
    dungeon_widget._session_loot_pool = [
        {"entry_id": "loot-1", "type": "item", "item_id": "item-a", "title": "Potion"},
        {"entry_id": "loot-2", "type": "note", "note": "Keep", "title": "Keep"},
    ]
    monkeypatch.setattr(dungeon_widget, "_selected_loot_pool_ids", lambda: ["loot-1"])
    monkeypatch.setattr(dungeon_widget, "_choose_sheet_for_claim", lambda: ("sheet-1", "Hero"))

    def _apply_claim(sheet_id, claimed_entries):
        captured["sheet_id"] = sheet_id
        captured["claimed_entries"] = [dict(entry) for entry in claimed_entries]
        return True, "Claim applied."

    monkeypatch.setattr(dungeon_widget, "_apply_claim_entries_to_sheet", _apply_claim)

    dungeon_widget._on_loot_claim_selected()

    assert captured["sheet_id"] == "sheet-1"
    assert [entry["entry_id"] for entry in captured["claimed_entries"]] == ["loot-1"]
    assert [entry["entry_id"] for entry in dungeon_widget._session_loot_pool] == ["loot-2"]


def test_apply_claim_entries_to_sheet_uses_canonical_item_ids(dungeon_widget, monkeypatch, tmp_path):
    items_root = tmp_path / "items"
    source_dir = tmp_path / "remote"
    items_root.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / "claimed_sword.dmtitem"

    document = build_item_document(
        {
            "title": "Claimed Sword",
            "rarity": "common",
            "level": 1,
        },
        "",
    )
    write_item_document(source_path, document)
    payload = document["payload"]
    assert isinstance(payload, dict)
    item_id = str(payload["item_id"])

    captured = {}

    def _apply_claim_to_sheet(sheet_id, *, item_ids, note_lines):
        captured["sheet_id"] = sheet_id
        captured["item_ids"] = list(item_ids)
        captured["note_lines"] = list(note_lines)
        return True, "Claim applied.", {}

    monkeypatch.setattr("dungeon_applet.items_dir", lambda: items_root)
    monkeypatch.setitem(sys.modules, "player_sheets", types.SimpleNamespace(apply_claim_to_sheet=_apply_claim_to_sheet))

    ok, message = dungeon_widget._apply_claim_entries_to_sheet(
        "sheet-1",
        [
            {
                "entry_id": "loot-1",
                "type": "item",
                "item_id": item_id,
                "title": "Claimed Sword",
                "path": str(source_path),
                "item_document": document,
            }
        ],
    )

    assert ok is True
    assert message == "Claim applied."
    assert captured["sheet_id"] == "sheet-1"
    assert captured["item_ids"] == [item_id]
    persisted_files = list(items_root.glob("*.dmtitem"))
    assert len(persisted_files) == 1
    persisted_payload = load_item_payload(persisted_files[0])
    assert isinstance(persisted_payload, dict)
    assert persisted_payload["item_id"] == item_id


def test_apply_claim_entries_to_sheet_requires_overwrite_confirmation_for_same_item_id(
    dungeon_widget, monkeypatch, tmp_path
):
    items_root = tmp_path / "items"
    source_dir = tmp_path / "remote"
    items_root.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)

    existing_document = build_item_document(
        {
            "title": "Shared Sword",
            "rarity": "common",
            "level": 1,
        },
        "",
    )
    incoming_document = build_item_document(
        {
            "title": "Shared Sword",
            "rarity": "rare",
            "level": 2,
        },
        "",
    )
    existing_path = items_root / "old_sword.dmtitem"
    source_path = source_dir / "new_sword.dmtitem"
    write_item_document(existing_path, existing_document)
    write_item_document(source_path, incoming_document)

    apply_calls = {"count": 0}

    def _apply_claim_to_sheet(*args, **kwargs):
        apply_calls["count"] += 1
        return True, "Claim applied.", {}

    monkeypatch.setattr("dungeon_applet.items_dir", lambda: items_root)
    monkeypatch.setattr(
        dungeon_widget,
        "_confirm_claimed_item_overwrite",
        lambda **_kwargs: False,
    )
    monkeypatch.setitem(sys.modules, "player_sheets", types.SimpleNamespace(apply_claim_to_sheet=_apply_claim_to_sheet))

    ok, message = dungeon_widget._apply_claim_entries_to_sheet(
        "sheet-1",
        [
            {
                "entry_id": "loot-1",
                "type": "item",
                "item_id": str(incoming_document["payload"]["item_id"]),
                "title": "Shared Sword",
                "path": str(source_path),
                "item_document": incoming_document,
            }
        ],
    )

    assert ok is False
    assert "overwrite" in message.lower() or "cancelled" in message.lower()
    assert apply_calls["count"] == 0
    persisted_payload = load_item_payload(existing_path)
    assert isinstance(persisted_payload, dict)
    assert persisted_payload["title"] == "Shared Sword"
    assert persisted_payload["rarity"] == "common"


def test_loot_add_from_library_dialog_contract_and_selection(monkeypatch, dungeon_widget, tmp_path):
    chosen_path = tmp_path / "sword.dmtitem"
    write_item_document(
        chosen_path,
        build_item_document(
            {
                "item_id": "item-sword",
                "title": "Sword",
                "rarity": "common",
                "level": 1,
            },
            "",
        ),
    )
    selected_item = types.SimpleNamespace(
        item_id="item-sword",
        title="Sword",
        path=str(chosen_path),
    )
    init_calls = []

    class _Dialog:
        def __init__(self, items, icon_provider, preview_provider, parent=None):
            init_calls.append((items, icon_provider, preview_provider, parent))
            self.selected_item_id = "item-sword"

        def exec(self):
            return QDialog.DialogCode.Accepted

    fake_module = types.SimpleNamespace(
        InventoryItemPickerDialog=_Dialog,
        _inventory_icon_pixmap=lambda _item: None,
        _render_item_preview_pixmap=lambda *_args, **_kwargs: None,
        _load_loot_item_library=lambda: ([selected_item], {"item-sword": selected_item}),
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)

    dungeon_widget._session_loot_pool = []
    dungeon_widget._on_loot_add_from_library()

    assert len(init_calls) == 1
    _items, icon_provider, preview_provider, parent = init_calls[0]
    assert callable(icon_provider)
    assert callable(preview_provider)
    assert parent is dungeon_widget
    assert len(dungeon_widget._session_loot_pool) == 1
    row = dungeon_widget._session_loot_pool[0]
    assert row["item_id"] == "item-sword"
    assert row["title"] == "Sword"
    assert Path(row["path"]) == chosen_path
    assert isinstance(row.get("item_document"), dict)


def test_loot_add_from_library_ignores_missing_selected_item(monkeypatch, dungeon_widget):
    ghost_item = types.SimpleNamespace(item_id="ghost", title="Ghost", path="ghost.dmtitem")

    class _Dialog:
        def __init__(self, items, icon_provider, preview_provider, parent=None):
            self.selected_item_id = "missing-id"

        def exec(self):
            return QDialog.DialogCode.Accepted

    fake_module = types.SimpleNamespace(
        InventoryItemPickerDialog=_Dialog,
        _inventory_icon_pixmap=lambda _item: None,
        _render_item_preview_pixmap=lambda *_args, **_kwargs: None,
        _load_loot_item_library=lambda: ([ghost_item], {"ghost": ghost_item}),
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)

    dungeon_widget._session_loot_pool = []
    dungeon_widget._on_loot_add_from_library()
    assert dungeon_widget._session_loot_pool == []


def test_loot_pool_resolve_item_path_supports_absolute_item_id_path(dungeon_widget, tmp_path):
    item_path = tmp_path / "abs_item.dmtitem"
    write_item_document(
        item_path,
        build_item_document(
            {
                "item_id": "abs-item",
                "title": "Absolute Item",
                "rarity": "common",
                "level": 1,
            },
            "",
        ),
    )
    resolved = dungeon_widget._loot_pool_resolve_item_path({"item_id": str(item_path)})
    assert resolved == item_path


def test_loot_pool_resolve_item_path_materializes_item_document(dungeon_widget, tmp_path):
    icon_path = tmp_path / "blade.png"
    icon_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc``\xf8\xff\xff?\x00\x05\xfe\x02\xfe"
        b"\xa7\xd6\x9f\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    payload = {
        "item_id": "blade-item",
        "title": "Blade",
        "rarity": "common",
        "level": 1,
        "icon_path": str(icon_path),
    }
    entry = {
        "entry_id": "loot-doc-1",
        "type": "item",
        "item_id": "blade-item",
        "title": "Blade",
        "path": "",
        "item_document": build_item_document(payload, str(icon_path)),
    }

    resolved = dungeon_widget._loot_pool_resolve_item_path(entry)
    assert resolved is not None
    assert resolved.exists()
    assert resolved.suffix == ".dmtitem"

    loaded = load_item_payload(resolved)
    assert isinstance(loaded, dict)
    assert loaded.get("title") == "Blade"
    assert str(loaded.get("icon_path") or "").strip()


def test_host_start_failure_reverts_to_local_mode(dungeon_widget, monkeypatch):
    class _HostFailStub:
        def __init__(self):
            self.players = {}
            self.stopped = False

        def stop(self):
            self.stopped = True

        def start(self, _port):
            return False, "port busy"

    host_stub = _HostFailStub()
    errors = []
    dungeon_widget._host_controller = host_stub

    monkeypatch.setattr(
        "dungeon_applet.QMessageBox.critical",
        lambda *args, **kwargs: errors.append((args, kwargs)),
    )

    started = dungeon_widget.start_online_host(8765)

    assert started is False
    assert host_stub.stopped is True
    assert errors
    assert dungeon_widget._online_mode == ONLINE_MODE_LOCAL_DM


def test_starting_host_disconnects_existing_client_controller(dungeon_widget, monkeypatch):
    class _HostOkStub:
        def __init__(self):
            self.players = {}
            self.stopped = False
            self.started_port = None

        def stop(self):
            self.stopped = True

        def start(self, port):
            self.started_port = port
            return True, ""

    class _ClientStub:
        def __init__(self):
            self.disconnected = False

        def disconnect(self):
            self.disconnected = True

    host_stub = _HostOkStub()
    client_stub = _ClientStub()
    dungeon_widget._host_controller = host_stub
    dungeon_widget._client_controller = client_stub
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: None)

    started = dungeon_widget.start_online_host(8765)

    assert started is True
    assert host_stub.started_port == 8765
    assert client_stub.disconnected is True


def test_joining_player_session_stops_existing_host_controller(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True

    class _ClientStub:
        def __init__(self):
            self.disconnected = False
            self.connect_args = None

        def disconnect(self):
            self.disconnected = True

        def connect_to_host(self, host, port, name, persistent_player_id=None):
            self.connect_args = (host, port, name, persistent_player_id)

    host_stub = _HostStub()
    client_stub = _ClientStub()
    dungeon_widget._host_controller = host_stub
    dungeon_widget._client_controller = client_stub

    dungeon_widget.join_online_session("192.168.1.10", 8765, "Mira")

    assert host_stub.stopped is True
    assert client_stub.disconnected is True
    assert client_stub.connect_args == (
        "192.168.1.10",
        8765,
        "Mira",
        dungeon_widget._persistent_local_player_id,
    )


def test_clear_online_runtime_cache_uses_shared_runtime_cleanup(dungeon_widget, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dungeon_applet.clear_online_runtime_storage",
        lambda session_id: calls.append(session_id),
    )
    dungeon_widget._online_session_id = "session-cleanup"
    dungeon_widget._clear_online_runtime_cache()
    assert calls == ["session-cleanup"]


def test_client_icon_asset_does_not_escape_icon_cache(dungeon_widget, monkeypatch, tmp_path):
    cache_dir = tmp_path / "session" / "cache" / "icons"
    monkeypatch.setattr("dungeon_applet.online_icon_cache_dir", lambda _sid: cache_dir)
    dungeon_widget._online_session_id = "session-1"

    dungeon_widget._on_client_icon_asset(
        "missing-entity",
        "../escaped.png",
        base64.b64encode(b"png").decode("ascii"),
    )

    escaped_target = cache_dir.parent / "escaped.png"
    assert not escaped_target.exists()


def test_local_ping_is_forwarded_by_mode(dungeon_widget):
    host_calls = []
    player_calls = []

    class _HostStub:
        def broadcast_ping(self, **kwargs):
            host_calls.append(kwargs)

        def stop(self):
            return None

    class _ClientStub:
        def send_command(self, action, payload, request_id=None):
            player_calls.append((action, payload, request_id))

        def disconnect(self):
            return None

    dungeon_widget._active_dungeon_id = "dungeon-1"
    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._on_local_ping_placed(QPointF(5.0, 6.0))
    assert host_calls and host_calls[0]["dungeon_id"] == "dungeon-1"

    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._on_local_ping_placed(QPointF(7.0, 8.0))
    assert player_calls
    action, payload, request_id = player_calls[0]
    assert action == "ping"
    assert payload["dungeon_id"] == "dungeon-1"
    assert isinstance(request_id, str) and request_id


def test_player_upload_icon_resolves_owner_from_target_dungeon_and_broadcasts(dungeon_widget, monkeypatch, tmp_path):
    cache_dir = tmp_path / "session" / "cache" / "icons"
    monkeypatch.setattr("dungeon_applet.online_icon_cache_dir", lambda _sid: cache_dir)
    dungeon_widget._online_session_id = "session-2"

    class _HostStub:
        def __init__(self):
            self.results = []
            self.assets = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_icon_asset(self, **kwargs):
            self.assets.append(kwargs)

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

        def stop(self):
            return None

    host_stub = _HostStub()
    dungeon_widget._host_controller = host_stub
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST

    dm = dungeon_widget._create_dungeon_entry("DM")
    players = dungeon_widget._create_dungeon_entry(
        "Players",
        state={
            "items": [
                {
                    "type": "entity",
                    "entity_id": "entity-players-1",
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

    payload = {
        "entity_id": "entity-players-1",
        "filename": "token.png",
        "content_b64": base64.b64encode(b"png-bytes").decode("ascii"),
        "owner_player_id": "player-1",
        "dungeon_id": players["id"],
    }
    dungeon_widget._handle_uploaded_icon("player-1", payload, request_id="req-1")

    assert host_stub.results
    result = host_stub.results[-1][1]
    assert result["ok"] is True
    assert host_stub.assets
    assert host_stub.assets[-1]["entity_id"] == "entity-players-1"
    updated_state = players["state"]["items"][0]
    assert str(updated_state.get("icon_path", "")).startswith(SESSION_ICON_PREFIX)
    assert cache_dir.exists()


def test_dm_host_local_icon_is_normalized_and_broadcast(dungeon_widget, monkeypatch, tmp_path):
    cache_dir = tmp_path / "session" / "cache" / "icons"
    monkeypatch.setattr("dungeon_applet.online_icon_cache_dir", lambda _sid: cache_dir)
    dungeon_widget._online_session_id = "session-3"

    class _HostStub:
        def __init__(self):
            self.assets = []

        def broadcast_icon_asset(self, **kwargs):
            self.assets.append(kwargs)

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST

    local_icon = tmp_path / "dm_icon.png"
    local_icon.write_bytes(_PNG_1X1_BYTES)

    entity = EntityItem(QPointF(10, 10), icon_path=str(local_icon))
    entity.setData(ROLE_ENTITY_ID, "dm-entity-1")
    entity.setData(ROLE_ICON, str(local_icon))
    dungeon_widget.canvas.scene().addItem(entity)

    dungeon_widget._sync_host_scene_icons_for_online()
    assert dungeon_widget._host_controller.assets
    first_asset = dungeon_widget._host_controller.assets[0]
    assert first_asset["entity_id"] == "dm-entity-1"
    assert str(entity.data(ROLE_ICON) or "").startswith(SESSION_ICON_PREFIX)

    dungeon_widget._sync_host_scene_icons_for_online()
    assert len(dungeon_widget._host_controller.assets) == 1


def test_player_icon_upload_payload_includes_active_dungeon_id(dungeon_widget, monkeypatch, tmp_path):
    class _ClientStub:
        def __init__(self):
            self.calls = []

        def send_command(self, action, payload, request_id=None):
            self.calls.append((action, payload, request_id))

        def disconnect(self):
            return None

    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._active_dungeon_id = "players-dungeon-id"

    icon_file = tmp_path / "player_icon.png"
    icon_file.write_bytes(_PNG_1X1_BYTES)

    entity = EntityItem(QPointF(0, 0))
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-local")
    entity.setData(ROLE_ENTITY_ID, "entity-player-local")
    dungeon_widget.inspector._entity = entity

    dungeon_widget._on_deferred_icon_selected(str(icon_file))

    assert dungeon_widget._client_controller.calls
    action, payload, request_id = dungeon_widget._client_controller.calls[-1]
    assert action == "upload_icon"
    assert payload["dungeon_id"] == "players-dungeon-id"
    assert payload["owner_player_id"] == "player-local"
    assert isinstance(request_id, str) and request_id


def test_host_upload_icon_bypasses_generic_pre_authz_and_uses_handler(dungeon_widget, monkeypatch):
    class _HostStub:
        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    calls = []

    def _fake_handle(player_id, payload, request_id=None):
        calls.append((player_id, dict(payload), request_id))

    monkeypatch.setattr(dungeon_widget, "_handle_uploaded_icon", _fake_handle)

    dungeon_widget._on_host_command_received(
        "player-42",
        {
            "action": "upload_icon",
            "payload": {"entity_id": "entity-42", "content_b64": "ZGF0YQ=="},
            "request_id": "req-42",
        },
    )

    assert calls == [("player-42", {"entity_id": "entity-42", "content_b64": "ZGF0YQ=="}, "req-42")]


def test_host_snapshot_requested_sends_icon_assets_for_session_refs(dungeon_widget, monkeypatch, tmp_path):
    cache_dir = tmp_path / "session" / "cache" / "icons"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "token.png").write_bytes(_PNG_1X1_BYTES)
    monkeypatch.setattr("dungeon_applet.online_icon_cache_dir", lambda _sid: cache_dir)
    dungeon_widget._online_session_id = "session-snap"

    class _HostStub:
        def __init__(self):
            self.snapshots = []
            self.assets = []

        def send_snapshot_to(self, player_id, snapshot):
            self.snapshots.append((player_id, snapshot))

        def send_icon_asset(self, player_id, **kwargs):
            self.assets.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    entity = EntityItem(QPointF(0, 0))
    entity.setData(ROLE_ENTITY_ID, "entity-1")
    entity.setData(ROLE_ICON, f"{SESSION_ICON_PREFIX}token.png")
    entity.icon_path = "ignored-local.png"
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-1",
                        "owner_player_id": "player-1",
                        "icon_path": f"{SESSION_ICON_PREFIX}token.png",
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
    dungeon_widget._active_dungeon_id = "d1"
    dungeon_widget._players_dungeon_id = "d1"

    dungeon_widget._on_host_snapshot_requested("player-x")

    assert dungeon_widget._host_controller.snapshots
    assert dungeon_widget._host_controller.assets
    player_id, payload = dungeon_widget._host_controller.assets[0]
    assert player_id == "player-x"
    assert payload["entity_id"] == "entity-1"
    assert payload["filename"] == "token.png"


def test_materialize_state_icons_for_archive_moves_session_refs_to_assets(dungeon_widget, monkeypatch, tmp_path):
    cache_dir = tmp_path / "online" / "cache" / "icons"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "token.png").write_bytes(_PNG_1X1_BYTES)
    monkeypatch.setattr("dungeon_applet.online_icon_cache_dir", lambda _sid: cache_dir)
    dungeon_widget._online_session_id = "session-save"

    state = {
        "items": [
            {
                "type": "entity",
                "entity_id": "entity-2",
                "icon_path": f"{SESSION_ICON_PREFIX}token.png",
                "pos": [0.0, 0.0],
            }
        ],
        "fog": {"path": []},
    }
    assets = {}
    result = dungeon_widget._materialize_state_icons_for_archive(state, assets)

    icon_path = str(result["items"][0]["icon_path"])
    assert icon_path.startswith("assets/icons/")
    assert icon_path.endswith(".png")
    assert icon_path in assets


def test_collection_autosave_writes_sidecar_file_and_clears_dirty(dungeon_widget, tmp_path):
    main_path = tmp_path / "campaign.dmtcollection"
    dungeon_widget._collection_path = main_path
    dungeon_widget._collection_name = "Campaign"
    dungeon_widget._players_dungeon_id = dungeon_widget._active_dungeon_id
    dungeon_widget._autosave_enabled = True
    dungeon_widget._collection_meta_dirty = True
    dungeon_widget._refresh_collection_dirty()

    dungeon_widget._run_collection_autosave()

    autosave_path = tmp_path / "campaign_autosave.dmtcollection"
    assert autosave_path.exists()
    assert dungeon_widget._collection_dirty is False
    payload = read_dmt_package_info(autosave_path)
    assert isinstance(payload, dict)
    assert payload["players_dungeon_id"] == dungeon_widget._players_dungeon_id
    assert "local_player_profile_id" in payload


def test_collection_autosave_timer_uses_fifteen_second_interval(dungeon_widget):
    assert dungeon_widget._collection_autosave_timer.interval() == 15000
    assert not dungeon_widget._collection_autosave_timer.isSingleShot()


def test_collection_autosave_status_label_is_dm_only(dungeon_widget, tmp_path):
    main_path = tmp_path / "campaign.dmtcollection"
    dungeon_widget._collection_path = main_path
    dungeon_widget._collection_name = "Campaign"
    dungeon_widget._players_dungeon_id = dungeon_widget._active_dungeon_id
    dungeon_widget._autosave_enabled = True
    dungeon_widget._collection_meta_dirty = True
    dungeon_widget._refresh_collection_dirty()
    dungeon_widget._set_online_mode(ONLINE_MODE_LOCAL_DM)

    dungeon_widget._run_collection_autosave()

    assert not dungeon_widget._autosave_status_label.isHidden()
    assert dungeon_widget._autosave_status_label.text().startswith("autosaved-")

    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)

    assert dungeon_widget._autosave_status_label.isHidden()


def test_linked_character_fields_round_trip_in_scene_state(dungeon_widget):
    scene = dungeon_widget.canvas.scene()
    entity = EntityItem(QPointF(12, 18))
    entity.setData(ROLE_ENTITY_ID, "linked-entity-1")
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    entity.setData(ROLE_LINKED_SHEET_ID, "sheet-alpha")
    entity.setData(ROLE_LINKED_SHEET_NAME, "Aria")
    entity.setData(ROLE_LINKED_CHARACTER_ID, "character_20260210_abc")
    entity.linked_inventory = {
        "inventory": ["item_1"],
        "inventory_notes": "note",
        "equipment": {"head": "helm_1"},
        "gold": 9,
        "silver": 1,
        "copper": 0,
        "hp": 99,
    }
    scene.addItem(entity)

    state = dungeon_widget._serialize_scene()
    target_scene = QGraphicsScene()
    dungeon_widget._populate_scene(target_scene, state, include_fog=False)
    loaded = [item for item in target_scene.items() if isinstance(item, EntityItem)]
    assert len(loaded) == 1
    loaded_entity = loaded[0]
    assert loaded_entity.data(ROLE_LINKED_SHEET_ID) == "sheet-alpha"
    assert loaded_entity.data(ROLE_LINKED_SHEET_NAME) == "Aria"
    assert loaded_entity.data(ROLE_LINKED_CHARACTER_ID) == "character_20260210_abc"
    assert loaded_entity.linked_inventory["inventory"] == [
        {"item_id": "item_1", "normalized_item_name": "item_1", "quantity": 1}
    ]
    assert loaded_entity.linked_inventory["gold"] == 9
    assert "hp" not in loaded_entity.linked_inventory


def test_host_sync_character_inventory_updates_owned_linked_entities(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._broadcast_snapshot_if_host = lambda: None
    dungeon_widget._active_dungeon_id = "d1"
    dungeon_widget._players_dungeon_id = "d1"
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-sheet-1",
                        "linked_inventory": {},
                        "icon_path": "",
                        "pos": [0.0, 0.0],
                    },
                    {
                        "type": "entity",
                        "entity_id": "e2",
                        "owner_player_id": "player-2",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-sheet-2",
                        "linked_inventory": {},
                        "icon_path": "",
                        "pos": [0.0, 0.0],
                    },
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
            "inventory": {
                "inventory": ["item_x"],
                "inventory_notes": "claimed",
                "equipment": {"head": "helm_a"},
                "gold": 5,
                "hp": 999,
            },
        },
        request_id="sync-1",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is True
    first_item = dungeon_widget._dungeons[0]["state"]["items"][0]
    second_item = dungeon_widget._dungeons[0]["state"]["items"][1]
    assert first_item["linked_inventory"]["inventory"] == [
        {"item_id": "item_x", "normalized_item_name": "item_x", "quantity": 1}
    ]
    assert first_item["linked_inventory"]["gold"] == 5
    assert "hp" not in first_item["linked_inventory"]
    assert second_item["linked_inventory"] == {}
    assert dungeon_widget._dungeons[0]["dirty"] is True


def test_host_sync_character_inventory_persists_authoritative_sheet_state(
    monkeypatch, dungeon_widget
):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

        def stop(self):
            return None

    captured = {}

    def _apply_remote_inventory(character_id, sheet_name, inventory_payload, **kwargs):
        captured["character_id"] = character_id
        captured["sheet_name"] = sheet_name
        captured["inventory_payload"] = dict(inventory_payload)
        captured["kwargs"] = dict(kwargs)
        return (
            True,
            "Inventory synchronized.",
            {
                "inventory": [
                    {
                        "item_id": "item_saved",
                        "normalized_item_name": "item_saved",
                        "quantity": 1,
                    }
                ],
                "inventory_notes": "saved",
                "equipment": {
                    "head": {
                        "item_id": "helm_saved",
                        "normalized_item_name": "helm_saved",
                        "quantity": 1,
                    }
                },
                "gold": 7,
                "silver": 2,
                "copper": 1,
            },
        )

    fake_module = types.SimpleNamespace(
        apply_remote_inventory_payload_for_character_id=_apply_remote_inventory,
        character_id_for_sheet_id=lambda _sheet_id: "character-sheet-1",
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._broadcast_snapshot_if_host = lambda: None
    dungeon_widget._active_dungeon_id = "d1"
    dungeon_widget._players_dungeon_id = "d1"
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-sheet-1",
                        "linked_inventory": {},
                        "icon_path": "",
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
            "inventory": {
                "inventory": ["item_x"],
                "inventory_notes": "claimed",
                "equipment": {"head": "helm_a"},
                "gold": 5,
                "hp": 999,
            },
        },
        request_id="sync-2",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is True
    assert captured["character_id"] == "character-sheet-1"
    assert captured["sheet_name"] == "sheet-1"
    assert captured["inventory_payload"]["inventory"] == [
        {"item_id": "item_x", "normalized_item_name": "item_x", "quantity": 1}
    ]
    assert "hp" not in captured["inventory_payload"]
    assert captured["kwargs"]["emit_event"] is False

    first_item = dungeon_widget._dungeons[0]["state"]["items"][0]
    assert first_item["linked_inventory"]["inventory"] == [
        {"item_id": "item_saved", "normalized_item_name": "item_saved", "quantity": 1}
    ]
    assert first_item["linked_inventory"]["gold"] == 7


def test_host_sync_character_inventory_rejects_unowned_character_target(
    monkeypatch, dungeon_widget
):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

        def stop(self):
            return None

    apply_calls = []

    def _apply_remote_inventory(*args, **kwargs):
        apply_calls.append((args, kwargs))
        return True, "ok", {}

    fake_module = types.SimpleNamespace(
        apply_remote_inventory_payload_for_character_id=_apply_remote_inventory,
        character_id_for_sheet_id=lambda _sheet_id: "",
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._broadcast_snapshot_if_host = lambda: None
    dungeon_widget._active_dungeon_id = "d1"
    dungeon_widget._players_dungeon_id = "d1"
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-owned",
                        "linked_inventory": {},
                        "icon_path": "",
                        "pos": [0.0, 0.0],
                    },
                    {
                        "type": "entity",
                        "entity_id": "e2",
                        "owner_player_id": "player-2",
                        "linked_sheet_id": "sheet-2",
                        "linked_character_id": "character-other",
                        "linked_inventory": {},
                        "icon_path": "",
                        "pos": [0.0, 0.0],
                    },
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
            "sheet_id": "sheet-2",
            "character_id": "character-other",
            "inventory": {"inventory": ["item_x"]},
        },
        request_id="sync-denied",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is False
    assert "not linked to one of your owned entities" in str(result["message"]).lower()
    assert apply_calls == []


def test_host_link_character_sync_allows_claim_for_player_owned_entity(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "label": "Entity",
                        "hp": 10,
                        "max_hp": 10,
                        "ac": 10,
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
    dungeon_widget._session_loot_pool = [
        {"entry_id": "loot-1", "type": "item", "item_id": "item_a", "title": "Item A"}
    ]

    dungeon_widget._handle_host_link_character_entity(
        "player-1",
        {
            "entity_id": "e1",
            "sheet_id": "sheet-1",
            "sheet_name": "test",
            "dungeon_id": "d1",
            "inventory": {"inventory": ["item_a"]},
            "stats": {
                "name": "test",
                "strength": 11,
                "dexterity": 12,
                "constitution": 13,
                "intelligence": 14,
                "wisdom": 15,
                "charisma": 16,
                "ac": 17,
                "hp_max": 23,
                "hp_current": 14,
            },
        },
        request_id="link-1",
    )
    link_result = dungeon_widget._host_controller.results[-1][1]
    assert link_result["ok"] is True
    entity_state = dungeon_widget._dungeons[0]["state"]["items"][0]
    assert entity_state["linked_sheet_id"] == "sheet-1"
    assert entity_state["label"] == "test"
    assert entity_state["ac"] == 17
    assert entity_state["max_hp"] == 23
    assert entity_state["hp"] == 14

    dungeon_widget._handle_host_claim_loot(
        "player-1",
        {"entry_ids": ["loot-1"], "sheet_id": "sheet-1"},
        request_id="claim-1",
    )
    claim_result = dungeon_widget._host_controller.results[-1][1]
    assert claim_result["ok"] is True


def test_host_claim_loot_blocks_when_character_not_linked(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            return None

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-linked",
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
    dungeon_widget._session_loot_pool = [
        {"entry_id": "loot-1", "type": "item", "item_id": "item_a", "title": "Item A"}
    ]
    dungeon_widget._refresh_loot_pool_list()

    dungeon_widget._handle_host_claim_loot(
        "player-1",
        {"entry_ids": ["loot-1"], "sheet_id": "sheet-other"},
        request_id="claim-1",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is False
    assert "not linked" in result["message"]
    assert len(dungeon_widget._session_loot_pool) == 1


def test_host_add_loot_from_inventory_transfers_items_and_syncs_inventory(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_inventory": {
                            "inventory": ["item_a", "item_b"],
                            "inventory_notes": "",
                            "equipment": {},
                            "gold": 0,
                            "silver": 0,
                            "copper": 0,
                        },
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
    dungeon_widget._session_loot_pool = []

    dungeon_widget._handle_host_add_loot_from_inventory(
        "player-1",
        {
            "sheet_id": "sheet-1",
            "items": [
                {
                    "item_id": "item_a",
                    "title": "Item A",
                    "path": "item_a",
                }
            ],
        },
        request_id="add-1",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is True
    assert result["data"]["action"] == "add_loot_from_inventory"
    assert result["data"]["sheet_id"] == "sheet-1"
    assert result["data"]["inventory"]["inventory"] == [
        {"item_id": "item_b", "normalized_item_name": "item_b", "quantity": 1}
    ]
    assert len(dungeon_widget._session_loot_pool) == 1
    assert dungeon_widget._session_loot_pool[0]["item_id"] == "item_a"
    linked_inventory = dungeon_widget._dungeons[0]["state"]["items"][0]["linked_inventory"]
    assert linked_inventory["inventory"] == [
        {"item_id": "item_b", "normalized_item_name": "item_b", "quantity": 1}
    ]
    assert dungeon_widget._host_controller.snapshots


def test_host_add_loot_from_equipment_clears_slot_and_adds_loot_entry(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_inventory": {
                            "inventory": ["item_a"],
                            "inventory_notes": "",
                            "equipment": {"head": "item_b", "neck": None},
                            "gold": 0,
                            "silver": 0,
                            "copper": 0,
                        },
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
    dungeon_widget._session_loot_pool = []

    dungeon_widget._handle_host_add_loot_from_inventory(
        "player-1",
        {
            "sheet_id": "sheet-1",
            "items": [
                {
                    "item_id": "item_b",
                    "title": "Head Item",
                    "path": "item_b",
                    "source": "equipment",
                    "source_slot": "head",
                }
            ],
        },
        request_id="add-equip-1",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is True
    inventory_payload = result["data"]["inventory"]
    assert inventory_payload["inventory"] == [
        {"item_id": "item_a", "normalized_item_name": "item_a", "quantity": 1}
    ]
    assert inventory_payload["equipment"]["head"] is None
    assert len(dungeon_widget._session_loot_pool) == 1
    assert dungeon_widget._session_loot_pool[0]["item_id"] == "item_b"
    linked_inventory = dungeon_widget._dungeons[0]["state"]["items"][0]["linked_inventory"]
    assert linked_inventory["equipment"]["head"] is None


def test_host_add_loot_from_inventory_rejects_missing_inventory_item(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_inventory": {"inventory": ["item_a"]},
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
    dungeon_widget._session_loot_pool = []

    dungeon_widget._handle_host_add_loot_from_inventory(
        "player-1",
        {
            "sheet_id": "sheet-1",
            "items": [{"item_id": "missing_item", "title": "Missing"}],
        },
        request_id="add-missing",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is False
    assert "no longer available" in result["message"]
    assert dungeon_widget._session_loot_pool == []
    assert not dungeon_widget._host_controller.snapshots


def test_host_claim_loot_reserves_entries_until_finalize(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
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
    dungeon_widget._session_loot_pool = [
        {"entry_id": "loot-1", "type": "item", "item_id": "item_a", "title": "Item A"},
        {"entry_id": "loot-2", "type": "note", "note": "Test note", "title": "Test note"},
    ]
    dungeon_widget._refresh_loot_pool_list()

    dungeon_widget._handle_host_claim_loot(
        "player-1",
        {"entry_ids": ["loot-1"], "sheet_id": "sheet-1"},
        request_id="claim-2",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is True
    assert isinstance(result["data"].get("claim_id"), str) and result["data"]["claim_id"]
    assert result["data"]["sheet_id"] == "sheet-1"
    assert len(result["data"]["claimed_entries"]) == 1
    assert result["data"]["claimed_entries"][0]["entry_id"] == "loot-1"
    assert len(dungeon_widget._session_loot_pool) == 1
    assert dungeon_widget._session_loot_pool[0]["entry_id"] == "loot-2"
    assert len(dungeon_widget._host_controller.snapshots) == 1

    claim_id = str(result["data"]["claim_id"])
    dungeon_widget._handle_host_finalize_loot_claim(
        "player-1",
        {"claim_id": claim_id, "applied": True},
        request_id="finalize-2",
    )
    finalize_result = dungeon_widget._host_controller.results[-1][1]
    assert finalize_result["ok"] is True
    assert len(dungeon_widget._session_loot_pool) == 1
    assert dungeon_widget._session_loot_pool[0]["entry_id"] == "loot-2"
    assert len(dungeon_widget._host_controller.snapshots) == 1


def test_host_claim_loot_finalize_failure_keeps_entries(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
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
    dungeon_widget._session_loot_pool = [
        {"entry_id": "loot-1", "type": "item", "item_id": "item_a", "title": "Item A"},
    ]

    dungeon_widget._handle_host_claim_loot(
        "player-1",
        {"entry_ids": ["loot-1"], "sheet_id": "sheet-1"},
        request_id="claim-fail",
    )
    claim_result = dungeon_widget._host_controller.results[-1][1]
    claim_id = str(claim_result["data"]["claim_id"])
    dungeon_widget._handle_host_finalize_loot_claim(
        "player-1",
        {"claim_id": claim_id, "applied": False, "error": "sheet apply failed"},
        request_id="finalize-fail",
    )
    finalize_result = dungeon_widget._host_controller.results[-1][1]
    assert finalize_result["ok"] is False
    assert len(dungeon_widget._session_loot_pool) == 1
    assert len(dungeon_widget._host_controller.snapshots) >= 2


def test_host_claim_loot_rejects_partial_selection_when_any_entry_missing(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []
            self.snapshots = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
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
    dungeon_widget._session_loot_pool = [
        {"entry_id": "loot-1", "type": "item", "item_id": "item-a", "title": "Item A"},
    ]

    dungeon_widget._handle_host_claim_loot(
        "player-1",
        {"entry_ids": ["loot-1", "loot-missing"], "sheet_id": "sheet-1"},
        request_id="claim-partial",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is False
    assert "no longer available" in str(result.get("message") or "").lower()
    assert len(dungeon_widget._session_loot_pool) == 1
    assert dungeon_widget._session_loot_pool[0]["entry_id"] == "loot-1"
    assert not dungeon_widget._host_controller.snapshots


def test_client_loot_add_result_syncs_local_inventory_payload(monkeypatch, dungeon_widget):
    captured = {}

    def _apply_remote_inventory(character_id, sheet_name, inventory_payload, **kwargs):
        captured["character_id"] = character_id
        captured["sheet_name"] = sheet_name
        captured["inventory_payload"] = dict(inventory_payload)
        captured["kwargs"] = dict(kwargs)
        return True, "Inventory synchronized.", dict(inventory_payload)

    fake_module = types.SimpleNamespace(
        apply_remote_inventory_payload_for_character_id=_apply_remote_inventory,
        character_id_for_sheet_id=lambda _sheet_id: "character-sheet-1",
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)
    dungeon_widget._local_player_id = "player-1"
    dungeon_widget._pending_add_loot_from_inventory_requests["loot-sync-1"] = {
        "sheet_id": "sheet-1",
        "sheet_name": "Hero",
    }

    dungeon_widget._on_client_command_result(
        {
            "ok": True,
            "request_id": "loot-sync-1",
            "data": {
                "action": "add_loot_from_inventory",
                "sheet_id": "sheet-1",
                "sheet_name": "Hero",
                "character_id": "character-sheet-1",
                "save_revision": 4,
                "last_saved_at": "2026-03-01T10:00:00+00:00",
                "content_hash": "host-hash-1",
                "inventory": {
                    "inventory": ["item_b"],
                    "inventory_notes": "",
                    "equipment": {},
                    "gold": 0,
                    "silver": 0,
                    "copper": 0,
                },
            },
        }
    )

    assert captured["character_id"] == "character-sheet-1"
    assert captured["sheet_name"] == "Hero"
    assert captured["inventory_payload"]["inventory"] == [
        {"item_id": "item_b", "normalized_item_name": "item_b", "quantity": 1}
    ]
    assert captured["kwargs"]["emit_event"] is True
    assert captured["kwargs"]["save_revision"] == 4
    assert captured["kwargs"]["last_saved_at"] == "2026-03-01T10:00:00+00:00"
    assert captured["kwargs"]["content_hash"] == "host-hash-1"


def test_client_loot_add_result_ignores_uncorrelated_response(monkeypatch, dungeon_widget):
    calls = []

    def _apply_remote_inventory(*args, **kwargs):
        calls.append((args, kwargs))
        return True, "Inventory synchronized.", {}

    fake_module = types.SimpleNamespace(
        apply_remote_inventory_payload_for_character_id=_apply_remote_inventory,
        character_id_for_sheet_id=lambda _sheet_id: "character-sheet-1",
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)

    dungeon_widget._on_client_command_result(
        {
            "ok": True,
            "request_id": "unmatched-loot-result",
            "data": {
                "action": "add_loot_from_inventory",
                "sheet_id": "sheet-1",
                "inventory": {"inventory": ["item_b"], "equipment": {}},
            },
        }
    )

    assert calls == []


def test_sync_local_sheet_inventory_creates_missing_character_entry(monkeypatch, dungeon_widget):
    calls = {}

    def _apply_remote_inventory(character_id, sheet_name, inventory_payload, **kwargs):
        calls["character_id"] = character_id
        calls["sheet_name"] = sheet_name
        calls["inventory_payload"] = dict(inventory_payload)
        calls["kwargs"] = dict(kwargs)
        return True, "Inventory synchronized.", dict(inventory_payload)

    fake_module = types.SimpleNamespace(
        apply_remote_inventory_payload_for_character_id=_apply_remote_inventory,
        character_id_for_sheet_id=lambda _sheet_id: "character-sheet-1",
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)

    ok, message = dungeon_widget._sync_local_sheet_inventory_from_host(
        "sheet-1",
        {"inventory": ["item_z"], "equipment": {}},
        sheet_name="Hero Name",
        refresh_entities=False,
    )

    assert ok is True
    assert "synchronized" in message.lower()
    assert calls["character_id"] == "character-sheet-1"
    assert calls["sheet_name"] == "Hero Name"
    assert calls["inventory_payload"]["inventory"] == [
        {"item_id": "item_z", "normalized_item_name": "item_z", "quantity": 1}
    ]
    assert calls["kwargs"]["emit_event"] is True


def test_external_character_inventory_save_refreshes_linked_sync_metadata(dungeon_widget, monkeypatch):
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-1",
                        "linked_save_revision": 2,
                        "linked_last_saved_at": "2026-03-01T09:00:00+00:00",
                        "linked_content_hash": "old-hash",
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
    broadcast_calls = []
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: broadcast_calls.append(True))
    monkeypatch.setattr(
        dungeon_widget,
        "_resolve_local_sheet_sync_payload",
        lambda character_id: {
            "character_id": character_id,
            "sheet_id": "sheet-1",
            "sheet_name": "Hero",
            "save_revision": 3,
            "last_saved_at": "2026-03-01T10:15:00+00:00",
            "content_hash": "fresh-hash",
            "inventory": {"inventory": [{"item_id": "item-1", "quantity": 1}]},
            "stats": {"name": "Hero"},
        },
    )
    monkeypatch.setitem(
        sys.modules,
        "player_sheets",
        types.SimpleNamespace(
            character_id_for_sheet_id=lambda _sheet_id: "character-1",
            inventory_payload_for_sheet_id=lambda _sheet_id: None,
        ),
    )

    dungeon_widget._on_external_character_inventory_saved(
        "sheet-1",
        {"inventory": [{"item_id": "item-1", "quantity": 1}], "equipment": {}},
    )

    item_data = dungeon_widget._dungeons[0]["state"]["items"][0]
    assert item_data["linked_save_revision"] == 3
    assert item_data["linked_last_saved_at"] == "2026-03-01T10:15:00+00:00"
    assert item_data["linked_content_hash"] == "fresh-hash"
    assert broadcast_calls == [True]


def test_client_claim_result_applies_items_and_custom_notes(monkeypatch, dungeon_widget):
    class _ClientStub:
        def __init__(self):
            self.calls = []

        def send_command(self, action, payload, request_id=None):
            self.calls.append((action, payload, request_id))

        def disconnect(self):
            return None

    captured = {}

    def _apply_claim(sheet_id, *, item_ids, note_lines):
        captured["sheet_id"] = sheet_id
        captured["item_ids"] = list(item_ids)
        captured["note_lines"] = list(note_lines)
        return True, "Claim applied.", {}

    fake_module = types.SimpleNamespace(apply_claim_to_sheet=_apply_claim)
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._player_connection_ready = True

    dungeon_widget._on_client_command_result(
        {
            "ok": True,
            "data": {
                "claim_id": "claim-1",
                "sheet_id": "sheet-1",
                "claimed_entries": [
                    {"type": "item", "item_id": "item-a", "title": "Potion"},
                    {"type": "note", "note": "Custom loot text", "title": "Custom loot text"},
                ],
            },
        }
    )

    assert captured["sheet_id"] == "sheet-1"
    assert captured["item_ids"] == ["item-a"]
    assert captured["note_lines"] == ["Custom loot text"]
    assert dungeon_widget._client_controller.calls
    action, payload, request_id = dungeon_widget._client_controller.calls[-1]
    assert action == "claim_loot_finalize"
    assert payload["claim_id"] == "claim-1"


def test_client_claim_finalize_failure_rolls_back_local_inventory(monkeypatch, dungeon_widget):
    class _ClientStub:
        def __init__(self):
            self.calls = []

        def send_command(self, action, payload, request_id=None):
            self.calls.append((action, payload, request_id))
            return True

        def disconnect(self):
            return None

    inventory_state = {
        "inventory": [{"item_id": "item-before", "quantity": 1}],
        "inventory_notes": "",
        "equipment": {},
        "gold": 0,
        "silver": 0,
        "copper": 0,
    }
    restore_calls = []

    def _apply_claim(sheet_id, *, item_ids, note_lines):
        inventory_state["inventory"] = [
            {"item_id": item_id, "normalized_item_name": item_id, "quantity": 1}
            for item_id in item_ids
        ]
        inventory_state["inventory_notes"] = "\n".join(note_lines)
        return True, "Claim applied.", dict(inventory_state)

    def _inventory_payload_for_sheet_id(_sheet_id):
        return dict(inventory_state)

    def _set_inventory_payload_for_sheet_id(sheet_id, inventory_payload, *, emit_event=True):
        restore_calls.append((sheet_id, dict(inventory_payload), emit_event))
        inventory_state.clear()
        inventory_state.update(dict(inventory_payload))
        return True, "Inventory restored.", dict(inventory_state)

    fake_module = types.SimpleNamespace(
        apply_claim_to_sheet=_apply_claim,
        inventory_payload_for_sheet_id=_inventory_payload_for_sheet_id,
        set_inventory_payload_for_sheet_id=_set_inventory_payload_for_sheet_id,
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._player_connection_ready = True

    dungeon_widget._on_client_command_result(
        {
            "ok": True,
            "data": {
                "claim_id": "claim-rollback-1",
                "sheet_id": "sheet-1",
                "claimed_entries": [
                    {"type": "item", "item_id": "item-new", "title": "Potion"},
                ],
            },
        }
    )

    dungeon_widget._on_client_command_result(
        {
            "ok": False,
            "message": "Claim is no longer active.",
            "data": {
                "action": "claim_loot_finalize",
                "claim_id": "claim-rollback-1",
            },
        }
    )

    assert restore_calls
    assert restore_calls[-1][0] == "sheet-1"
    assert restore_calls[-1][1]["inventory"] == [
        {"item_id": "item-before", "normalized_item_name": "item-before", "quantity": 1}
    ]


def test_client_claim_finalize_ack_clears_pending_finalize_queue(monkeypatch, dungeon_widget):
    class _ClientStub:
        def __init__(self):
            self.calls = []

        def send_command(self, action, payload, request_id=None):
            self.calls.append((action, payload, request_id))

        def disconnect(self):
            return None

    def _apply_claim(_sheet_id, *, item_ids, note_lines):
        _ = item_ids, note_lines
        return True, "Claim applied.", {}

    fake_module = types.SimpleNamespace(apply_claim_to_sheet=_apply_claim)
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._player_connection_ready = True

    dungeon_widget._on_client_command_result(
        {
            "ok": True,
            "data": {
                "claim_id": "claim-ack-1",
                "sheet_id": "sheet-1",
                "claimed_entries": [
                    {"type": "item", "item_id": "item-a", "title": "Potion"},
                ],
            },
        }
    )

    assert "claim-ack-1" in dungeon_widget._pending_loot_claim_finalizations
    assert dungeon_widget._pending_loot_claim_finalizations["claim-ack-1"]["inflight"] is True
    assert dungeon_widget._client_controller.calls
    assert dungeon_widget._client_controller.calls[-1][0] == "claim_loot_finalize"

    dungeon_widget._on_client_command_result(
        {
            "ok": True,
            "data": {"action": "claim_loot_finalize", "claim_id": "claim-ack-1"},
        }
    )

    assert "claim-ack-1" not in dungeon_widget._pending_loot_claim_finalizations


def test_client_claim_result_materializes_item_document_for_item_id(monkeypatch, dungeon_widget, tmp_path):
    class _ClientStub:
        def __init__(self):
            self.calls = []

        def send_command(self, action, payload, request_id=None):
            self.calls.append((action, payload, request_id))

        def disconnect(self):
            return None

    captured = {}

    def _apply_claim(sheet_id, *, item_ids, note_lines):
        captured["sheet_id"] = sheet_id
        captured["item_ids"] = list(item_ids)
        captured["note_lines"] = list(note_lines)
        return True, "Claim applied.", {}

    fake_module = types.SimpleNamespace(apply_claim_to_sheet=_apply_claim)
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._player_connection_ready = True
    library_dir = tmp_path / "claimed_items"
    monkeypatch.setattr("dungeon_applet.items_dir", lambda: library_dir)

    icon_path = tmp_path / "doc_icon.png"
    icon_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc``\xf8\xff\xff?\x00\x05\xfe\x02\xfe"
        b"\xa7\xd6\x9f\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    payload = {
        "item_id": "remote-item",
        "title": "Remote Item",
        "rarity": "common",
        "level": 1,
        "icon_path": str(icon_path),
    }

    dungeon_widget._on_client_command_result(
        {
            "ok": True,
            "data": {
                "claim_id": "claim-remote",
                "sheet_id": "sheet-1",
                "claimed_entries": [
                    {
                        "type": "item",
                        "item_id": "remote-item",
                        "title": "Remote Item",
                        "path": "",
                        "item_document": build_item_document(payload, str(icon_path)),
                    }
                ],
            },
        }
    )

    assert captured["sheet_id"] == "sheet-1"
    assert len(captured["item_ids"]) == 1
    claimed_item_id = captured["item_ids"][0]
    assert claimed_item_id == "remote-item"
    persisted_files = list(library_dir.glob("*.dmtitem"))
    assert len(persisted_files) == 1
    persisted_payload = load_item_payload(persisted_files[0])
    assert isinstance(persisted_payload, dict)
    assert persisted_payload["item_id"] == "remote-item"
    assert dungeon_widget._client_controller.calls
    action, payload, request_id = dungeon_widget._client_controller.calls[-1]
    assert action == "claim_loot_finalize"
    assert payload["claim_id"] == "claim-remote"
    assert payload["applied"] is True
    assert isinstance(request_id, str) and request_id


def test_loot_pool_displays_items_before_notes_with_icons(dungeon_widget, tmp_path):
    item_path = tmp_path / "blade.dmtitem"
    write_item_document(
        item_path,
        build_item_document(
            {
                "item_id": "blade_1",
                "title": "Blade",
                "rarity": "common",
                "level": 1,
            },
            "",
        ),
    )
    dungeon_widget._session_loot_pool = [
        {"entry_id": "n-1", "type": "note", "title": "Remember trap", "note": "Remember trap"},
        {
            "entry_id": "i-1",
            "type": "item",
            "item_id": "blade_1",
            "title": "Blade",
            "path": str(item_path),
        },
        {"entry_id": "n-2", "type": "note", "title": "Share gold", "note": "Share gold"},
    ]

    dungeon_widget._refresh_loot_pool_list()
    rows = [
        dungeon_widget._loot_pool_list.item(index).data(Qt.ItemDataRole.UserRole + 1)
        for index in range(dungeon_widget._loot_pool_list.count())
    ]
    assert [str(row.get("type")) for row in rows] == ["item", "note", "note"]
    assert not dungeon_widget._loot_pool_list.item(0).icon().isNull()
    assert dungeon_widget._loot_pool_list.item(1).text() == "Remember trap"
    assert not dungeon_widget._loot_pool_list.item(1).text().lower().startswith("note:")


def test_loot_pool_add_button_is_square(dungeon_widget):
    assert dungeon_widget._loot_add_btn.width() == dungeon_widget._loot_add_btn.height()
    assert dungeon_widget._loot_add_note_btn.text() == "Add Custom"


def test_loot_pool_bottom_controls_are_aligned(dungeon_widget):
    dungeon_widget.resize(1200, 820)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._toggle_loot_pool_panel()

    add_height = dungeon_widget._loot_add_btn.height()
    custom_height = dungeon_widget._loot_add_note_btn.height()
    remove_height = dungeon_widget._loot_remove_btn.height()
    assert dungeon_widget._loot_add_btn.width() == add_height
    assert custom_height == remove_height
    assert add_height == custom_height
    assert dungeon_widget._loot_add_note_btn.width() == dungeon_widget._loot_remove_btn.width()

    add_center = dungeon_widget._loot_add_btn.mapToGlobal(
        dungeon_widget._loot_add_btn.rect().center()
    ).y()
    custom_center = dungeon_widget._loot_add_note_btn.mapToGlobal(
        dungeon_widget._loot_add_note_btn.rect().center()
    ).y()
    remove_center = dungeon_widget._loot_remove_btn.mapToGlobal(
        dungeon_widget._loot_remove_btn.rect().center()
    ).y()
    assert abs(add_center - custom_center) <= 1
    assert abs(add_center - remove_center) <= 1


def test_initiative_command_is_dm_online_only(dungeon_widget, monkeypatch):
    calls = []
    monkeypatch.setattr(
        dungeon_widget,
        "_show_initiative_overlay",
        lambda *args, **kwargs: calls.append(("show", kwargs)),
    )
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: calls.append("broadcast"))

    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._on_chat_submitted("/initiative")
    assert calls == [("show", {"activate": True}), "broadcast"]

    messages = []
    monkeypatch.setattr(
        dungeon_widget,
        "_append_chat_message",
        lambda actor, text, system=False: messages.append((actor, text, system)),
    )
    dungeon_widget._set_online_mode(ONLINE_MODE_LOCAL_DM)
    dungeon_widget._on_chat_submitted("/initiative")
    assert messages
    assert "online DM sessions" in messages[-1][1]


def test_player_snapshot_initiative_rows_show_only_local_player(dungeon_widget):
    dungeon_widget._local_player_id = "player-1"
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)

    snapshot = {
        "players": {"player-1": "Alice", "player-2": "Bob"},
        "scene": {
            "items": [
                {
                    "type": "entity",
                    "pos": [8.0, 8.0],
                    "entity_id": "e1",
                    "label": "Wolf",
                    "owner_player_id": "player-1",
                },
                {
                    "type": "entity",
                    "pos": [24.0, 8.0],
                    "entity_id": "e2",
                    "label": "Bear",
                    "owner_player_id": "player-2",
                },
            ],
            "fog": {"path": []},
        },
        "initiative_state": {
            "active": True,
            "collapsed": False,
            "player_entries": {
                "player-1:e1": {
                    "player_id": "player-1",
                    "entity_id": "e1",
                    "name": "Alice - Wolf",
                    "initiative": 12,
                },
                "player-2:e2": {
                    "player_id": "player-2",
                    "entity_id": "e2",
                    "name": "Bob - Bear",
                    "initiative": 8,
                },
            },
            "entity_entries": {"e1": {"name": "Goblin", "initiative": 9}},
        },
    }

    dungeon_widget._on_client_snapshot_received(snapshot)
    assert not dungeon_widget._initiative_overlay.isHidden()
    labels = [label.text() for label in dungeon_widget._initiative_rows_root.findChildren(QLabel)]
    assert "Alice - Wolf" in labels
    assert "Bob - Bear" not in labels
    assert all(not text.startswith("Entity:") for text in labels)

    collapsed_snapshot = dict(snapshot)
    collapsed_snapshot["initiative_state"] = dict(snapshot["initiative_state"])
    collapsed_snapshot["initiative_state"]["collapsed"] = True
    dungeon_widget._on_client_snapshot_received(collapsed_snapshot)
    assert dungeon_widget._initiative_overlay.isHidden()
    assert dungeon_widget._initiative_reopen_btn.isHidden()


def test_player_snapshot_without_active_initiative_stays_hidden(dungeon_widget):
    dungeon_widget._local_player_id = "player-1"
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._on_client_snapshot_received(
        {
            "players": {"player-1": "Alice"},
            "scene": {"items": [], "fog": {"path": []}},
            "initiative_state": {
                "active": False,
                "collapsed": False,
                "player_entries": {
                    "player-1:e1": {
                        "player_id": "player-1",
                        "entity_id": "e1",
                        "name": "Alice - Wolf",
                        "initiative": None,
                    }
                },
                "entity_entries": {},
            },
        }
    )
    assert dungeon_widget._initiative_overlay.isHidden()
    assert dungeon_widget._initiative_reopen_btn.isHidden()


def test_player_snapshot_with_no_assigned_initiative_rows_stays_hidden(dungeon_widget):
    dungeon_widget._local_player_id = "player-1"
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._on_client_snapshot_received(
        {
            "players": {"player-1": "Alice", "player-2": "Bob"},
            "scene": {"items": [], "fog": {"path": []}},
            "initiative_state": {
                "active": True,
                "collapsed": False,
                "player_entries": {
                    "player-2:e2": {
                        "player_id": "player-2",
                        "entity_id": "e2",
                        "name": "Bob - Bear",
                        "initiative": None,
                    }
                },
                "entity_entries": {},
            },
        }
    )
    assert dungeon_widget._initiative_overlay.isHidden()
    assert dungeon_widget._initiative_reopen_btn.isHidden()


def test_player_can_collapse_initiative_overlay_locally(dungeon_widget, qtbot):
    dungeon_widget._local_player_id = "player-1"
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {
            "player-1:e1": {
                "player_id": "player-1",
                "entity_id": "e1",
                "name": "Alice - Wolf",
                "initiative": None,
            }
        },
        "entity_entries": {},
    }

    dungeon_widget._show_initiative_overlay()
    assert not dungeon_widget._initiative_overlay.isHidden()
    assert dungeon_widget._initiative_collapse_btn.isEnabled()

    dungeon_widget._initiative_collapse_btn.click()
    qtbot.wait(220)

    assert dungeon_widget._initiative_overlay.isHidden()
    assert dungeon_widget._initiative_state["collapsed"] is True
    assert dungeon_widget._initiative_reopen_btn.isHidden()


def test_initiative_can_collapse_when_no_player_entity_rows_exist(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {},
        "entity_entries": {},
    }

    dungeon_widget._render_initiative_overlay()
    assert dungeon_widget._all_players_have_initiative() is True
    assert dungeon_widget._initiative_collapse_btn.isEnabled()


def test_initiative_reopen_button_is_square_in_online_mode(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    assert not dungeon_widget._initiative_reopen_btn.isHidden()
    assert dungeon_widget._initiative_reopen_btn.width() == dungeon_widget._initiative_reopen_btn.height()


def test_initiative_top_right_button_toggles_overlay(dungeon_widget, qtbot):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {},
        "entity_entries": {},
    }
    dungeon_widget._show_initiative_overlay()
    assert not dungeon_widget._initiative_overlay.isHidden()
    dungeon_widget._on_initiative_reopen_clicked()
    qtbot.waitUntil(lambda: dungeon_widget._initiative_overlay.isHidden(), timeout=1200)
    assert dungeon_widget._initiative_overlay.isHidden()
    dungeon_widget._on_initiative_reopen_clicked()
    qtbot.wait(220)
    assert not dungeon_widget._initiative_overlay.isHidden()


def test_initiative_dm_force_close_works_with_missing_player_values(dungeon_widget, qtbot):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {
            "player-1:e1": {
                "player_id": "player-1",
                "entity_id": "e1",
                "name": "Alice - Wolf",
                "initiative": None,
            }
        },
        "entity_entries": {},
    }
    dungeon_widget._show_initiative_overlay()
    assert not dungeon_widget._initiative_overlay.isHidden()
    assert dungeon_widget._initiative_collapse_btn.isEnabled()

    dungeon_widget._on_initiative_reopen_clicked()
    qtbot.wait(220)
    assert dungeon_widget._initiative_overlay.isHidden()
    assert dungeon_widget._initiative_state["collapsed"] is True


def test_initiative_draft_value_survives_overlay_rerender(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._connected_players = {"player-1": "Alice"}
    owned = EntityItem(QPointF(0, 0))
    owned.setData(ROLE_ENTITY_ID, "e1")
    owned.setData(ROLE_LABEL, "Wolf")
    owned.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    dungeon_widget.canvas.scene().addItem(owned)
    dungeon_widget._initiative_state = {"active": True, "collapsed": False, "player_entries": {}, "entity_entries": {}}
    dungeon_widget._seed_initiative_state()
    dungeon_widget._initiative_state["player_entries"]["player-1:e1"]["initiative"] = 43
    dungeon_widget._show_initiative_overlay()
    dungeon_widget._on_initiative_text_edited("player", "player-1:e1", "9")
    dungeon_widget._render_initiative_overlay()
    QApplication.processEvents()
    edits = dungeon_widget._initiative_rows_root.findChildren(QLineEdit)
    assert edits
    matching = [
        candidate
        for candidate in edits
        if str(candidate.property("initiative_kind") or "") == "player"
        and str(candidate.property("initiative_id") or "") == "player-1:e1"
    ]
    edit = matching[-1] if matching else None
    assert edit is not None
    assert edit.text() == "9"


def test_player_initiative_field_keeps_focus_across_rerender_and_accepts_typing(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._local_player_id = "player-1"
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    snapshot = {
        "players": {"player-1": "Alice"},
        "scene": {
            "items": [
                {
                    "type": "entity",
                    "pos": [8.0, 8.0],
                    "entity_id": "e1",
                    "label": "Wolf",
                    "owner_player_id": "player-1",
                }
            ],
            "fog": {"path": []},
        },
        "initiative_state": {
            "active": True,
            "collapsed": False,
            "player_entries": {
                "player-1:e1": {
                    "player_id": "player-1",
                    "entity_id": "e1",
                    "name": "Alice - Wolf",
                    "initiative": None,
                }
            },
            "entity_entries": {},
        },
    }
    dungeon_widget._on_client_snapshot_received(snapshot)
    edits = [
        candidate
        for candidate in dungeon_widget._initiative_rows_root.findChildren(QLineEdit)
        if str(candidate.property("initiative_kind") or "") == "player"
        and str(candidate.property("initiative_id") or "") == "player-1:e1"
    ]
    assert edits
    edit = edits[-1]
    edit.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()
    focused_before = QApplication.focusWidget()
    assert isinstance(focused_before, QLineEdit)
    assert str(focused_before.property("initiative_id") or "") == "player-1:e1"

    dungeon_widget._render_initiative_overlay()
    QApplication.processEvents()

    rerendered = [
        candidate
        for candidate in dungeon_widget._initiative_rows_root.findChildren(QLineEdit)
        if str(candidate.property("initiative_kind") or "") == "player"
        and str(candidate.property("initiative_id") or "") == "player-1:e1"
    ]
    assert rerendered
    focused = QApplication.focusWidget()
    assert isinstance(focused, QLineEdit)
    assert str(focused.property("initiative_id") or "") == "player-1:e1"
    qtbot.keyClicks(focused, "17")
    assert focused.text() == "17"


def test_initiative_field_accepts_parent_routed_keypresses(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._connected_players = {"player-1": "Alice"}
    entity = EntityItem(QPointF(0, 0))
    entity.setData(ROLE_ENTITY_ID, "e1")
    entity.setData(ROLE_LABEL, "Wolf")
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget._initiative_state = {"active": True, "collapsed": False, "player_entries": {}, "entity_entries": {}}
    dungeon_widget._show_initiative_overlay()
    QApplication.processEvents()

    edits = [
        candidate
        for candidate in dungeon_widget._initiative_rows_root.findChildren(QLineEdit)
        if str(candidate.property("initiative_kind") or "") == "player"
        and str(candidate.property("initiative_id") or "") == "player-1:e1"
    ]
    assert edits
    edit = edits[-1]
    edit.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()
    qtbot.keyClicks(dungeon_widget, "42")
    assert edit.text() == "42"


def test_initiative_field_accepts_canvas_routed_keypresses(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._connected_players = {"player-1": "Alice"}
    entity = EntityItem(QPointF(0, 0))
    entity.setData(ROLE_ENTITY_ID, "e1")
    entity.setData(ROLE_LABEL, "Wolf")
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget._initiative_state = {"active": True, "collapsed": False, "player_entries": {}, "entity_entries": {}}
    dungeon_widget._show_initiative_overlay()
    QApplication.processEvents()

    edits = [
        candidate
        for candidate in dungeon_widget._initiative_rows_root.findChildren(QLineEdit)
        if str(candidate.property("initiative_kind") or "") == "player"
        and str(candidate.property("initiative_id") or "") == "player-1:e1"
    ]
    assert edits
    edit = edits[-1]
    edit.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()
    qtbot.keyClicks(dungeon_widget.canvas, "77")
    assert edit.text() == "77"


def test_player_initiative_enter_confirms_without_focus_loss(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._local_player_id = "player-1"
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    snapshot = {
        "players": {"player-1": "Alice"},
        "scene": {
            "items": [
                {
                    "type": "entity",
                    "pos": [8.0, 8.0],
                    "entity_id": "e1",
                    "label": "Wolf",
                    "owner_player_id": "player-1",
                }
            ],
            "fog": {"path": []},
        },
        "initiative_state": {
            "active": True,
            "collapsed": False,
            "player_entries": {
                "player-1:e1": {
                    "player_id": "player-1",
                    "entity_id": "e1",
                    "name": "Alice - Wolf",
                    "initiative": None,
                }
            },
            "entity_entries": {},
        },
    }
    dungeon_widget._on_client_snapshot_received(snapshot)
    QApplication.processEvents()

    edits = [
        candidate
        for candidate in dungeon_widget._initiative_rows_root.findChildren(QLineEdit)
        if str(candidate.property("initiative_kind") or "") == "player"
        and str(candidate.property("initiative_id") or "") == "player-1:e1"
    ]
    assert edits
    edit = edits[-1]
    edit.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()
    dungeon_widget.canvas.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()

    qtbot.keyClicks(dungeon_widget.canvas, "23")
    qtbot.keyClick(dungeon_widget.canvas, Qt.Key.Key_Return)
    QApplication.processEvents()

    assert dungeon_widget._initiative_state["player_entries"]["player-1:e1"]["initiative"] == 23


def test_player_mode_hides_initiative_reopen_button(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    assert dungeon_widget._initiative_reopen_btn.isHidden()


def test_dm_initiative_reopen_button_mirrors_origin_position(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget.resize(1200, 800)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._position_floating_overlays()
    btn = dungeon_widget._initiative_reopen_btn

    assert not btn.isHidden()
    assert btn.y() == 20
    assert btn.x() == max(8, dungeon_widget.width() - btn.width() - 20)


def test_initiative_non_numeric_commit_is_rejected_without_state_change(dungeon_widget):
    dungeon_widget._local_player_id = "player-1"
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._connected_players = {"player-1": "Alice"}
    entity = EntityItem(QPointF(0, 0))
    entity.setData(ROLE_ENTITY_ID, "e1")
    entity.setData(ROLE_LABEL, "Wolf")
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {
            "player-1:e1": {
                "player_id": "player-1",
                "entity_id": "e1",
                "name": "Alice - Wolf",
                "initiative": 12,
            }
        },
        "entity_entries": {},
    }
    sends = []

    class _ClientStub:
        def send_command(self, action, payload, request_id=None):
            sends.append((action, payload, request_id))

        def disconnect(self):
            return None

    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._on_initiative_value_changed("player", "player-1:e1", "abc")

    assert dungeon_widget._initiative_state["player_entries"]["player-1:e1"]["initiative"] == 12
    assert sends == []
    assert "numbers only" in dungeon_widget._initiative_value_warning.lower()


def test_reopen_button_opens_inactive_panel_without_starting_round(dungeon_widget, qtbot):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._connected_players = {"player-1": "Alice"}
    entity = EntityItem(QPointF(0, 0))
    entity.setData(ROLE_ENTITY_ID, "e1")
    entity.setData(ROLE_LABEL, "Wolf")
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget._initiative_state = {"active": False, "collapsed": False, "player_entries": {}, "entity_entries": {}}
    dungeon_widget._on_initiative_reopen_clicked()
    qtbot.wait(220)

    assert dungeon_widget._initiative_state["active"] is False
    assert "player-1:e1" in dungeon_widget._initiative_state["player_entries"]
    assert not dungeon_widget._initiative_overlay.isHidden()
    assert "inactive" in dungeon_widget._initiative_hint.text().lower()


def test_player_initiative_unchanged_value_does_not_resend_command(dungeon_widget):
    dungeon_widget._local_player_id = "player-1"
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {
            "player-1:e1": {
                "player_id": "player-1",
                "entity_id": "e1",
                "name": "Alice - Wolf",
                "initiative": 45,
            }
        },
        "entity_entries": {},
    }
    calls = []

    class _ClientStub:
        def send_command(self, action, payload, request_id=None):
            calls.append((action, payload, request_id))

        def disconnect(self):
            return None

    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._on_initiative_value_changed("player", "player-1:e1", "45")

    assert calls == []


def test_dm_initiative_unchanged_value_does_not_rebroadcast(dungeon_widget, monkeypatch):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._initiative_state = {
        "active": True,
        "collapsed": False,
        "player_entries": {
            "player-1:e1": {
                "player_id": "player-1",
                "entity_id": "e1",
                "name": "Alice - Wolf",
                "initiative": 12,
            }
        },
        "entity_entries": {},
    }
    sent = []
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: sent.append(True))

    dungeon_widget._on_initiative_value_changed("player", "player-1:e1", "12")

    assert sent == []


def test_initiative_input_does_not_cross_route_between_two_applets(qtbot):
    host = DungeonAppletWidget()
    player = DungeonAppletWidget()
    qtbot.addWidget(host)
    qtbot.addWidget(player)
    host.show()
    player.show()
    qtbot.wait(20)

    host._set_online_mode(ONLINE_MODE_DM_HOST)
    host._connected_players = {"player-1": "Alice"}
    entity = EntityItem(QPointF(0, 0))
    entity.setData(ROLE_ENTITY_ID, "e1")
    entity.setData(ROLE_LABEL, "Wolf")
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    host.canvas.scene().addItem(entity)
    host._initiative_state = {"active": True, "collapsed": False, "player_entries": {}, "entity_entries": {}}
    host._show_initiative_overlay()

    player._local_player_id = "player-1"
    player._set_online_mode(ONLINE_MODE_PLAYER)
    player._on_client_snapshot_received(
        {
            "players": {"player-1": "Alice"},
            "scene": {
                "items": [
                    {
                        "type": "entity",
                        "pos": [0.0, 0.0],
                        "entity_id": "e1",
                        "label": "Wolf",
                        "owner_player_id": "player-1",
                    }
                ],
                "fog": {"path": []},
            },
            "initiative_state": host._initiative_state,
        }
    )
    QApplication.processEvents()

    host_edits = [
        candidate
        for candidate in host._initiative_rows_root.findChildren(QLineEdit)
        if str(candidate.property("initiative_kind") or "") == "player"
        and str(candidate.property("initiative_id") or "") == "player-1:e1"
    ]
    player_edits = [
        candidate
        for candidate in player._initiative_rows_root.findChildren(QLineEdit)
        if str(candidate.property("initiative_kind") or "") == "player"
        and str(candidate.property("initiative_id") or "") == "player-1:e1"
    ]
    assert host_edits and player_edits
    host_edit = host_edits[-1]
    player_edit = player_edits[-1]

    host.activateWindow()
    host.raise_()
    host_edit.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()
    qtbot.keyClicks(host, "12")
    assert host_edit.text() == "12"
    assert player_edit.text() == ""

    player.activateWindow()
    player.raise_()
    player_edit.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()
    qtbot.keyClicks(player, "34")
    assert player_edit.text() == "34"
    assert host_edit.text() == "12"


def test_player_mode_link_button_enabled_for_owned_entity(dungeon_widget):
    entity = EntityItem(QPointF(25, 25))
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-local")
    dungeon_widget.canvas.scene().addItem(entity)

    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._apply_online_permissions()
    dungeon_widget.inspector.set_entity(entity)

    assert dungeon_widget.inspector.link_character_btn.isEnabled()


def test_inspector_hides_actions_and_description_for_linked_entity(dungeon_widget):
    entity = EntityItem(QPointF(25, 25))
    entity.setData(ROLE_LINKED_SHEET_ID, "sheet-1")
    entity.setData(ROLE_LINKED_SHEET_NAME, "Test Character")
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget.inspector.set_entity(entity)

    assert not dungeon_widget.inspector.actions_header_lbl.isVisible()
    assert not dungeon_widget.inspector.actions_text.isVisible()
    assert not dungeon_widget.inspector.desc_header_lbl.isVisible()
    assert not dungeon_widget.inspector.desc_text.isVisible()


def test_inspector_lore_visibility_depends_on_entity_content(dungeon_widget):
    dungeon_widget.show()
    QApplication.processEvents()
    entity = EntityItem(QPointF(25, 25))
    entity.actions = ""
    entity.description = ""
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget.inspector.set_entity(entity)
    QApplication.processEvents()

    assert dungeon_widget.inspector.actions_header_lbl.isHidden()
    assert dungeon_widget.inspector.actions_text.isHidden()
    assert dungeon_widget.inspector.desc_header_lbl.isHidden()
    assert dungeon_widget.inspector.desc_text.isHidden()

    entity.actions = "Bite. +4 to hit."
    entity.description = ""
    dungeon_widget.inspector.set_entity(entity)
    QApplication.processEvents()

    assert not dungeon_widget.inspector.actions_header_lbl.isHidden()
    assert not dungeon_widget.inspector.actions_text.isHidden()
    assert dungeon_widget.inspector.desc_header_lbl.isHidden()
    assert dungeon_widget.inspector.desc_text.isHidden()


def test_inspector_type_label_switches_to_player_for_owned_entity(dungeon_widget):
    entity = EntityItem(QPointF(25, 25))
    entity.setData(ROLE_OWNER_PLAYER_ID, "")
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget.inspector.set_entity(entity)
    QApplication.processEvents()
    assert dungeon_widget.inspector.type_lbl.text() == "NPC"

    entity.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    dungeon_widget.inspector.set_entity(entity)
    QApplication.processEvents()
    assert dungeon_widget.inspector.type_lbl.text() == "Player"


def test_inspector_center_stays_invariant_when_lore_sections_hide(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget.resize(1600, 1000)
    dungeon_widget._set_online_mode(ONLINE_MODE_LOCAL_DM)

    entity = EntityItem(QPointF(25, 25))
    entity.actions = "Long action text " * 8
    entity.description = "Long description text " * 8
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget.inspector.set_entity(entity)
    dungeon_widget._position_floating_overlays()
    QApplication.processEvents()
    y_with_lore = dungeon_widget.inspector.y()
    h_with_lore = dungeon_widget.inspector.height()
    center_with_lore = y_with_lore + (h_with_lore / 2.0)

    entity.actions = ""
    entity.description = ""
    dungeon_widget.inspector.set_entity(entity)
    dungeon_widget._position_floating_overlays()
    QApplication.processEvents()
    y_without_lore = dungeon_widget.inspector.y()
    h_without_lore = dungeon_widget.inspector.height()
    center_without_lore = y_without_lore + (h_without_lore / 2.0)

    assert h_without_lore < h_with_lore
    assert y_without_lore > y_with_lore
    assert abs(center_without_lore - center_with_lore) <= 2.0


def test_overlay_lift_requirement_reduces_when_inspector_lore_hidden(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget.resize(700, 360)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._set_session_panels_collapsed(False, animate=False)

    entity = EntityItem(QPointF(10, 10))
    entity.actions = "Action " * 30
    entity.description = "Description " * 30
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget.inspector.set_entity(entity)
    dungeon_widget._position_session_overlay()
    lift_with_lore = dungeon_widget._required_session_overlay_lift()

    entity.actions = ""
    entity.description = ""
    dungeon_widget.inspector.set_entity(entity)
    dungeon_widget._position_session_overlay()
    lift_without_lore = dungeon_widget._required_session_overlay_lift()

    assert lift_without_lore <= lift_with_lore


def test_player_toolbar_loot_badge_visible_when_pool_has_entries(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._session_loot_pool = [
        {"entry_id": "loot-1", "type": "item", "item_id": "item_a", "title": "Item A"}
    ]
    dungeon_widget._refresh_loot_pool_list()
    dungeon_widget._position_floating_overlays()

    assert not dungeon_widget.tool_panel.btn_loot_panel.isHidden()
    assert dungeon_widget.tool_panel._loot_pool_tool_badge.isVisible()
    tool_badge = dungeon_widget.tool_panel._loot_pool_tool_badge
    tool_button = dungeon_widget.tool_panel.btn_loot_panel
    assert tool_badge.x() <= 6
    assert tool_button.height() - tool_badge.height() - 6 <= tool_badge.y() <= tool_button.height() - tool_badge.height() + 1


def test_floating_loot_badge_uses_bottom_left_inset_anchor(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._session_loot_pool = [
        {"entry_id": "loot-1", "type": "item", "item_id": "item_a", "title": "Item A"}
    ]
    dungeon_widget._refresh_loot_pool_list()
    dungeon_widget._position_floating_overlays()

    badge = dungeon_widget._loot_pool_badge
    button = dungeon_widget._loot_pool_btn
    assert badge.x() <= 6
    assert button.height() - badge.height() - 6 <= badge.y() <= button.height() - badge.height() + 1


def test_player_snapshot_updates_loot_toolbar_badge_and_tooltip(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    snapshot = {
        "players": {"player-1": "A"},
        "loot_pool": [
            {"entry_id": "loot-1", "type": "item", "item_id": "item_a", "title": "Item A"},
            {"entry_id": "loot-2", "type": "note", "note": "Custom note"},
        ],
        "scene": dungeon_widget._blank_dungeon_state(),
    }

    dungeon_widget._on_client_snapshot_received(snapshot)

    assert not dungeon_widget.tool_panel.btn_loot_panel.isHidden()
    assert dungeon_widget.tool_panel._loot_pool_tool_badge.isVisible()
    assert "2 entries" in dungeon_widget.tool_panel.btn_loot_panel.toolTip()


def test_player_loot_badge_clears_when_loot_pool_is_opened(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._session_loot_pool = [
        {"entry_id": "loot-1", "type": "item", "item_id": "item_a", "title": "Item A"}
    ]
    dungeon_widget._refresh_loot_pool_list()
    assert dungeon_widget.tool_panel._loot_pool_tool_badge.isVisible()

    dungeon_widget._toggle_loot_pool_panel()

    assert not dungeon_widget.tool_panel._loot_pool_tool_badge.isVisible()


def test_player_permissions_keep_loot_badge_visible_with_existing_pool(dungeon_widget, qtbot):
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._session_loot_pool = [
        {"entry_id": "loot-1", "type": "item", "item_id": "item_a", "title": "Item A"}
    ]
    dungeon_widget._refresh_loot_pool_list()
    assert not dungeon_widget.tool_panel._loot_pool_tool_badge.isVisible()

    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._apply_online_permissions()

    assert not dungeon_widget.tool_panel.btn_loot_panel.isHidden()
    assert dungeon_widget.tool_panel._loot_pool_tool_badge.isVisible()


def test_client_snapshot_preserves_selected_entity(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._local_player_id = "player-1"
    selected = EntityItem(QPointF(10, 10))
    selected.setData(ROLE_ENTITY_ID, "e1")
    selected.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    dungeon_widget.canvas.scene().addItem(selected)
    selected.setSelected(True)

    snapshot = {
        "players": {"player-1": "Alice"},
        "dungeons": [
            {
                "id": "d1",
                "name": "Dungeon 1",
                "state": {
                    "items": [
                        {
                            "type": "entity",
                            "entity_id": "e1",
                            "label": "Wolf",
                            "owner_player_id": "player-1",
                            "pos": [10.0, 10.0],
                            "color": "#3B82F6",
                            "hp": 12,
                            "max_hp": 12,
                            "ac": 13,
                        }
                    ],
                    "fog": {"path": []},
                },
            }
        ],
        "players_dungeon_id": "d1",
        "active_dungeon_id": "d1",
    }
    dungeon_widget._on_client_snapshot_received(snapshot)

    selected_ids = [
        str(item.data(ROLE_ENTITY_ID) or "")
        for item in dungeon_widget.canvas.scene().selectedItems()
        if isinstance(item, EntityItem)
    ]
    assert "e1" in selected_ids


def test_player_link_character_sends_host_sync_command(monkeypatch, dungeon_widget, tmp_path):
    class _ClientStub:
        def __init__(self):
            self.calls = []

        def send_command(self, action, payload, request_id=None):
            self.calls.append((action, payload, request_id))

        def disconnect(self):
            return None

    pdf_path = tmp_path / "sheet.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    entry = types.SimpleNamespace(name="Test Hero", pdf_path=str(pdf_path))
    fake_module = types.SimpleNamespace(
        character_id_for_entry=lambda _entry: "character-sheet-1",
        list_character_link_targets=lambda: [entry],
        sheet_id_for_entry=lambda _entry: "sheet-1",
        inventory_payload_for_sheet_id=lambda _sheet_id: {"inventory": ["item-1"]},
        ensure_entry_archive=lambda _entry: None,
        character_sheet_pdf_path=lambda _sheet_id: pdf_path,
        character_sheet_archive_path=lambda _sheet_id: tmp_path / "sheet-1.dmtchar",
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)
    monkeypatch.setattr(
        "dungeon_applet._extract_character_stats_from_pdf",
        lambda _path: {
            "name": "test",
            "strength": 11,
            "dexterity": 12,
            "constitution": 13,
            "intelligence": 14,
            "wisdom": 15,
            "charisma": 16,
            "ac": 17,
            "hp_max": 23,
            "hp_current": 14,
            "hp": 23,
        },
    )
    monkeypatch.setattr(
        "dungeon_applet.QInputDialog.getItem",
        lambda *args, **kwargs: ("Test Hero (sheet-1)", True),
    )

    entity = EntityItem(QPointF(12, 12))
    entity.setData(ROLE_OWNER_PLAYER_ID, "player-local")
    entity.setData(ROLE_ENTITY_ID, "entity-local-1")
    dungeon_widget.canvas.scene().addItem(entity)

    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._active_dungeon_id = "players-dungeon-id"
    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget.inspector.set_entity(entity)

    dungeon_widget._on_link_character_requested()

    assert dungeon_widget._client_controller.calls
    action, payload, request_id = dungeon_widget._client_controller.calls[-1]
    assert action == "link_character_entity"
    assert payload["entity_id"] == "entity-local-1"
    assert payload["sheet_id"] == "sheet-1"
    assert payload["stats"]["ac"] == 17
    assert payload["dungeon_id"] == "players-dungeon-id"
    assert isinstance(payload["character_id"], str) and payload["character_id"]
    assert isinstance(request_id, str) and request_id


def test_join_snapshot_prompts_resolution_instead_of_auto_overwrite_push(monkeypatch, dungeon_widget, tmp_path):
    class _ClientStub:
        def __init__(self):
            self.calls = []

        def send_command(self, action, payload, request_id=None):
            self.calls.append((action, payload, request_id))

        def disconnect(self):
            return None

    pdf_path = tmp_path / "sheet.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    entry = types.SimpleNamespace(name="Join Hero", pdf_path=str(pdf_path), archive_path="")
    fake_module = types.SimpleNamespace(
        character_id_for_entry=lambda _entry: "character-sheet-1",
        list_character_link_targets=lambda: [entry],
        sheet_id_for_entry=lambda _entry: "sheet-1",
        inventory_payload_for_sheet_id=lambda _sheet_id: {"inventory": ["item-join"]},
        ensure_entry_archive=lambda _entry: None,
        character_sheet_pdf_path=lambda _sheet_id: pdf_path,
        character_sheet_archive_path=lambda _sheet_id: tmp_path / "sheet-1.dmtchar",
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)
    monkeypatch.setattr(
        "dungeon_applet._extract_character_stats_from_pdf",
        lambda _path: {"name": "Join Hero", "ac": 15, "hp_max": 21, "hp_current": 19},
    )

    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._player_connection_ready = True
    dungeon_widget._pending_join_character_override_sync = True
    dungeon_widget._client_controller = _ClientStub()

    snapshot = {
        "players": {"player-local": "Mira"},
        "dungeons": [
            {
                "id": "d1",
                "name": "Dungeon 1",
                "state": {
                    "items": [
                        {
                            "type": "entity",
                            "entity_id": "entity-local-1",
                            "owner_player_id": "player-local",
                            "linked_sheet_id": "sheet-1",
                            "linked_sheet_name": "Join Hero",
                            "linked_inventory": {"inventory": []},
                            "pos": [10.0, 10.0],
                        }
                    ],
                    "fog": {"path": []},
                },
            }
        ],
        "players_dungeon_id": "d1",
        "active_dungeon_id": "d1",
    }
    dungeon_widget._on_client_snapshot_received(snapshot)

    assert dungeon_widget._client_controller.calls == []


def test_snapshot_conflict_replaces_local_sheet_without_auto_host_overwrite(monkeypatch, dungeon_widget, tmp_path):
    class _ClientStub:
        def __init__(self):
            self.calls = []

        def send_command(self, action, payload, request_id=None):
            self.calls.append((action, payload, request_id))

        def disconnect(self):
            return None

    pdf_path = tmp_path / "sheet.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    entry = types.SimpleNamespace(name="Local Hero", pdf_path=str(pdf_path), archive_path="")
    fake_module = types.SimpleNamespace(
        character_id_for_entry=lambda _entry: "character-sheet-1",
        list_character_link_targets=lambda: [entry],
        sheet_id_for_entry=lambda _entry: "sheet-1",
        inventory_payload_for_sheet_id=lambda _sheet_id: {"inventory": ["item-local"]},
        ensure_entry_archive=lambda _entry: None,
        character_sheet_pdf_path=lambda _sheet_id: pdf_path,
        character_sheet_archive_path=lambda _sheet_id: tmp_path / "sheet-1.dmtchar",
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)
    monkeypatch.setattr(
        "dungeon_applet._extract_character_stats_from_pdf",
        lambda _path: {"name": "Local Hero", "ac": 19, "hp_max": 31, "hp_current": 28},
    )

    synced_from_host = []

    def _fake_sync_from_host(
        character_id,
        inventory_payload,
        *,
        sheet_name="",
        save_revision=0,
        last_saved_at="",
        content_hash="",
        refresh_entities=True,
    ):
        synced_from_host.append(
            (
                character_id,
                dict(inventory_payload),
                sheet_name,
                int(save_revision),
                str(last_saved_at),
                str(content_hash),
                bool(refresh_entities),
            )
        )
        return True, "Inventory synchronized."

    monkeypatch.setattr(dungeon_widget, "_sync_local_sheet_inventory_from_host", _fake_sync_from_host)

    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._player_connection_ready = True
    dungeon_widget._pending_join_character_override_sync = False
    dungeon_widget._client_controller = _ClientStub()

    snapshot = {
        "players": {"player-local": "Mira"},
        "dungeons": [
            {
                "id": "d1",
                "name": "Dungeon 1",
                "state": {
                    "items": [
                        {
                            "type": "entity",
                            "entity_id": "entity-local-1",
                            "owner_player_id": "player-local",
                            "linked_sheet_id": "sheet-1",
                            "linked_character_id": "character-sheet-1",
                            "linked_sheet_name": "Local Hero",
                            "linked_inventory": {"inventory": ["item-host"]},
                            "pos": [10.0, 10.0],
                        }
                    ],
                    "fog": {"path": []},
                },
            }
        ],
        "players_dungeon_id": "d1",
        "active_dungeon_id": "d1",
    }
    dungeon_widget._on_client_snapshot_received(snapshot)

    assert synced_from_host == [
        (
            "character-sheet-1",
            {
                "inventory": [
                    {
                        "item_id": "item-host",
                        "normalized_item_name": "item-host",
                        "quantity": 1,
                    }
                ],
                "inventory_notes": "",
                "equipment": {},
                "gold": 0,
                "silver": 0,
                "copper": 0,
            },
            "Local Hero",
            0,
            "",
            "",
            True,
        )
    ]
    assert dungeon_widget._client_controller.calls == []


def test_player_link_character_extracts_archive_when_runtime_pdf_missing(monkeypatch, dungeon_widget, tmp_path):
    runtime_pdf = tmp_path / "runtime-sheet.pdf"
    archive_path = tmp_path / "sheet-1.dmtchar"
    archive_path.write_bytes(b"archive")

    entry = types.SimpleNamespace(name="Archive Hero", pdf_path="", archive_path=str(archive_path))
    fake_module = types.SimpleNamespace(
        character_id_for_entry=lambda _entry: "character-sheet-1",
        list_character_link_targets=lambda: [entry],
        sheet_id_for_entry=lambda _entry: "sheet-1",
        inventory_payload_for_sheet_id=lambda _sheet_id: {"inventory": []},
        ensure_entry_archive=lambda _entry: None,
        character_sheet_pdf_path=lambda _sheet_id: runtime_pdf,
        character_sheet_archive_path=lambda _sheet_id: archive_path,
    )
    monkeypatch.setitem(sys.modules, "player_sheets", fake_module)

    extraction_calls = []

    def _fake_extract(src: Path, dst: Path) -> bool:
        extraction_calls.append((src, dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"%PDF-1.4 extracted")
        return True

    extracted_stats_paths: list[str] = []

    def _fake_extract_stats(path: str) -> dict:
        extracted_stats_paths.append(path)
        return {"name": "Archive Hero", "ac": 12, "hp_max": 9}

    monkeypatch.setattr("dungeon_applet.extract_character_pdf", _fake_extract)
    monkeypatch.setattr("dungeon_applet._extract_character_stats_from_pdf", _fake_extract_stats)
    monkeypatch.setattr(
        "dungeon_applet.QInputDialog.getItem",
        lambda *args, **kwargs: ("Archive Hero (sheet-1)", True),
    )

    entity = EntityItem(QPointF(22, 22))
    dungeon_widget.canvas.scene().addItem(entity)
    dungeon_widget.inspector.set_entity(entity)

    dungeon_widget._on_link_character_requested()

    assert extraction_calls == [(archive_path, runtime_pdf)]
    assert runtime_pdf.exists()
    assert extracted_stats_paths == [str(runtime_pdf)]
    assert entity.data(ROLE_LINKED_SHEET_ID) == "sheet-1"
    assert entity.data(ROLE_LINKED_SHEET_NAME) == "Archive Hero"


def test_host_link_character_sync_rejects_non_owner(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            return None

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-2",
                        "label": "Entity",
                        "hp": 10,
                        "max_hp": 10,
                        "ac": 10,
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

    dungeon_widget._handle_host_link_character_entity(
        "player-1",
        {
            "entity_id": "e1",
            "sheet_id": "sheet-1",
            "sheet_name": "test",
            "dungeon_id": "d1",
            "inventory": {"inventory": []},
            "stats": {"ac": 17, "hp_max": 23, "hp_current": 14},
        },
        request_id="link-owner-check",
    )
    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is False
    assert "different player" in result["message"]


def test_initiative_sort_key_orders_by_value_then_name(dungeon_widget):
    entries = [
        ("a", {"name": "B", "initiative": 10}),
        ("b", {"name": "A", "initiative": 16}),
        ("c", {"name": "C", "initiative": None}),
    ]
    ordered = [entry_id for entry_id, _ in sorted(entries, key=dungeon_widget._initiative_sort_key)]
    assert ordered == ["b", "a", "c"]


def test_initiative_requires_all_assigned_entity_rows_per_player(dungeon_widget):
    dungeon_widget._connected_players = {"player-1": "Alice"}
    first = EntityItem(QPointF(0, 0))
    first.setData(ROLE_ENTITY_ID, "e1")
    first.setData(ROLE_LABEL, "Wolf")
    first.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    second = EntityItem(QPointF(40, 0))
    second.setData(ROLE_ENTITY_ID, "e2")
    second.setData(ROLE_LABEL, "Bear")
    second.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    dungeon_widget.canvas.scene().addItem(first)
    dungeon_widget.canvas.scene().addItem(second)

    dungeon_widget._seed_initiative_state()
    entries = dungeon_widget._initiative_state["player_entries"]
    assert len(entries) == 2
    assert dungeon_widget._all_players_have_initiative() is False

    for entry in entries.values():
        entry["initiative"] = 12
    assert dungeon_widget._all_players_have_initiative() is True


def test_seed_initiative_excludes_player_owned_rows_from_dm_entity_rows(dungeon_widget):
    dungeon_widget._connected_players = {"player-1": "Alice"}
    owned = EntityItem(QPointF(0, 0))
    owned.setData(ROLE_ENTITY_ID, "e-owned")
    owned.setData(ROLE_LABEL, "Wolf")
    owned.setData(ROLE_OWNER_PLAYER_ID, "player-1")
    npc = EntityItem(QPointF(40, 0))
    npc.setData(ROLE_ENTITY_ID, "e-npc")
    npc.setData(ROLE_LABEL, "Goblin")
    npc.setData(ROLE_OWNER_PLAYER_ID, "")
    dungeon_widget.canvas.scene().addItem(owned)
    dungeon_widget.canvas.scene().addItem(npc)

    dungeon_widget._seed_initiative_state()
    player_entries = dungeon_widget._initiative_state["player_entries"]
    entity_entries = dungeon_widget._initiative_state["entity_entries"]
    assert "player-1:e-owned" in player_entries
    assert "e-owned" not in entity_entries
    assert "e-npc" in entity_entries


def test_extract_character_stats_uses_text_fallback_for_missing_form_fields(monkeypatch, tmp_path):
    from dungeon_applet import _extract_character_stats_from_pdf

    class _FakePage:
        def extract_text(self):
            return "Character Name: Test Hero\nSTR 14 DEX 13 CON 12 INT 11 WIS 10 CHA 9 AC 16 HP 27"

    class _FakeReader:
        def __init__(self, _path):
            self.pages = [_FakePage()]

        def get_fields(self):
            return {"CharacterName": {"/V": "Test Hero"}}

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=_FakeReader))
    pdf_path = tmp_path / "sheet.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    stats = _extract_character_stats_from_pdf(str(pdf_path))
    assert stats["name"] == "Test Hero"
    assert stats["strength"] == 14
    assert stats["dexterity"] == 13
    assert stats["ac"] == 16
    assert stats["hp"] == 27


def test_extract_character_stats_uses_raw_pdf_field_fallback_when_reader_is_unavailable(
    monkeypatch, tmp_path
):
    from dungeon_applet import _extract_character_stats_from_pdf

    class _FailingReader:
        def __init__(self, _path):
            raise RuntimeError("reader unavailable")

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=_FailingReader))
    pdf_path = tmp_path / "sheet_raw_tokens.pdf"
    pdf_path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Subtype/Widget/T(CharacterName)/V(test)>>endobj\n"
        b"2 0 obj<</Subtype/Widget/T(STR)/V(11)>>endobj\n"
        b"3 0 obj<</Subtype/Widget/T(DEX)/V(12)>>endobj\n"
        b"4 0 obj<</Subtype/Widget/T(CON)/V(13)>>endobj\n"
        b"5 0 obj<</Subtype/Widget/T(INT)/V(14)>>endobj\n"
        b"6 0 obj<</Subtype/Widget/T(WIS)/V(15)>>endobj\n"
        b"7 0 obj<</Subtype/Widget/T(CHA)/V(16)>>endobj\n"
        b"8 0 obj<</Subtype/Widget/T(AC)/V(17)>>endobj\n"
        b"9 0 obj<</Subtype/Widget/T(HPMax)/V(23)>>endobj\n"
        b"10 0 obj<</Subtype/Widget/T(HPCurrent)/V(14)>>endobj\n",
    )

    stats = _extract_character_stats_from_pdf(str(pdf_path))
    assert stats["name"] == "test"
    assert stats["strength"] == 11
    assert stats["dexterity"] == 12
    assert stats["constitution"] == 13
    assert stats["intelligence"] == 14
    assert stats["wisdom"] == 15
    assert stats["charisma"] == 16
    assert stats["ac"] == 17
    assert stats["hp_max"] == 23
    assert stats["hp_current"] == 14
    assert stats["hp"] == 23


def test_extract_character_stats_from_generated_pdf_fixture(tmp_path):
    from dungeon_applet import _extract_character_stats_from_pdf

    pdf_path = tmp_path / "generated_stats_fixture.pdf"
    pdf_path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Subtype/Widget/T(CharacterName)/V(Test)>>endobj\n"
        b"2 0 obj<</Subtype/Widget/T(AC)/V(18)>>endobj\n"
        b"3 0 obj<</Subtype/Widget/T(HPMax)/V(31)>>endobj\n"
        b"4 0 obj<</Subtype/Widget/T(HPCurrent)/V(19)>>endobj\n",
    )

    stats = _extract_character_stats_from_pdf(str(pdf_path))
    assert str(stats.get("name") or "").strip().lower() == "test"
    assert stats.get("ac") == 18
    assert stats.get("hp_max") == 31
    assert stats.get("hp_current") == 19


def test_host_can_ignore_player_overwrite_requests_for_current_session(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            return None

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._ignore_player_overwrite_requests = True
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_sheet_name": "Hero",
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

    dungeon_widget._handle_host_resolve_linked_character_conflict(
        "player-1",
        {
            "mode": "overwrite_dm",
            "conflict_key": "d1::e1::character-1",
            "entity_id": "e1",
            "sheet_id": "sheet-1",
            "sheet_name": "Hero",
            "dungeon_id": "d1",
            "character_id": "character-1",
            "inventory": {"inventory": ["item-1"]},
            "stats": {"name": "Hero"},
        },
        request_id="ignore-overwrite-1",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is False
    assert result["data"]["action"] == "resolve_linked_character_conflict"
    assert result["data"]["resolution"] == "dm_ignored"
    assert "ignoring overwrite requests" in str(result["message"]).lower()


def test_host_conflict_resolution_missing_entity_returns_error_without_crash(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            return None

        def stop(self):
            return None

    host = _HostStub()
    dungeon_widget._host_controller = host
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {"items": [], "fog": {"path": []}},
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]

    dungeon_widget._handle_host_resolve_linked_character_conflict(
        "player-1",
        {
            "mode": "overwrite_dm",
            "conflict_key": "d1::missing::character-1",
            "entity_id": "missing",
            "sheet_id": "sheet-1",
            "sheet_name": "Hero",
            "dungeon_id": "d1",
            "character_id": "character-1",
            "inventory": {"inventory": ["item-1"]},
            "stats": {"name": "Hero"},
        },
        request_id="missing-entity",
    )

    assert host.results
    result = host.results[-1][1]
    assert result["ok"] is False
    assert "not found" in str(result.get("message") or "").lower()
    assert result["data"]["action"] == "resolve_linked_character_conflict"
    assert result["data"]["conflict"]["character_id"] == ""


def test_host_duplicate_overwrite_requests_are_throttled(monkeypatch, dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def broadcast_snapshot(self, snapshot):
            return None

        def stop(self):
            return None

    class _FakeDialog:
        ButtonRole = dungeon_applet_module.QMessageBox.ButtonRole
        shown = 0

        def __init__(self, *_args, **_kwargs):
            self._reject = object()
            self._clicked = self._reject

        def setWindowTitle(self, *_args, **_kwargs):
            return None

        def setText(self, *_args, **_kwargs):
            return None

        def setInformativeText(self, *_args, **_kwargs):
            return None

        def addButton(self, _label, role):
            if role == self.ButtonRole.RejectRole:
                return self._reject
            return object()

        def exec(self):
            _FakeDialog.shown += 1
            return None

        def clickedButton(self):
            return self._clicked

    monkeypatch.setattr(dungeon_applet_module, "_in_test_env", lambda: False)
    monkeypatch.setattr(dungeon_applet_module, "QMessageBox", _FakeDialog)

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._connected_players = {"player-1": "Mira"}
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Dungeon 1",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "e1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_sheet_name": "Hero",
                        "linked_character_id": "character-1",
                        "linked_save_revision": 1,
                        "linked_content_hash": "host-hash",
                        "linked_inventory": {"inventory": [{"item_id": "item-1", "quantity": 1}]},
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

    payload = {
        "mode": "overwrite_dm",
        "conflict_key": "d1::e1::character-1",
        "entity_id": "e1",
        "sheet_id": "sheet-1",
        "sheet_name": "Hero",
        "dungeon_id": "d1",
        "character_id": "character-1",
        "save_revision": 2,
        "last_saved_at": "",
        "content_hash": "player-hash",
        "inventory": {"inventory": [{"item_id": "item-local", "quantity": 1}]},
        "stats": {"name": "Hero"},
    }

    dungeon_widget._handle_host_resolve_linked_character_conflict(
        "player-1",
        dict(payload),
        request_id="overwrite-1",
    )
    dungeon_widget._handle_host_resolve_linked_character_conflict(
        "player-1",
        dict(payload),
        request_id="overwrite-2",
    )

    assert _FakeDialog.shown == 1
    assert len(dungeon_widget._host_controller.results) == 2
    first = dungeon_widget._host_controller.results[0][1]
    second = dungeon_widget._host_controller.results[1][1]
    assert first["message"] == second["message"]
    assert first["data"]["resolution"] == "dm_denied"
    assert second["data"]["resolution"] == "dm_denied"


def test_dm_denied_conflict_response_does_not_force_reprompt_loop(dungeon_widget, monkeypatch):
    prompts = []
    monkeypatch.setattr(
        dungeon_widget,
        "_prompt_linked_character_conflict",
        lambda *args, **kwargs: prompts.append((args, kwargs)),
    )

    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    conflict = {
        "conflict_key": "d1::e1::character-1",
        "dungeon_id": "d1",
        "entity_id": "e1",
        "character_id": "character-1",
        "sheet_id": "sheet-1",
        "sheet_name": "Hero",
        "save_revision": 1,
        "last_saved_at": "",
        "content_hash": "host-hash",
        "inventory": {"inventory": [{"item_id": "item-1", "quantity": 1}]},
    }
    dungeon_widget._on_client_command_result(
        {
            "ok": False,
            "message": "DM denied overwrite request.",
            "data": {
                "action": "resolve_linked_character_conflict",
                "resolution": "dm_denied",
                "conflict": dict(conflict),
            },
        }
    )

    assert prompts == []
    assert conflict["conflict_key"] in dungeon_widget._pending_link_conflicts
    assert conflict["conflict_key"] in dungeon_widget._suppressed_link_conflicts


def test_snapshot_missing_local_character_prompts_before_creating_local_copy(dungeon_widget, monkeypatch):
    prompts = []
    sync_calls = []

    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._player_connection_ready = True
    dungeon_widget._client_controller = types.SimpleNamespace(
        send_command=lambda *_args, **_kwargs: True,
        disconnect=lambda: None,
    )

    monkeypatch.setattr(dungeon_widget, "_resolve_local_sheet_sync_payload", lambda _character_id: None)
    monkeypatch.setattr(
        dungeon_widget,
        "_prompt_linked_character_conflict",
        lambda payload, force=False: prompts.append((dict(payload), bool(force))),
    )
    monkeypatch.setattr(
        dungeon_widget,
        "_sync_local_sheet_inventory_from_host",
        lambda *args, **kwargs: sync_calls.append((args, kwargs)) or (True, "ok"),
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
                            "linked_save_revision": 1,
                            "linked_content_hash": "host-hash",
                            "linked_inventory": {"inventory": [{"item_id": "item-1", "quantity": 1}]},
                        }
                    ],
                    "fog": {"path": []},
                },
            }
        ],
    }

    dungeon_widget._on_client_snapshot_received(snapshot)

    assert len(prompts) == 1
    payload, force = prompts[0]
    assert force is False
    assert payload["requires_local_create"] is True
    assert payload["allow_force_push"] is False
    assert sync_calls == []


def test_snapshot_does_not_reprompt_suppressed_conflict_with_unchanged_host_payload(
    dungeon_widget, monkeypatch
):
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._player_connection_ready = True
    dungeon_widget._client_controller = types.SimpleNamespace(
        send_command=lambda *_args, **_kwargs: True,
        disconnect=lambda: None,
    )

    monkeypatch.setattr(
        dungeon_widget,
        "_resolve_local_sheet_sync_payload",
        lambda _character_id: {
            "sheet_id": "sheet-1",
            "sheet_name": "Hero",
            "character_id": "character-1",
            "save_revision": 1,
            "last_saved_at": "",
            "content_hash": "local-hash",
            "inventory": {"inventory": [{"item_id": "item-local", "quantity": 1}]},
            "stats": {"name": "Hero"},
        },
    )

    prompts = []
    monkeypatch.setattr(
        dungeon_widget,
        "_prompt_linked_character_conflict",
        lambda payload, force=False: prompts.append((dict(payload), bool(force))),
    )

    suppressed_conflict = {
        "conflict_key": "d1::entity-1::character-1",
        "dungeon_id": "d1",
        "entity_id": "entity-1",
        "character_id": "character-1",
        "sheet_id": "sheet-1",
        "sheet_name": "Hero",
        "save_revision": 1,
        "last_saved_at": "",
        "content_hash": "host-hash",
        "inventory": {"inventory": [{"item_id": "item-host", "quantity": 1}]},
        "allow_force_push": True,
        "requires_local_create": False,
    }
    conflict_key = str(suppressed_conflict["conflict_key"])
    dungeon_widget._suppressed_link_conflicts[conflict_key] = (
        dungeon_widget._linked_character_conflict_signature(suppressed_conflict)
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
                            "linked_save_revision": 1,
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


def test_player_state_update_is_queued_when_send_fails_and_flushed_after_snapshot(
    dungeon_widget, monkeypatch
):
    class _ClientStub:
        def __init__(self):
            self.calls = []
            self.fail_state_update = True

        def send_command(self, action, payload, request_id=None):
            self.calls.append((action, dict(payload), request_id))
            if action == "state_update" and self.fail_state_update:
                return False
            return True

        def disconnect(self):
            return None

    client = _ClientStub()
    dungeon_widget._client_controller = client
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._player_connection_ready = True
    dungeon_widget._active_dungeon_id = "d1"
    monkeypatch.setattr(
        dungeon_widget,
        "_serialize_scene",
        lambda: {"items": [{"type": "entity", "entity_id": "entity-1"}], "fog": {"path": []}},
    )

    dungeon_widget._on_canvas_changed()

    assert dungeon_widget._pending_player_state_update is not None
    state_update_calls = [call for call in client.calls if call[0] == "state_update"]
    assert len(state_update_calls) == 1

    client.fail_state_update = False
    snapshot = {
        "players": {"player-local": "Mira"},
        "players_dungeon_id": "d1",
        "active_dungeon_id": "d1",
        "dungeons": [
            {
                "id": "d1",
                "name": "Players",
                "state": {"items": [], "fog": {"path": []}},
            }
        ],
    }
    dungeon_widget._on_client_snapshot_received(snapshot)

    state_update_calls = [call for call in client.calls if call[0] == "state_update"]
    assert len(state_update_calls) >= 2
    last_request_id = state_update_calls[-1][2]
    assert dungeon_widget._pending_player_state_update is not None
    assert dungeon_widget._pending_player_state_update_request_id == last_request_id

    dungeon_widget._on_client_command_result(
        {
            "ok": True,
            "request_id": last_request_id,
            "data": {"action": "state_update"},
        }
    )

    assert dungeon_widget._pending_player_state_update is None


def test_player_state_update_retries_after_disconnect_before_ack(dungeon_widget, monkeypatch):
    class _ClientStub:
        def __init__(self):
            self.calls = []

        def send_command(self, action, payload, request_id=None):
            self.calls.append((action, dict(payload), request_id))
            return True

        def disconnect(self):
            return None

    client = _ClientStub()
    dungeon_widget._client_controller = client
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._player_connection_ready = True
    dungeon_widget._active_dungeon_id = "d1"
    monkeypatch.setattr(
        dungeon_widget,
        "_serialize_scene",
        lambda: {"items": [{"type": "entity", "entity_id": "entity-1"}], "fog": {"path": []}},
    )

    dungeon_widget._on_canvas_changed()

    first_state_update = [call for call in client.calls if call[0] == "state_update"][-1]
    assert dungeon_widget._pending_player_state_update is not None
    assert dungeon_widget._pending_player_state_update_request_id == first_state_update[2]

    dungeon_widget._on_client_disconnected()

    assert dungeon_widget._pending_player_state_update is not None
    assert dungeon_widget._pending_player_state_update_request_id == ""

    snapshot = {
        "players": {"player-local": "Mira"},
        "players_dungeon_id": "d1",
        "active_dungeon_id": "d1",
        "dungeons": [
            {
                "id": "d1",
                "name": "Players",
                "state": {"items": [], "fog": {"path": []}},
            }
        ],
    }
    dungeon_widget._local_player_id = "player-local"
    dungeon_widget._awaiting_player_snapshot = True
    dungeon_widget._on_client_snapshot_received(snapshot)

    state_update_calls = [call for call in client.calls if call[0] == "state_update"]
    assert len(state_update_calls) >= 2
    assert state_update_calls[-1][2] != first_state_update[2]


def test_leaving_player_mode_clears_sent_override_fingerprints(dungeon_widget):
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._sent_character_override_fingerprints["d1::entity-1"] = "fingerprint"

    dungeon_widget._set_online_mode(ONLINE_MODE_LOCAL_DM)

    assert dungeon_widget._sent_character_override_fingerprints == {}
