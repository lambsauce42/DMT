from __future__ import annotations

from PyQt6.QtGui import QUndoCommand, QPainterPath
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsItem
from PyQt6.QtCore import QPointF, QRectF

class CreateItemCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, item: QGraphicsItem, description: str):
        super().__init__(description)
        self._scene = scene
        self._item = item

    def redo(self):
        if self._item.scene() != self._scene:
             self._scene.addItem(self._item)

    def undo(self):
        if self._item.scene() == self._scene:
             self._scene.removeItem(self._item)


class DeleteItemCommand(QUndoCommand):
    """Delete a single item (opposite of CreateItemCommand)."""
    def __init__(self, scene: QGraphicsScene, item: QGraphicsItem, description: str):
        super().__init__(description)
        self._scene = scene
        self._item = item

    def redo(self):
        if self._item.scene() == self._scene:
             self._scene.removeItem(self._item)

    def undo(self):
        if self._item.scene() != self._scene:
             self._scene.addItem(self._item)

class DeleteItemsCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, items: list[QGraphicsItem]):
        super().__init__("Delete items")
        self._scene = scene
        self._items = items

    def redo(self):
        for item in self._items:
            if item.scene() == self._scene:
                self._scene.removeItem(item)

    def undo(self):
        for item in self._items:
            if item.scene() != self._scene:
                self._scene.addItem(item)

class MoveItemsCommand(QUndoCommand):
    def __init__(self, items: list[QGraphicsItem], start_positions: dict[QGraphicsItem, QPointF]):
        super().__init__("Move items")
        self._items = items
        self._start_positions = start_positions
        self._end_positions = {item: item.pos() for item in items}

    def redo(self):
        for item in self._items:
            if item in self._end_positions:
                item.setPos(self._end_positions[item])

    def undo(self):
        for item in self._items:
            if item in self._start_positions:
                item.setPos(self._start_positions[item])

class PropertyChangeCommand(QUndoCommand):
    def __init__(self, item: QGraphicsItem, key: int, old_value, new_value, description="Change Property"):
        super().__init__(description)
        self._item = item
        self._key = key
        self._old_value = old_value
        self._new_value = new_value

    def redo(self):
        self._item.setData(self._key, self._new_value)
        # We might need a callback or signal to refresh visuals if the property affects them
        # For now, rely on external updates or property observers if any. 
        # But QGraphicsItem doesn't signal on data change.
        # So the caller (often canvas) might need to trigger update() on item.
        self._item.update()

    def undo(self):
        self._item.setData(self._key, self._old_value)
        self._item.update()

class ModifyFogCommand(QUndoCommand):
    def __init__(self, fog_item, old_path: QPainterPath, new_path: QPainterPath):
        super().__init__("Modify Fog")
        self._fog_item = fog_item
        self._old_path = old_path
        self._new_path = new_path
        
    def redo(self):
        self._fog_item.setPath(self._new_path)
        
    def undo(self):
        self._fog_item.setPath(self._old_path)

class AttributeChangeCommand(QUndoCommand):
    """Command to change a python attribute on an object (e.g. item.hp = 10)."""
    def __init__(self, item: object, attr: str, old_value, new_value, description="Change Attribute"):
        super().__init__(description)
        self._item = item
        self._attr = attr
        self._old_value = old_value
        self._new_value = new_value

    def redo(self):
        setattr(self._item, self._attr, self._new_value)
        if isinstance(self._item, QGraphicsItem):
            self._item.update()

    def undo(self):
        setattr(self._item, self._attr, self._old_value)
        if isinstance(self._item, QGraphicsItem):
            self._item.update()


class ResizeImageCommand(QUndoCommand):
    """Command to resize a DungeonImageItem while preserving undo/redo."""
    def __init__(
        self,
        image_item: QGraphicsItem,
        old_rect: QRectF,
        new_rect: QRectF,
        old_pos: QPointF | None = None,
        new_pos: QPointF | None = None,
    ):
        super().__init__("Resize Image")
        self._image_item = image_item
        self._old_rect = QRectF(old_rect)
        self._new_rect = QRectF(new_rect)
        self._old_pos = QPointF(old_pos) if old_pos is not None else None
        self._new_pos = QPointF(new_pos) if new_pos is not None else None

    def redo(self):
        if self._new_pos is not None:
            self._image_item.setPos(self._new_pos)
        if hasattr(self._image_item, "set_rect_size"):
            self._image_item.set_rect_size(self._new_rect.width(), self._new_rect.height())

    def undo(self):
        if self._old_pos is not None:
            self._image_item.setPos(self._old_pos)
        if hasattr(self._image_item, "set_rect_size"):
            self._image_item.set_rect_size(self._old_rect.width(), self._old_rect.height())


class ResizeRoomCommand(QUndoCommand):
    """Command to resize a room path while preserving undo/redo."""
    def __init__(self, room_item: QGraphicsItem, old_path: QPainterPath, new_path: QPainterPath):
        super().__init__("Resize Room")
        self._room_item = room_item
        self._old_path = QPainterPath(old_path)
        self._new_path = QPainterPath(new_path)

    def _apply_path(self, path: QPainterPath) -> None:
        if hasattr(self._room_item, "rebuild_from_path"):
            self._room_item.rebuild_from_path(path)
        if isinstance(self._room_item, QGraphicsItem):
            self._room_item.update()

    def redo(self):
        self._apply_path(self._new_path)

    def undo(self):
        self._apply_path(self._old_path)


class SpawnPingCommand(QUndoCommand):
    """Command to spawn a transient ping effect."""
    def __init__(self, scene: QGraphicsScene, position: QPointF):
        super().__init__("Ping")
        self._scene = scene
        self._position = QPointF(position)
        self._ping_item = None

    def redo(self):
        from dungeon_items import PingItem
        if self._ping_item is None:
            self._ping_item = PingItem(self._position)
        if self._ping_item.scene() != self._scene:
            self._scene.addItem(self._ping_item)
        if hasattr(self._ping_item, "restart_animation"):
            self._ping_item.restart_animation()

    def undo(self):
        if self._ping_item and self._ping_item.scene() == self._scene:
            if hasattr(self._ping_item, "stop_animation"):
                self._ping_item.stop_animation()
            self._scene.removeItem(self._ping_item)
