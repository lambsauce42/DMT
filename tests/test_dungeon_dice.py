import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import dungeon_applet
from dungeon_applet import DungeonAppletWidget


pytestmark = pytest.mark.tier1


def _global_center(widget):
    return widget.mapToGlobal(widget.rect().center())


def _global_contents_left(widget):
    return widget.mapToGlobal(widget.contentsRect().topLeft()).x()


@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    return widget


def test_dice_button_sits_next_to_media_without_overlap(dungeon_widget, qtbot):
    dungeon_widget.resize(1280, 720)
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._loot_pool_btn.setVisible(True)
    dungeon_widget._initiative_reopen_btn.setVisible(True)
    dungeon_widget._position_floating_overlays()

    assert not dungeon_widget._dice_btn.isHidden()
    buttons = [
        dungeon_widget._loot_pool_btn,
        dungeon_widget._dice_btn,
        dungeon_widget._media_btn,
        dungeon_widget._initiative_reopen_btn,
    ]
    heights = {button.height() for button in buttons}
    y_positions = {button.y() for button in buttons}
    assert heights == {46}
    assert y_positions == {20}
    gaps = [
        buttons[index + 1].x() - (buttons[index].x() + buttons[index].width())
        for index in range(len(buttons) - 1)
    ]
    assert gaps == [10, 10, 10]


def test_dice_tiles_are_square_svg_buttons_in_one_balanced_row(dungeon_widget, qtbot):
    dungeon_widget.resize(1280, 720)
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._toggle_dice_panel()
    qtbot.wait(220)
    dungeon_widget._refresh_dice_panel()

    tiles = list(dungeon_widget._dice_tile_buttons.values())
    y_positions = {tile.y() for tile in tiles}
    widths = {tile.width() for tile in tiles}
    heights = {tile.height() for tile in tiles}

    assert len(tiles) == 7
    assert len(y_positions) == 1
    assert widths == heights
    assert min(widths) >= 56
    assert all(not tile.icon().isNull() for tile in tiles)


def test_dice_pool_rows_and_actions_use_fixed_peer_geometry(dungeon_widget, qtbot):
    dungeon_widget._dice_groups = [
        {"group_id": "g1", "die_key": "d6", "sides": 6, "count": 2, "modifier": 0},
        {"group_id": "g2", "die_key": "d20", "sides": 20, "count": 1, "modifier": 1},
    ]
    dungeon_widget.resize(1280, 720)
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._dice_panel.show()
    dungeon_widget._refresh_dice_panel()
    qtbot.wait(20)

    row_heights = {row.height() for row in dungeon_widget._dice_group_row_widgets}
    remove_widths = {button.width() for button in dungeon_widget._dice_group_remove_buttons}
    mode_widths = {button.width() for button in dungeon_widget._dice_mode_buttons.values()}
    action_widths = {dungeon_widget._dice_roll_btn.width(), dungeon_widget._dice_reset_btn.width()}
    overall_left = dungeon_widget._dice_overall_modifier_spin.geometry().x()
    action_left = dungeon_widget._dice_roll_btn.geometry().x()
    mode_buttons = sorted(dungeon_widget._dice_mode_buttons.values(), key=lambda button: button.geometry().x())
    mode_center = dungeon_widget._dice_mode_center
    assert mode_center is not None
    center_left = mode_center.mapToGlobal(mode_center.rect().topLeft()).x()
    center_right = center_left + mode_center.width()
    first_button_left = mode_buttons[0].mapToGlobal(mode_buttons[0].rect().topLeft()).x()
    second_button_left = mode_buttons[1].mapToGlobal(mode_buttons[1].rect().topLeft()).x()
    last_button_right = mode_buttons[-1].mapToGlobal(mode_buttons[-1].rect().topRight()).x() + 1
    left_gap = first_button_left - center_left
    inner_gap = second_button_left - (first_button_left + mode_buttons[0].width())
    right_gap = center_right - last_button_right

    assert len(dungeon_widget._dice_group_row_widgets) == 2
    assert row_heights == {40}
    assert remove_widths == {88}
    assert mode_widths == {102}
    assert action_widths == {118}
    assert dungeon_widget._dice_overall_modifier_spin.width() == 118
    assert dungeon_widget._dice_overall_modifier_value.width() == 118
    assert overall_left == action_left
    assert abs(left_gap - inner_gap) <= 1
    assert abs(right_gap - inner_gap) <= 1
    assert dungeon_widget._dice_roll_btn.height() == dungeon_widget._dice_reset_btn.height() == 46


def test_dice_pool_remove_buttons_align_with_row_controls(dungeon_widget):
    dungeon_widget._dice_groups = [
        {"group_id": "g1", "die_key": "d4", "sides": 4, "count": 2, "modifier": 0},
    ]
    dungeon_widget._dice_panel.show()
    dungeon_widget._refresh_dice_panel()
    dungeon_applet.QApplication.processEvents()

    row = dungeon_widget._dice_group_row_widgets[0]
    remove_button = dungeon_widget._dice_group_remove_buttons[0]
    spin_boxes = row.findChildren(dungeon_applet.QSpinBox)

    assert len(spin_boxes) == 2
    assert row.height() == 40
    assert spin_boxes[0].height() == spin_boxes[1].height() == 40
    assert remove_button.height() == 40
    assert remove_button.width() == spin_boxes[1].width() == 88
    assert abs(_global_center(remove_button).y() - _global_center(row).y()) <= 1
    assert remove_button.mapToGlobal(remove_button.rect().topLeft()).y() == spin_boxes[0].mapToGlobal(spin_boxes[0].rect().topLeft()).y()
    assert remove_button.mapToGlobal(remove_button.rect().bottomLeft()).y() == spin_boxes[0].mapToGlobal(spin_boxes[0].rect().bottomLeft()).y()
    assert abs(_global_center(remove_button).y() - _global_center(spin_boxes[0]).y()) <= 1
    assert abs(_global_center(remove_button).y() - _global_center(spin_boxes[1]).y()) <= 1


def test_dice_pool_header_columns_match_row_columns(dungeon_widget):
    dungeon_widget._dice_groups = [
        {"group_id": "g1", "die_key": "d6", "sides": 6, "count": 2, "modifier": 1},
    ]
    dungeon_widget._dice_panel.show()
    dungeon_widget._refresh_dice_panel()
    dungeon_applet.QApplication.processEvents()

    row = dungeon_widget._dice_group_row_widgets[0]
    row_children = [
        child for child in row.children()
        if hasattr(child, "geometry") and child.metaObject().className() in {"QLabel", "QSpinBox", "QPushButton"}
    ]
    header_row = None
    for child in dungeon_widget._dice_pool_card.findChildren(dungeon_applet.QWidget):
        if child is row or child.height() != 46:
            continue
        labels = [label for label in child.findChildren(dungeon_applet.QLabel) if label.text() in {"Group", "Count", "Modifier", "Result", "Remove"}]
        if len(labels) == 5:
            header_row = child
            break

    assert header_row is not None
    header_labels = {label.text(): label for label in header_row.findChildren(dungeon_applet.QLabel)}
    group_label = next(child for child in row_children if child.metaObject().className() == "QLabel" and child.text() == "d6")
    count_spin, modifier_spin = row.findChildren(dungeon_applet.QSpinBox)
    result_label = next(child for child in row_children if child.metaObject().className() == "QLabel" and child.text() == "+1")
    remove_button = dungeon_widget._dice_group_remove_buttons[0]

    assert abs(_global_center(header_labels["Count"]).x() - _global_center(count_spin).x()) <= 1
    assert abs(_global_center(header_labels["Modifier"]).x() - _global_center(modifier_spin).x()) <= 1
    assert abs(_global_center(header_labels["Result"]).x() - _global_center(result_label).x()) <= 1
    assert abs(_global_center(header_labels["Remove"]).x() - _global_center(remove_button).x()) <= 1
    assert abs(_global_center(header_labels["Group"]).x() - _global_center(group_label).x()) <= 1
    assert abs(_global_contents_left(header_labels["Count"]) - count_spin.mapToGlobal(count_spin.rect().topLeft()).x() - 2) <= 1
    assert abs(_global_contents_left(header_labels["Modifier"]) - modifier_spin.mapToGlobal(modifier_spin.rect().topLeft()).x() - 2) <= 1
    assert abs(_global_contents_left(header_labels["Result"]) - result_label.mapToGlobal(result_label.rect().topLeft()).x() - 2) <= 1
    assert abs(_global_contents_left(header_labels["Remove"]) - remove_button.mapToGlobal(remove_button.rect().topLeft()).x() - 2) <= 1
    assert header_labels["Count"].alignment() & dungeon_applet.Qt.AlignmentFlag.AlignLeft
    assert header_labels["Modifier"].alignment() & dungeon_applet.Qt.AlignmentFlag.AlignLeft
    assert header_labels["Result"].alignment() & dungeon_applet.Qt.AlignmentFlag.AlignLeft
    assert header_labels["Remove"].alignment() & dungeon_applet.Qt.AlignmentFlag.AlignLeft


def test_dice_panel_opens_in_left_right_layout_without_existing_groups(dungeon_widget, qtbot):
    dungeon_widget.resize(1280, 720)
    dungeon_widget.show()
    qtbot.wait(20)

    dungeon_widget._toggle_dice_panel()
    qtbot.wait(20)
    assert dungeon_widget._dice_body_layout.direction() == dungeon_applet.QBoxLayout.Direction.LeftToRight
    qtbot.wait(260)

    assert dungeon_widget._dice_body_layout.direction() == dungeon_applet.QBoxLayout.Direction.LeftToRight


def test_dice_panel_layout_stays_left_right_after_adding_and_removing_group(dungeon_widget, qtbot):
    dungeon_widget.resize(1280, 720)
    dungeon_widget.show()
    qtbot.wait(20)

    dungeon_widget._toggle_dice_panel()
    qtbot.wait(260)
    dungeon_widget._on_dice_tile_clicked("d6")
    dungeon_widget._on_dice_reset_requested()

    assert dungeon_widget._dice_body_layout.direction() == dungeon_applet.QBoxLayout.Direction.LeftToRight


def test_dice_panel_cards_fit_inside_overlay_without_bottom_cutoff(dungeon_widget, qtbot):
    dungeon_widget.resize(1024, 680)
    dungeon_widget.show()
    qtbot.wait(20)
    for index in range(8):
        dungeon_widget._dice_groups.append(
            {
                "group_id": f"g{index}",
                "die_key": "d6",
                "sides": 6,
                "count": 2,
                "modifier": index % 3,
            }
        )
    dungeon_widget._toggle_dice_panel()
    qtbot.wait(220)
    dungeon_widget._refresh_dice_panel()

    panel_bottom = dungeon_widget._dice_panel.rect().bottom()
    body_bottom = dungeon_widget._dice_body_scroll.geometry().bottom()
    controls_bottom = dungeon_widget._dice_controls_card.geometry().bottom()
    history_bottom = dungeon_widget._dice_history_card.geometry().bottom()

    assert body_bottom <= panel_bottom
    assert controls_bottom <= dungeon_widget._dice_body_root.rect().bottom()
    assert history_bottom <= dungeon_widget._dice_body_root.rect().bottom()


def test_dice_panel_stacks_columns_before_horizontal_cutoff(dungeon_widget, qtbot):
    dungeon_widget.resize(1024, 680)
    dungeon_widget.show()
    qtbot.wait(20)
    for index in range(6):
        dungeon_widget._dice_groups.append(
            {
                "group_id": f"g{index}",
                "die_key": "d6",
                "sides": 6,
                "count": 2,
                "modifier": index % 2,
            }
        )
    dungeon_widget._toggle_dice_panel()
    qtbot.wait(220)
    dungeon_widget._refresh_dice_panel()

    viewport_width = dungeon_widget._dice_body_scroll.viewport().width()
    body_width = dungeon_widget._dice_body_root.width()
    layout_direction = dungeon_widget._dice_body_layout.direction()
    card_right_edges = {
        dungeon_widget._dice_quick_card.geometry().right(),
        dungeon_widget._dice_pool_card.geometry().right(),
        dungeon_widget._dice_controls_card.geometry().right(),
        dungeon_widget._dice_result_card.geometry().right(),
        dungeon_widget._dice_history_card.geometry().right(),
    }

    assert layout_direction == dungeon_applet.QBoxLayout.Direction.TopToBottom
    assert body_width <= viewport_width
    assert max(card_right_edges) <= dungeon_widget._dice_body_root.rect().right()


def test_small_screen_stack_keeps_breakdown_and_history_usable(dungeon_widget, qtbot):
    dungeon_widget.resize(1024, 680)
    dungeon_widget.show()
    qtbot.wait(20)
    for index in range(6):
        dungeon_widget._dice_groups.append(
            {
                "group_id": f"g{index}",
                "die_key": "d8",
                "sides": 8,
                "count": 2,
                "modifier": index % 2,
            }
        )
    dungeon_widget._toggle_dice_panel()
    qtbot.wait(220)
    dungeon_widget._refresh_dice_panel()

    assert dungeon_widget._dice_body_layout.direction() == dungeon_applet.QBoxLayout.Direction.TopToBottom
    assert dungeon_widget._dice_detail_stack.currentIndex() == 0
    assert dungeon_widget._dice_breakdown_scroll.viewport().height() >= 220
    dungeon_widget._on_dice_detail_view_selected("history")
    assert dungeon_widget._dice_detail_stack.currentIndex() == 1
    assert dungeon_widget._dice_history_scroll.viewport().height() >= 220


def test_result_card_geometry_stays_stable_before_and_after_roll(dungeon_widget, qtbot):
    dungeon_widget.resize(1600, 900)
    dungeon_widget.show()
    qtbot.wait(20)
    dungeon_widget._toggle_dice_panel()
    qtbot.wait(220)
    dungeon_widget._on_dice_tile_clicked("d20")
    qtbot.wait(20)

    before_card = dungeon_widget._dice_result_card.geometry()
    before_candidate = dungeon_widget._dice_candidate_slot.geometry()
    before_total = dungeon_widget._dice_total_label.geometry()
    before_controls = dungeon_widget._dice_controls_card.geometry()
    before_detail = dungeon_widget._dice_detail_card.geometry()
    assert dungeon_widget._dice_candidate_stack.currentIndex() == 0

    dungeon_widget._on_dice_mode_selected("advantage")
    dungeon_widget._on_dice_roll_requested()
    qtbot.wait(20)

    after_card = dungeon_widget._dice_result_card.geometry()
    after_candidate = dungeon_widget._dice_candidate_slot.geometry()
    after_total = dungeon_widget._dice_total_label.geometry()
    after_controls = dungeon_widget._dice_controls_card.geometry()
    after_detail = dungeon_widget._dice_detail_card.geometry()

    assert before_card.size() == after_card.size()
    assert before_candidate.size() == after_candidate.size()
    assert before_total.width() == after_total.width()
    assert before_controls.size() == after_controls.size()
    assert before_detail.size() == after_detail.size()
    assert dungeon_widget._dice_candidate_slot is not None
    assert dungeon_widget._dice_candidate_stack.currentIndex() == 1


def test_dice_roll_supports_duplicate_die_groups_with_distinct_modifiers(dungeon_widget, monkeypatch):
    dungeon_widget._dice_groups = [
        {"group_id": "g1", "die_key": "d4", "sides": 4, "count": 2, "modifier": 0},
        {"group_id": "g2", "die_key": "d4", "sides": 4, "count": 1, "modifier": 1},
    ]

    rolls = iter([1, 3, 2])
    monkeypatch.setattr(dungeon_applet.random, "randint", lambda _low, _high: next(rolls))

    dungeon_widget._on_dice_roll_requested()

    assert dungeon_widget._dice_last_result is not None
    assert dungeon_widget._dice_last_result["total"] == 7
    assert dungeon_widget._dice_total_label.text() == "7"
    assert dungeon_widget._dice_last_result["formula"] == "2d4 + 1d4+1"


def test_dice_roll_advantage_keeps_higher_attempt(dungeon_widget, monkeypatch):
    dungeon_widget._dice_groups = [
        {"group_id": "g1", "die_key": "d20", "sides": 20, "count": 1, "modifier": 0},
    ]
    dungeon_widget._dice_mode = "advantage"

    rolls = iter([5, 17])
    monkeypatch.setattr(dungeon_applet.random, "randint", lambda _low, _high: next(rolls))

    dungeon_widget._on_dice_roll_requested()

    assert dungeon_widget._dice_last_result is not None
    assert dungeon_widget._dice_last_result["selected_index"] == 1
    assert dungeon_widget._dice_last_result["total"] == 17
    assert [label.text() for label in dungeon_widget._dice_candidate_labels] == ["Drop: 5", "Kept: 17"]


def test_dice_mode_selection_does_not_auto_roll(dungeon_widget):
    dungeon_widget._dice_groups = [
        {"group_id": "g1", "die_key": "d20", "sides": 20, "count": 1, "modifier": 0},
    ]

    dungeon_widget._on_dice_mode_selected("advantage")

    assert dungeon_widget._dice_mode == "advantage"
    assert dungeon_widget._dice_last_result is None
    assert dungeon_widget._dice_history == []


def test_dice_detail_selection_switches_views_only(dungeon_widget):
    dungeon_widget._dice_groups = [
        {"group_id": "g1", "die_key": "d20", "sides": 20, "count": 1, "modifier": 0},
    ]
    dungeon_widget._dice_panel.show()
    dungeon_widget._refresh_dice_panel()

    dungeon_widget._on_dice_detail_view_selected("history")

    assert dungeon_widget._dice_detail_view == "history"
    assert dungeon_widget._dice_detail_stack.currentIndex() == 1
    assert dungeon_widget._dice_last_result is None
