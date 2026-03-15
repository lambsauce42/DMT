import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSplitter, QWidget

import player_sheets as player_sheets_module
from player_sheets import (
    LootItem,
    PlayerSheetEntry,
    PlayerSheetsWidget,
    EQUIPMENT_SLOTS_LEFT,
    EQUIPMENT_SLOTS_RIGHT,
    EQUIPMENT_SLOTS_WEAPONS,
    EQUIPMENT_SLOTS_MISC,
    compute_cursor_preview_position,
    compute_equipment_preview_position,
)


class PlayerSheetsEquipmentLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])
        # Keep UI-layout tests deterministic and fast by avoiding full loot-library disk scans.
        cls._loot_library_patcher = patch(
            "player_sheets._load_loot_item_library",
            return_value=([], {}),
        )
        cls._loot_library_patcher.start()
        # Avoid PDF viewer initialization side effects in layout-only tests.
        cls._pdfium_available_patcher = patch(
            "player_sheets.PDFIUM_VIEW_AVAILABLE",
            False,
        )
        cls._pdfium_available_patcher.start()

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_loot_library_patcher"):
            cls._loot_library_patcher.stop()
        if hasattr(cls, "_pdfium_available_patcher"):
            cls._pdfium_available_patcher.stop()

    def tearDown(self) -> None:
        # Ensure QWidget/QTimer cleanup between tests under pytest-qt to avoid
        # lingering event-loop work that can make the process appear hung.
        app = QApplication.instance()
        if app is None:
            return
        for widget in list(app.topLevelWidgets()):
            if isinstance(widget, QWidget):
                widget.close()
                widget.deleteLater()
        QApplication.sendPostedEvents(None, 0)
        QApplication.processEvents()

    @staticmethod
    def _apply_ratio(splitter: QSplitter, ratio: float) -> list[int]:
        sizes = splitter.sizes()
        total = sum(max(0, int(size)) for size in sizes)
        if total <= 2:
            return sizes
        primary = max(1, int(total * ratio))
        secondary = max(1, total - primary)
        splitter.setSizes([primary, secondary])
        QApplication.processEvents()
        return splitter.sizes()

    def _assert_sizes_close(
        self, actual: list[int], expected: list[int], tolerance: int = 4
    ) -> None:
        self.assertEqual(len(actual), len(expected))
        for a, e in zip(actual, expected):
            self.assertLessEqual(abs(a - e), tolerance)

    def test_equipment_slot_group_counts(self) -> None:
        self.assertEqual(len(EQUIPMENT_SLOTS_LEFT), 7)
        self.assertEqual(len(EQUIPMENT_SLOTS_RIGHT), 7)
        self.assertEqual(len(EQUIPMENT_SLOTS_WEAPONS), 4)
        self.assertEqual(len(EQUIPMENT_SLOTS_MISC), 10)
        self.assertEqual(EQUIPMENT_SLOTS_WEAPONS[-1], ("weapon_4", "Shield"))
        self.assertEqual(EQUIPMENT_SLOTS_LEFT[1], ("necklace", "Necklace"))
        self.assertEqual(EQUIPMENT_SLOTS_LEFT[-1], ("bracer", "Bracer"))
        self.assertEqual(EQUIPMENT_SLOTS_RIGHT[0], ("belt", "Belt"))
        self.assertEqual(EQUIPMENT_SLOTS_RIGHT[1], ("pants", "Pants"))
        self.assertEqual(EQUIPMENT_SLOTS_RIGHT[2], ("shoes", "Shoes"))
        right_labels = dict(EQUIPMENT_SLOTS_RIGHT)
        self.assertEqual(right_labels["misc_1"], "Trinket 1")
        self.assertEqual(right_labels["misc_2"], "Trinket 2")
        misc_labels = [label for _, label in EQUIPMENT_SLOTS_MISC]
        self.assertEqual(misc_labels, [f"Misc {index}" for index in range(1, 11)])

    def test_equipment_slot_group_counts_and_weapon_strip_parent(self) -> None:
        widget = PlayerSheetsWidget()
        self.assertEqual(len(EQUIPMENT_SLOTS_LEFT), 7)
        self.assertEqual(len(EQUIPMENT_SLOTS_RIGHT), 7)
        self.assertEqual(len(EQUIPMENT_SLOTS_WEAPONS), 4)
        self.assertEqual(len(EQUIPMENT_SLOTS_MISC), 10)
        for slot_id, _ in (
            *EQUIPMENT_SLOTS_LEFT,
            *EQUIPMENT_SLOTS_RIGHT,
            *EQUIPMENT_SLOTS_WEAPONS,
            *EQUIPMENT_SLOTS_MISC,
        ):
            self.assertIn(slot_id, widget._equipment_slot_widgets)
        self.assertIsNotNone(widget._equipment_weapon_strip)
        self.assertIsNotNone(widget._equipment_figure_frame)
        self.assertIs(
            widget._equipment_weapon_strip.parentWidget(),
            widget._equipment_figure_frame,
        )
        widget.close()

    def test_inventory_toggle_buttons_match_action_button_height(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        QApplication.processEvents()

        self.assertIsNotNone(widget._inventory_backpack_button)
        self.assertIsNotNone(widget._inventory_equipment_button)
        self.assertIsNotNone(widget._inventory_add_button)
        self.assertIsNotNone(widget._inventory_remove_button)

        expected = widget._inventory_add_button.height()
        self.assertEqual(widget._inventory_remove_button.height(), expected)
        self.assertEqual(widget._inventory_backpack_button.height(), expected)
        self.assertEqual(widget._inventory_equipment_button.height(), expected)

        add_center_y = widget._inventory_add_button.mapToGlobal(
            widget._inventory_add_button.rect().center()
        ).y()
        backpack_center_y = widget._inventory_backpack_button.mapToGlobal(
            widget._inventory_backpack_button.rect().center()
        ).y()
        equipment_center_y = widget._inventory_equipment_button.mapToGlobal(
            widget._inventory_equipment_button.rect().center()
        ).y()
        self.assertLessEqual(abs(add_center_y - backpack_center_y), 1)
        self.assertLessEqual(abs(add_center_y - equipment_center_y), 1)

        header = widget._inventory_header
        self.assertIsNotNone(header)
        assert header is not None
        header_rect = QRect(header.mapToGlobal(header.rect().topLeft()), header.size())
        for button in (
            widget._inventory_backpack_button,
            widget._inventory_equipment_button,
            widget._inventory_add_button,
            widget._inventory_remove_button,
        ):
            button_rect = QRect(button.mapToGlobal(button.rect().topLeft()), button.size())
            self.assertGreaterEqual(button_rect.top(), header_rect.top())
            self.assertLessEqual(button_rect.bottom(), header_rect.bottom())
        widget.close()

    def test_equipment_view_reclaims_hidden_notepad_space(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        QApplication.processEvents()

        self.assertIsNotNone(widget._inventory_stack)
        self.assertIsNotNone(widget._inventory_notes_row)
        self.assertIsNotNone(widget._equipment_panel)
        assert widget._inventory_stack is not None
        assert widget._inventory_notes_row is not None
        assert widget._equipment_panel is not None

        widget._set_inventory_view("backpack")
        QApplication.processEvents()
        backpack_stack_height = widget._inventory_stack.height()
        self.assertTrue(widget._inventory_notes_row.isVisible())

        widget._set_inventory_view("equipment")
        QApplication.processEvents()
        equipment_stack_height = widget._inventory_stack.height()
        self.assertFalse(widget._inventory_notes_row.isVisible())
        self.assertGreater(equipment_stack_height, backpack_stack_height)

        panel = widget._equipment_panel
        self.assertIsNotNone(widget._equipment_row_separator)
        assert widget._equipment_row_separator is not None
        separator_bottom = widget._equipment_row_separator.mapTo(
            panel, QPoint(0, widget._equipment_row_separator.height() - 1)
        ).y()
        misc_top = min(
            widget._equipment_slot_widgets[slot_id]
            .mapTo(panel, widget._equipment_slot_widgets[slot_id].rect().topLeft())
            .y()
            for slot_id, _ in EQUIPMENT_SLOTS_MISC
        )
        misc_bottom = max(
            widget._equipment_slot_widgets[slot_id]
            .mapTo(panel, widget._equipment_slot_widgets[slot_id].rect().bottomLeft())
            .y()
            for slot_id, _ in EQUIPMENT_SLOTS_MISC
        )
        self.assertGreaterEqual(misc_top, separator_bottom + 1)
        self.assertLessEqual(misc_bottom, panel.height() - 1)

        misc_center = (misc_top + misc_bottom) / 2.0
        lower_band_center = (separator_bottom + 1 + panel.height() - 1) / 2.0
        self.assertLessEqual(abs(misc_center - lower_band_center), 4.0)
        widget.close()

    def test_misc_row_remains_visible_across_tight_window_sizes(self) -> None:
        widget = PlayerSheetsWidget()
        widget.show()
        QApplication.processEvents()

        self.assertIsNotNone(widget._equipment_panel)
        self.assertIsNotNone(widget._equipment_row_separator)
        assert widget._equipment_panel is not None
        assert widget._equipment_row_separator is not None

        for width, height in (
            (1280, 820),
            (1180, 760),
            (1080, 700),
            (980, 640),
        ):
            widget.resize(width, height)
            widget._set_inventory_view("equipment")
            QApplication.processEvents()
            widget._update_equipment_layout_sizes()
            QApplication.processEvents()

            panel = widget._equipment_panel
            separator_bottom = widget._equipment_row_separator.mapTo(
                panel, QPoint(0, widget._equipment_row_separator.height() - 1)
            ).y()
            misc_top = min(
                widget._equipment_slot_widgets[slot_id]
                .mapTo(panel, widget._equipment_slot_widgets[slot_id].rect().topLeft())
                .y()
                for slot_id, _ in EQUIPMENT_SLOTS_MISC
            )
            misc_bottom = max(
                widget._equipment_slot_widgets[slot_id]
                .mapTo(panel, widget._equipment_slot_widgets[slot_id].rect().bottomLeft())
                .y()
                for slot_id, _ in EQUIPMENT_SLOTS_MISC
            )

            self.assertGreaterEqual(misc_top, separator_bottom + 1)
            self.assertLessEqual(misc_bottom, panel.height() - 1)
        widget.close()

    def test_detail_splitter_enforces_fixed_pdf_ratio(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        QApplication.processEvents()

        splitter = widget._detail_splitter
        self.assertIsNotNone(splitter)
        assert splitter is not None

        widget._restore_splitter_sizes()
        QApplication.processEvents()
        sizes = splitter.sizes()
        total = max(1, sum(sizes))
        ratio = float(sizes[0]) / float(total)
        self.assertGreaterEqual(ratio, 0.42)
        self.assertLessEqual(ratio, 0.47)

        splitter.setSizes([100, 900])
        widget.resize(1310, 840)
        QApplication.processEvents()
        QApplication.processEvents()

        resized_sizes = splitter.sizes()
        resized_total = max(1, sum(resized_sizes))
        resized_ratio = float(resized_sizes[0]) / float(resized_total)
        self.assertGreaterEqual(resized_ratio, 0.42)
        self.assertLessEqual(resized_ratio, 0.47)
        widget.close()

    def test_inventory_view_switch_restores_splitter_sizes_after_relayout_drift(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        QApplication.processEvents()

        splitter = widget._detail_splitter
        self.assertIsNotNone(splitter)
        assert splitter is not None

        outer_splitter = None
        parent = splitter.parentWidget()
        while parent is not None:
            if isinstance(parent, QSplitter) and parent is not splitter:
                outer_splitter = parent
                break
            parent = parent.parentWidget()

        # Settle into a realistic baseline layout before simulating drift.
        widget._set_inventory_view("equipment")
        QTest.qWait(40)
        QApplication.processEvents()
        baseline_detail = splitter.sizes()
        baseline_outer = outer_splitter.sizes() if outer_splitter is not None else None
        widget._set_inventory_view("backpack")
        QTest.qWait(40)
        QApplication.processEvents()

        original_update_equipment_layout_sizes = widget._update_equipment_layout_sizes
        drift_applied = False

        def _drift_update_equipment_layout_sizes() -> None:
            nonlocal drift_applied
            original_update_equipment_layout_sizes()
            if drift_applied:
                return
            drift_applied = True
            self._apply_ratio(splitter, 0.24)
            if outer_splitter is not None:
                self._apply_ratio(outer_splitter, 0.18)

        widget._update_equipment_layout_sizes = _drift_update_equipment_layout_sizes  # type: ignore[assignment]
        try:
            widget._set_inventory_view("equipment")
            QTest.qWait(60)
            QApplication.processEvents()
            self._assert_sizes_close(splitter.sizes(), baseline_detail)
            if outer_splitter is not None and baseline_outer is not None:
                self._assert_sizes_close(outer_splitter.sizes(), baseline_outer)

            widget._set_inventory_view("backpack")
            QTest.qWait(60)
            QApplication.processEvents()
            self._assert_sizes_close(splitter.sizes(), baseline_detail)
            if outer_splitter is not None and baseline_outer is not None:
                self._assert_sizes_close(outer_splitter.sizes(), baseline_outer)
        finally:
            widget._update_equipment_layout_sizes = original_update_equipment_layout_sizes  # type: ignore[assignment]
            widget.close()

    def test_equipment_selection_does_not_change_inventory_panel_heights(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        widget._set_inventory_view("equipment")
        QApplication.processEvents()

        self.assertIsNotNone(widget._inventory_panel)
        self.assertIsNotNone(widget._inventory_stack)
        self.assertIsNotNone(widget._equipment_panel)
        assert widget._inventory_panel is not None
        assert widget._inventory_stack is not None
        assert widget._equipment_panel is not None

        stable_slots = EQUIPMENT_SLOTS_LEFT[:2] + EQUIPMENT_SLOTS_RIGHT[:2]
        first_slot, _ = stable_slots[0]
        widget._on_equipment_slot_selected(first_slot)
        QApplication.processEvents()
        base_inventory_h = widget._inventory_panel.height()
        base_stack_h = widget._inventory_stack.height()
        base_equipment_h = widget._equipment_panel.height()

        for slot_id, _ in stable_slots[1:]:
            widget._on_equipment_slot_selected(slot_id)
            QApplication.processEvents()

        self.assertEqual(widget._inventory_panel.height(), base_inventory_h)
        self.assertEqual(widget._inventory_stack.height(), base_stack_h)
        self.assertEqual(widget._equipment_panel.height(), base_equipment_h)
        widget.close()

    def test_weapon_row_aligns_with_seventh_side_slot_and_has_bottom_padding(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        QApplication.processEvents()

        left_slot_id = EQUIPMENT_SLOTS_LEFT[-1][0]
        right_slot_id = EQUIPMENT_SLOTS_RIGHT[-1][0]
        weapon_slot_id = EQUIPMENT_SLOTS_WEAPONS[1][0]

        left_slot = widget._equipment_slot_widgets[left_slot_id]
        right_slot = widget._equipment_slot_widgets[right_slot_id]
        weapon_slot = widget._equipment_slot_widgets[weapon_slot_id]
        figure_frame = widget._equipment_figure_frame
        self.assertIsNotNone(figure_frame)
        assert figure_frame is not None

        left_center = left_slot.mapToGlobal(left_slot.rect().center()).y()
        right_center = right_slot.mapToGlobal(right_slot.rect().center()).y()
        weapon_center = weapon_slot.mapToGlobal(weapon_slot.rect().center()).y()
        target_center = (left_center + right_center) // 2
        self.assertLessEqual(abs(weapon_center - target_center), 2)

        weapon_bottom_in_figure = weapon_slot.mapTo(
            figure_frame, weapon_slot.rect().bottomLeft()
        ).y()
        bottom_gap = max(0, figure_frame.height() - 1 - weapon_bottom_in_figure)
        self.assertGreaterEqual(bottom_gap, 3)
        widget.close()

    def test_equipment_separator_sits_between_top_row_and_misc_row(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        widget._set_inventory_view("equipment")
        QApplication.processEvents()
        widget._update_equipment_layout_sizes()
        QApplication.processEvents()

        self.assertIsNotNone(widget._equipment_row_separator)
        self.assertIsNotNone(widget._equipment_panel)
        assert widget._equipment_row_separator is not None
        assert widget._equipment_panel is not None

        panel = widget._equipment_panel
        separator_top = widget._equipment_row_separator.mapTo(panel, QPoint(0, 0)).y()
        separator_bottom = widget._equipment_row_separator.mapTo(
            panel, QPoint(0, widget._equipment_row_separator.height() - 1)
        ).y()

        top_slot_ids = [slot_id for slot_id, _ in (*EQUIPMENT_SLOTS_LEFT, *EQUIPMENT_SLOTS_RIGHT, *EQUIPMENT_SLOTS_WEAPONS)]
        top_bottom = max(
            widget._equipment_slot_widgets[slot_id]
            .mapTo(panel, widget._equipment_slot_widgets[slot_id].rect().bottomLeft())
            .y()
            for slot_id in top_slot_ids
        )

        misc_slot_ids = [slot_id for slot_id, _ in EQUIPMENT_SLOTS_MISC]
        misc_top = min(
            widget._equipment_slot_widgets[slot_id]
            .mapTo(panel, widget._equipment_slot_widgets[slot_id].rect().topLeft())
            .y()
            for slot_id in misc_slot_ids
        )

        self.assertGreater(separator_top, top_bottom)
        self.assertLess(separator_bottom, misc_top)
        widget.close()

    def test_rightmost_misc_slot_aligns_with_right_column(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        widget._set_inventory_view("equipment")
        QApplication.processEvents()
        widget._update_equipment_layout_sizes()
        QApplication.processEvents()

        self.assertIsNotNone(widget._equipment_panel)
        assert widget._equipment_panel is not None
        panel = widget._equipment_panel

        right_column_slot_id = EQUIPMENT_SLOTS_RIGHT[-1][0]
        rightmost_misc_slot_id = EQUIPMENT_SLOTS_MISC[-1][0]
        right_col_slot = widget._equipment_slot_widgets[right_column_slot_id]
        right_misc_slot = widget._equipment_slot_widgets[rightmost_misc_slot_id]

        right_col_edge = right_col_slot.mapTo(panel, right_col_slot.rect().topRight()).x()
        right_misc_edge = right_misc_slot.mapTo(panel, right_misc_slot.rect().topRight()).x()

        self.assertLessEqual(abs(right_col_edge - right_misc_edge), 1)
        widget.close()

    def test_preview_position_prefers_silhouette_side(self) -> None:
        hover_rect = QRect(80, 120, 40, 40)
        preview_size = QSize(120, 180)
        screen_rect = QRect(0, 0, 1600, 900)
        point = compute_equipment_preview_position(
            hover_rect=hover_rect,
            preview_size=preview_size,
            blocked_rects=[],
            screen_rect=screen_rect,
            toward_silhouette="right",
        )
        self.assertGreaterEqual(point.x(), hover_rect.right())

    def test_preview_position_avoids_blocked_slot_icons(self) -> None:
        hover_rect = QRect(200, 200, 42, 42)
        preview_size = QSize(160, 200)
        screen_rect = QRect(0, 0, 1400, 900)
        blocked = [QRect(hover_rect.right() + 10, hover_rect.top() - 20, 180, 220)]
        point = compute_equipment_preview_position(
            hover_rect=hover_rect,
            preview_size=preview_size,
            blocked_rects=blocked,
            screen_rect=screen_rect,
            toward_silhouette="right",
        )
        self.assertFalse(QRect(point, preview_size).intersects(blocked[0]))

    def test_preview_position_clamps_to_screen_bounds(self) -> None:
        hover_rect = QRect(760, 540, 42, 42)
        preview_size = QSize(220, 260)
        screen_rect = QRect(0, 0, 800, 600)
        point = compute_equipment_preview_position(
            hover_rect=hover_rect,
            preview_size=preview_size,
            blocked_rects=[],
            screen_rect=screen_rect,
            toward_silhouette="right",
        )
        preview_rect = QRect(point, preview_size)
        self.assertGreaterEqual(preview_rect.left(), screen_rect.left())
        self.assertGreaterEqual(preview_rect.top(), screen_rect.top())
        self.assertLessEqual(preview_rect.right(), screen_rect.right())
        self.assertLessEqual(preview_rect.bottom(), screen_rect.bottom())

    def test_cursor_preview_position_avoids_hovered_slot_overlap(self) -> None:
        hover_rect = QRect(300, 220, 84, 84)
        preview_size = QSize(210, 260)
        cursor_pos = QPoint(335, 255)
        screen_rect = QRect(0, 0, 1280, 720)
        point = compute_cursor_preview_position(
            hover_rect=hover_rect,
            preview_size=preview_size,
            cursor_pos=cursor_pos,
            screen_rect=screen_rect,
        )
        self.assertFalse(QRect(point, preview_size).intersects(hover_rect))

    def test_equipment_preview_stays_in_silhouette_frame_and_avoids_slot_overlap(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1920, 1080)
        widget.show()
        widget._set_inventory_view("equipment")
        QApplication.processEvents()

        frame = widget._equipment_figure_frame
        self.assertIsNotNone(frame)
        assert frame is not None

        hover_slot_id = EQUIPMENT_SLOTS_RIGHT[0][0]
        hover_slot = widget._equipment_slot_widgets[hover_slot_id]
        hover_rect = QRect(hover_slot.mapToGlobal(hover_slot.rect().topLeft()), hover_slot.size())
        frame_rect = QRect(frame.mapToGlobal(frame.rect().topLeft()), frame.size()).adjusted(4, 4, -4, -4)
        if frame_rect.width() < 80:
            widget.close()
            self.skipTest("Equipment frame is too narrow for non-overlap preview placement.")
        preview_size = QSize(
            max(40, min(140, frame_rect.width() - 8)),
            max(60, min(220, frame_rect.height() - 8)),
        )

        blocked_rects = [
            QRect(slot.mapToGlobal(slot.rect().topLeft()), slot.size())
            for slot in widget._equipment_slot_widgets.values()
        ]
        toward_silhouette = (
            "right"
            if hover_rect.center().x() <= frame_rect.center().x()
            else "left"
        )
        top_left = compute_equipment_preview_position(
            hover_rect=hover_rect,
            preview_size=preview_size,
            blocked_rects=blocked_rects,
            screen_rect=frame_rect,
            toward_silhouette=toward_silhouette,
        )
        preview_rect = QRect(top_left, preview_size)

        self.assertGreaterEqual(preview_rect.left(), frame_rect.left())
        self.assertGreaterEqual(preview_rect.top(), frame_rect.top())
        self.assertLessEqual(preview_rect.right(), frame_rect.right())
        self.assertLessEqual(preview_rect.bottom(), frame_rect.bottom())
        for slot_rect in blocked_rects:
            self.assertFalse(preview_rect.intersects(slot_rect))
        widget.close()

    def test_equipment_preview_shows_when_blocked_positions_are_unavoidable(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        widget._set_inventory_view("equipment")
        QApplication.processEvents()

        shown: list[tuple[QSize, object]] = []

        def _capture_preview(pixmap, top_left) -> None:
            shown.append((QSize(pixmap.size()), top_left))

        widget._equipment_preview_tooltip.show_preview_at = _capture_preview  # type: ignore[assignment]

        original_intersects = player_sheets_module._intersects_blocked
        try:
            player_sheets_module._intersects_blocked = lambda _rect, _blocked: True
            preview = QPixmap(360, 540)
            preview.fill(QColor("#ff0000"))
            widget._show_equipment_preview(EQUIPMENT_SLOTS_RIGHT[0][0], preview)
        finally:
            player_sheets_module._intersects_blocked = original_intersects

        self.assertTrue(shown)
        self.assertGreater(shown[0][0].width(), 0)
        self.assertGreater(shown[0][0].height(), 0)
        widget.close()

    def test_inventory_preview_cache_key_includes_bounds_and_dpr(self) -> None:
        widget = PlayerSheetsWidget()
        calls: list[tuple[int, int, float]] = []

        def _fake_render(item, *, max_width=322, max_height=None, dpr=1.0):
            safe_width = max(1, int(round(max_width)))
            safe_height = max(1, int(round(max_height if max_height is not None else max_width)))
            safe_dpr = max(1.0, float(dpr))
            calls.append((safe_width, safe_height, safe_dpr))
            pixmap = QPixmap(
                max(1, int(round(safe_width * safe_dpr))),
                max(1, int(round(safe_height * safe_dpr))),
            )
            pixmap.fill(QColor("#00ff00"))
            pixmap.setDevicePixelRatio(safe_dpr)
            return pixmap

        item = LootItem(
            item_id="cache-test-item",
            title="Cache Test",
            rarity="common",
            category_label=None,
            categories=set(),
            level=1,
            tags=set(),
            path="cache_test_item.json",
        )

        original_render = player_sheets_module._render_item_preview_pixmap
        try:
            player_sheets_module._render_item_preview_pixmap = _fake_render
            first = widget._inventory_preview_pixmap(item, max_width=160, max_height=240, dpr=1.0)
            second = widget._inventory_preview_pixmap(item, max_width=160, max_height=240, dpr=1.0)
            third = widget._inventory_preview_pixmap(item, max_width=160, max_height=240, dpr=2.0)
            fourth = widget._inventory_preview_pixmap(item, max_width=120, max_height=240, dpr=2.0)
        finally:
            player_sheets_module._render_item_preview_pixmap = original_render

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(third)
        self.assertIsNotNone(fourth)
        self.assertIs(first, second)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(widget._inventory_preview_cache), 3)
        widget.close()

    def test_occupied_equipment_slots_have_no_tooltip(self) -> None:
        widget = PlayerSheetsWidget()
        slot_id = EQUIPMENT_SLOTS_LEFT[0][0]
        slot = widget._equipment_slot_widgets[slot_id]
        slot.set_item("equipped-item", QPixmap(32, 32))
        self.assertEqual(slot.toolTip(), "")
        slot.set_item(None, None)
        self.assertTrue(bool(slot.toolTip()))
        widget.close()

    def test_empty_backpack_list_stays_visible_as_drop_target(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        QApplication.processEvents()

        entry = PlayerSheetEntry(name="Test Character", pdf_path="test.pdf")
        widget._current_entry = entry
        widget._set_inventory(entry)
        widget._set_inventory_view("backpack")
        QApplication.processEvents()

        self.assertTrue(widget._inventory_list.isVisible())
        self.assertTrue(widget._inventory_placeholder.isVisible())
        widget.close()

    def test_backpack_items_have_no_tooltip(self) -> None:
        widget = PlayerSheetsWidget()
        widget.show()
        QApplication.processEvents()

        item = LootItem(
            item_id="tooltip-test-item",
            title="Tooltip Test",
            rarity="common",
            category_label=None,
            categories=set(),
            level=1,
            tags=set(),
            path="tooltip_test_item.json",
        )
        widget._inventory_item_by_id[item.item_id] = item
        entry = PlayerSheetEntry(
            name="Tooltip Character",
            pdf_path="test.pdf",
            inventory=[item.item_id],
        )
        widget._current_entry = entry
        widget._set_inventory(entry)
        self.assertEqual(widget._inventory_list.count(), 1)
        self.assertEqual(widget._inventory_list.item(0).toolTip(), "")
        widget.close()

    def test_backpack_stacks_duplicate_items_into_one_tile(self) -> None:
        widget = PlayerSheetsWidget()
        widget.show()
        QApplication.processEvents()

        item = LootItem(
            item_id="stacked-item",
            title="Stacked Item",
            rarity="common",
            category_label=None,
            categories=set(),
            level=1,
            tags=set(),
            path="stacked_item.json",
        )
        widget._inventory_item_by_id[item.item_id] = item
        entry = PlayerSheetEntry(
            name="Stacked Character",
            pdf_path="test.pdf",
            inventory=[item.item_id, item.item_id, item.item_id],
        )
        widget._current_entry = entry
        widget._set_inventory(entry)

        self.assertEqual(widget._inventory_list.count(), 1)
        row = widget._inventory_list.item(0)
        self.assertEqual(
            row.data(player_sheets_module.INVENTORY_ITEM_QUANTITY_ROLE),
            3,
        )
        widget.close()

    def test_backpack_quantity_button_click_edits_stack_exactly(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        QApplication.processEvents()
        widget._save_entries = lambda **_kwargs: None  # type: ignore[assignment]

        item = LootItem(
            item_id="editable-stack",
            title="Editable Stack",
            rarity="common",
            category_label=None,
            categories=set(),
            level=1,
            tags=set(),
            path="editable_stack.json",
        )
        widget._inventory_item_by_id[item.item_id] = item
        entry = PlayerSheetEntry(
            name="Editable Character",
            pdf_path="test.pdf",
            inventory=[item.item_id, item.item_id],
        )
        widget._current_entry = entry
        widget._set_inventory(entry)
        QApplication.processEvents()

        row = widget._inventory_list.item(0)
        row_rect = widget._inventory_list.visualItemRect(row)
        icon_rect = player_sheets_module._inventory_icon_rect(row_rect)
        plus_center = player_sheets_module._inventory_quantity_button_rect(icon_rect).center()
        QTest.mouseMove(widget._inventory_list.viewport(), plus_center)
        QApplication.processEvents()
        self.assertTrue(widget._inventory_list.is_quantity_button_visible_for_row(0))
        self.assertTrue(widget._inventory_list.is_quantity_button_hot_for_row(0))

        with patch("player_sheets.QInputDialog.getInt", return_value=(7, True)):
            QTest.mouseClick(
                widget._inventory_list.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                plus_center,
            )
        QApplication.processEvents()

        self.assertEqual(
            entry.inventory,
            [{"item_id": item.item_id, "normalized_item_name": item.item_id, "quantity": 7}],
        )
        self.assertEqual(widget._inventory_list.count(), 1)
        self.assertEqual(
            widget._inventory_list.item(0).data(player_sheets_module.INVENTORY_ITEM_QUANTITY_ROLE),
            7,
        )
        widget.close()

    def test_backpack_large_quantity_edit_keeps_single_stack_row(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        QApplication.processEvents()
        widget._save_entries = lambda **_kwargs: None  # type: ignore[assignment]

        item = LootItem(
            item_id="large-stack",
            title="Large Stack",
            rarity="common",
            category_label=None,
            categories=set(),
            level=1,
            tags=set(),
            path="large_stack.json",
        )
        widget._inventory_item_by_id[item.item_id] = item
        entry = PlayerSheetEntry(
            name="Large Stack Character",
            pdf_path="test.pdf",
            inventory=[item.item_id],
        )
        widget._current_entry = entry
        widget._set_inventory(entry)
        QApplication.processEvents()

        with patch("player_sheets.QInputDialog.getInt", return_value=(4444, True)):
            widget._edit_inventory_item_quantity(item.item_id)
        QApplication.processEvents()

        self.assertEqual(widget._inventory_list.count(), 1)
        self.assertEqual(
            entry.inventory,
            [{"item_id": item.item_id, "normalized_item_name": item.item_id, "quantity": 4444}],
        )
        self.assertEqual(
            widget._inventory_list.item(0).data(player_sheets_module.INVENTORY_ITEM_QUANTITY_ROLE),
            4444,
        )
        widget.close()

    def test_backpack_quantity_button_uses_current_quantity_as_dialog_default(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        QApplication.processEvents()
        widget._save_entries = lambda **_kwargs: None  # type: ignore[assignment]

        item = LootItem(
            item_id="default-stack",
            title="Default Stack",
            rarity="common",
            category_label=None,
            categories=set(),
            level=1,
            tags=set(),
            path="default_stack.json",
        )
        widget._inventory_item_by_id[item.item_id] = item
        entry = PlayerSheetEntry(
            name="Default Quantity Character",
            pdf_path="test.pdf",
            inventory=[item.item_id, item.item_id, item.item_id],
        )
        widget._current_entry = entry
        widget._set_inventory(entry)
        QApplication.processEvents()

        captured = {}

        def _capture_get_int(*args, **kwargs):
            captured["default_value"] = args[3]
            return (3, False)

        with patch("player_sheets.QInputDialog.getInt", side_effect=_capture_get_int):
            widget._edit_inventory_item_quantity(item.item_id)

        self.assertEqual(captured["default_value"], 3)
        widget.close()

    def test_inventory_quantity_formatter_supports_millions(self) -> None:
        self.assertEqual(player_sheets_module._format_inventory_quantity(999), "999")
        self.assertEqual(player_sheets_module._format_inventory_quantity(1200), "1.2k")
        self.assertEqual(player_sheets_module._format_inventory_quantity(1_200_000), "1.2m")

    def test_backpack_remove_button_decrements_stack_until_empty(self) -> None:
        widget = PlayerSheetsWidget()
        widget.show()
        QApplication.processEvents()
        widget._save_entries = lambda **_kwargs: None  # type: ignore[assignment]

        item = LootItem(
            item_id="remove-stack",
            title="Remove Stack",
            rarity="common",
            category_label=None,
            categories=set(),
            level=1,
            tags=set(),
            path="remove_stack.json",
        )
        widget._inventory_item_by_id[item.item_id] = item
        entry = PlayerSheetEntry(
            name="Remove Character",
            pdf_path="test.pdf",
            inventory=[item.item_id, item.item_id],
        )
        widget._current_entry = entry
        widget._set_inventory(entry)
        widget._select_inventory_item_by_id(item.item_id)

        widget._remove_inventory_item()
        QApplication.processEvents()
        self.assertEqual(
            entry.inventory,
            [{"item_id": item.item_id, "normalized_item_name": item.item_id, "quantity": 1}],
        )
        self.assertEqual(widget._inventory_list.count(), 1)
        self.assertEqual(
            widget._inventory_list.item(0).data(player_sheets_module.INVENTORY_ITEM_QUANTITY_ROLE),
            1,
        )

        widget._select_inventory_item_by_id(item.item_id)
        widget._remove_inventory_item()
        QApplication.processEvents()
        self.assertEqual(entry.inventory, [])
        self.assertEqual(widget._inventory_list.count(), 0)
        self.assertTrue(widget._inventory_placeholder.isVisible())
        widget.close()

    def test_dragging_between_backpack_and_equipment_moves_one_unit(self) -> None:
        widget = PlayerSheetsWidget()
        widget.show()
        QApplication.processEvents()
        widget._save_entries = lambda **_kwargs: None  # type: ignore[assignment]

        item = LootItem(
            item_id="equip-stack",
            title="Equip Stack",
            rarity="common",
            category_label=None,
            categories=set(),
            level=1,
            tags=set(),
            path="equip_stack.json",
        )
        widget._inventory_item_by_id[item.item_id] = item
        entry = PlayerSheetEntry(
            name="Equip Character",
            pdf_path="test.pdf",
            inventory=[item.item_id, item.item_id],
        )
        widget._current_entry = entry
        widget._set_inventory(entry)

        widget._on_equipment_slot_dropped(
            "head",
            {"source": "backpack", "item_id": item.item_id, "index": 0},
        )
        QApplication.processEvents()
        self.assertEqual(
            entry.inventory,
            [{"item_id": item.item_id, "normalized_item_name": item.item_id, "quantity": 1}],
        )
        self.assertEqual(entry.equipment["head"], item.item_id)
        self.assertEqual(widget._inventory_list.count(), 1)
        self.assertEqual(
            widget._inventory_list.item(0).data(player_sheets_module.INVENTORY_ITEM_QUANTITY_ROLE),
            1,
        )

        widget._on_inventory_drop_from_equipment(
            {"source": "equipment", "slot": "head", "item_id": item.item_id}
        )
        QApplication.processEvents()
        self.assertEqual(
            entry.inventory,
            [{"item_id": item.item_id, "normalized_item_name": item.item_id, "quantity": 2}],
        )
        self.assertIsNone(entry.equipment["head"])
        self.assertEqual(widget._inventory_list.count(), 1)
        self.assertEqual(
            widget._inventory_list.item(0).data(player_sheets_module.INVENTORY_ITEM_QUANTITY_ROLE),
            2,
        )
        widget.close()

    def test_backpack_preview_position_is_sticky_until_unhover(self) -> None:
        widget = PlayerSheetsWidget()
        widget.show()
        QApplication.processEvents()

        preview = QPixmap(80, 120)
        preview.fill(QColor("#00aaff"))
        widget._inventory_preview_pixmap = lambda *_args, **_kwargs: preview  # type: ignore[assignment]

        item = LootItem(
            item_id="sticky-backpack-item",
            title="Sticky Backpack",
            rarity="common",
            category_label=None,
            categories=set(),
            level=1,
            tags=set(),
            path="sticky_backpack_item.json",
        )
        widget._inventory_item_by_id[item.item_id] = item
        entry = PlayerSheetEntry(
            name="Sticky Backpack Character",
            pdf_path="test.pdf",
            inventory=[item.item_id],
        )
        widget._current_entry = entry
        widget._set_inventory(entry)
        row = widget._inventory_list.item(0)

        with patch("player_sheets.QCursor.pos", return_value=QPoint(220, 220)):
            widget._show_inventory_preview_for_item(row)
        first_top_left = widget._inventory_preview_top_left
        self.assertIsNotNone(first_top_left)

        with patch("player_sheets.QCursor.pos", return_value=QPoint(520, 420)):
            widget._show_inventory_preview_for_item(row)
        self.assertEqual(widget._inventory_preview_top_left, first_top_left)

        widget._hide_inventory_preview()
        self.assertIsNone(widget._inventory_preview_top_left)
        widget.close()

    def test_equipment_preview_position_is_sticky_until_unhover(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        widget._set_inventory_view("equipment")
        QApplication.processEvents()

        preview = QPixmap(100, 150)
        preview.fill(QColor("#ffaa00"))
        widget._inventory_preview_pixmap = lambda *_args, **_kwargs: preview  # type: ignore[assignment]

        slot_id = EQUIPMENT_SLOTS_RIGHT[0][0]
        item = LootItem(
            item_id="sticky-equipment-item",
            title="Sticky Equipment",
            rarity="common",
            category_label=None,
            categories=set(),
            level=1,
            tags=set(),
            path="sticky_equipment_item.json",
        )
        widget._inventory_item_by_id[item.item_id] = item

        with patch("player_sheets.QCursor.pos", return_value=QPoint(300, 280)):
            widget._on_equipment_slot_hovered(slot_id, item.item_id)
        first_top_left = widget._equipment_preview_top_left
        self.assertIsNotNone(first_top_left)

        with patch("player_sheets.QCursor.pos", return_value=QPoint(620, 520)):
            widget._on_equipment_slot_hovered(slot_id, item.item_id)
        self.assertEqual(widget._equipment_preview_top_left, first_top_left)

        widget._hide_equipment_preview()
        self.assertIsNone(widget._equipment_preview_top_left)
        widget.close()

    def test_inventory_notepad_is_backpack_only_and_does_not_add_items(self) -> None:
        widget = PlayerSheetsWidget()
        widget.resize(1280, 820)
        widget.show()
        QApplication.processEvents()

        entry = PlayerSheetEntry(name="Notepad Test", pdf_path="test.pdf")
        widget._current_entry = entry
        widget._save_entries = lambda **_kwargs: None  # type: ignore[assignment]
        widget._set_inventory(entry)
        QApplication.processEvents()

        self.assertIsNotNone(widget._inventory_notes_row)
        self.assertIsNotNone(widget._inventory_notepad)
        assert widget._inventory_notes_row is not None
        assert widget._inventory_notepad is not None

        self.assertTrue(widget._inventory_notes_row.isVisible())
        widget._inventory_notepad.setPlainText("Homebrew Bomb\nAncient Rune")
        QApplication.processEvents()

        self.assertEqual(entry.inventory_notes, "Homebrew Bomb\nAncient Rune")
        self.assertEqual(entry.inventory, [])

        widget._set_inventory_view("equipment")
        QApplication.processEvents()
        self.assertFalse(widget._inventory_notes_row.isVisible())

        widget._set_inventory_view("backpack")
        QApplication.processEvents()
        self.assertTrue(widget._inventory_notes_row.isVisible())
        self.assertEqual(widget._inventory_notepad.toPlainText(), "Homebrew Bomb\nAncient Rune")
        widget.close()


if __name__ == "__main__":
    unittest.main()
