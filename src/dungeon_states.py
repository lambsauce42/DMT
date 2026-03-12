from __future__ import annotations

import math
import uuid
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QCursor, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
)

from asset_paths import icon_path
from dungeon_constants import *
from dungeon_commands import (
    CreateItemCommand,
    DeleteItemCommand,
    ModifyFogCommand,
    MoveItemsCommand,
    ResizeImageCommand,
    ResizeRoomCommand,
)
from dungeon_items import WallItem, DungeonEllipseItem, RoomGroup, DungeonImageItem, _qt_object_is_valid

if TYPE_CHECKING:
    from dungeon_applet import DungeonCanvas


def _stroke_z_for_layer(layer: str) -> float:
    if layer == LAYER_MID:
        return 255.0
    if layer == LAYER_BG:
        return 205.0
    return 305.0


def _snap(value: float, grid: int = GRID_SIZE) -> float:
    if QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
        return value
    return round(value / grid) * grid

def _snap_point(point: QPointF, grid: int = GRID_SIZE) -> QPointF:
    if QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
        return point
    return QPointF(_snap(point.x(), grid), _snap(point.y(), grid))


def _snap_entity_center(point: QPointF, grid: int = GRID_SIZE) -> QPointF:
    if QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
        return point
    half_grid = grid / 2.0
    cell_x = math.floor(point.x() / grid)
    cell_y = math.floor(point.y() / grid)
    return QPointF(cell_x * grid + half_grid, cell_y * grid + half_grid)

def _rect_from_points(a: QPointF, b: QPointF, grid: int) -> QRectF:
    """Create a rectangle from two points, snapped to grid (unless Alt is held)."""
    if QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
        left = min(a.x(), b.x())
        top = min(a.y(), b.y())
        width = abs(a.x() - b.x())
        height = abs(a.y() - b.y())
        return QRectF(left, top, width, height)

    # Snap both points to grid
    a_snapped = _snap_point(a, grid)
    b_snapped = _snap_point(b, grid)
    
    left = min(a_snapped.x(), b_snapped.x())
    top = min(a_snapped.y(), b_snapped.y())
    right = max(a_snapped.x(), b_snapped.x())
    bottom = max(a_snapped.y(), b_snapped.y())
    width = max(grid * MIN_RECT_SIZE, right - left)
    height = max(grid * MIN_RECT_SIZE, bottom - top)
    return QRectF(left, top, width, height)


def _room_floor_path_local(room: RoomGroup) -> QPainterPath:
    if hasattr(room, "floor_path"):
        path = room.floor_path()
        if isinstance(path, QPainterPath):
            return path
    path = QPainterPath()
    for child in room.childItems():
        if isinstance(child, WallItem):
            continue
        child_path = child.path() if isinstance(child, QGraphicsPathItem) else child.shape()
        return child_path.translated(child.pos())
    return path


def _scaled_path_to_rect(path: QPainterPath, source_rect: QRectF, target_rect: QRectF) -> QPainterPath:
    if path.isEmpty():
        return QPainterPath(path)
    src_w = float(source_rect.width())
    src_h = float(source_rect.height())
    dst_w = float(target_rect.width())
    dst_h = float(target_rect.height())
    if src_w <= 1e-6 or src_h <= 1e-6:
        return QPainterPath(path)

    def _map_point(x: float, y: float) -> QPointF:
        nx = (x - source_rect.left()) / src_w
        ny = (y - source_rect.top()) / src_h
        return QPointF(target_rect.left() + (nx * dst_w), target_rect.top() + (ny * dst_h))

    scaled = QPainterPath()
    move_to = int(QPainterPath.ElementType.MoveToElement.value)
    line_to = int(QPainterPath.ElementType.LineToElement.value)
    curve_to = int(QPainterPath.ElementType.CurveToElement.value)
    index = 0
    element_count = path.elementCount()
    def _etype(element) -> int:
        value = element.type
        return int(value.value) if hasattr(value, "value") else int(value)

    while index < element_count:
        element = path.elementAt(index)
        element_type = _etype(element)
        mapped = _map_point(float(element.x), float(element.y))
        if element_type == move_to:
            scaled.moveTo(mapped)
            index += 1
            continue
        if element_type == line_to:
            scaled.lineTo(mapped)
            index += 1
            continue
        if element_type == curve_to and index + 2 < element_count:
            ctrl_two = path.elementAt(index + 1)
            end_point = path.elementAt(index + 2)
            mapped_ctrl_two = _map_point(float(ctrl_two.x), float(ctrl_two.y))
            mapped_end = _map_point(float(end_point.x), float(end_point.y))
            scaled.cubicTo(mapped, mapped_ctrl_two, mapped_end)
            index += 3
            continue
        scaled.lineTo(mapped)
        index += 1
    return scaled


def _paths_close(a: QPainterPath, b: QPainterPath, tol: float = 0.05) -> bool:
    if a.elementCount() != b.elementCount():
        return False
    if not a.boundingRect().adjusted(-tol, -tol, tol, tol).contains(b.boundingRect()):
        return False
    for idx in range(a.elementCount()):
        ea = a.elementAt(idx)
        eb = b.elementAt(idx)
        ta = int(ea.type.value) if hasattr(ea.type, "value") else int(ea.type)
        tb = int(eb.type.value) if hasattr(eb.type, "value") else int(eb.type)
        if ta != tb:
            return False
        if abs(float(ea.x) - float(eb.x)) > tol:
            return False
        if abs(float(ea.y) - float(eb.y)) > tol:
            return False
    return True


def _apply_room_floor_path(room: RoomGroup, path: QPainterPath) -> None:
    if hasattr(room, "rebuild_from_path"):
        room.rebuild_from_path(path)
        return
    scene = room.scene()
    for child in list(room.childItems()):
        room.removeFromGroup(child)
        if scene is not None and child.scene() is scene:
            scene.removeItem(child)
    room.add_path_floor(path)
    polygons = path.toSubpathPolygons()
    for poly in polygons:
        if poly.count() <= 1:
            continue
        for idx in range(poly.count()):
            p1 = poly[idx]
            p2 = poly[(idx + 1) % poly.count()]
            if (p1 - p2).manhattanLength() <= 0.1:
                continue
            room.add_wall(p1.x(), p1.y(), p2.x(), p2.y())

def _smooth_connect_rooms(canvas: 'DungeonCanvas', target_item: QGraphicsItem):
    """Remove segments of walls that are inside other rooms to create a smooth connection."""
    scene = canvas.scene()
    target_layer = target_item.data(ROLE_LAYER) or LAYER_FG
    target_kind = target_item.data(ROLE_KIND) or TOOL_ROOM
    target_z = float(target_item.zValue()) if hasattr(target_item, "zValue") else 0.0
    
    # 1. Find all "room-like" items in the scene
    # We use ROLE_KIND and LAYER_GEOMETRY to find rooms
    all_rooms = []
    for item in scene.items():
        kind = item.data(ROLE_KIND)
        layer = item.data(ROLE_LAYER) or LAYER_FG
        if layer != target_layer:
            continue
        if kind in LAYER_GEOMETRY and kind not in (TOOL_WALL, TOOL_FLOOR):
            all_rooms.append(item)
            
    if target_item not in all_rooms:
        all_rooms.append(target_item)
    
    # 2. Get the "floor path" for each room in absolute scene coordinates
    # and collect floor edges for splitting walls.
    room_floors: dict[QGraphicsItem, QPainterPath] = {}
    room_edges: dict[QGraphicsItem, list[QLineF]] = {}
    
    for room in all_rooms:
        path = QPainterPath()
        edges = []
        item_kind = room.data(ROLE_KIND)
        
        if isinstance(room, RoomGroup):
            for child in room.childItems():
                if not isinstance(child, WallItem):
                    # Shape in absolute scene coordinates
                    child_path = child.shape()
                    # child.pos() is relative to RoomGroup. room.pos() is absolute.
                    child_path = child_path.translated(child.pos()).translated(room.pos())
                    path.addPath(child_path)
                    
                    # Extract edges
                    if isinstance(child, QGraphicsRectItem):
                        r = child.rect().translated(child.pos()).translated(room.pos())
                        tl, tr, bl, br = r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()
                        edges.extend([QLineF(tl, tr), QLineF(tr, br), QLineF(br, bl), QLineF(bl, tl)])
                    elif isinstance(child, QGraphicsPolygonItem):
                        poly = child.polygon().translated(child.pos()).translated(room.pos())
                        if poly.count() > 1:
                            for i in range(poly.count()):
                                edges.append(QLineF(poly[i], poly[(i + 1) % poly.count()]))
            
            # If no edges found from floor (e.g. Ellipse with Path floor), use walls
            if not edges and room.data(ROLE_KIND) == TOOL_ELLIPSE:
                for child in room.childItems():
                    if isinstance(child, WallItem):
                         edges.append(child.line().translated(child.pos()).translated(room.pos()))
        
        # Removed legacy TOOL_ELLIPSE block as DungeonEllipseItem is now a RoomGroup

        room_floors[room] = path
        room_edges[room] = edges

    target_path = room_floors.get(target_item)
    if not target_path or target_path.isEmpty():
        return

    # 3. Identify rooms that intersect with target_item
    intersecting_rooms = []
    for room, path in room_floors.items():
        if room == target_item:
            continue
        if target_path.intersects(path):
            intersecting_rooms.append(room)
    
    if not intersecting_rooms:
        return

    # 4. Rooms to process: target_item + intersecting_rooms
    # rooms_to_clean was removed as we are merging now
    if not intersecting_rooms:
        return
    
    # We are performing a physical merge of rooms.
    # Instead of just removing walls, we will create a new RoomGroup that is the union
    # of the target room and all intersecting rooms.
    
    # 1. Collect all rooms to merge
    rooms_to_merge = [target_item] + intersecting_rooms
    
    # 2. Compute Union Floor Path
    union_path = QPainterPath()
    for room, path in room_floors.items():
        if room in rooms_to_merge:
            union_path = union_path.united(path)

    # 3. Create the new Merged Room
    new_room = RoomGroup()
    new_room.setZValue(target_z)
    new_room.setData(ROLE_LAYER, target_layer)
    new_room.setData(ROLE_KIND, target_kind)
    new_room.setData(ROLE_LOCKED, any(bool(room.data(ROLE_LOCKED)) for room in rooms_to_merge))
    
    # Add the complex union floor
    new_room.add_path_floor(union_path)
    # 4. Generate Walls from Union Path Outline
    # QPainterPath.toSubpathPolygons() gives us the boundary polygons
    polygons = union_path.toSubpathPolygons()
    for poly in polygons:
        # poly is QPolygonF
        if poly.count() > 1:
            for i in range(poly.count()):
                p1 = poly[i]
                p2 = poly[(i + 1) % poly.count()]
                # Only add if segment has length > 0
                    # (QPainterPath sometimes produces tiny duplicate points)
                if (p1 - p2).manhattanLength() > 0.1:
                    new_room.add_wall(p1.x(), p1.y(), p2.x(), p2.y())
    
    # 5. Execute Commands
    # We need to:
    # - Remove the old individual rooms
    # - Add the new merged room
    
    # Note: target_item is likely already in the scene (or just added by a command)
    # If this is called within a macro where target_item was just created, 
    # we should queue a deletion for it.
    
    # Delete old rooms
    for room in rooms_to_merge:
        canvas.undo_stack.push(DeleteItemCommand(canvas.scene(), room, "Merge: Delete Old"))
    
    # Add new room
    canvas.undo_stack.push(CreateItemCommand(canvas.scene(), new_room, "Merge: Create New"))
    
    return # Done merging for this target

class CanvasState:
    def __init__(self, canvas: 'DungeonCanvas'):
        self.canvas = canvas
    
    def on_enter(self): pass
    def on_exit(self): pass
    
    def mousePressEvent(self, event, scene_pos: QPointF) -> bool:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.canvas._panning = True
            self.canvas._last_pan_point = event.position()
            self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return True
        return False

    def mouseMoveEvent(self, event, scene_pos: QPointF) -> bool:
        if self.canvas._panning and self.canvas._last_pan_point is not None:
            delta = event.position() - self.canvas._last_pan_point
            self.canvas._last_pan_point = event.position()
            self.canvas.horizontalScrollBar().setValue(
                self.canvas.horizontalScrollBar().value() - int(delta.x())
            )
            self.canvas.verticalScrollBar().setValue(
                self.canvas.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
            return True
        return False

    def mouseReleaseEvent(self, event, scene_pos: QPointF) -> bool:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.canvas._panning = False
            self.canvas._last_pan_point = None
            self.on_enter() # Check tool cursor
            event.accept()
            return True
        return False

    def mouseDoubleClickEvent(self, event): pass
    def keyPressEvent(self, event): pass

class SelectState(CanvasState):
    _RESIZE_HANDLE_TOLERANCE = 14.0

    def __init__(self, canvas: 'DungeonCanvas'):
        super().__init__(canvas)
        self.drag_start_positions: dict[QGraphicsItem, QPointF] = {}
        self.is_dragging = False
        self._drag_press_scene_pos: QPointF | None = None
        self._drag_started = False
        self._drag_primary_item: QGraphicsItem | None = None
        self._drag_move_logged = False
        self._merge_requested_during_drag = False
        self._resizing_room: RoomGroup | None = None
        self._resize_handle: str | None = None
        self._resize_anchor_scene: QPointF | None = None
        self._resize_start_scene_rect: QRectF | None = None
        self._resize_start_path_scene: QPainterPath | None = None
        self._resize_start_path_local: QPainterPath | None = None
        self._resize_last_path_local: QPainterPath | None = None
        self._resize_pointer_offset_scene: QPointF | None = None

    @staticmethod
    def _movable_anchor(item: QGraphicsItem | None) -> QGraphicsItem | None:
        current = item
        while current is not None:
            if not _qt_object_is_valid(current):
                return None
            if current.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
                return current
            current = current.parentItem()
        return None

    def on_enter(self):
        self.canvas.setCursor(Qt.CursorShape.ArrowCursor)

    @staticmethod
    def _cursor_for_handle(handle: str | None) -> Qt.CursorShape:
        if handle in {"top_left", "bottom_right"}:
            return Qt.CursorShape.SizeFDiagCursor
        if handle in {"top_right", "bottom_left"}:
            return Qt.CursorShape.SizeBDiagCursor
        return Qt.CursorShape.ArrowCursor

    def _detect_resize_handle(self, room: RoomGroup, scene_pos: QPointF) -> str | None:
        rect = room.sceneBoundingRect()
        if rect.isNull() or rect.width() <= 0.1 or rect.height() <= 0.1:
            return None
        tolerance = max(8.0, min(float(self.canvas.grid_size) * 0.35, self._RESIZE_HANDLE_TOLERANCE))
        handles = {
            "top_left": rect.topLeft(),
            "top_right": rect.topRight(),
            "bottom_left": rect.bottomLeft(),
            "bottom_right": rect.bottomRight(),
        }
        for handle_name, point in handles.items():
            if QLineF(scene_pos, point).length() <= tolerance:
                return handle_name
        return None

    @staticmethod
    def _opposite_corner(rect: QRectF, handle: str) -> QPointF:
        if handle == "top_left":
            return rect.bottomRight()
        if handle == "top_right":
            return rect.bottomLeft()
        if handle == "bottom_left":
            return rect.topRight()
        return rect.topLeft()

    @staticmethod
    def _handle_point(rect: QRectF, handle: str | None) -> QPointF:
        if handle == "top_left":
            return rect.topLeft()
        if handle == "top_right":
            return rect.topRight()
        if handle == "bottom_left":
            return rect.bottomLeft()
        return rect.bottomRight()

    @staticmethod
    def _build_target_rect(
        anchor: QPointF,
        moving: QPointF,
        min_size: float,
        handle: str | None = None,
    ) -> QRectF:
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

    def _active_room_candidate(self, scene_pos: QPointF) -> RoomGroup | None:
        raw_item = self.canvas.scene().itemAt(scene_pos, self.canvas.transform())
        anchor = self._movable_anchor(raw_item)
        if isinstance(anchor, RoomGroup):
            return anchor
        selected_rooms = [
            item
            for item in self.canvas.scene().selectedItems()
            if isinstance(self._movable_anchor(item), RoomGroup)
        ]
        if len(selected_rooms) == 1:
            room_anchor = self._movable_anchor(selected_rooms[0])
            if isinstance(room_anchor, RoomGroup):
                return room_anchor
        return None

    def _update_resize_hover(self, scene_pos: QPointF) -> None:
        if self._resizing_room is not None or self.is_dragging:
            return
        room = self._active_room_candidate(scene_pos)
        if room is None:
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
            return
        handle = self._detect_resize_handle(room, scene_pos)
        self.canvas.setCursor(self._cursor_for_handle(handle))

    def _clear_resize_state(self) -> None:
        self._resizing_room = None
        self._resize_handle = None
        self._resize_anchor_scene = None
        self._resize_start_scene_rect = None
        self._resize_start_path_scene = None
        self._resize_start_path_local = None
        self._resize_last_path_local = None
        self._resize_pointer_offset_scene = None

    def _emit_drag_debug(self, event: str, **fields: object) -> None:
        emitter = getattr(self.canvas, "_emit_online_debug_event", None)
        if callable(emitter):
            emitter(str(event or ""), **fields)

    @staticmethod
    def _entity_id_for_item(item: QGraphicsItem | None) -> str:
        if item is None:
            return ""
        return str(item.data(ROLE_ENTITY_ID) or "").strip()

    @staticmethod
    def _owner_id_for_item(item: QGraphicsItem | None) -> str:
        if item is None:
            return ""
        return str(item.data(ROLE_OWNER_PLAYER_ID) or "").strip()

    @staticmethod
    def _point_text(point: QPointF | None) -> str:
        if point is None:
            return ""
        return f"{float(point.x()):.1f},{float(point.y()):.1f}"

    def _selected_entity_ids_csv(self) -> str:
        entity_ids: list[str] = []
        for item in self.canvas.scene().selectedItems():
            entity_id = self._entity_id_for_item(item)
            if entity_id:
                entity_ids.append(entity_id)
        return ",".join(entity_ids)

    def cancel_active_interaction(self) -> None:
        self.is_dragging = False
        self._drag_press_scene_pos = None
        self._drag_started = False
        self._drag_primary_item = None
        self._drag_move_logged = False
        self.drag_start_positions = {}
        self._merge_requested_during_drag = False
        self._clear_resize_state()
        self.canvas.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event, scene_pos: QPointF):
        if super().mousePressEvent(event, scene_pos): return True
        
        if event.button() == Qt.MouseButton.LeftButton:
            raw_item = self.canvas.scene().itemAt(scene_pos, self.canvas.transform())
            item = self._movable_anchor(raw_item)
            room_for_resize: RoomGroup | None = item if isinstance(item, RoomGroup) else None
            if room_for_resize is None:
                tolerance = max(8.0, min(float(self.canvas.grid_size) * 0.35, self._RESIZE_HANDLE_TOLERANCE))
                search_rect = QRectF(
                    scene_pos.x() - tolerance,
                    scene_pos.y() - tolerance,
                    tolerance * 2.0,
                    tolerance * 2.0,
                )
                for hit in self.canvas.scene().items(search_rect):
                    anchor = self._movable_anchor(hit)
                    if isinstance(anchor, RoomGroup):
                        room_for_resize = anchor
                        break
            if room_for_resize is not None:
                resize_handle = self._detect_resize_handle(room_for_resize, scene_pos)
                if resize_handle is not None:
                    local_path = _room_floor_path_local(room_for_resize)
                    if not local_path.isEmpty():
                        scene_path = local_path.translated(room_for_resize.pos())
                        scene_rect = scene_path.boundingRect()
                        if scene_rect.width() > 0.1 and scene_rect.height() > 0.1:
                            self._resizing_room = room_for_resize
                            self._resize_handle = resize_handle
                            self._resize_anchor_scene = self._opposite_corner(scene_rect, resize_handle)
                            self._resize_start_scene_rect = scene_rect
                            self._resize_start_path_local = local_path
                            self._resize_start_path_scene = scene_path
                            self._resize_last_path_local = QPainterPath(local_path)
                            handle_point = self._handle_point(
                                room_for_resize.sceneBoundingRect(),
                                resize_handle,
                            )
                            self._resize_pointer_offset_scene = QPointF(
                                scene_pos.x() - handle_point.x(),
                                scene_pos.y() - handle_point.y(),
                            )
                            self._merge_requested_during_drag = bool(
                                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                            )
                            self.canvas.scene().clearSelection()
                            room_for_resize.setSelected(True)
                            self.canvas.setCursor(self._cursor_for_handle(resize_handle))
                            return True

            if isinstance(item, DungeonImageItem):
                local_pos = item.mapFromScene(scene_pos)
                if item._detect_resize_handle(local_pos) is not None:
                    # Let the item handle its own resize drag; do not arm move/snap.
                    self.is_dragging = False
                    self._drag_press_scene_pos = None
                    self._drag_started = False
                    self._drag_primary_item = None
                    self._drag_move_logged = False
                    self.drag_start_positions = {}
                    self._merge_requested_during_drag = False
                    return False

            selection_modifiers = event.modifiers() & (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
            )
            if item is not None and not selection_modifiers:
                if not item.isSelected():
                    self.canvas.scene().clearSelection()
                    item.setSelected(True)

                selected: list[QGraphicsItem] = []
                seen: set[int] = set()
                for candidate in self.canvas.scene().selectedItems():
                    anchor = self._movable_anchor(candidate)
                    if anchor is None:
                        continue
                    key = id(anchor)
                    if key in seen:
                        continue
                    seen.add(key)
                    selected.append(anchor)
                if id(item) not in seen:
                    selected.append(item)
                self.drag_start_positions = {i: QPointF(i.pos()) for i in selected}
                self.is_dragging = True
                self._drag_press_scene_pos = QPointF(scene_pos)
                self._drag_started = False
                self._drag_primary_item = item
                self._drag_move_logged = False
                self._merge_requested_during_drag = False
                self._emit_drag_debug(
                    "player_drag_press",
                    entity_id=self._entity_id_for_item(item),
                    owner_player_id=self._owner_id_for_item(item),
                    press_scene_pos=self._point_text(scene_pos),
                    selected_entity_ids=self._selected_entity_ids_csv(),
                )
                return True
            
            selected = []
            seen: set[int] = set()
            for candidate in self.canvas.scene().selectedItems():
                anchor = self._movable_anchor(candidate)
                if anchor is None:
                    continue
                key = id(anchor)
                if key in seen:
                    continue
                seen.add(key)
                selected.append(anchor)
            if item is not None and id(item) not in seen:
                selected.append(item)
                seen.add(id(item))
            self.drag_start_positions = {i: i.pos() for i in selected}
            
            # If we clicked an item, we might drag it
            if item:
                 # If item is not selected yet, it will be selected by view event (if we propagate or handle?)
                 # QGraphicsView default implementation handles selection if we call super().mousePress (which we do if we return False)
                 self.is_dragging = True
                 self._drag_press_scene_pos = QPointF(scene_pos)
                 self._drag_started = False
                 self._drag_primary_item = item
                 self._drag_move_logged = False
                 self._merge_requested_during_drag = bool(
                     event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                 )
            else:
                 # Rubberband drag potentially
                 self.is_dragging = False
                 self._drag_press_scene_pos = None
                 self._drag_started = False
                 self._drag_primary_item = None
                 self._drag_move_logged = False
                 self._merge_requested_during_drag = False
        return False

    def mouseMoveEvent(self, event, scene_pos: QPointF):
        if super().mouseMoveEvent(event, scene_pos):
            return True
        if self._resizing_room is not None:
            if (
                self._resize_anchor_scene is None
                or self._resize_start_scene_rect is None
                or self._resize_start_path_scene is None
            ):
                return True
            alt_pressed = bool(
                (event.modifiers() & Qt.KeyboardModifier.AltModifier)
                or (QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier)
            )
            snap_enabled = self.canvas.snap_to_grid and not alt_pressed
            moving = QPointF(scene_pos)
            if self._resize_pointer_offset_scene is not None:
                moving = QPointF(
                    moving.x() - self._resize_pointer_offset_scene.x(),
                    moving.y() - self._resize_pointer_offset_scene.y(),
                )
            if snap_enabled:
                grid = float(self.canvas.grid_size)
                anchor_x = float(self._resize_anchor_scene.x())
                anchor_y = float(self._resize_anchor_scene.y())
                moving = QPointF(
                    anchor_x + (round((moving.x() - anchor_x) / grid) * grid),
                    anchor_y + (round((moving.y() - anchor_y) / grid) * grid),
                )
            min_size = float(self.canvas.grid_size if snap_enabled else 8.0)
            target_rect = self._build_target_rect(
                self._resize_anchor_scene,
                moving,
                min_size,
                self._resize_handle,
            )
            resized_scene_path = _scaled_path_to_rect(
                self._resize_start_path_scene,
                self._resize_start_scene_rect,
                target_rect,
            )
            local_path = resized_scene_path.translated(-self._resizing_room.pos())
            _apply_room_floor_path(self._resizing_room, local_path)
            self._resize_last_path_local = QPainterPath(local_path)
            return True

        if self.is_dragging and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._merge_requested_during_drag = True
        if self.is_dragging and self._drag_press_scene_pos is not None:
            delta = scene_pos - self._drag_press_scene_pos
            if not self._drag_started and delta.manhattanLength() < 1.0:
                return True
            self._drag_started = True
            for item, start_pos in self.drag_start_positions.items():
                if not _qt_object_is_valid(item):
                    continue
                if not (item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable):
                    continue
                item.setPos(
                    QPointF(
                        float(start_pos.x()) + float(delta.x()),
                        float(start_pos.y()) + float(delta.y()),
                    )
                )
            if not self._drag_move_logged:
                primary_item = self._drag_primary_item
                current_pos = primary_item.pos() if primary_item is not None else None
                self._emit_drag_debug(
                    "player_drag_move",
                    entity_id=self._entity_id_for_item(primary_item),
                    owner_player_id=self._owner_id_for_item(primary_item),
                    press_scene_pos=self._point_text(self._drag_press_scene_pos),
                    current_scene_pos=self._point_text(scene_pos),
                    current_item_pos=self._point_text(current_pos),
                    delta_x=round(float(delta.x()), 2),
                    delta_y=round(float(delta.y()), 2),
                )
                self._drag_move_logged = True
            return True
        self._update_resize_hover(scene_pos)
        return False

    def mouseReleaseEvent(self, event, scene_pos: QPointF):
        if super().mouseReleaseEvent(event, scene_pos):
            return True
        
        if event.button() == Qt.MouseButton.LeftButton:
            if self._resizing_room is not None:
                alt_pressed = bool(
                    (event.modifiers() & Qt.KeyboardModifier.AltModifier)
                    or (QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier)
                )
                if (
                    alt_pressed
                    and self._resize_anchor_scene is not None
                    and self._resize_start_scene_rect is not None
                    and self._resize_start_path_scene is not None
                ):
                    moving = QPointF(scene_pos)
                    if self._resize_pointer_offset_scene is not None:
                        moving = QPointF(
                            moving.x() - self._resize_pointer_offset_scene.x(),
                            moving.y() - self._resize_pointer_offset_scene.y(),
                        )
                    target_rect = self._build_target_rect(
                        self._resize_anchor_scene,
                        moving,
                        8.0,
                        self._resize_handle,
                    )
                    resized_scene_path = _scaled_path_to_rect(
                        self._resize_start_path_scene,
                        self._resize_start_scene_rect,
                        target_rect,
                    )
                    local_path = resized_scene_path.translated(-self._resizing_room.pos())
                    _apply_room_floor_path(self._resizing_room, local_path)
                    self._resize_last_path_local = QPainterPath(local_path)
                if (
                    self._resize_start_path_local is not None
                    and self._resize_last_path_local is not None
                    and not _paths_close(self._resize_start_path_local, self._resize_last_path_local)
                ):
                    self.canvas.undo_stack.push(
                        ResizeRoomCommand(
                            self._resizing_room,
                            self._resize_start_path_local,
                            self._resize_last_path_local,
                        )
                    )
                self._clear_resize_state()
                self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
                return True

            if self.is_dragging:
                # Snap
                selected = self.canvas.scene().selectedItems()
                selected_for_move: list[QGraphicsItem] = []
                seen: set[int] = set()
                for candidate in [*selected, *self.drag_start_positions.keys()]:
                    anchor = self._movable_anchor(candidate)
                    if anchor is None:
                        continue
                    key = id(anchor)
                    if key in seen:
                        continue
                    seen.add(key)
                    selected_for_move.append(anchor)
                if self.canvas.snap_to_grid:
                    from dungeon_items import EntityItem
                    for item in selected_for_move:
                         if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
                             if isinstance(item, EntityItem):
                                 snapped = _snap_entity_center(item.pos(), self.canvas.grid_size)
                             else:
                                 snapped = _snap_point(item.pos(), self.canvas.grid_size)
                             if item.pos() != snapped:
                                 item.setPos(snapped)
                
                # Check for move
                moved_list = []
                for item in selected_for_move:
                     start = self.drag_start_positions.get(item)
                     if start is not None and item.pos() != start:
                          moved_list.append(item)
                
                if moved_list:
                    moved_entity_ids = ",".join(
                        entity_id
                        for entity_id in (self._entity_id_for_item(item) for item in moved_list)
                        if entity_id
                    )
                    primary_item = self._drag_primary_item
                    primary_pos = primary_item.pos() if primary_item is not None else None
                    self._emit_drag_debug(
                        "player_drag_release_commit",
                        entity_id=self._entity_id_for_item(primary_item),
                        owner_player_id=self._owner_id_for_item(primary_item),
                        moved_count=int(len(moved_list)),
                        moved_entity_ids=moved_entity_ids,
                        current_item_pos=self._point_text(primary_pos),
                        selected_entity_ids=self._selected_entity_ids_csv(),
                    )
                    self.canvas.undo_stack.beginMacro("Move Items")
                    merge_requested = self._merge_requested_during_drag or bool(
                        event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                    )
                    if merge_requested:
                        for item in moved_list:
                             _smooth_connect_rooms(self.canvas, item)
                    
                    cmd = MoveItemsCommand(moved_list, self.drag_start_positions)
                    self.canvas.undo_stack.push(cmd)
                    self.canvas.undo_stack.endMacro()
                elif self._drag_primary_item is not None:
                    self._emit_drag_debug(
                        "player_drag_release_noop",
                        entity_id=self._entity_id_for_item(self._drag_primary_item),
                        owner_player_id=self._owner_id_for_item(self._drag_primary_item),
                        selected_entity_ids=self._selected_entity_ids_csv(),
                    )

            self.is_dragging = False
            self._drag_press_scene_pos = None
            self._drag_started = False
            self._drag_primary_item = None
            self._drag_move_logged = False
            self.drag_start_positions = {}
            self._merge_requested_during_drag = False
            self._update_resize_hover(scene_pos)
        return False


class FreeDrawState(CanvasState):
    """State for free-form drawing strokes (no snapping)."""
    def __init__(self, canvas: 'DungeonCanvas'):
        super().__init__(canvas)
        self.current_path: Optional[QPainterPath] = None
        self.preview_item: Optional[QGraphicsPathItem] = None
        self.is_drawing = False

    def on_enter(self):
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)

    def on_exit(self):
        self.cleanup()

    def cleanup(self):
        if self.preview_item and _qt_object_is_valid(self.preview_item):
            if self.preview_item.scene():
                self.canvas.scene().removeItem(self.preview_item)
        self.preview_item = None
        self.current_path = None
        self.is_drawing = False

    def mousePressEvent(self, event, scene_pos: QPointF):
        if super().mousePressEvent(event, scene_pos): return True
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_drawing = True
            self.current_path = QPainterPath()
            self.current_path.moveTo(scene_pos)
            self.preview_item = QGraphicsPathItem(self.current_path)
            draw_color = QColor(getattr(self.canvas, "stroke_color", QColor(WALL_COLOR)))
            self.preview_item.setPen(QPen(draw_color, WALL_WIDTH))
            
            # Layer assignment
            current_layer = getattr(self.canvas, "_current_layer", LAYER_FG)
            z_val = _stroke_z_for_layer(current_layer)
            
            self.preview_item.setZValue(z_val)
            self.preview_item.setData(ROLE_LAYER, current_layer)
            self.canvas.scene().addItem(self.preview_item)
            return True
        return False

    def mouseMoveEvent(self, event, scene_pos: QPointF):
        if super().mouseMoveEvent(event, scene_pos): return
        if self.is_drawing and self.current_path and self.preview_item:
            if not _qt_object_is_valid(self.preview_item):
                self.cleanup()
                return
            self.current_path.lineTo(scene_pos)
            self.preview_item.setPath(self.current_path)

    def mouseReleaseEvent(self, event, scene_pos: QPointF):
        if super().mouseReleaseEvent(event, scene_pos): return
        if event.button() == Qt.MouseButton.LeftButton and self.is_drawing:
            if self.current_path and self.preview_item and _qt_object_is_valid(self.preview_item):
                # Finalize the stroke
                final_item = QGraphicsPathItem(self.current_path)
                
                # Layer assignment
                current_layer = getattr(self.canvas, "_current_layer", LAYER_FG)
                z_val = _stroke_z_for_layer(current_layer)
                
                draw_color = QColor(getattr(self.canvas, "stroke_color", QColor(WALL_COLOR)))
                final_item.setPen(QPen(draw_color, WALL_WIDTH))
                final_item.setZValue(z_val)
                final_item.setData(ROLE_LAYER, current_layer)
                final_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                final_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
                final_item.setData(ROLE_KIND, "stroke")
                final_item.setData(ROLE_LOCKED, False)
                final_item.setData(
                    ROLE_OWNER_PLAYER_ID,
                    str(getattr(self.canvas, "_stroke_owner_player_id", "") or "").strip(),
                )
                final_item.setData(ROLE_ENTITY_ID, uuid.uuid4().hex)
                
                # Remove preview and add final
                if self.preview_item.scene():
                    self.canvas.scene().removeItem(self.preview_item)
                cmd = CreateItemCommand(self.canvas.scene(), final_item, "Draw Stroke")
                self.canvas.undo_stack.push(cmd)
            self.cleanup()

class DrawingRectState(CanvasState):
    def __init__(self, canvas: 'DungeonCanvas', tool: str):
        super().__init__(canvas)
        self.tool = tool
        self.origin: Optional[QPointF] = None
        self.preview_item: Optional[QGraphicsRectItem] = None

    def on_enter(self):
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)

    def on_exit(self):
        self.cleanup()

    def cleanup(self):
        if self.preview_item and _qt_object_is_valid(self.preview_item):
            self.canvas.scene().removeItem(self.preview_item)
            self.preview_item = None
        self.origin = None

    def mousePressEvent(self, event, scene_pos: QPointF):
        if super().mousePressEvent(event, scene_pos): return True
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = scene_pos
            self.preview_item = QGraphicsRectItem(0, 0, 0, 0)
            self.preview_item.setPos(scene_pos)
            self.preview_item.setBrush(QColor(FLOOR_COLOR))
            self.preview_item.setPen(QPen(QColor(WALL_COLOR), WALL_WIDTH))
            
            # Layer assignment
            current_layer = getattr(self.canvas, "_current_layer", LAYER_FG)
            z_val = 100
            if current_layer == LAYER_MID:
                z_val = 50
            elif current_layer == LAYER_BG:
                z_val = 0
            
            self.preview_item.setZValue(z_val)
            self.preview_item.setData(ROLE_LAYER, current_layer)
            self.canvas.scene().addItem(self.preview_item)
            return True
        return False

    def mouseMoveEvent(self, event, scene_pos: QPointF):
        if super().mouseMoveEvent(event, scene_pos): return
        if self.origin and self.preview_item:
            if not _qt_object_is_valid(self.preview_item):
                self.preview_item = None
                self.origin = None
                return
            rect = _rect_from_points(self.origin, scene_pos, self.canvas.grid_size)
            if self.tool == TOOL_CORRIDOR and hasattr(self.canvas, '_corridor_rect'):
                 rect = self.canvas._corridor_rect(rect)
            self.preview_item.setPos(rect.topLeft())
            self.preview_item.setRect(0, 0, rect.width(), rect.height())

    def mouseReleaseEvent(self, event, scene_pos: QPointF):
        if super().mouseReleaseEvent(event, scene_pos): return
        if event.button() == Qt.MouseButton.LeftButton and self.origin and self.preview_item:
            if not _qt_object_is_valid(self.preview_item):
                self.cleanup()
                return
            rect = self.preview_item.rect()
            is_alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            if is_alt or (rect.width() >= self.canvas.grid_size and rect.height() >= self.canvas.grid_size):
                self.canvas.undo_stack.beginMacro(f"Create {self.tool.title()}")
                room = self.create_room(self.preview_item.pos(), rect)
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    _smooth_connect_rooms(self.canvas, room)
                self.canvas.undo_stack.endMacro()
            self.cleanup()

    def create_room(self, pos: QPointF, rect: QRectF) -> RoomGroup:
        # Create room group (position is handled by floor/wall coords)
        room = RoomGroup()
        
        # Layer assignment
        current_layer = getattr(self.canvas, "_current_layer", LAYER_FG)
        z_val = 0
        if current_layer == LAYER_MID:
            z_val = -50
        elif current_layer == LAYER_BG:
            z_val = -100
        
        room.setZValue(z_val)
        room.setData(ROLE_LAYER, current_layer)
        room.setData(ROLE_KIND, TOOL_ROOM)
        room.setData(ROLE_LOCKED, False)
        
        # Floor rect is already positioned correctly via pos + rect dimensions
        # Create floor at absolute position
        floor_rect = QRectF(pos.x(), pos.y(), rect.width(), rect.height())
        room.add_floor(floor_rect)
        
        # Add walls at absolute positions
        tl = floor_rect.topLeft()
        tr = floor_rect.topRight()
        bl = floor_rect.bottomLeft()
        br = floor_rect.bottomRight()
        
        room.add_wall(tl.x(), tl.y(), tr.x(), tr.y())  # Top
        room.add_wall(tr.x(), tr.y(), br.x(), br.y())  # Right
        room.add_wall(br.x(), br.y(), bl.x(), bl.y())  # Bottom
        room.add_wall(bl.x(), bl.y(), tl.x(), tl.y())  # Left
        
        # Single undo command for the whole room
        cmd = CreateItemCommand(self.canvas.scene(), room, f"Create {self.tool.title()}")
        self.canvas.undo_stack.push(cmd)
        return room

class DrawingEllipseState(CanvasState):
    def __init__(self, canvas: 'DungeonCanvas'):
        super().__init__(canvas)
        self.origin: Optional[QPointF] = None
        self.preview_item: Optional[QGraphicsEllipseItem] = None

    def on_enter(self):
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)
    
    def on_exit(self):
        self.cleanup()
    
    def cleanup(self):
        if self.preview_item and _qt_object_is_valid(self.preview_item):
            if self.preview_item.scene():
                self.canvas.scene().removeItem(self.preview_item)
            self.preview_item = None
        self.origin = None

    def mousePressEvent(self, event, scene_pos: QPointF):
        if super().mousePressEvent(event, scene_pos): return True
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = scene_pos
            self.preview_item = QGraphicsEllipseItem(QRectF(0, 0, 0, 0))
            self.preview_item.setPos(scene_pos)
            self.preview_item.setPen(QPen(QColor(WALL_COLOR), WALL_WIDTH))
            self.preview_item.setBrush(QColor(FLOOR_COLOR))
            
            # Layer assignment
            current_layer = getattr(self.canvas, "_current_layer", LAYER_FG)
            z_val = 100
            if current_layer == LAYER_MID:
                z_val = 50
            elif current_layer == LAYER_BG:
                z_val = 0
            
            self.preview_item.setZValue(z_val)
            self.preview_item.setData(ROLE_LAYER, current_layer)
            self.canvas.scene().addItem(self.preview_item)
            return True
        return False

    def mouseMoveEvent(self, event, scene_pos: QPointF):
        if super().mouseMoveEvent(event, scene_pos): return
        if self.origin and self.preview_item:
            if not _qt_object_is_valid(self.preview_item):
                self.preview_item = None
                self.origin = None
                return
            rect = _rect_from_points(self.origin, scene_pos, self.canvas.grid_size)
            self.preview_item.setPos(rect.topLeft())
            self.preview_item.setRect(0, 0, rect.width(), rect.height())

    def mouseReleaseEvent(self, event, scene_pos: QPointF):
        if super().mouseReleaseEvent(event, scene_pos): return
        if event.button() == Qt.MouseButton.LeftButton and self.origin and self.preview_item:
            if not _qt_object_is_valid(self.preview_item):
                self.cleanup()
                return
            rect = self.preview_item.rect()
            is_alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            
            # Ensure valid size (or any size if Alt)
            if is_alt or (rect.width() >= self.canvas.grid_size and rect.height() >= self.canvas.grid_size):
                final_item = DungeonEllipseItem(rect)
                final_item.setPos(self.preview_item.pos())
                
                # Layer assignment
                current_layer = getattr(self.canvas, "_current_layer", LAYER_FG)
                z_val = 1
                if current_layer == LAYER_MID:
                    z_val = -49
                elif current_layer == LAYER_BG:
                    z_val = -99
                
                final_item.setZValue(z_val)
                final_item.setData(ROLE_LAYER, current_layer)
                
                self.canvas.undo_stack.beginMacro("Create Ellipse Room")
                cmd = CreateItemCommand(self.canvas.scene(), final_item, "Create Ellipse")
                self.canvas.undo_stack.push(cmd)
                
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    _smooth_connect_rooms(self.canvas, final_item)
                    
                self.canvas.undo_stack.endMacro()
            
            self.cleanup()

class PlacingState(CanvasState):
    def __init__(self, canvas: 'DungeonCanvas', tool: str):
        super().__init__(canvas)
        self.tool = tool

    def on_enter(self):
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event, scene_pos: QPointF):
        if super().mousePressEvent(event, scene_pos): return True
        if event.button() == Qt.MouseButton.LeftButton:
            if self.tool == TOOL_DOOR:
                self.canvas._place_door(scene_pos)
            elif self.tool == TOOL_PILLAR:
                self.canvas._place_pillar(scene_pos)
            elif self.tool == TOOL_MONSTER:
                self.canvas._place_monster(scene_pos)
            elif self.tool == TOOL_PLAYER:
                self.canvas._place_player(scene_pos)
            elif self.tool == TOOL_ENCOUNTER:
                self.canvas._spawn_encounter(scene_pos)
            elif self.tool == 'entity':
                self.canvas._place_entity(scene_pos)
            return True
        return False

class DrawingPolygonState(CanvasState):
    def __init__(self, canvas: 'DungeonCanvas'):
        super().__init__(canvas)
        self.points: list[QPointF] = []
        self.preview: Optional[QGraphicsPathItem] = None

    def on_enter(self):
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)

    def on_exit(self):
        if self.preview and _qt_object_is_valid(self.preview):
            self.canvas.scene().removeItem(self.preview)
            self.preview = None
        self.points = []

    def mousePressEvent(self, event, scene_pos: QPointF):
        if super().mousePressEvent(event, scene_pos): return True
        if event.button() == Qt.MouseButton.LeftButton:
            snapped_pos = _snap_point(scene_pos, self.canvas.grid_size)
            if not self.points:
                self.points = [snapped_pos]
                self.preview = QGraphicsPathItem()
                self.preview.setPen(QPen(QColor(WALL_COLOR), WALL_WIDTH))
                fill_color = QColor(FLOOR_COLOR)
                fill_color.setAlpha(120)
                self.preview.setBrush(fill_color)
                
                # Layer assignment
                current_layer = getattr(self.canvas, "_current_layer", LAYER_FG)
                z_val = 100
                if current_layer == LAYER_MID:
                    z_val = 50
                elif current_layer == LAYER_BG:
                    z_val = 0
                
                self.preview.setZValue(z_val)
                self.preview.setData(ROLE_LAYER, current_layer)
                self.canvas.scene().addItem(self.preview)
            else:
                # Check if closing the polygon (clicking near start)
                if len(self.points) >= 3 and (snapped_pos - self.points[0]).manhattanLength() < self.canvas.grid_size:
                    self.finish(event.modifiers())
                else:
                    self.points.append(snapped_pos)
            return True
        return False

    def mouseMoveEvent(self, event, scene_pos: QPointF):
        if super().mouseMoveEvent(event, scene_pos): return
        if self.preview and self.points:
            if not _qt_object_is_valid(self.preview):
                self.preview = None
                self.points = []
                return
            snapped_pos = _snap_point(scene_pos, self.canvas.grid_size)
            path = QPainterPath()
            path.moveTo(self.points[0])
            for p in self.points[1:]:
                path.lineTo(p)
            path.lineTo(snapped_pos)
            self.preview.setPath(path)

    def mouseDoubleClickEvent(self, event):
        self.finish(event.modifiers())
        
    def finish(self, modifiers = Qt.KeyboardModifier.NoModifier):
        if len(self.points) < 3:
            return
            
        self.canvas.undo_stack.beginMacro("Create Polygon Room")
        
        # Create room group
        room = RoomGroup()
        
        # Layer assignment
        current_layer = getattr(self.canvas, "_current_layer", LAYER_FG)
        z_val = 0
        if current_layer == LAYER_MID:
            z_val = -50
        elif current_layer == LAYER_BG:
            z_val = -100
        
        room.setZValue(z_val)
        room.setData(ROLE_LAYER, current_layer)
        room.setData(ROLE_KIND, TOOL_POLYGON)
        room.setData(ROLE_LOCKED, False)
        
        # Create polygon floor
        poly = QPolygonF(self.points)
        room.add_polygon_floor(poly)
        
        # Add walls
        points = self.points
        # Close loop explicitly if not closed
        if points[0] != points[-1]:
            # No need to append to self.points as we are done
            pass
            
        # We need walls between points in order, plus last to first
        for i in range(len(points)):
            p1 = points[i]
            p2 = points[(i + 1) % len(points)]
            room.add_wall(p1.x(), p1.y(), p2.x(), p2.y())
            
        self.canvas.undo_stack.push(CreateItemCommand(self.canvas.scene(), room, "Create Polygon Room"))
        
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            _smooth_connect_rooms(self.canvas, room)
            
        self.canvas.undo_stack.endMacro()
        self.on_exit()


class EraserState(CanvasState):
    """State for erasing items by clicking on them."""
    def __init__(self, canvas: 'DungeonCanvas'):
        super().__init__(canvas)
        self.is_erasing = False

    def on_enter(self):
        # Use eraser icon as cursor
        eraser_icon_path = icon_path("eraser.svg")
        if eraser_icon_path.exists():
            from PySide6.QtGui import QCursor, QPixmap
            pixmap = QPixmap(str(eraser_icon_path)).scaled(24, 24)
            self.canvas.setCursor(QCursor(pixmap, 0, 24))  # Hotspot at bottom-left
        else:
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event, scene_pos: QPointF):
        if super().mousePressEvent(event, scene_pos): return True
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_erasing = True
            self.canvas.undo_stack.beginMacro("Erase Items")
            self._erase_at(scene_pos)
            return True
        return False

    def mouseMoveEvent(self, event, scene_pos: QPointF):
        if super().mouseMoveEvent(event, scene_pos): return
        if self.is_erasing:
            self._erase_at(scene_pos)

    def mouseReleaseEvent(self, event, scene_pos: QPointF):
        if super().mouseReleaseEvent(event, scene_pos): return
        if event.button() == Qt.MouseButton.LeftButton and self.is_erasing:
            self.is_erasing = False
            self.canvas.undo_stack.endMacro()

    def _erase_at(self, scene_pos: QPointF):
        # Find items in a small area around click (better hit detection for thin strokes)
        hit_radius = 5
        hit_rect = QRectF(scene_pos.x() - hit_radius, scene_pos.y() - hit_radius, 
                         hit_radius * 2, hit_radius * 2)
        items = self.canvas.scene().items(hit_rect)
        current_owner = str(getattr(self.canvas, "_stroke_owner_player_id", "") or "").strip()
        for item in items:
            # ONLY erase brush strokes
            if item.data(ROLE_KIND) == "stroke":
                if current_owner:
                    stroke_owner = str(item.data(ROLE_OWNER_PLAYER_ID) or "").strip()
                    if stroke_owner != current_owner:
                        continue
                # Verify item is still in scene (might have been deleted in previous step of same stroke)
                if item.scene() == self.canvas.scene():
                    cmd = DeleteItemCommand(self.canvas.scene(), item, "Erase Item")
                    self.canvas.undo_stack.push(cmd)
                    break # Only erase one per click/move


class FogState(CanvasState):
    def __init__(self, canvas: 'DungeonCanvas', tool: str):
        super().__init__(canvas)
        self.tool = tool
        self.is_drawing = False
        self.brush_size = GRID_SIZE * 2
        
    def on_enter(self):
        # We need to make sure fog item exists
        if not self.canvas.fog_item:
             self.canvas.init_fog()
             
        # Hide standard cursor
        self.canvas.setCursor(Qt.CursorShape.BlankCursor)

        # Set up foreground preview (drawn in DungeonCanvas.drawForeground)
        self.canvas._fog_preview_radius = self.brush_size / 2
        local_mouse = self.canvas.mapFromGlobal(QCursor.pos())
        self.canvas._fog_preview_pos = self.canvas.mapToScene(local_mouse)
        self.canvas.viewport().update()

    def on_exit(self):
        # Clear the foreground preview
        self.canvas._fog_preview_pos = None
        self.canvas.viewport().update()

    def mousePressEvent(self, event, scene_pos: QPointF):
        if super().mousePressEvent(event, scene_pos): return True
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_drawing = True
            # Cache start path for undo
            self.start_path = self.canvas.fog_item.path()
            self._apply_fog(scene_pos)
            return True
        return False

    def mouseMoveEvent(self, event, scene_pos: QPointF):
        # Update foreground preview position
        self.canvas._fog_preview_pos = scene_pos
        self.canvas.viewport().update()
            
        if super().mouseMoveEvent(event, scene_pos): return
        if self.is_drawing:
             self._apply_fog(scene_pos)

    def mouseReleaseEvent(self, event, scene_pos: QPointF):
        if super().mouseReleaseEvent(event, scene_pos): return
        if event.button() == Qt.MouseButton.LeftButton and self.is_drawing:
            self.is_drawing = False
            # Commit undo command
            new_path = self.canvas.fog_item.path()
            if new_path != self.start_path:
                 cmd = ModifyFogCommand(self.canvas.fog_item, self.start_path, new_path)
                 self.canvas.undo_stack.push(cmd)

    def _apply_fog(self, pos: QPointF):
        # Create brush shape
        brush = QPainterPath()
        brush.addEllipse(pos, self.brush_size/2, self.brush_size/2)
        
        current_path = self.canvas.fog_item.path()
        if self.tool == TOOL_FOW_BRUSH:
            new_path = current_path.united(brush)
        else: # Eraser
            new_path = current_path.subtracted(brush)
            
        self.canvas.fog_item.setPath(new_path)

class EncounterPlacingState(CanvasState):
    def __init__(self, canvas: 'DungeonCanvas'):
        super().__init__(canvas)
        self.monsters_data = None

    def on_enter(self):
        self.canvas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.monsters_data = self.canvas.get_encounter_data()
        if not self.monsters_data:
            # If cancelled, we might want to change tool back to Select to avoid confusion
            # But we can't easily change tool from inside on_enter without carefully managing re-entrancy
            # For now, we'll just leave it. Clicking will prompt again.
            pass

    def on_exit(self):
        self.monsters_data = None

    def mousePressEvent(self, event, scene_pos: QPointF):
        if super().mousePressEvent(event, scene_pos): return True
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.monsters_data:
                self.monsters_data = self.canvas.get_encounter_data()
            
            if self.monsters_data:
                self.canvas._spawn_encounter_entities(scene_pos, self.monsters_data)
                return True
        return False


class PingState(CanvasState):
    """
    State for the Ping tool. Spawns a PingItem on click.
    """
    def on_enter(self):
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event, scene_pos: QPointF):
        if super().mousePressEvent(event, scene_pos): return True
        if event.button() == Qt.MouseButton.LeftButton:
            self.canvas.show_ping(scene_pos)
            return True
        return False


class ImagePlacingState(CanvasState):
    """
    State for placing images. Opens a file dialog immediately on enter, 
    then shows a ghost of the image until placed.
    """
    def __init__(self, canvas: 'DungeonCanvas'):
        super().__init__(canvas)
        self.pixmap: Optional[QPixmap] = None
        self.preview_item: Optional[QGraphicsPixmapItem] = None
        self.file_path: Optional[str] = None

    def on_enter(self):
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)
        # Prompt for image immediately
        file_path, _ = QFileDialog.getOpenFileName(
            self.canvas, "Open Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            self.file_path = file_path
            self.pixmap = QPixmap(file_path)
            if not self.pixmap.isNull():
                self.preview_item = QGraphicsPixmapItem(self.pixmap)
                self.preview_item.setOpacity(0.5)
                self.preview_item.setZValue(1000)
                self.canvas.scene().addItem(self.preview_item)
            else:
                self._cancel()
        else:
            self._cancel()

    def _cancel(self):
        # Switch back to select tool if cancelled or failed
        from dungeon_applet import ToolType
        self.canvas.current_tool = ToolType.SELECT

    def on_exit(self):
        if self.preview_item and _qt_object_is_valid(self.preview_item):
            if self.preview_item.scene():
                self.canvas.scene().removeItem(self.preview_item)
        self.preview_item = None
        self.pixmap = None
        self.file_path = None

    def mouseMoveEvent(self, event, scene_pos: QPointF):
        if super().mouseMoveEvent(event, scene_pos): return
        if self.preview_item:
            if not _qt_object_is_valid(self.preview_item):
                self.preview_item = None
                return
            # Snap the ghost if Alt is not held
            pos = _snap_point(scene_pos, self.canvas.grid_size)
            self.preview_item.setPos(pos)

    def mousePressEvent(self, event, scene_pos: QPointF):
        if super().mousePressEvent(event, scene_pos): return True
        if event.button() == Qt.MouseButton.LeftButton and self.pixmap:
            pos = _snap_point(scene_pos, self.canvas.grid_size)
            img_item = DungeonImageItem(self.pixmap, pos, source_path=self.file_path or "")
            img_item.setData(ROLE_ENTITY_ID, uuid.uuid4().hex)
            
            # Layer assignment
            current_layer = getattr(self.canvas, "_current_layer", LAYER_FG)
            if current_layer == LAYER_MID:
                img_item.setZValue(img_item.zValue() - 50)
            elif current_layer == LAYER_BG:
                img_item.setZValue(img_item.zValue() - 100)
            img_item.setData(ROLE_LAYER, current_layer)
            img_item.setData(ROLE_KIND, "image")
            img_item.set_resize_finished_callback(
                lambda old_rect, new_rect, old_pos, new_pos, item=img_item: self.canvas.undo_stack.push(
                    ResizeImageCommand(item, old_rect, new_rect, old_pos, new_pos)
                )
            )

            cmd = CreateItemCommand(self.canvas.scene(), img_item, "Place Image")
            self.canvas.undo_stack.push(cmd)
            
            # Switch back to select tool after placement
            from dungeon_applet import ToolType
            self.canvas.current_tool = ToolType.SELECT
            return True
        elif event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return True
        return False
