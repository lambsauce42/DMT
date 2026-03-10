from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import (
    QGraphicsLineItem, 
    QGraphicsEllipseItem, 
    QGraphicsItem, 
    QStyleOptionGraphicsItem, 
    QWidget,
    QStyle,
    QGraphicsItemGroup,
    QGraphicsItemGroup,
    QGraphicsRectItem,
    QGraphicsPolygonItem,
    QGraphicsPathItem,
    QMenu,
)
from PySide6.QtGui import QPen, QColor, QPainter, QPainterPath, QPolygonF, QBrush, QPainterPathStroker, QPixmap
from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QEasingCurve
from dungeon_constants import GRID_SIZE, FLOOR_COLOR, WALL_COLOR, WALL_WIDTH, ROLE_LABEL, ROLE_ENTITY_ID

try:
    import shiboken6
except Exception:  # pragma: no cover - optional runtime guard
    shiboken6 = None


def _qt_object_is_valid(obj: object) -> bool:
    if shiboken6 is None:
        return True
    try:
        return bool(shiboken6.isValid(obj))
    except Exception:
        return False


class FogItem(QGraphicsPathItem):
    """
    Fog of War overlay item.
    """
    def __init__(self, parent: QGraphicsItem | None = None):
        super().__init__(parent)
        self.setZValue(200) # Always on top
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QColor(0, 0, 0))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        
        # We start with a large rectangle covering everything
        # Or empty if we want to "add" fog. User said "spawn everywhere".
        # Let's start empty and let user spawn.
        self._view_mode = "dm"
        self._update_opacity()

    def set_view_mode(self, mode: str):
        self._view_mode = mode
        self._update_opacity()

    def _update_opacity(self):
        if self._view_mode == "player":
            self.setOpacity(1.0)
        else:
            self.setOpacity(0.5)


class RoomGroup(QGraphicsItemGroup):
    """
    A group that contains a floor rectangle and its surrounding walls.
    When selected/moved, all children move together.
    """
    def __init__(self, parent: QGraphicsItem | None = None):
        super().__init__(parent)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
    
    def add_floor(self, rect: QRectF) -> QGraphicsRectItem:
        """Add the floor rectangle to the group."""
        floor = QGraphicsRectItem(rect)
        floor.setBrush(QColor(FLOOR_COLOR))
        floor.setPen(QPen(Qt.PenStyle.NoPen))
        floor.setZValue(0)
        self.addToGroup(floor)
        return floor

    def add_polygon_floor(self, polygon: QPolygonF) -> QGraphicsPolygonItem:
        """Add a polygonal floor to the group."""
        floor = QGraphicsPolygonItem(polygon)
        floor.setBrush(QColor(FLOOR_COLOR))
        floor.setPen(QPen(Qt.PenStyle.NoPen))
        floor.setZValue(0)
        self.addToGroup(floor)
        return floor
    
    def add_path_floor(self, path: QPainterPath) -> QGraphicsPathItem:
        """Add a custom path floor to the group."""
        floor = QGraphicsPathItem(path)
        floor.setBrush(QColor(FLOOR_COLOR))
        floor.setPen(QPen(Qt.PenStyle.NoPen))
        floor.setZValue(0)
        self.addToGroup(floor)
        return floor
    
    def add_wall(self, x1: float, y1: float, x2: float, y2: float) -> 'WallItem':
        """Add a wall to the group."""
        wall = WallItem(x1, y1, x2, y2)
        wall.setZValue(1)
        # Disable individual selection/movement since group handles it
        wall.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        wall.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.addToGroup(wall)
        return wall

    def floor_path(self) -> QPainterPath:
        """Return the room floor path in room-local coordinates."""
        for child in self.childItems():
            if isinstance(child, WallItem):
                continue
            if isinstance(child, QGraphicsPathItem):
                path = child.path()
            elif isinstance(child, QGraphicsRectItem):
                path = QPainterPath()
                path.addRect(child.rect())
            elif isinstance(child, QGraphicsPolygonItem):
                path = QPainterPath()
                path.addPolygon(child.polygon())
                path.closeSubpath()
            else:
                path = child.shape()
            return path.translated(child.pos())
        return QPainterPath()

    def rebuild_from_path(self, path: QPainterPath) -> None:
        """Replace floor + walls with a new path outline."""
        scene = self.scene()
        for child in list(self.childItems()):
            self.removeFromGroup(child)
            if scene is not None and child.scene() is scene:
                scene.removeItem(child)
        self.add_path_floor(path)
        polygons = path.toSubpathPolygons()
        for poly in polygons:
            if poly.count() <= 1:
                continue
            for idx in range(poly.count()):
                p1 = poly[idx]
                p2 = poly[(idx + 1) % poly.count()]
                if (p1 - p2).manhattanLength() <= 0.1:
                    continue
                self.add_wall(p1.x(), p1.y(), p2.x(), p2.y())


class WallItem(QGraphicsLineItem):
    def __init__(self, x1: float, y1: float, x2: float, y2: float, parent: QGraphicsItem | None = None):
        super().__init__(x1, y1, x2, y2, parent)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setPen(QPen(QColor(WALL_COLOR), WALL_WIDTH))
        
    def shape(self) -> QPainterPath:
        """Override to provide a wider hitbox for easy selection."""
        path = QPainterPath()
        line = self.line()
        p1 = line.p1()
        p2 = line.p2()
        
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        length = (dx*dx + dy*dy)**0.5
        
        if length == 0:
            return super().shape()
            
        PADDING = 10.0
        nx = -dy / length
        ny = dx / length
        
        offset_x = nx * PADDING
        offset_y = ny * PADDING
        
        path.moveTo(p1.x() - offset_x, p1.y() - offset_y)
        path.lineTo(p2.x() - offset_x, p2.y() - offset_y)
        path.lineTo(p2.x() + offset_x, p2.y() + offset_y)
        path.lineTo(p1.x() + offset_x, p1.y() + offset_y)
        path.closeSubpath()
        return path

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        """Custom paint to show a glow when selected instead of dashed box."""
        is_selected = option.state & QStyle.StateFlag.State_Selected
        
        # Remove selected state from option so super() doesn't draw default selection
        # We manually modify the option style
        # Actually, copy option if we could, but we can just manipulate painter
        
        if is_selected:
            # Draw glow
            pen = self.pen()
            glow_pen = QPen(QColor(100, 149, 237, 150), pen.width() + 6)
            glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(glow_pen)
            painter.drawLine(self.line())
            
        super().paint(painter, option, widget)

class DungeonEllipseItem(RoomGroup):
    """
    Representation of an elliptical room using segmented walls
    to allow for cutting/merging operations.
    """
    def __init__(self, rect: QRectF, parent: QGraphicsItem | None = None):
        super().__init__(parent)
        from dungeon_constants import ROLE_KIND, TOOL_ELLIPSE
        self.setData(ROLE_KIND, TOOL_ELLIPSE)
        
        # 1. Create Floor
        path = QPainterPath()
        path.addEllipse(rect)
        self.add_path_floor(path)
        
        # 2. Create Walls (Segments)
        import math
        cx, cy = rect.center().x(), rect.center().y()
        rx, ry = rect.width() / 2.0, rect.height() / 2.0
        
        # Number of segments scaling with size, but at least 32, max 128?
        # Fixed 64 is reasonably smooth
        segments = 64
        pts = []
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            # Use top-left relative coordinates from rect
            px = cx + rx * math.cos(angle)
            py = cy + ry * math.sin(angle)
            pts.append(QPointF(px, py))
            
        for i in range(segments):
            p1 = pts[i]
            p2 = pts[(i + 1) % segments]
            self.add_wall(p1.x(), p1.y(), p2.x(), p2.y())


class EntityItem(QGraphicsItem):
    """Entity token with optional icon, DM-only HP ring + AC chip, and NxN footprint."""
    def __init__(
        self,
        position: QPointF,
        color: QColor = None,
        hp: int = 100,
        max_hp: int = 100,
        ac: int = 20,
        strength: int = 10,
        dexterity: int = 10,
        constitution: int = 10,
        intelligence: int = 10,
        wisdom: int = 10,
        charisma: int = 10,
        actions: str = "",
        description: str = "",
        icon_path: str = "",
        size_w_cells: int = 1,
        size_h_cells: int = 1,
        lock_square: bool = True,
        parent: QGraphicsItem | None = None,
    ):
        super().__init__(parent)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        
        # Entity properties
        self._color = color if color else QColor("#3B82F6")  # Default blue
        self._hp = hp
        self._max_hp = max_hp
        self._ac = ac
        self.strength = strength
        self.dexterity = dexterity
        self.constitution = constitution
        self.intelligence = intelligence
        self.wisdom = wisdom
        self.charisma = charisma
        self.actions = actions
        self.description = description

        # Grid size for snapping
        from dungeon_constants import GRID_SIZE
        self._grid_size = GRID_SIZE

        self._icon_path = icon_path or ""
        self._size_w_cells = self._clamp_cell_size(size_w_cells)
        self._size_h_cells = self._clamp_cell_size(size_h_cells)
        self._lock_square = bool(lock_square)
        if self._lock_square:
            self._size_h_cells = self._size_w_cells
        self._icon_cache_key: str | None = None
        self._icon_cache_pixmap = QPixmap()
        self._player_stats_visible = False
        self._duplicate_badge_text_cache = ""
        self._duplicate_badge_cache_valid = False
        self._duplicate_badge_cache_type_key = ""
        self._duplicate_badge_cache_entity_id = ""

        self.setPos(position)
        self.setZValue(10)  # Entities on top

    @staticmethod
    def _clamp_cell_size(value: int) -> int:
        try:
            as_int = int(value)
        except (TypeError, ValueError):
            as_int = 1
        return max(1, min(6, as_int))

    @property
    def size_w_cells(self) -> int:
        return self._size_w_cells

    @size_w_cells.setter
    def size_w_cells(self, value: int):
        clamped = self._clamp_cell_size(value)
        if clamped == self._size_w_cells and not self._lock_square:
            return
        old_scene_rect = self._scene_bounds_rect()
        self.prepareGeometryChange()
        self._size_w_cells = clamped
        if self._lock_square:
            self._size_h_cells = clamped
        self.update()
        self._invalidate_scene_bounds(old_scene_rect)

    @property
    def size_h_cells(self) -> int:
        return self._size_h_cells

    @size_h_cells.setter
    def size_h_cells(self, value: int):
        clamped = self._clamp_cell_size(value)
        if self._lock_square:
            clamped = self._size_w_cells
        if clamped == self._size_h_cells:
            return
        old_scene_rect = self._scene_bounds_rect()
        self.prepareGeometryChange()
        self._size_h_cells = clamped
        self.update()
        self._invalidate_scene_bounds(old_scene_rect)

    @property
    def lock_square(self) -> bool:
        return self._lock_square

    @lock_square.setter
    def lock_square(self, value: bool):
        value_bool = bool(value)
        if value_bool == self._lock_square:
            return
        old_scene_rect = self._scene_bounds_rect()
        self.prepareGeometryChange()
        self._lock_square = value_bool
        self.update()
        self._invalidate_scene_bounds(old_scene_rect)

    @property
    def icon_path(self) -> str:
        return self._icon_path

    @icon_path.setter
    def icon_path(self, value: str):
        normalized = str(value or "")
        if normalized == self._icon_path:
            return
        self._icon_path = normalized
        self._icon_cache_key = None
        self._icon_cache_pixmap = QPixmap()
        self.update()

    def icon_status(self) -> str:
        if not self._icon_path:
            return "default"
        icon_file = Path(self._icon_path)
        if not icon_file.exists() or not icon_file.is_file():
            return "missing"
        pix = QPixmap(str(icon_file))
        if pix.isNull():
            return "invalid"
        return "ok"

    def _token_rect(self) -> QRectF:
        margin_px = 8.0
        width = max(12.0, self._grid_size * self._size_w_cells - margin_px * 2)
        height = max(12.0, self._grid_size * self._size_h_cells - margin_px * 2)
        return QRectF(-width / 2.0, -height / 2.0, width, height)

    def _ring_width(self, rect: QRectF) -> float:
        return max(5.0, min(13.0, min(rect.width(), rect.height()) * 0.125))

    @staticmethod
    def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
        t_clamped = max(0.0, min(1.0, float(t)))
        r = int(c1.red() + (c2.red() - c1.red()) * t_clamped)
        g = int(c1.green() + (c2.green() - c1.green()) * t_clamped)
        b = int(c1.blue() + (c2.blue() - c1.blue()) * t_clamped)
        return QColor(r, g, b)

    def _hp_color(self, ratio: float) -> QColor:
        ratio_clamped = max(0.0, min(1.0, float(ratio)))
        red = QColor("#ef4444")
        yellow = QColor("#eab308")
        green = QColor("#22c55e")
        if ratio_clamped <= 0.5:
            return self._lerp_color(red, yellow, ratio_clamped / 0.5)
        return self._lerp_color(yellow, green, (ratio_clamped - 0.5) / 0.5)

    def _scene_bounds_rect(self) -> QRectF:
        mapped = self.mapRectToScene(self.boundingRect())
        if isinstance(mapped, QRectF):
            return mapped
        return mapped.boundingRect()

    def _invalidate_scene_bounds(self, old_scene_rect: QRectF | None = None) -> None:
        scene = self.scene()
        if scene is None:
            return
        new_scene_rect = self._scene_bounds_rect()
        dirty_rect = new_scene_rect if old_scene_rect is None else old_scene_rect.united(new_scene_rect)
        scene.update(dirty_rect.adjusted(-2.0, -2.0, 2.0, 2.0))

    def _icon_pixmap(self) -> QPixmap:
        if not self._icon_path:
            return QPixmap()
        cache_key = self._icon_path
        if self._icon_cache_key == cache_key and not self._icon_cache_pixmap.isNull():
            return self._icon_cache_pixmap
        source = QPixmap(self._icon_path)
        if source.isNull():
            self._icon_cache_key = cache_key
            self._icon_cache_pixmap = QPixmap()
            return self._icon_cache_pixmap
        self._icon_cache_key = cache_key
        self._icon_cache_pixmap = source
        return source

    def _entity_type_key(self) -> str:
        label = str(self.data(ROLE_LABEL) or "").strip()
        if not label:
            return "entity"
        return label.casefold()

    def _set_duplicate_instance_badge_text(self, text: str) -> None:
        normalized = str(text or "").strip()
        current_type_key = self._entity_type_key()
        current_entity_id = str(self.data(ROLE_ENTITY_ID) or "").strip()
        if (
            self._duplicate_badge_cache_valid
            and self._duplicate_badge_text_cache == normalized
            and self._duplicate_badge_cache_type_key == current_type_key
            and self._duplicate_badge_cache_entity_id == current_entity_id
        ):
            return
        self._duplicate_badge_text_cache = normalized
        self._duplicate_badge_cache_valid = True
        self._duplicate_badge_cache_type_key = current_type_key
        self._duplicate_badge_cache_entity_id = current_entity_id
        self.update()

    def _compute_duplicate_instance_badge_text(self) -> str:
        scene = self.scene()
        if scene is None:
            return ""
        entity_type = self._entity_type_key()
        same_type_entities: list[EntityItem] = []
        for item in scene.items():
            if not isinstance(item, EntityItem):
                continue
            if item._entity_type_key() == entity_type:
                same_type_entities.append(item)
        if len(same_type_entities) < 2:
            return ""

        def _sort_key(item: EntityItem) -> tuple[int, str, float, float, int]:
            entity_id = str(item.data(ROLE_ENTITY_ID) or "").strip()
            return (
                0 if entity_id else 1,
                entity_id.casefold(),
                round(item.pos().y(), 3),
                round(item.pos().x(), 3),
                id(item),
            )

        same_type_entities.sort(key=_sort_key)
        try:
            index = same_type_entities.index(self) + 1
        except ValueError:
            return ""
        return str(index) if index <= 99 else "99+"

    def _duplicate_instance_badge_text(self) -> str:
        current_type_key = self._entity_type_key()
        current_entity_id = str(self.data(ROLE_ENTITY_ID) or "").strip()
        if (
            self._duplicate_badge_cache_valid
            and self._duplicate_badge_cache_type_key == current_type_key
            and self._duplicate_badge_cache_entity_id == current_entity_id
        ):
            return self._duplicate_badge_text_cache
        badge_text = self._compute_duplicate_instance_badge_text()
        self._duplicate_badge_text_cache = badge_text
        self._duplicate_badge_cache_valid = True
        self._duplicate_badge_cache_type_key = current_type_key
        self._duplicate_badge_cache_entity_id = current_entity_id
        return badge_text
    
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
    
    @property
    def hp(self) -> int:
        return self._hp
    
    @hp.setter
    def hp(self, value: int):
        self._hp = max(0, min(value, self._max_hp))
        self.update()

    @property
    def view_mode(self) -> str:
        return getattr(self, "_view_mode", "dm")

    def set_view_mode(self, mode: str):
        self._view_mode = mode
        self.update()

    @property
    def player_stats_visible(self) -> bool:
        return bool(self._player_stats_visible)

    def set_player_stats_visible(self, visible: bool) -> None:
        visible_bool = bool(visible)
        if visible_bool == self._player_stats_visible:
            return
        self._player_stats_visible = visible_bool
        self.update()
    
    @property
    def ac(self) -> int:
        return self._ac
    
    @ac.setter
    def ac(self, value: int):
        self._ac = value
        self.update()
    
    def boundingRect(self) -> QRectF:
        token_rect = self._token_rect()
        ring_pad = self._ring_width(token_rect) + 5.0
        return token_rect.adjusted(-ring_pad, -ring_pad, ring_pad, ring_pad)
    
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        token_rect = self._token_rect()
        ring_width = self._ring_width(token_rect)
        chip_size = max(20.0, min(40.0, min(token_rect.width(), token_rect.height()) * 0.34))
        if option.state & QStyle.StateFlag.State_Selected:
            glow_pen = QPen(QColor(100, 149, 237, 140), max(4.0, ring_width + 2.0))
            painter.setPen(glow_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(token_rect.adjusted(-3.0, -3.0, 3.0, 3.0))

        icon_rect = token_rect
        icon = self._icon_pixmap()
        if not icon.isNull():
            clip = QPainterPath()
            clip.addEllipse(icon_rect)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.setClipPath(clip)
            source_rect = QRectF(0.0, 0.0, float(icon.width()), float(icon.height()))
            painter.drawPixmap(icon_rect, icon, source_rect)
            painter.restore()
        else:
            painter.setPen(QPen(self._color.darker(120), 1))
            painter.setBrush(self._color)
            painter.drawEllipse(token_rect)

        if self._hp <= 0:
            x_size = max(7.0, min(icon_rect.width(), icon_rect.height()) * 0.38)
            x_half = x_size / 2.0
            x_center = icon_rect.center()
            x_p1 = QPointF(x_center.x() - x_half, x_center.y() - x_half)
            x_p2 = QPointF(x_center.x() + x_half, x_center.y() + x_half)
            x_p3 = QPointF(x_center.x() - x_half, x_center.y() + x_half)
            x_p4 = QPointF(x_center.x() + x_half, x_center.y() - x_half)

            outline_width = max(2.0, ring_width * 0.38)
            stroke_width = max(1.0, ring_width * 0.22)
            painter.setPen(QPen(QColor(15, 23, 42, 210), outline_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(x_p1, x_p2)
            painter.drawLine(x_p3, x_p4)
            painter.setPen(QPen(QColor("#ef4444"), stroke_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(x_p1, x_p2)
            painter.drawLine(x_p3, x_p4)

        if self.view_mode == "dm" or self.player_stats_visible:
            hp_ratio = self._hp / self._max_hp if self._max_hp > 0 else 0
            hp_color = self._hp_color(hp_ratio)

            ring_rect = token_rect.adjusted(
                -ring_width / 2.0 - 1.0,
                -ring_width / 2.0 - 1.0,
                ring_width / 2.0 + 1.0,
                ring_width / 2.0 + 1.0,
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#27272a"), ring_width))
            painter.drawEllipse(ring_rect)
            if hp_ratio > 0:
                painter.setPen(QPen(hp_color, ring_width))
                painter.drawArc(
                    ring_rect,
                    90 * 16,
                    int(-360 * 16 * hp_ratio),
                )

            shield_x = token_rect.right() - chip_size * 0.78
            shield_y = token_rect.bottom() - chip_size * 0.78
            shield_cx = shield_x + chip_size / 2.0
            shield_top = shield_y
            shield_bottom = shield_y + chip_size
            shield_left = shield_x + 1.0
            shield_right = shield_x + chip_size - 1.0
            shield_path = QPainterPath()
            shield_path.moveTo(shield_cx, shield_top)
            shield_path.quadTo(shield_right, shield_top, shield_right, shield_top + chip_size * 0.32)
            shield_path.lineTo(shield_right, shield_top + chip_size * 0.55)
            shield_path.lineTo(shield_cx, shield_bottom)
            shield_path.lineTo(shield_left, shield_top + chip_size * 0.55)
            shield_path.lineTo(shield_left, shield_top + chip_size * 0.32)
            shield_path.quadTo(shield_left, shield_top, shield_cx, shield_top)
            shield_path.closeSubpath()
            painter.setPen(QPen(QColor("#71717a"), 1))
            painter.setBrush(QColor("#3f3f46"))
            painter.drawPath(shield_path)
            chip_rect = QRectF(shield_x, shield_y - 0.8, chip_size, chip_size - 1.8)
            painter.setPen(QColor("#fafafa"))
            font = painter.font()
            font.setPixelSize(9)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, str(self._ac))

        duplicate_badge = self._duplicate_instance_badge_text()
        if duplicate_badge:
            count_size = max(14.0, chip_size * 0.82)
            count_x = token_rect.left() - count_size * 0.22
            count_y = token_rect.bottom() - count_size * 0.78
            count_rect = QRectF(count_x, count_y, count_size, count_size)
            painter.setPen(QPen(QColor("#71717a"), 1))
            painter.setBrush(QColor("#3f3f46"))
            painter.drawEllipse(count_rect)
            painter.setPen(QColor("#fafafa"))
            count_font = painter.font()
            count_font.setPixelSize(max(8, min(12, int(round(count_size * 0.52)))))
            count_font.setBold(True)
            painter.setFont(count_font)
            painter.drawText(count_rect, Qt.AlignmentFlag.AlignCenter, duplicate_badge)


class PingItem(QGraphicsEllipseItem):
    """
    Ping effect that spawns a growing and fading circle.
    """
    def __init__(self, position: QPointF, parent: QGraphicsItem | None = None):
        super().__init__(parent)
        self._max_radius = 80
        self._duration = 800
        
        # Initial state
        self.setRect(-1, -1, 2, 2)
        self.setPos(position)
        self.setZValue(1000) # Above everything (FoW is 200, Entities 10)
        
        self.setPen(QPen(QColor(255, 255, 200), 3)) # Bright white-yellow
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        
        # Animation
        # QGraphicsItem is not a QObject, so QVariantAnimation cannot use this
        # item as QObject parent.
        self.anim = QVariantAnimation()
        self.anim.setDuration(self._duration)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._on_anim_value_changed)
        self.anim.finished.connect(self._on_anim_finished)
        self._finished = False
        self.restart_animation()

    def restart_animation(self):
        if not _qt_object_is_valid(self):
            return
        self._finished = False
        self.setOpacity(1.0)
        self.setRect(-1, -1, 2, 2)
        self.anim.stop()
        self.anim.start()

    def stop_animation(self):
        try:
            self.anim.stop()
        except RuntimeError:
            return

    def itemChange(self, change, value):
        if (
            change == QGraphicsItem.GraphicsItemChange.ItemSceneHasChanged
            and value is None
        ):
            self.stop_animation()
        return super().itemChange(change, value)

    def _on_anim_value_changed(self, value: float):
        if not _qt_object_is_valid(self):
            return
        # Outer circle
        outer_radius = value * self._max_radius
        self.setRect(-outer_radius, -outer_radius, outer_radius * 2, outer_radius * 2)
        
        # Inner circle radius (max 7.5px)
        self._inner_radius = value * 7.5
        
        # Fade out in the last 30% of animation
        opacity = 1.0
        if value > 0.7:
            opacity = 1.0 - (value - 0.7) / 0.3
        self.setOpacity(opacity)
        self.update()

    def _on_anim_finished(self):
        if not _qt_object_is_valid(self):
            return
        self._finished = True
        scene = self.scene()
        if scene is not None:
            scene.removeItem(self)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Draw outer circle
        super().paint(painter, option, widget)
        
        # Draw inner expanding filled circle
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self.pen().color()))
        r = getattr(self, "_inner_radius", 0)
        painter.drawEllipse(QPointF(0, 0), r, r)


class DungeonImageItem(QGraphicsItem):
    """
    An image item that can be moved, resized, and have its aspect ratio locked.
    """
    def __init__(self, pixmap: QPixmap, position: QPointF, source_path: str = "", parent=None):
        super().__init__(parent)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        self._source_path = str(source_path or "")
        if pixmap.isNull():
            pixmap = self._placeholder_pixmap(120, 90)
        self._pixmap = pixmap
        self._rect = QRectF(0, 0, max(20, pixmap.width()), max(20, pixmap.height()))
        self._keep_aspect = False
        self._aspect_ratio = pixmap.width() / pixmap.height() if pixmap.height() > 0 else 1.0
        
        self.setPos(position)
        self.setZValue(5) # Below entities (10) but above floor
        
        self._resizing = False
        self._resize_start_rect = None
        self._resize_start_pos: QPointF | None = None
        self._resize_handle: str | None = None
        self._resize_anchor_scene: QPointF | None = None
        self._on_resize_finished: Callable[[QRectF, QRectF, QPointF, QPointF], None] | None = None
        self._resize_handle_size = 12
        self.setAcceptHoverEvents(True)

    @staticmethod
    def _placeholder_pixmap(width: int, height: int) -> QPixmap:
        safe_w = max(20, int(width))
        safe_h = max(20, int(height))
        pix = QPixmap(safe_w, safe_h)
        pix.fill(QColor("#111827"))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#374151"), 2))
        painter.drawLine(0, 0, safe_w, safe_h)
        painter.drawLine(0, safe_h, safe_w, 0)
        painter.end()
        return pix

    @property
    def source_path(self) -> str:
        return self._source_path

    @source_path.setter
    def source_path(self, value: str) -> None:
        self._source_path = str(value or "")

    @property
    def keep_aspect(self) -> bool:
        return self._keep_aspect

    @keep_aspect.setter
    def keep_aspect(self, value: bool) -> None:
        self._keep_aspect = bool(value)

    def set_resize_finished_callback(
        self,
        callback: Callable[[QRectF, QRectF, QPointF, QPointF], None] | None,
    ) -> None:
        self._on_resize_finished = callback

    def set_rect_size(self, width: float, height: float) -> None:
        new_width = max(20.0, float(width))
        new_height = max(20.0, float(height))
        if (
            abs(self._rect.width() - new_width) < 0.001
            and abs(self._rect.height() - new_height) < 0.001
        ):
            return
        self.prepareGeometryChange()
        self._rect.setWidth(new_width)
        self._rect.setHeight(new_height)
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-self._resize_handle_size, -self._resize_handle_size, 
                                   self._resize_handle_size, self._resize_handle_size)

    @staticmethod
    def _cursor_for_handle(handle: str | None) -> Qt.CursorShape:
        if handle in {"top_left", "bottom_right"}:
            return Qt.CursorShape.SizeFDiagCursor
        if handle in {"top_right", "bottom_left"}:
            return Qt.CursorShape.SizeBDiagCursor
        return Qt.CursorShape.ArrowCursor

    @staticmethod
    def _build_target_rect(anchor: QPointF, moving: QPointF, min_size: float, handle: str | None) -> QRectF:
        ax = float(anchor.x())
        ay = float(anchor.y())
        mx = float(moving.x())
        my = float(moving.y())

        if handle == "top_left":
            mx = min(mx, ax - min_size)
            my = min(my, ay - min_size)
        elif handle == "top_right":
            mx = max(mx, ax + min_size)
            my = min(my, ay - min_size)
        elif handle == "bottom_left":
            mx = min(mx, ax - min_size)
            my = max(my, ay + min_size)
        elif handle == "bottom_right":
            mx = max(mx, ax + min_size)
            my = max(my, ay + min_size)
        else:
            if abs(mx - ax) < min_size:
                mx = ax + min_size if mx >= ax else ax - min_size
            if abs(my - ay) < min_size:
                my = ay + min_size if my >= ay else ay - min_size

        return QRectF(QPointF(ax, ay), QPointF(mx, my)).normalized()

    def _handle_rects(self) -> dict[str, QRectF]:
        s = float(self._resize_handle_size)
        return {
            "top_left": QRectF(self._rect.left(), self._rect.top(), s, s),
            "top_right": QRectF(self._rect.right() - s, self._rect.top(), s, s),
            "bottom_left": QRectF(self._rect.left(), self._rect.bottom() - s, s, s),
            "bottom_right": QRectF(self._rect.right() - s, self._rect.bottom() - s, s, s),
        }

    def _detect_resize_handle(self, local_pos: QPointF) -> str | None:
        for handle_name, handle_rect in self._handle_rects().items():
            if handle_rect.contains(local_pos):
                return handle_name
        return None

    @staticmethod
    def _handle_signs(handle: str | None) -> tuple[float, float]:
        if handle == "top_left":
            return -1.0, -1.0
        if handle == "top_right":
            return 1.0, -1.0
        if handle == "bottom_left":
            return -1.0, 1.0
        return 1.0, 1.0

    def _apply_aspect_ratio(self, target_rect: QRectF, handle: str | None, anchor_scene: QPointF) -> QRectF:
        if self._aspect_ratio <= 1e-6:
            return target_rect
        width = float(target_rect.width())
        height = float(target_rect.height())
        if width <= 1e-6 or height <= 1e-6:
            return target_rect
        if width / height > self._aspect_ratio:
            width = height * self._aspect_ratio
        else:
            height = width / self._aspect_ratio
        sign_x, sign_y = self._handle_signs(handle)
        moving = QPointF(anchor_scene.x() + sign_x * width, anchor_scene.y() + sign_y * height)
        return QRectF(anchor_scene, moving).normalized()

    def _opposite_corner_local(self, handle: str | None) -> QPointF:
        if handle == "top_left":
            return self._rect.bottomRight()
        if handle == "top_right":
            return self._rect.bottomLeft()
        if handle == "bottom_left":
            return self._rect.topRight()
        return self._rect.topLeft()

    def paint(self, painter: QPainter, option, widget=None):
        painter.drawPixmap(self._rect.toRect(), self._pixmap)
        
        if self.isSelected():
            # Draw selection border
            pen = QPen(QColor("#60a5fa"), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(self._rect)
            
            # Draw resize handles at all corners.
            painter.setBrush(QColor("#60a5fa"))
            painter.setPen(Qt.PenStyle.NoPen)
            for handle_rect in self._handle_rects().values():
                painter.drawRect(handle_rect)

    def mousePressEvent(self, event):
        handle = self._detect_resize_handle(event.pos())
        if handle is not None:
            self._resizing = True
            self._resize_handle = handle
            self._resize_start_rect = QRectF(self._rect)
            self._resize_start_pos = QPointF(self.pos())
            self._resize_anchor_scene = self.mapToScene(self._opposite_corner_local(handle))
            self.setCursor(self._cursor_for_handle(handle))
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            if self._resize_anchor_scene is None:
                event.accept()
                return
            moving_scene = self.mapToScene(event.pos())
            target_rect = self._build_target_rect(
                self._resize_anchor_scene,
                moving_scene,
                20.0,
                self._resize_handle,
            )
            if self._keep_aspect:
                target_rect = self._apply_aspect_ratio(
                    target_rect,
                    self._resize_handle,
                    self._resize_anchor_scene,
                )
            self.setPos(target_rect.topLeft())
            self.set_rect_size(target_rect.width(), target_rect.height())
            event.accept()
        else:
            handle = self._detect_resize_handle(event.pos()) if self.isSelected() else None
            self.setCursor(self._cursor_for_handle(handle))
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            old_rect = QRectF(self._resize_start_rect) if self._resize_start_rect is not None else QRectF(self._rect)
            old_pos = QPointF(self._resize_start_pos) if self._resize_start_pos is not None else QPointF(self.pos())
            self._resize_start_rect = None
            self._resize_start_pos = None
            self._resize_handle = None
            self._resize_anchor_scene = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if (
                self._on_resize_finished is not None
                and (
                    abs(old_rect.width() - self._rect.width()) >= 0.001
                    or abs(old_rect.height() - self._rect.height()) >= 0.001
                    or abs(old_pos.x() - self.pos().x()) >= 0.001
                    or abs(old_pos.y() - self.pos().y()) >= 0.001
                )
            ):
                self._on_resize_finished(old_rect, QRectF(self._rect), old_pos, QPointF(self.pos()))
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu()
        keep_aspect_action = menu.addAction("Keep Aspect Ratio")
        keep_aspect_action.setCheckable(True)
        keep_aspect_action.setChecked(self._keep_aspect)
        
        action = menu.exec(event.screenPos())
        if action == keep_aspect_action:
            self._keep_aspect = keep_aspect_action.isChecked()
            if self._keep_aspect:
                # Capture the current dimensions as the new aspect ratio to maintain
                current_w = self._rect.width()
                current_h = self._rect.height()
                if current_h > 0:
                    self._aspect_ratio = current_w / current_h
                self.update()
