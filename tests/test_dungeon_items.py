"""Tests for dungeon items - RoomGroup, EntityItem, WallItem"""

import sys
import os
from datetime import datetime
from pathlib import Path
import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsScene

# Adjust import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dungeon_items import RoomGroup, EntityItem, WallItem, DungeonEllipseItem, PingItem
from dungeon_constants import GRID_SIZE, ROLE_LABEL, ROLE_ENTITY_ID


@pytest.fixture(scope="module")
def app():
    """Create QApplication for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def scene(app):
    """Create a QGraphicsScene for testing."""
    return QGraphicsScene()


def _debug_log(message: str) -> None:
    path = Path(__file__).resolve().parents[1] / "debug" / "ping_item_lifecycle.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        ts = datetime.now().isoformat(timespec="seconds")
        handle.write(f"[{ts}] {message}\n")


class TestRoomGroup:
    """Tests for RoomGroup class."""
    
    def test_room_group_creation(self, scene):
        """RoomGroup can be instantiated."""
        room = RoomGroup()
        assert room is not None
    
    def test_room_group_is_selectable(self, scene):
        """RoomGroup should be selectable."""
        room = RoomGroup()
        scene.addItem(room)
        assert room.flags() & room.GraphicsItemFlag.ItemIsSelectable
    
    def test_room_group_is_movable(self, scene):
        """RoomGroup should be movable."""
        room = RoomGroup()
        scene.addItem(room)
        assert room.flags() & room.GraphicsItemFlag.ItemIsMovable
    
    def test_add_floor(self, scene):
        """RoomGroup.add_floor creates a floor rectangle."""
        room = RoomGroup()
        scene.addItem(room)
        rect = QRectF(0, 0, 100, 100)
        floor = room.add_floor(rect)
        assert floor is not None
        assert floor.rect() == rect
    
    def test_add_wall(self, scene):
        """RoomGroup.add_wall creates a wall."""
        room = RoomGroup()
        scene.addItem(room)
        wall = room.add_wall(0, 0, 100, 0)
        assert wall is not None
        assert isinstance(wall, WallItem)
    
    def test_group_contains_children(self, scene):
        """RoomGroup should contain floor and walls after adding them."""
        room = RoomGroup()
        scene.addItem(room)
        room.add_floor(QRectF(0, 0, 100, 100))
        room.add_wall(0, 0, 100, 0)
        room.add_wall(100, 0, 100, 100)
        
        # Group should have children
        children = room.childItems()
        assert len(children) == 3  # 1 floor + 2 walls
    
    def test_group_position(self, scene):
        """RoomGroup position can be set."""
        room = RoomGroup()
        room.setPos(QPointF(50, 50))
        scene.addItem(room)
        
        assert room.pos() == QPointF(50, 50)


class TestEntityItem:
    """Tests for EntityItem class."""
    
    def test_entity_creation(self, scene):
        """EntityItem can be instantiated."""
        entity = EntityItem(QPointF(100, 100))
        assert entity is not None
    
    def test_entity_default_hp(self, scene):
        """EntityItem has default HP of 100/100."""
        entity = EntityItem(QPointF(0, 0))
        assert entity.hp == 100
        assert entity._max_hp == 100
    
    def test_entity_default_ac(self, scene):
        """EntityItem has default AC of 20."""
        entity = EntityItem(QPointF(0, 0))
        assert entity.ac == 20
    
    def test_entity_hp_setter(self, scene):
        """EntityItem HP can be modified."""
        entity = EntityItem(QPointF(0, 0))
        entity.hp = 50
        assert entity.hp == 50
    
    def test_entity_hp_clamped(self, scene):
        """EntityItem HP is clamped between 0 and max_hp."""
        entity = EntityItem(QPointF(0, 0))
        entity.hp = -10
        assert entity.hp == 0
        entity.hp = 200
        assert entity.hp == 100  # Clamped to max
    
    def test_entity_snap_on_release(self, scene):
        """EntityItem snaps to cell center on mouse release."""
        import math
        from unittest.mock import patch
        from PySide6.QtWidgets import QGraphicsItem
        
        # Initial pos (not snapped yet)
        pos = QPointF(150, 200)
        entity = EntityItem(pos)
        scene.addItem(entity)
        
        # Simulate moving to a new non-snapped position
        new_pos = QPointF(160, 210)
        entity.setPos(new_pos)
        assert entity.pos() == new_pos  # Should NOT snap during move
        
        # Call mouseReleaseEvent with patched super() and mock event
        from unittest.mock import MagicMock
        mock_event = MagicMock()
        # Set mouse position to a specific location (e.g. 170, 220) which is in different cell if close to border?
        # Let's use the same position as new_pos for simplicity, or slightly different to prove it uses mouse
        mouse_scene_pos = QPointF(162, 212) 
        mock_event.scenePos.return_value = mouse_scene_pos
        
        with patch.object(QGraphicsItem, 'mouseReleaseEvent', return_value=None):
            entity.mouseReleaseEvent(mock_event)
        
        # Now it should be snapped based on MOUSE position
        half_grid = GRID_SIZE / 2
        expected_x = math.floor(mouse_scene_pos.x() / GRID_SIZE) * GRID_SIZE + half_grid
        expected_y = math.floor(mouse_scene_pos.y() / GRID_SIZE) * GRID_SIZE + half_grid
        assert entity.pos() == QPointF(expected_x, expected_y)
    
    def test_entity_is_selectable(self, scene):
        """EntityItem should be selectable."""
        entity = EntityItem(QPointF(0, 0))
        scene.addItem(entity)
        assert entity.flags() & entity.GraphicsItemFlag.ItemIsSelectable
    
    def test_entity_is_movable(self, scene):
        """EntityItem should be movable."""
        entity = EntityItem(QPointF(0, 0))
        scene.addItem(entity)
        assert entity.flags() & entity.GraphicsItemFlag.ItemIsMovable
    
    def test_entity_bounding_rect(self, scene):
        """EntityItem has a valid bounding rect."""
        entity = EntityItem(QPointF(0, 0))
        rect = entity.boundingRect()
        assert rect.width() > 0
        assert rect.height() > 0

    def test_entity_size_clamped(self, scene):
        """Entity footprint sizes should be clamped to 1..6."""
        entity = EntityItem(QPointF(0, 0), size_w_cells=0, size_h_cells=99, lock_square=False)
        assert entity.size_w_cells == 1
        assert entity.size_h_cells == 6

    def test_entity_bounding_rect_scales_with_size(self, scene):
        """Larger footprint should produce larger bounds."""
        small = EntityItem(QPointF(0, 0), size_w_cells=1, size_h_cells=1, lock_square=False)
        large = EntityItem(QPointF(0, 0), size_w_cells=3, size_h_cells=2, lock_square=False)
        small_rect = small.boundingRect()
        large_rect = large.boundingRect()
        assert large_rect.width() > small_rect.width()
        assert large_rect.height() > small_rect.height()

    def test_entity_size_setter_with_scene_does_not_crash(self, scene):
        """Changing size on scene-mounted entity should not crash across Qt return variants."""
        entity = EntityItem(QPointF(0, 0), lock_square=False)
        scene.addItem(entity)
        entity.size_w_cells = 2
        entity.size_h_cells = 3
        assert entity.size_w_cells == 2
        assert entity.size_h_cells == 3

    def test_entity_missing_icon_status(self, scene):
        """Missing icon path should be reported without errors."""
        entity = EntityItem(QPointF(0, 0), icon_path="does_not_exist_icon.png")
        assert entity.icon_status() == "missing"

    def test_entity_dead_hp_renders_red_x_overlay(self, app):
        """Dead entities should render a red X overlay on the token."""
        def _render_scene_with_hp(hp_value: int) -> QImage:
            local_scene = QGraphicsScene()
            local_scene.setSceneRect(0, 0, 120, 120)
            entity = EntityItem(QPointF(60, 60), hp=hp_value, max_hp=100)
            local_scene.addItem(entity)
            image = QImage(120, 120, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            local_scene.render(painter, QRectF(0, 0, 120, 120), QRectF(0, 0, 120, 120))
            painter.end()
            return image

        alive_image = _render_scene_with_hp(50)
        dead_image = _render_scene_with_hp(0)

        def _count_red_pixels(image: QImage) -> int:
            count = 0
            for y in range(30, 90):
                for x in range(30, 90):
                    c = image.pixelColor(x, y)
                    if c.red() >= 200 and c.green() <= 100 and c.blue() <= 100 and c.alpha() >= 180:
                        count += 1
            return count

        alive_red_pixels = _count_red_pixels(alive_image)
        dead_red_pixels = _count_red_pixels(dead_image)
        assert dead_red_pixels > alive_red_pixels + 30

    def test_entity_duplicate_badge_hidden_for_single_instance(self, scene):
        """Duplicate badge should stay hidden when no same-type duplicate exists."""
        entity = EntityItem(QPointF(0, 0))
        entity.setData(ROLE_LABEL, "Goblin")
        entity.setData(ROLE_ENTITY_ID, "goblin-1")
        scene.addItem(entity)
        assert entity._duplicate_instance_badge_text() == ""

    def test_entity_duplicate_badge_uses_stable_index_for_same_label(self, scene):
        """Duplicate badge text should be a stable per-instance index among same labels."""
        first = EntityItem(QPointF(0, 0))
        first.setData(ROLE_LABEL, "Goblin")
        first.setData(ROLE_ENTITY_ID, "goblin-1")

        second = EntityItem(QPointF(40, 0))
        second.setData(ROLE_LABEL, "goblin")
        second.setData(ROLE_ENTITY_ID, "goblin-2")

        other = EntityItem(QPointF(80, 0))
        other.setData(ROLE_LABEL, "Orc")
        other.setData(ROLE_ENTITY_ID, "orc-1")

        scene.addItem(first)
        scene.addItem(second)
        scene.addItem(other)

        assert first._duplicate_instance_badge_text() == "1"
        assert second._duplicate_instance_badge_text() == "2"
        assert other._duplicate_instance_badge_text() == ""


class TestWallItem:
    """Tests for WallItem class."""
    
    def test_wall_creation(self, scene):
        """WallItem can be instantiated."""
        wall = WallItem(0, 0, 100, 100)
        assert wall is not None
    
    def test_wall_line_coords(self, scene):
        """WallItem line coordinates are correct."""
        wall = WallItem(10, 20, 30, 40)
        line = wall.line()
        assert line.p1().x() == 10
        assert line.p1().y() == 20
        assert line.p2().x() == 30
        assert line.p2().y() == 40
    
    def test_wall_shape_is_wider(self, scene):
        """WallItem shape is wider than the line for easier selection."""
        wall = WallItem(0, 0, 100, 0)
        scene.addItem(wall)
        shape = wall.shape()
        bounding = shape.boundingRect()
        # Shape should be wider than just a line (has padding)
        assert bounding.height() > 1


class TestDungeonEllipseItem:
    """Tests for DungeonEllipseItem class."""
    
    def test_ellipse_creation(self, scene):
        """DungeonEllipseItem can be instantiated."""
        ellipse = DungeonEllipseItem(QRectF(0, 0, 100, 50))
        assert ellipse is not None
    
    def test_ellipse_is_selectable(self, scene):
        """DungeonEllipseItem should be selectable."""
        ellipse = DungeonEllipseItem(QRectF(0, 0, 100, 50))
        scene.addItem(ellipse)
        assert ellipse.flags() & ellipse.GraphicsItemFlag.ItemIsSelectable


class TestGridConstants:
    """Tests for grid-related constants."""
    
    def test_grid_size(self):
        """GRID_SIZE should be 58px."""
        assert GRID_SIZE == 58


def test_ping_item_does_not_emit_callbacks_after_scene_clear(qtbot):
    """Clearing a scene during active ping animation should not trigger deleted-object callbacks."""
    scene = QGraphicsScene()
    item = PingItem(QPointF(20, 20))
    scene.addItem(item)
    _debug_log("created PingItem and added to scene")

    # This mirrors real lifecycle teardown where scene-owned items are deleted
    # while animations may still be running.
    scene.clear()
    _debug_log("cleared scene while ping animation active")

    # If callback wiring is unsafe, pytest-qt will surface Qt event loop exceptions here.
    qtbot.wait(950)
    _debug_log("waited for animation window without Qt callback exceptions")
