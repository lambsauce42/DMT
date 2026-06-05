import os
import sys

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dungeon_applet import DungeonAppletWidget, ToolType
from dungeon_constants import GRID_SIZE, ROLE_KIND
from dungeon_items import DungeonImageItem, RoomGroup


@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    widget.resize(1100, 800)
    widget.show()
    return widget


def _create_rect_room(dungeon_widget, qtbot, p1: QPointF, p2: QPointF) -> RoomGroup:
    canvas = dungeon_widget.canvas
    viewport = canvas.viewport()
    dungeon_widget._on_tool_changed(ToolType.RECTANGLE)
    qtbot.mouseMove(viewport, canvas.mapFromScene(p1))
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(p1))
    qtbot.mouseMove(viewport, canvas.mapFromScene(p2))
    qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(p2))
    QApplication.processEvents()
    rooms = [item for item in canvas.scene().items() if isinstance(item, RoomGroup)]
    assert rooms
    return rooms[0]


def _room_scene_floor_rect(room: RoomGroup):
    return room.floor_path().translated(room.pos()).boundingRect()


def test_draw_color_rail_visibility_tracks_tool_selection(dungeon_widget, qtbot):
    panel = dungeon_widget.tool_panel
    free_draw_btn = panel.button_for_tool(ToolType.FREE_DRAW)
    select_btn = panel.button_for_tool(ToolType.SELECT)
    assert free_draw_btn is not None
    assert select_btn is not None

    assert not panel._draw_color_rail.isVisible()
    qtbot.mouseClick(free_draw_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(120)
    assert panel._draw_color_rail.isVisible()

    qtbot.mouseClick(select_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(460)
    assert not panel._draw_color_rail.isVisible()


def test_draw_color_rail_has_requested_core_colors(dungeon_widget):
    panel = dungeon_widget.tool_panel
    colors = {button.color.name().lower() for button in panel._draw_color_rail._buttons}
    assert "#ffffff" in colors
    assert "#3b82f6" in colors
    assert "#facc15" in colors


def test_draw_color_rail_exposes_ruler_toggle_below_colors(dungeon_widget, qtbot):
    panel = dungeon_widget.tool_panel
    free_draw_btn = panel.button_for_tool(ToolType.FREE_DRAW)
    assert free_draw_btn is not None

    qtbot.mouseClick(free_draw_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(120)
    QApplication.processEvents()

    rail = panel._draw_color_rail
    ruler_button = rail._ruler_button
    assert ruler_button.isVisible()
    assert ruler_button.width() == ruler_button.height()
    assert ruler_button.y() > rail._buttons[-1].y()
    assert rail._ruler_angle_label.isVisible()
    assert rail._ruler_angle_label.y() > ruler_button.y()


def test_draw_ruler_toggle_updates_canvas(dungeon_widget, qtbot):
    panel = dungeon_widget.tool_panel
    ruler_button = panel._draw_color_rail._ruler_button

    assert not dungeon_widget.canvas.draw_ruler_enabled
    qtbot.mouseClick(ruler_button, Qt.MouseButton.LeftButton)

    assert dungeon_widget.canvas.draw_ruler_enabled


def test_draw_ruler_angle_is_integer(dungeon_widget):
    canvas = dungeon_widget.canvas

    canvas.set_draw_ruler_angle(12.4)
    assert canvas.draw_ruler_angle == 12
    assert dungeon_widget.tool_panel._draw_color_rail._ruler_angle_label.text() == "12 deg"

    canvas.rotate_draw_ruler(1)
    assert canvas.draw_ruler_angle == 13
    assert dungeon_widget.tool_panel._draw_color_rail._ruler_angle_label.text() == "13 deg"

    canvas.set_draw_ruler_angle(180)
    assert canvas.draw_ruler_angle == 0
    assert dungeon_widget.tool_panel._draw_color_rail._ruler_angle_label.text() == "0 deg"

    canvas.set_draw_ruler_angle(181)
    assert canvas.draw_ruler_angle == 1
    assert dungeon_widget.tool_panel._draw_color_rail._ruler_angle_label.text() == "1 deg"


def test_draw_color_rail_does_not_squeeze_tool_grid(dungeon_widget, qtbot):
    panel = dungeon_widget.tool_panel
    free_draw_btn = panel.button_for_tool(ToolType.FREE_DRAW)
    select_btn = panel.button_for_tool(ToolType.SELECT)
    image_btn = panel.button_for_tool(ToolType.IMAGE)
    assert free_draw_btn is not None
    assert select_btn is not None
    assert image_btn is not None

    QApplication.processEvents()
    width_before = panel.container.width()
    image_before_right = image_btn.geometry().right()

    qtbot.mouseClick(free_draw_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(140)
    QApplication.processEvents()
    width_show = panel.container.width()
    image_show_right = image_btn.geometry().right()

    qtbot.mouseClick(select_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(360)
    QApplication.processEvents()
    width_hide = panel.container.width()
    image_hide_right = image_btn.geometry().right()

    assert abs(width_show - width_before) <= 1
    assert abs(width_hide - width_before) <= 1
    assert abs(image_show_right - image_before_right) <= 1
    assert abs(image_hide_right - image_before_right) <= 1


def test_draw_color_rail_keeps_full_vertical_size(dungeon_widget, qtbot):
    panel = dungeon_widget.tool_panel
    free_draw_btn = panel.button_for_tool(ToolType.FREE_DRAW)
    assert free_draw_btn is not None
    qtbot.mouseClick(free_draw_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(120)
    QApplication.processEvents()

    rail = panel._draw_color_rail
    buttons = rail._buttons
    assert buttons
    min_required = len(buttons) * buttons[0].height()
    assert rail.height() >= min_required


def test_free_draw_uses_selected_color(dungeon_widget, qtbot):
    panel = dungeon_widget.tool_panel
    free_draw_btn = panel.button_for_tool(ToolType.FREE_DRAW)
    assert free_draw_btn is not None
    qtbot.mouseClick(free_draw_btn, Qt.MouseButton.LeftButton)
    panel.set_draw_color(QColor("#ef4444"))

    canvas = dungeon_widget.canvas
    viewport = canvas.viewport()
    p1 = QPointF(116, 116)
    p2 = QPointF(232, 174)
    qtbot.mouseMove(viewport, canvas.mapFromScene(p1))
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(p1))
    qtbot.mouseMove(viewport, canvas.mapFromScene(p2))
    qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(p2))
    QApplication.processEvents()

    strokes = [item for item in canvas.scene().items() if item.data(ROLE_KIND) == "stroke"]
    assert strokes
    assert strokes[0].pen().color().name().lower() == "#ef4444"


def test_ruler_draws_straight_line_with_selected_color(dungeon_widget, qtbot):
    panel = dungeon_widget.tool_panel
    free_draw_btn = panel.button_for_tool(ToolType.FREE_DRAW)
    assert free_draw_btn is not None
    qtbot.mouseClick(free_draw_btn, Qt.MouseButton.LeftButton)
    panel.set_draw_color(QColor("#22c55e"))
    qtbot.mouseClick(panel._draw_color_rail._ruler_button, Qt.MouseButton.LeftButton)

    canvas = dungeon_widget.canvas
    canvas.set_draw_ruler_angle(0)
    viewport = canvas.viewport()
    p1 = QPointF(120, 140)
    p2 = QPointF(260, 210)
    qtbot.mouseMove(viewport, canvas.mapFromScene(p1))
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(p1))
    qtbot.mouseMove(viewport, canvas.mapFromScene(p2))
    qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(p2))
    QApplication.processEvents()

    strokes = [item for item in canvas.scene().items() if item.data(ROLE_KIND) == "stroke"]
    assert strokes
    stroke = strokes[0]
    path = stroke.path()
    assert path.elementCount() == 2
    start = path.elementAt(0)
    end = path.elementAt(1)
    assert abs(float(start.y) - p1.y()) < 0.1
    assert abs(float(end.y) - p1.y()) < 0.1
    assert abs(float(end.x) - p2.x()) < 0.1
    assert stroke.pen().color().name().lower() == "#22c55e"


def test_room_resize_snaps_to_grid_unless_alt(dungeon_widget, qtbot):
    room = _create_rect_room(
        dungeon_widget,
        qtbot,
        QPointF(116, 116),
        QPointF(232, 232),
    )
    canvas = dungeon_widget.canvas
    viewport = canvas.viewport()
    dungeon_widget._on_tool_changed(ToolType.SELECT)
    QApplication.processEvents()

    initial_width = room.floor_path().boundingRect().width()

    corner = room.sceneBoundingRect().bottomRight()
    qtbot.mouseMove(viewport, canvas.mapFromScene(corner))
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(corner))
    snapped_target = corner + QPointF(41, 41)
    qtbot.mouseMove(viewport, canvas.mapFromScene(snapped_target))
    qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(snapped_target))
    QApplication.processEvents()

    snapped_width = room.floor_path().boundingRect().width()
    snapped_units = snapped_width / GRID_SIZE
    assert abs(snapped_units - round(snapped_units)) < 0.02
    assert snapped_width > initial_width

    corner = room.sceneBoundingRect().bottomRight()
    qtbot.mouseMove(viewport, canvas.mapFromScene(corner))
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(corner))
    qtbot.keyPress(canvas, Qt.Key.Key_Alt)
    unsnapped_target = corner + QPointF(13, 17)
    qtbot.mouseMove(viewport, canvas.mapFromScene(unsnapped_target))
    qtbot.mouseRelease(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
        pos=canvas.mapFromScene(unsnapped_target),
    )
    qtbot.keyRelease(canvas, Qt.Key.Key_Alt)
    QApplication.processEvents()

    unsnapped_width = room.floor_path().boundingRect().width()
    unsnapped_units = unsnapped_width / GRID_SIZE
    assert abs(unsnapped_units - round(unsnapped_units)) > 0.05

    canvas.undo()
    QApplication.processEvents()
    width_after_undo_alt = room.floor_path().boundingRect().width()
    assert abs(width_after_undo_alt - snapped_width) < 0.5

    canvas.undo()
    QApplication.processEvents()
    width_after_undo_snap = room.floor_path().boundingRect().width()
    assert abs(width_after_undo_snap - initial_width) < 0.5


def test_room_resize_near_corner_respects_drag_direction_without_jump(dungeon_widget, qtbot):
    room = _create_rect_room(
        dungeon_widget,
        qtbot,
        QPointF(116, 116),
        QPointF(232, 232),
    )
    canvas = dungeon_widget.canvas
    viewport = canvas.viewport()
    dungeon_widget._on_tool_changed(ToolType.SELECT)
    QApplication.processEvents()

    initial_width = room.floor_path().boundingRect().width()
    initial_height = room.floor_path().boundingRect().height()

    corner = room.sceneBoundingRect().bottomRight()
    press_pos = corner - QPointF(4, 4)
    tiny_outward_drag = corner + QPointF(18, 18)

    qtbot.mouseMove(viewport, canvas.mapFromScene(press_pos))
    qtbot.keyPress(canvas, Qt.Key.Key_Alt)
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(press_pos))
    qtbot.mouseMove(viewport, canvas.mapFromScene(tiny_outward_drag))
    qtbot.mouseRelease(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
        pos=canvas.mapFromScene(tiny_outward_drag),
    )
    qtbot.keyRelease(canvas, Qt.Key.Key_Alt)
    QApplication.processEvents()

    resized_width = room.floor_path().boundingRect().width()
    resized_height = room.floor_path().boundingRect().height()
    assert resized_width > initial_width + 0.5
    assert resized_height > initial_height + 0.5


@pytest.mark.parametrize(
    "corner,delta,expect_x_move,expect_y_move",
    [
        ("top_left", QPointF(-24, -18), True, True),
        ("top_right", QPointF(24, -18), False, True),
        ("bottom_left", QPointF(-24, 18), True, False),
        ("bottom_right", QPointF(24, 18), False, False),
    ],
)
def test_image_resize_works_from_every_corner(
    dungeon_widget,
    qtbot,
    corner,
    delta,
    expect_x_move,
    expect_y_move,
):
    canvas = dungeon_widget.canvas
    viewport = canvas.viewport()
    dungeon_widget._on_tool_changed(ToolType.SELECT)

    pix = QPixmap(80, 60)
    pix.fill(QColor("#94a3b8"))
    image = DungeonImageItem(pix, QPointF(232, 232))
    image.setData(ROLE_KIND, "image")
    canvas.scene().addItem(image)
    dungeon_widget._bind_image_resize_undo(canvas.scene(), image)
    image.setSelected(True)
    QApplication.processEvents()

    start_pos = QPointF(image.pos())
    start_w = float(image._rect.width())
    start_h = float(image._rect.height())

    if corner == "top_left":
        handle_scene = image.mapToScene(QPointF(2, 2))
    elif corner == "top_right":
        handle_scene = image.mapToScene(QPointF(image._rect.width() - 2, 2))
    elif corner == "bottom_left":
        handle_scene = image.mapToScene(QPointF(2, image._rect.height() - 2))
    else:
        handle_scene = image.mapToScene(QPointF(image._rect.width() - 2, image._rect.height() - 2))

    target = handle_scene + delta
    qtbot.mouseMove(viewport, canvas.mapFromScene(handle_scene))
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(handle_scene))
    qtbot.mouseMove(viewport, canvas.mapFromScene(target))
    qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(target))
    QApplication.processEvents()

    assert image._rect.width() > start_w + 0.5
    assert image._rect.height() > start_h + 0.5
    if expect_x_move:
        assert image.pos().x() < start_pos.x() - 0.5
    else:
        assert abs(image.pos().x() - start_pos.x()) < 0.5
    if expect_y_move:
        assert image.pos().y() < start_pos.y() - 0.5
    else:
        assert abs(image.pos().y() - start_pos.y()) < 0.5

    canvas.undo()
    QApplication.processEvents()
    assert abs(image.pos().x() - start_pos.x()) < 0.5
    assert abs(image.pos().y() - start_pos.y()) < 0.5
    assert abs(image._rect.width() - start_w) < 0.5
    assert abs(image._rect.height() - start_h) < 0.5


def test_merged_room_resize_does_not_flip_anchor_corner(dungeon_widget, qtbot):
    canvas = dungeon_widget.canvas
    viewport = canvas.viewport()
    dungeon_widget._on_tool_changed(ToolType.RECTANGLE)

    p1 = QPointF(116, 116)
    p2 = QPointF(232, 232)
    qtbot.mouseMove(viewport, canvas.mapFromScene(p1))
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(p1))
    qtbot.mouseMove(viewport, canvas.mapFromScene(p2))
    qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(p2))

    p3 = QPointF(174, 174)
    p4 = QPointF(290, 290)
    qtbot.keyPress(canvas, Qt.Key.Key_Shift)
    qtbot.mouseMove(viewport, canvas.mapFromScene(p3))
    qtbot.mousePress(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.mapFromScene(p3),
    )
    qtbot.mouseMove(viewport, canvas.mapFromScene(p4))
    qtbot.mouseRelease(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.mapFromScene(p4),
    )
    qtbot.keyRelease(canvas, Qt.Key.Key_Shift)
    QApplication.processEvents()

    rooms = [item for item in canvas.scene().items() if isinstance(item, RoomGroup)]
    assert len(rooms) == 1
    room = rooms[0]

    dungeon_widget._on_tool_changed(ToolType.SELECT)
    QApplication.processEvents()

    before = _room_scene_floor_rect(room)
    corner = room.sceneBoundingRect().bottomRight()
    cross_target = before.topLeft() - QPointF(120, 120)
    qtbot.mouseMove(viewport, canvas.mapFromScene(corner))
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(corner))
    qtbot.mouseMove(viewport, canvas.mapFromScene(cross_target))
    qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(cross_target))
    QApplication.processEvents()

    after = _room_scene_floor_rect(room)
    assert abs(after.left() - before.left()) < 1.0
    assert abs(after.top() - before.top()) < 1.0
    assert after.width() >= GRID_SIZE - 0.5
    assert after.height() >= GRID_SIZE - 0.5
