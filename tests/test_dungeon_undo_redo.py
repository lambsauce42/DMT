
import sys
import os
import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPen, QColor, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QApplication, QGraphicsPathItem, QGraphicsScene
from PySide6.QtCore import Qt

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dungeon_applet import DungeonAppletWidget, ToolType
from dungeon_commands import CreateItemCommand
from dungeon_items import EntityItem, DungeonImageItem, RoomGroup
from dungeon_constants import ROLE_LABEL, ROLE_KIND, ROLE_LAYER, TOOL_ROOM, LAYER_FG, LAYER_BG
from dungeon_states import _smooth_connect_rooms

@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    widget.show()
    qtbot.addWidget(widget)
    return widget

def test_undo_redo_create_entity(dungeon_widget):
    canvas = dungeon_widget.canvas
    scene = canvas.scene()
    
    initial_count = len(scene.items())
    
    canvas._place_entity(QPointF(100, 100))
    
    assert len(scene.items()) == initial_count + 1
    item = scene.items()[0]
    assert isinstance(item, EntityItem)
    
    canvas.undo()
    assert len(scene.items()) == initial_count
    
    canvas.redo()
    assert len(scene.items()) == initial_count + 1
    
def test_delete_functionality(dungeon_widget):
    canvas = dungeon_widget.canvas
    scene = canvas.scene()
    
    initial_count = len(scene.items())
    
    canvas._place_entity(QPointF(200, 200))
    item = scene.items()[0]
    
    item.setSelected(True)
    canvas.delete_selected_items()
    assert len(scene.items()) == initial_count
    
    canvas.undo()
    assert len(scene.items()) == initial_count + 1
    
    canvas.redo()
    assert len(scene.items()) == initial_count

def test_undo_redo_properties(dungeon_widget, qtbot):
    canvas = dungeon_widget.canvas
    
    # 1. Setup Entity
    canvas._place_entity(QPointF(100, 100))
    # Note: scene.items() order is Z-order usually. Entity is on top.
    # But let's find the entity.
    entities = [i for i in canvas.scene().items() if isinstance(i, EntityItem)]
    assert len(entities) == 1
    entity = entities[0]
    
    initial_hp = entity.hp
    
    # Select to activate inspector
    entity.setSelected(True)
    # Process events to allow scene signal to propagate
    QApplication.processEvents()
    
    inspector = dungeon_widget.inspector
    if inspector._entity != entity:
         dungeon_widget._on_selection_changed()
    
    # 2. Change HP via Inspector
    # Simulate rapid changes
    inspector.hp_stat.curr_edit.setValue(50) 
    # Timer started
    assert entity.hp == 50
    
    inspector.hp_stat.curr_edit.setValue(40)
    assert entity.hp == 40
    
    # Force timeout/commit
    inspector._commit_changes()
    
    # Stack check
    # 0: Create Entity
    # 1: Change Properties
    assert canvas.undo_stack.count() == 2
    
    # 3. Undo
    canvas.undo()
    assert entity.hp == initial_hp 
    
    # 4. Redo
    canvas.redo()
    assert entity.hp == 40


def test_undo_redo_entity_name(dungeon_widget):
    canvas = dungeon_widget.canvas

    canvas._place_entity(QPointF(100, 100))
    entity = next(i for i in canvas.scene().items() if isinstance(i, EntityItem))
    entity.setSelected(True)
    QApplication.processEvents()
    dungeon_widget._on_selection_changed()

    inspector = dungeon_widget.inspector
    inspector.name_edit.setText("Bandit Captain")
    inspector._update_name()

    assert entity.data(ROLE_LABEL) == "Bandit Captain"
    assert canvas.undo_stack.count() == 2

    canvas.undo()
    assert (entity.data(ROLE_LABEL) or "") == ""

    canvas.redo()
    assert entity.data(ROLE_LABEL) == "Bandit Captain"


def test_image_placement_is_undoable(dungeon_widget, qtbot, monkeypatch, tmp_path):
    canvas = dungeon_widget.canvas
    image_path = tmp_path / "token.png"
    pix = QPixmap(32, 32)
    pix.fill(QColor("#3b82f6"))
    assert pix.save(str(image_path))

    monkeypatch.setattr(
        "dungeon_states.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(image_path), "Images (*.png)"),
    )

    canvas.current_tool = ToolType.IMAGE
    click_pos = canvas.mapFromScene(QPointF(200, 200))
    qtbot.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=click_pos)

    images = [i for i in canvas.scene().items() if isinstance(i, DungeonImageItem)]
    assert len(images) == 1
    assert canvas.undo_stack.count() == 1

    canvas.undo()
    assert len([i for i in canvas.scene().items() if isinstance(i, DungeonImageItem)]) == 0

    canvas.redo()
    assert len([i for i in canvas.scene().items() if isinstance(i, DungeonImageItem)]) == 1


def test_merge_ignores_other_layers(dungeon_widget):
    scene = dungeon_widget.canvas.scene()

    fg_room = RoomGroup()
    fg_room.setData(ROLE_KIND, TOOL_ROOM)
    fg_room.setData(ROLE_LAYER, LAYER_FG)
    fg_room.add_floor(QRectF(0, 0, 120, 120))
    fg_room.add_wall(0, 0, 120, 0)
    fg_room.add_wall(120, 0, 120, 120)
    fg_room.add_wall(120, 120, 0, 120)
    fg_room.add_wall(0, 120, 0, 0)
    scene.addItem(fg_room)

    bg_room = RoomGroup()
    bg_room.setData(ROLE_KIND, TOOL_ROOM)
    bg_room.setData(ROLE_LAYER, LAYER_BG)
    bg_room.add_floor(QRectF(60, 60, 120, 120))
    bg_room.add_wall(60, 60, 180, 60)
    bg_room.add_wall(180, 60, 180, 180)
    bg_room.add_wall(180, 180, 60, 180)
    bg_room.add_wall(60, 180, 60, 60)
    scene.addItem(bg_room)

    _smooth_connect_rooms(dungeon_widget.canvas, fg_room)

    rooms = [i for i in scene.items() if isinstance(i, RoomGroup)]
    assert len(rooms) == 2
    assert dungeon_widget.canvas.undo_stack.count() == 0


def test_merge_preserves_layer_and_z(dungeon_widget):
    scene = dungeon_widget.canvas.scene()

    room_a = RoomGroup()
    room_a.setData(ROLE_KIND, TOOL_ROOM)
    room_a.setData(ROLE_LAYER, LAYER_BG)
    room_a.setZValue(-100)
    room_a.add_floor(QRectF(0, 0, 120, 120))
    room_a.add_wall(0, 0, 120, 0)
    room_a.add_wall(120, 0, 120, 120)
    room_a.add_wall(120, 120, 0, 120)
    room_a.add_wall(0, 120, 0, 0)
    scene.addItem(room_a)

    room_b = RoomGroup()
    room_b.setData(ROLE_KIND, TOOL_ROOM)
    room_b.setData(ROLE_LAYER, LAYER_BG)
    room_b.setZValue(-100)
    room_b.add_floor(QRectF(60, 60, 120, 120))
    room_b.add_wall(60, 60, 180, 60)
    room_b.add_wall(180, 60, 180, 180)
    room_b.add_wall(180, 180, 60, 180)
    room_b.add_wall(60, 180, 60, 60)
    scene.addItem(room_b)

    _smooth_connect_rooms(dungeon_widget.canvas, room_a)

    rooms = [i for i in scene.items() if isinstance(i, RoomGroup)]
    assert len(rooms) == 1
    merged = rooms[0]
    assert merged.data(ROLE_LAYER) == LAYER_BG
    assert merged.zValue() == -100


def test_round_trip_preserves_layer_z_and_image(dungeon_widget, tmp_path):
    scene = dungeon_widget.canvas.scene()

    entity = EntityItem(QPointF(20, 20))
    entity.setData(ROLE_KIND, "entity")
    entity.setData(ROLE_LAYER, LAYER_BG)
    entity.setZValue(-90)
    scene.addItem(entity)

    stroke_path = QPainterPath()
    stroke_path.moveTo(0, 0)
    stroke_path.lineTo(40, 40)
    stroke = QGraphicsPathItem(stroke_path)
    stroke.setPen(QPen(QColor("#334155"), 6))
    stroke.setData(ROLE_KIND, "stroke")
    stroke.setData(ROLE_LAYER, LAYER_BG)
    stroke.setZValue(-95)
    scene.addItem(stroke)

    image_path = tmp_path / "map.png"
    pix = QPixmap(48, 48)
    pix.fill(QColor("#94a3b8"))
    assert pix.save(str(image_path))
    image_item = DungeonImageItem(QPixmap(str(image_path)), QPointF(40, 40), source_path=str(image_path))
    image_item.setData(ROLE_KIND, "image")
    image_item.setData(ROLE_LAYER, LAYER_BG)
    image_item.setZValue(-95)
    image_item.set_rect_size(96, 72)
    scene.addItem(image_item)

    state = dungeon_widget._serialize_scene()
    new_scene = QGraphicsScene()
    dungeon_widget._populate_scene(new_scene, state, include_fog=False)

    loaded_entities = [i for i in new_scene.items() if isinstance(i, EntityItem)]
    loaded_strokes = [i for i in new_scene.items() if isinstance(i, QGraphicsPathItem) and i.data(ROLE_KIND) == "stroke"]
    loaded_images = [i for i in new_scene.items() if isinstance(i, DungeonImageItem)]

    assert len(loaded_entities) == 1
    assert loaded_entities[0].data(ROLE_LAYER) == LAYER_BG
    assert loaded_entities[0].zValue() == -90

    assert len(loaded_strokes) == 1
    assert loaded_strokes[0].data(ROLE_LAYER) == LAYER_BG
    # Strokes are elevated above fog so they stay visible in FoW mode.
    assert loaded_strokes[0].zValue() == 205

    assert len(loaded_images) == 1
    assert loaded_images[0].data(ROLE_LAYER) == LAYER_BG
    assert loaded_images[0].zValue() == -95
    assert int(loaded_images[0]._rect.width()) == 96
    assert int(loaded_images[0]._rect.height()) == 72
