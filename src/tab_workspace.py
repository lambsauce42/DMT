from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol, Set

from PySide6.QtCore import QEvent, QEventLoop, QObject, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLabel, QTabBar, QTabWidget, QWidget


class WorkspaceWindow(Protocol):
    def workspace_tabs(self) -> QTabWidget:
        ...

    def is_primary_window(self) -> bool:
        ...


@dataclass
class _ExternalTabDragState:
    widget: QWidget
    title: str
    source_window: WorkspaceWindow
    current_host_window: WorkspaceWindow
    hot_spot: QPoint
    ghost: Optional["_FloatingTabGhost"] = None
    last_target_window: Optional[WorkspaceWindow] = None
    last_target_index: Optional[int] = None
    cursor_polling: bool = False


class _FloatingTabGhost(QWidget):
    def __init__(self, title: str, size: QSize) -> None:
        flags = (
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(None, flags)
        self._title = str(title or "")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        width = max(96, int(size.width()))
        fm = self.fontMetrics()
        width = max(width, fm.horizontalAdvance(self._title) + 46)
        height = max(24, int(size.height()))
        self.resize(width, height)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fill = QColor(31, 111, 235, 120)
        border = QColor(88, 166, 255, 185)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(fill)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QColor(230, 237, 243, 230))
        text_rect = rect.adjusted(12, 0, -18, 0)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._title,
        )
        painter.setPen(QColor(230, 237, 243, 190))
        painter.drawText(
            rect.adjusted(0, 0, -8, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            "x",
        )


class DetachableTabBar(QTabBar):
    def __init__(
        self,
        controller: "TabWorkspaceController",
        owner_window: WorkspaceWindow,
        tab_widget: QTabWidget,
    ) -> None:
        super().__init__(tab_widget)
        self._controller = controller
        self._owner_window = owner_window
        self._tab_widget = tab_widget
        self._press_pos = QPoint()
        self._press_index = -1
        self._press_identity: Optional[int] = None
        self._width_lock_active = False
        self._locked_width_by_id: Dict[int, int] = {}
        self._hover_index = -1
        self._title_overlay_by_index: Dict[int, QLabel] = {}
        self._title_gap_by_identity: Dict[int, int] = {}
        self._title_width_by_identity: Dict[int, int] = {}
        self._external_drag_identity: Optional[int] = None
        self._external_drag_global_pos: Optional[QPoint] = None
        self._external_drag_hot_x: int = 0
        self._externally_repositioned_close_by_identity: Set[int] = set()
        self._settling_overlay_left_by_identity: Dict[int, float] = {}
        self._settling_overlay_start_ms_by_identity: Dict[int, int] = {}
        self._title_overlay_timer = QTimer(self)
        self._title_overlay_timer.setInterval(16)
        self._title_overlay_timer.timeout.connect(self._sync_title_overlays)
        self._title_overlay_timer.start()
        self.currentChanged.connect(lambda _index: self._sync_title_overlays())

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        self._sync_title_overlays()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._press_index = self.tabAt(self._press_pos)
            identity = self.tabData(self._press_index) if self._press_index >= 0 else None
            self._press_identity = int(identity) if identity is not None else None
            self._hover_index = -1
        super().mousePressEvent(event)
        self._sync_title_overlays()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self._press_index = -1
        self._press_identity = None
        self._press_pos = QPoint()
        super().mouseReleaseEvent(event)
        self._sync_title_overlays()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        dragging_with_left_button = (
            self._press_index >= 0 and bool(event.buttons() & Qt.MouseButton.LeftButton)
        )
        hover_index = -1 if dragging_with_left_button else self.tabAt(event.position().toPoint())
        if hover_index != self._hover_index:
            self._hover_index = hover_index
            self._sync_title_overlays()
        if not dragging_with_left_button:
            super().mouseMoveEvent(event)
            self._sync_title_overlays()
            return
        current_pos = event.position().toPoint()
        distance = (current_pos - self._press_pos).manhattanLength()
        threshold = max(3, min(int(QApplication.startDragDistance()), 4))
        self._controller._drag_trace(
            "bar_mouse_move",
            owner=self._controller._window_label(self._owner_window),
            press_index=self._press_index,
            cursor_x=current_pos.x(),
            cursor_y=current_pos.y(),
            distance=distance,
            threshold=threshold,
            bar_height=self.height(),
        )
        if distance < threshold:
            super().mouseMoveEvent(event)
            self._sync_title_overlays()
            return
        dragged_widget = self._tab_widget.widget(self._press_index)
        if dragged_widget is not None and self._controller.is_home_widget(dragged_widget):
            self._controller._drag_trace(
                "bar_home_drag_blocked",
                owner=self._controller._window_label(self._owner_window),
                press_index=self._press_index,
                cursor_x=current_pos.x(),
                cursor_y=current_pos.y(),
            )
            event.accept()
            self._sync_title_overlays()
            return
        effective_drag_pos = QPoint(current_pos)
        home_zone_passthrough = False
        if dragged_widget is not None and not self._controller.is_home_widget(dragged_widget):
            if self.count() > 0 and str(self.tabText(0)).strip().lower() == "home":
                home_rect = self.tabRect(0)
                ignore_guard = 0
                if self.count() > 1:
                    ignore_guard = max(12, min(80, int(self.tabRect(1).width() * 0.5)))
                expanded_home_drag_block = QRect(home_rect)
                expanded_home_drag_block.setRight(home_rect.right() + ignore_guard)
                if (
                    home_rect.width() > 0
                    and home_rect.height() > 0
                    and current_pos.x() >= 0
                    and expanded_home_drag_block.contains(current_pos)
                ):
                    # Treat Home as visually transparent while preserving pinned behavior.
                    home_zone_passthrough = True
                    self._controller._drag_trace(
                        "bar_home_region_passthrough",
                        owner=self._controller._window_label(self._owner_window),
                        press_index=self._press_index,
                        cursor_x=current_pos.x(),
                        cursor_y=current_pos.y(),
                        passthrough_x=current_pos.x(),
                        guard_px=ignore_guard,
                    )
        vertical_pull = 0
        if effective_drag_pos.y() < 0:
            vertical_pull = -effective_drag_pos.y()
        elif effective_drag_pos.y() > self.height():
            vertical_pull = effective_drag_pos.y() - self.height()
        horizontal_pull = 0
        if effective_drag_pos.x() < 0:
            horizontal_pull = -effective_drag_pos.x()
        elif effective_drag_pos.x() > self.width():
            horizontal_pull = effective_drag_pos.x() - self.width()
        self._controller._drag_trace(
            "bar_vertical_pull",
            owner=self._controller._window_label(self._owner_window),
            press_index=self._press_index,
            vertical_pull=vertical_pull,
            horizontal_pull=horizontal_pull,
            bar_height=self.height(),
            bar_width=self.width(),
        )
        if vertical_pull < 24 and horizontal_pull < 24:
            if home_zone_passthrough:
                event.accept()
                self._sync_title_overlays()
                return
            super().mouseMoveEvent(event)
            self._sync_title_overlays()
            return
        widget = self._tab_widget.widget(self._press_index)
        if widget is None or not self._controller.can_detach_widget(widget):
            super().mouseMoveEvent(event)
            self._sync_title_overlays()
            return
        tab_rect = self.tabRect(self._press_index)
        hot_spot = current_pos - tab_rect.topLeft()
        global_position = getattr(event, "globalPosition", None)
        if callable(global_position):
            global_pos = global_position().toPoint()
        else:
            global_pos = QCursor.pos()
        started = self._controller.start_external_tab_drag(
            self._owner_window,
            widget,
            global_pos,
            hot_spot=hot_spot,
        )
        self._controller._drag_trace(
            "bar_start_external_drag",
            owner=self._controller._window_label(self._owner_window),
            press_index=self._press_index,
            started=started,
            global_x=global_pos.x(),
            global_y=global_pos.y(),
        )
        self._press_index = -1
        self._press_identity = None
        self._press_pos = QPoint()
        if started:
            event.accept()
            self._sync_title_overlays()
            return
        super().mouseMoveEvent(event)
        self._sync_title_overlays()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_index = -1
        super().leaveEvent(event)
        self._sync_title_overlays()

    def _insertion_index_from_pos(self, pos: QPoint) -> int:
        if self.count() <= 0:
            return 0
        start_index = 0
        if str(self.tabText(0)).strip().lower() == "home":
            start_index = 1
        if start_index >= self.count():
            return self.count()
        x = pos.x()
        for index in range(start_index, self.count()):
            rect = self.tabRect(index)
            trigger_x = rect.left() + max(1, int(rect.width() * 0.25))
            if x < trigger_x:
                return index
        return self.count()

    def tabSizeHint(self, index: int) -> QSize:  # type: ignore[override]
        base = super().tabSizeHint(index)
        if not self._width_lock_active:
            return base
        identity = self.tabData(index)
        if identity is None:
            return base
        width = self._locked_width_by_id.get(int(identity))
        if width is None:
            return base
        base.setWidth(int(width))
        return base

    def owner_window(self) -> WorkspaceWindow:
        return self._owner_window

    def show_external_drop_indicator(self, global_pos: QPoint, title: str) -> None:
        _ = (global_pos, title)

    def hide_external_drop_indicator(self) -> None:
        return

    def insertion_index_for_global_pos(self, global_pos: QPoint) -> int:
        return self._insertion_index_from_pos(self.mapFromGlobal(global_pos))

    def begin_external_drag_width_lock(self) -> None:
        self._locked_width_by_id = {}
        for index in range(self.count()):
            identity = self.tabData(index)
            if identity is None:
                continue
            rect = self.tabRect(index)
            width = rect.width() if rect.width() > 0 else super().tabSizeHint(index).width()
            self._locked_width_by_id[int(identity)] = int(width)
        self._width_lock_active = True
        self.updateGeometry()
        self.update()

    def end_external_drag_width_lock(self) -> None:
        if not self._width_lock_active and not self._locked_width_by_id:
            return
        self._width_lock_active = False
        self._locked_width_by_id = {}
        self.updateGeometry()
        self.update()

    def set_external_drag_overlay(
        self,
        identity: int,
        global_pos: QPoint,
        *,
        hot_x: int,
    ) -> None:
        self._external_drag_identity = int(identity)
        self._external_drag_global_pos = QPoint(global_pos)
        self._external_drag_hot_x = int(max(0, hot_x))
        self._sync_title_overlays()

    def clear_external_drag_overlay(self) -> None:
        if (
            self._external_drag_identity is None
            and self._external_drag_global_pos is None
            and not self._externally_repositioned_close_by_identity
        ):
            return
        captured_settle = False
        for identity in list(self._externally_repositioned_close_by_identity):
            index = self._index_for_identity(identity)
            if index < 0:
                continue
            label = self._title_overlay_by_index.get(index)
            if label is not None and label.isVisible():
                self._settling_overlay_left_by_identity[int(identity)] = float(label.geometry().x())
                self._settling_overlay_start_ms_by_identity[int(identity)] = int(time.time() * 1000)
                captured_settle = True
        self._external_drag_identity = None
        self._external_drag_global_pos = None
        self._external_drag_hot_x = 0
        # Avoid one immediate post-release snap; let the timer drive settle.
        if not captured_settle:
            self._sync_title_overlays()

    def _sync_title_overlays(self) -> None:
        internal_dragged_index = -1
        if (
            self._press_identity is not None
            and bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)
        ):
            internal_dragged_index = self._index_for_identity(self._press_identity)
        external_dragged_index = -1
        if self._external_drag_identity is not None:
            external_dragged_index = self._index_for_identity(self._external_drag_identity)
        dragged_index = internal_dragged_index if internal_dragged_index >= 0 else external_dragged_index
        drag_active = dragged_index >= 0
        drag_cursor_local_x: Optional[int] = None
        drag_hot_x: Optional[int] = None
        if (
            dragged_index >= 0
            and dragged_index == external_dragged_index
            and self._external_drag_global_pos is not None
        ):
            drag_cursor_local_x = int(self.mapFromGlobal(self._external_drag_global_pos).x())
            drag_hot_x = int(self._external_drag_hot_x) if self._external_drag_hot_x > 0 else None
        external_dragging_active = (
            dragged_index >= 0
            and dragged_index == external_dragged_index
            and drag_cursor_local_x is not None
        )
        repositioned_this_frame: Set[int] = set()
        active: Dict[int, QLabel] = {}
        for index in range(self.count()):
            text = self.tabText(index)
            rect = self.tabRect(index)
            if not text or rect.width() <= 0 or rect.height() <= 0:
                continue
            label = self._title_overlay_by_index.get(index)
            if label is None:
                label = QLabel(self)
                label.setObjectName("WorkspaceTabOverlayLabel")
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            left, width = self._title_overlay_geometry(
                index,
                rect,
                dragging=(index == dragged_index),
                drag_cursor_local_x=drag_cursor_local_x if index == dragged_index else None,
                drag_hot_x=drag_hot_x if index == dragged_index else None,
            )
            identity = self.tabData(index)
            identity_key = int(identity) if identity is not None else None
            if identity_key is not None and index != dragged_index:
                settle_left = self._settling_overlay_left_by_identity.get(identity_key)
                if settle_left is not None:
                    target_left = float(rect.x() + 20)
                    start_ms = self._settling_overlay_start_ms_by_identity.get(
                        identity_key,
                        int(time.time() * 1000),
                    )
                    elapsed_ms = max(0, int(time.time() * 1000) - int(start_ms))
                    duration_ms = 260
                    progress = max(0.0, min(1.0, float(elapsed_ms) / float(duration_ms)))
                    eased = (3.0 * (progress ** 2)) - (2.0 * (progress ** 3))
                    next_left = settle_left + ((target_left - settle_left) * eased)
                    if progress >= 1.0 or abs(target_left - next_left) < 1.0:
                        next_left = target_left
                        self._settling_overlay_left_by_identity.pop(identity_key, None)
                        self._settling_overlay_start_ms_by_identity.pop(identity_key, None)
                    else:
                        # keep start position/time fixed across frames to preserve easing curve
                        pass
                    left = int(round(next_left))
            if (
                external_dragging_active
                and index != dragged_index
                and label is not None
                and label.isVisible()
            ):
                prev_left = int(label.geometry().x())
                delta = int(left - prev_left)
                max_step = 14
                if abs(delta) > max_step:
                    left = int(prev_left + (max_step if delta > 0 else -max_step))
            label.setGeometry(left, rect.y(), width, rect.height())
            elided = label.fontMetrics().elidedText(str(text), self.elideMode(), width)
            if label.text() != elided:
                label.setText(elided)
            color = "#8b949e"
            if index == self.currentIndex():
                color = "#58a6ff"
            elif (not drag_active) and index == self._hover_index:
                color = "#e6edf3"
            style = f"color: {color}; font-weight: 600; font-size: 13px;"
            if label.styleSheet() != style:
                label.setStyleSheet(style)
            label.show()
            label.raise_()
            active[index] = label
            if external_dragging_active and index == dragged_index:
                identity = self._position_close_button_for_overlay(
                    index=index,
                    overlay_left=left,
                    rect=rect,
                )
                if identity is not None:
                    repositioned_this_frame.add(identity)
            elif external_dragging_active and identity_key is not None and index != dragged_index:
                identity = self._position_close_button_for_overlay(
                    index=index,
                    overlay_left=left,
                    rect=rect,
                    max_step=14,
                )
                if identity is not None:
                    repositioned_this_frame.add(identity)
            elif identity_key is not None and identity_key in self._settling_overlay_left_by_identity:
                self._position_close_button_for_overlay(
                    index=index,
                    overlay_left=left,
                    rect=rect,
                )

        if dragged_index in active:
            active[dragged_index].raise_()

        for index, label in list(self._title_overlay_by_index.items()):
            if index in active:
                continue
            label.hide()

        self._title_overlay_by_index = active
        stale_repositioned = (
            self._externally_repositioned_close_by_identity - repositioned_this_frame
        )
        for identity in stale_repositioned:
            if identity in self._settling_overlay_left_by_identity:
                continue
            self._restore_close_button_position(identity)
        self._externally_repositioned_close_by_identity = repositioned_this_frame
        stale_settle_keys = set(self._settling_overlay_start_ms_by_identity.keys()) - set(
            self._settling_overlay_left_by_identity.keys()
        )
        for identity in stale_settle_keys:
            self._settling_overlay_start_ms_by_identity.pop(identity, None)

    def _index_for_identity(self, identity: Optional[int]) -> int:
        if identity is None:
            return -1
        for index in range(self.count()):
            data = self.tabData(index)
            if data is None:
                continue
            if int(data) == int(identity):
                return index
        return -1

    def _title_overlay_geometry(
        self,
        index: int,
        rect: QRect,
        *,
        dragging: bool,
        drag_cursor_local_x: Optional[int] = None,
        drag_hot_x: Optional[int] = None,
    ) -> tuple[int, int]:
        close_btn = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if close_btn is None or not close_btn.isVisible():
            return rect.x() + 20, max(6, rect.width() - 38)

        identity = self.tabData(index)
        if identity is None:
            identity_key = -1 - index
        else:
            identity_key = int(identity)
        baseline_gap = self._title_gap_by_identity.get(identity_key)
        if baseline_gap is None:
            baseline_gap = int(close_btn.x() - (rect.x() + 20))
            baseline_gap = max(18, baseline_gap)
            self._title_gap_by_identity[identity_key] = baseline_gap

        baseline_width = self._title_width_by_identity.get(identity_key)
        if baseline_width is None:
            baseline_width = max(6, int(rect.width() - 16))
            self._title_width_by_identity[identity_key] = baseline_width

        if dragging:
            width = int(baseline_width)
            max_width = max(6, int(self.width()) - 8)
            width = min(width, max_width)
            if drag_cursor_local_x is not None:
                anchor_x = int(drag_hot_x) if drag_hot_x is not None else width // 2
                anchor_x = max(8, min(anchor_x, max(8, width - 8)))
                left = int(drag_cursor_local_x - anchor_x)
                left = max(0, min(left, max(0, int(self.width()) - width)))
            else:
                left = int(close_btn.x() - baseline_gap)
            return left, width

        post_release_left = int(close_btn.x() - baseline_gap)
        rect_left = int(rect.x() + 8)
        rect_right = int(rect.right() - 4)
        if (
            not bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)
            and (post_release_left < rect_left - 24 or post_release_left > rect_right + 24)
        ):
            width = int(baseline_width)
            max_width = max(6, int(self.width()) - 8)
            width = min(width, max_width)
            left = max(0, min(post_release_left, max(0, int(self.width()) - width)))
            return left, width

        left = int(close_btn.x() - baseline_gap)
        right = int(close_btn.x() - 8)
        min_left = rect.x() + 8
        max_right = rect.right() - 4
        left = max(min_left, min(left, max_right - 6))
        right = max(left + 6, min(right, max_right))
        width = max(6, right - left)
        if width > self._title_width_by_identity.get(identity_key, 0):
            self._title_width_by_identity[identity_key] = width
        return left, width

    def _position_close_button_for_overlay(
        self,
        *,
        index: int,
        overlay_left: int,
        rect: QRect,
        max_step: Optional[int] = None,
    ) -> Optional[int]:
        identity = self.tabData(index)
        if identity is None:
            return None
        identity_key = int(identity)
        close_btn = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if close_btn is None or not close_btn.isVisible():
            return None
        baseline_gap = self._title_gap_by_identity.get(identity_key)
        if baseline_gap is None:
            baseline_gap = int(close_btn.x() - (rect.x() + 20))
            baseline_gap = max(18, baseline_gap)
            self._title_gap_by_identity[identity_key] = baseline_gap
        target_x = int(overlay_left + baseline_gap)
        max_x = max(0, int(self.width()) - int(close_btn.width()))
        target_x = max(0, min(target_x, max_x))
        if max_step is not None:
            step = max(1, int(max_step))
            prev_x = int(close_btn.x())
            if abs(target_x - prev_x) > step:
                target_x = int(prev_x + (step if target_x > prev_x else -step))
        target_y = int(rect.y() + max(0, (rect.height() - close_btn.height()) // 2))
        close_btn.move(target_x, target_y)
        close_btn.raise_()
        return identity_key

    def _restore_close_button_position(self, identity: int) -> None:
        index = self._index_for_identity(identity)
        if index < 0:
            return
        close_btn = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if close_btn is None or not close_btn.isVisible():
            return
        rect = self.tabRect(index)
        baseline_gap = self._title_gap_by_identity.get(int(identity))
        if baseline_gap is None:
            return
        default_x = int(rect.x() + 20 + baseline_gap)
        max_x = max(0, int(self.width()) - int(close_btn.width()))
        default_x = max(0, min(default_x, max_x))
        default_y = int(rect.y() + max(0, (rect.height() - close_btn.height()) // 2))
        close_btn.move(default_x, default_y)


class TabWorkspaceController(QObject):
    _DROP_TARGET_TOP_SLOP_PX = 4
    _DROP_TARGET_SIDE_SLOP_PX = 8
    # Keep a generous lower hit area so fast vertical moves do not bounce a
    # dragged tab in/out of floating mode while crossing window borders.
    _DROP_TARGET_BOTTOM_SLOP_PX = 40
    _DROP_TARGET_STICKY_BOTTOM_SLOP_PX = 40
    _EXTERNAL_DRAG_INDEX_HYSTERESIS_PX = 2
    _EXTERNAL_DRAG_CURSOR_POLL_MS = 16

    def __init__(self) -> None:
        super().__init__()
        self.tab_by_key: Dict[str, QWidget] = {}
        self.key_by_widget: Dict[QWidget, str] = {}
        self.title_by_widget: Dict[QWidget, str] = {}
        self.window_by_widget: Dict[QWidget, WorkspaceWindow] = {}
        self.registered_windows: Set[WorkspaceWindow] = set()
        self.loading_keys: set[str] = set()
        self.is_shutting_down: bool = False
        self._primary_window: Optional[WorkspaceWindow] = None
        self._home_widget: Optional[QWidget] = None
        self._external_drag: Optional[_ExternalTabDragState] = None
        self._drag_filter_installed: bool = False
        self._drag_cursor_poll_timer: Optional[QTimer] = None
        self._drag_cursor_poll_last_pos: Optional[QPoint] = None
        self._detached_window_factory: Optional[Callable[[], WorkspaceWindow]] = None
        self._debug_log_path = Path(__file__).resolve().parents[1] / "debug" / "tab_workspace.log"
        self._drag_trace_enabled = os.environ.get("DMT_TAB_DRAG_DEBUG", "").strip() == "1"
        self._drag_trace_path = Path(__file__).resolve().parents[1] / "debug" / "tab_workspace_drag_trace.log"
        self._drag_trace_seq = 0
        if self._drag_trace_enabled and os.environ.get("DMT_TAB_DRAG_DEBUG_APPEND", "").strip() != "1":
            self._drag_trace_path.parent.mkdir(parents=True, exist_ok=True)
            self._drag_trace_path.write_text("", encoding="utf-8")

    def set_detached_window_factory(self, factory: Callable[[], WorkspaceWindow]) -> None:
        self._detached_window_factory = factory

    def set_home_widget(self, widget: QWidget) -> None:
        self._home_widget = widget

    def register_window(self, window: WorkspaceWindow, *, primary: bool = False) -> None:
        self.registered_windows.add(window)
        if primary:
            self._primary_window = window
        setattr(window, "_tab_by_key", self.tab_by_key)
        setattr(window, "_loading_tabs", self.loading_keys)
        tabs = window.workspace_tabs()
        bar = DetachableTabBar(self, window, tabs)
        bar.setExpanding(False)
        bar.setElideMode(Qt.TextElideMode.ElideRight)
        tabs.setTabBar(bar)
        tabs.setMovable(True)
        tabs.setTabsClosable(True)
        bar.setTabsClosable(True)
        self.sync_tab_bar_extent(window)
        tabs.tabCloseRequested.connect(lambda index: self.close_tab_by_index(window, index))
        bar.tabMoved.connect(lambda _from, _to: self._enforce_home_pinned(window))

    def unregister_window(self, window: WorkspaceWindow) -> None:
        self.registered_windows.discard(window)
        if self._primary_window is window:
            self._primary_window = None

    def is_home_widget(self, widget: Optional[QWidget]) -> bool:
        return widget is not None and widget is self._home_widget

    def can_detach_widget(self, widget: QWidget) -> bool:
        return not self.is_home_widget(widget)

    def open_applet(
        self,
        window: WorkspaceWindow,
        applet: Dict[str, object],
        focus_if_new: bool = True,
    ) -> None:
        key = str(applet["key"])
        if key == "world_selector":
            primary = self._primary_window
            if primary is not None:
                primary.workspace_tabs().setCurrentIndex(0)
                home = getattr(primary, "_home", None)
                if home is not None and hasattr(home, "open_navigate"):
                    home.open_navigate()
            return

        existing = self.tab_by_key.get(key)
        if existing is not None:
            owner = self.window_by_widget.get(existing)
            if owner is not None:
                self.focus_widget(owner, existing)
            return

        if key in self.loading_keys:
            return

        self.loading_keys.add(key)
        if hasattr(window, "_show_applet_loading_overlay"):
            window._show_applet_loading_overlay(f"Loading {applet.get('title', 'applet')}...")
        if hasattr(window, "_warmup_loading_overlay"):
            window._warmup_loading_overlay()
        QApplication.processEvents()

        try:
            builder = getattr(window, "_build_applet_widget", None)
            widget = self._build_widget_with_animation_pump(builder, key, applet)
            if widget is None:
                return
            title = str(applet.get("tab", applet.get("title", key)))
            self._register_widget(key, widget, window, title)
            tabs = window.workspace_tabs()
            index = tabs.addTab(widget, title)
            tabs.tabBar().setTabData(index, int(id(widget)))
            if focus_if_new:
                tabs.setCurrentIndex(index)
            self.sync_tab_bar_extent(window)
            if self.is_home_widget(widget):
                self._enforce_home_pinned(window)
        finally:
            self.loading_keys.discard(key)
            if hasattr(window, "_hide_applet_loading_overlay"):
                window._hide_applet_loading_overlay()

    def _build_widget_with_animation_pump(
        self,
        builder: object,
        key: str,
        applet: Dict[str, object],
    ) -> Optional[QWidget]:
        if not callable(builder):
            return None

        previous_profile = sys.getprofile()
        pump_interval_s = 0.016
        last_pump = time.perf_counter()
        reentrant = False

        def _profile(frame, event, arg):  # type: ignore[no-untyped-def]
            nonlocal last_pump, reentrant
            if previous_profile is not None:
                previous_profile(frame, event, arg)
            if reentrant:
                return
            now = time.perf_counter()
            if now - last_pump < pump_interval_s:
                return
            reentrant = True
            try:
                QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 1)
            finally:
                last_pump = now
                reentrant = False

        sys.setprofile(_profile)
        try:
            return builder(key, applet)
        finally:
            sys.setprofile(previous_profile)

    def focus_widget(self, window: WorkspaceWindow, widget: QWidget) -> None:
        tabs = window.workspace_tabs()
        index = tabs.indexOf(widget)
        if index == -1:
            return
        tabs.setCurrentIndex(index)
        if hasattr(window, "show"):
            window.show()
        if hasattr(window, "raise_"):
            window.raise_()
        if hasattr(window, "activateWindow"):
            window.activateWindow()

    def close_tab_by_index(self, window: WorkspaceWindow, index: int, *, auto_close_window: bool = True) -> bool:
        tabs = window.workspace_tabs()
        if index < 0 or index >= tabs.count():
            return False
        widget = tabs.widget(index)
        if widget is None or self.is_home_widget(widget):
            return False
        try:
            closed = bool(widget.close())
        except RuntimeError:
            closed = True
        if not closed:
            key = self.key_by_widget.get(widget, "")
            self._debug_log("close_tab_veto", key=str(key))
            return False
        key = self.key_by_widget.pop(widget, None)
        if key:
            self.tab_by_key.pop(key, None)
        self.title_by_widget.pop(widget, None)
        self.window_by_widget.pop(widget, None)
        current_index = tabs.indexOf(widget)
        title = tabs.tabText(current_index if current_index != -1 else index)
        if current_index != -1:
            tabs.removeTab(current_index)
        self.sync_tab_bar_extent(window)
        self._debug_log("close_tab", key=str(key or ""), title=title)
        try:
            widget.deleteLater()
        except RuntimeError:
            pass
        if auto_close_window and not window.is_primary_window() and tabs.count() == 0:
            if hasattr(window, "close"):
                window.close()
        return True

    def close_all_tabs_in_window(self, window: WorkspaceWindow) -> None:
        tabs = window.workspace_tabs()
        while tabs.count() > 0:
            closed_any = False
            for index in range(tabs.count() - 1, -1, -1):
                widget = tabs.widget(index)
                if self.is_home_widget(widget):
                    continue
                if self.close_tab_by_index(window, index, auto_close_window=False):
                    closed_any = True
                    break
            if not closed_any:
                break

    def move_widget_to_window(
        self,
        widget: QWidget,
        target_window: WorkspaceWindow,
        *,
        target_index: int,
        focus: bool,
        auto_close_source_if_empty: bool = True,
    ) -> bool:
        if self.is_home_widget(widget):
            return False
        source_window = self.window_by_widget.get(widget)
        if source_window is None:
            return False
        source_tabs = source_window.workspace_tabs()
        source_index = source_tabs.indexOf(widget)
        if source_index == -1:
            return False

        if source_window is target_window:
            clamped = max(0, min(int(target_index), source_tabs.count() - 1))
            if source_index == clamped:
                if focus:
                    source_tabs.setCurrentWidget(widget)
                return True
            source_tabs.tabBar().moveTab(source_index, clamped)
            self.sync_tab_bar_extent(target_window)
            self._enforce_home_pinned(target_window)
            if focus:
                source_tabs.setCurrentWidget(widget)
            return True

        title = self.title_by_widget.get(widget, source_tabs.tabText(source_index))
        source_tabs.removeTab(source_index)
        target_tabs = target_window.workspace_tabs()
        insert_at = max(0, min(int(target_index), target_tabs.count()))
        target_tabs.insertTab(insert_at, widget, title)
        target_tabs.tabBar().setTabData(insert_at, int(id(widget)))
        self.window_by_widget[widget] = target_window
        self.sync_tab_bar_extent(source_window)
        self.sync_tab_bar_extent(target_window)
        self._enforce_home_pinned(source_window)
        self._enforce_home_pinned(target_window)
        if focus:
            target_tabs.setCurrentWidget(widget)
            self.focus_widget(target_window, widget)
        if (
            auto_close_source_if_empty
            and not source_window.is_primary_window()
            and source_tabs.count() == 0
            and hasattr(source_window, "close")
        ):
            source_window.close()
        return True

    def detach_widget_to_new_window(
        self,
        widget: QWidget,
        global_pos: QPoint,
        *,
        hot_spot: Optional[QPoint] = None,
    ) -> Optional[WorkspaceWindow]:
        if not self.can_detach_widget(widget):
            return None
        if self._detached_window_factory is None:
            return None
        new_window = self._detached_window_factory()
        if hasattr(new_window, "resize"):
            new_window.resize(1200, 700)
        if hasattr(new_window, "move"):
            new_window.move(global_pos.x(), global_pos.y())
        if hasattr(new_window, "show"):
            new_window.show()
        current_owner = self.window_by_widget.get(widget)
        if current_owner is None:
            moved = self._attach_floating_widget_to_window(widget, new_window, target_index=0, focus=True)
        else:
            moved = self.move_widget_to_window(widget, new_window, target_index=0, focus=True)
        if not moved:
            if hasattr(new_window, "close"):
                new_window.close()
            return None
        if hot_spot is not None:
            tabs = new_window.workspace_tabs()
            index = tabs.indexOf(widget)
            if index != -1:
                bar = tabs.tabBar()
                rect = bar.tabRect(index)
                if rect.width() > 0 and rect.height() > 0:
                    clamped_hot = QPoint(
                        max(1, min(int(hot_spot.x()), max(1, rect.width() - 1))),
                        max(1, min(int(hot_spot.y()), max(1, rect.height() - 1))),
                    )
                    actual_global = bar.mapToGlobal(rect.topLeft() + clamped_hot)
                    dx = int(global_pos.x() - actual_global.x())
                    dy = int(global_pos.y() - actual_global.y())
                    if dx != 0 or dy != 0:
                        new_window.move(new_window.x() + dx, new_window.y() + dy)
        self._debug_log("detach_widget", key=str(self.key_by_widget.get(widget, "")))
        return new_window

    def begin_primary_shutdown(self, primary_window: WorkspaceWindow) -> None:
        if self.is_shutting_down:
            return
        if self._external_drag is not None:
            self.finish_external_tab_drag(QCursor.pos(), detach_on_invalid_drop=False)
        self.is_shutting_down = True
        for window in list(self.registered_windows):
            if window is primary_window:
                continue
            if hasattr(window, "close"):
                window.close()

    def prepare_window_close(self, window: WorkspaceWindow) -> None:
        state = self._external_drag
        if state is not None:
            owner = self.window_by_widget.get(state.widget)
            if owner is window:
                self.finish_external_tab_drag(QCursor.pos(), detach_on_invalid_drop=False)
        tabs = window.workspace_tabs()
        for index in range(tabs.count()):
            widget = tabs.widget(index)
            if widget is None or self.is_home_widget(widget):
                continue
            key = self.key_by_widget.pop(widget, None)
            if key:
                self.tab_by_key.pop(key, None)
            self.title_by_widget.pop(widget, None)
            self.window_by_widget.pop(widget, None)
            try:
                widget.close()
            except RuntimeError:
                pass

    def start_external_tab_drag(
        self,
        source_window: WorkspaceWindow,
        widget: QWidget,
        global_pos: QPoint,
        *,
        hot_spot: Optional[QPoint] = None,
    ) -> bool:
        if self._external_drag is not None:
            return False
        if not self.can_detach_widget(widget):
            return False
        source_tabs = source_window.workspace_tabs()
        source_index = source_tabs.indexOf(widget)
        if source_index < 0:
            return False
        self._drag_trace(
            "drag_start_request",
            source=self._window_label(source_window),
            widget=self._widget_label(widget),
            global_x=global_pos.x(),
            global_y=global_pos.y(),
            source_index=source_index,
        )
        title = source_tabs.tabText(source_index) if source_index != -1 else self.title_by_widget.get(widget, "")
        tab_rect = source_tabs.tabBar().tabRect(source_index)
        ghost = _FloatingTabGhost(str(title or ""), tab_rect.size())
        if hot_spot is not None:
            hot_x = int(max(1, min(int(hot_spot.x()), ghost.width() - 1)))
            hot_y = int(max(1, min(int(hot_spot.y()), ghost.height() - 1)))
            drag_hot_spot = QPoint(hot_x, hot_y)
        else:
            drag_hot_spot = QPoint(max(1, ghost.width() // 2), max(1, ghost.height() // 2))
        self._external_drag = _ExternalTabDragState(
            widget=widget,
            title=str(title or ""),
            source_window=source_window,
            current_host_window=source_window,
            hot_spot=drag_hot_spot,
            ghost=ghost,
            cursor_polling=hot_spot is not None,
        )
        self._set_external_drag_width_lock(True)
        QApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)
        self._ensure_drag_event_filter()
        self._set_external_drag_cursor_polling(
            bool(self._external_drag.cursor_polling)
        )
        self.update_external_tab_drag(global_pos)
        self._drag_trace(
            "drag_start_created",
            source=self._window_label(source_window),
            widget=self._widget_label(widget),
            ghost_w=ghost.width(),
            ghost_h=ghost.height(),
            hot_x=drag_hot_spot.x(),
            hot_y=drag_hot_spot.y(),
        )
        self._debug_log("drag_begin", key=str(self.key_by_widget.get(widget, "")))
        return True

    def update_external_tab_drag(self, global_pos: QPoint) -> None:
        state = self._external_drag
        if state is None:
            return
        target_bar = self._tab_bar_from_global_pos(global_pos)
        current_owner = self.window_by_widget.get(state.widget)
        if current_owner is not None and current_owner.workspace_tabs().indexOf(state.widget) == -1:
            self.window_by_widget.pop(state.widget, None)
            current_owner = None
        if target_bar is None and current_owner is not None:
            target_bar = self._sticky_target_bar_from_owner(current_owner, global_pos)
        self._drag_trace(
            "drag_update_begin",
            widget=self._widget_label(state.widget),
            global_x=global_pos.x(),
            global_y=global_pos.y(),
            current_owner=self._window_label(current_owner),
            target_owner=self._window_label(target_bar.owner_window() if target_bar is not None else None),
        )
        if target_bar is not None:
            target_window = target_bar.owner_window()
            raw_target_index = target_bar.insertion_index_for_global_pos(global_pos)
            target_index = self._stable_external_target_index(
                state,
                target_bar,
                global_pos,
                raw_target_index,
            )
            moved = False
            if current_owner is None:
                moved = self._attach_floating_widget_to_window(
                    state.widget,
                    target_window,
                    target_index=int(target_index),
                    focus=False,
                )
            else:
                moved = self.move_widget_to_window(
                    state.widget,
                    target_window,
                    target_index=int(target_index),
                    focus=False,
                    auto_close_source_if_empty=True,
                )
            if moved:
                state.current_host_window = target_window
            self._drag_trace(
                "drag_update_attach",
                widget=self._widget_label(state.widget),
                moved=moved,
                from_owner=self._window_label(current_owner),
                to_owner=self._window_label(target_window),
                raw_target_index=raw_target_index,
                target_index=target_index,
            )
            attached_owner = self.window_by_widget.get(state.widget)
            if attached_owner is target_window:
                self._set_external_drag_overlay_for_bar(
                    target_bar,
                    state.widget,
                    global_pos,
                    hot_x=state.hot_spot.x(),
                )
            else:
                self._clear_external_drag_overlays()
            # Hide the floating ghost while a real tab preview is attached.
            if self.window_by_widget.get(state.widget) is not None:
                self._hide_drag_ghost(state)
            else:
                self._show_drag_ghost(state, global_pos)
            return
        self._clear_external_drag_overlays()
        state.last_target_window = None
        state.last_target_index = None
        if current_owner is not None:
            removed = self._remove_widget_from_window_for_drag(
                state.widget,
                close_empty_window=True,
            )
            if removed is not None:
                state.current_host_window = state.source_window
            self._drag_trace(
                "drag_update_detach_to_ghost",
                widget=self._widget_label(state.widget),
                removed_from=self._window_label(removed),
                close_empty=True,
            )
        self._show_drag_ghost(state, global_pos)
        self._drag_trace(
            "drag_update_show_ghost",
            widget=self._widget_label(state.widget),
            ghost_visible=bool(state.ghost is not None and state.ghost.isVisible()),
        )

    def finish_external_tab_drag(self, global_pos: QPoint, *, detach_on_invalid_drop: bool = True) -> bool:
        state = self._external_drag
        if state is None:
            return False
        self._drag_trace(
            "drag_finish_begin",
            widget=self._widget_label(state.widget),
            global_x=global_pos.x(),
            global_y=global_pos.y(),
            detach_on_invalid_drop=detach_on_invalid_drop,
            current_owner=self._window_label(self.window_by_widget.get(state.widget)),
        )
        self.update_external_tab_drag(global_pos)
        target_bar = self._tab_bar_from_global_pos(global_pos)
        moved = False
        current_owner = self.window_by_widget.get(state.widget)
        if target_bar is None and detach_on_invalid_drop:
            detached = self.detach_widget_to_new_window(
                state.widget,
                global_pos,
                hot_spot=state.hot_spot,
            )
            moved = detached is not None
            if moved and detached is not None:
                self.focus_widget(detached, state.widget)
                self._debug_log("drag_detach_finish", key=str(self.key_by_widget.get(state.widget, "")))
        elif current_owner is not None:
            moved = True
            if target_bar is not None:
                self._debug_log("drag_attach", key=str(self.key_by_widget.get(state.widget, "")))
        self._hide_drag_ghost(state)
        self._destroy_drag_ghost(state)
        self._clear_external_drag_overlays()
        self._set_external_drag_width_lock(False)
        QApplication.restoreOverrideCursor()
        self._set_external_drag_cursor_polling(False)
        self._external_drag = None
        self._remove_drag_event_filter()
        self._drag_trace(
            "drag_finish_end",
            widget=self._widget_label(state.widget),
            moved=moved,
            final_owner=self._window_label(self.window_by_widget.get(state.widget)),
            target_owner=self._window_label(target_bar.owner_window() if target_bar is not None else None),
        )
        return moved

    def _stable_external_target_index(
        self,
        state: _ExternalTabDragState,
        target_bar: DetachableTabBar,
        global_pos: QPoint,
        raw_index: int,
    ) -> int:
        count = target_bar.count()
        clamped = max(0, min(int(raw_index), count))
        target_window = target_bar.owner_window()
        previous_window = state.last_target_window
        previous_index = state.last_target_index
        if previous_window is not target_window or previous_index is None:
            state.last_target_window = target_window
            state.last_target_index = clamped
            return clamped
        if clamped == previous_index:
            return clamped

        stable_index = clamped
        local_x = target_bar.mapFromGlobal(global_pos).x()
        margin = int(self._EXTERNAL_DRAG_INDEX_HYSTERESIS_PX)

        # Apply only a tiny hysteresis around the same quarter-width trigger
        # used by insertion index, so attached external drag feels like native.
        if clamped == previous_index + 1 and count > 0 and 0 <= previous_index < count:
            prev_rect = target_bar.tabRect(previous_index)
            threshold = prev_rect.left() + max(1, int(prev_rect.width() * 0.25)) + margin
            if local_x < threshold:
                stable_index = previous_index
        elif clamped + 1 == previous_index and count > 0 and 0 <= previous_index < count:
            prev_rect = target_bar.tabRect(previous_index)
            threshold = prev_rect.left() + max(1, int(prev_rect.width() * 0.25)) - margin
            if local_x > threshold:
                stable_index = previous_index

        state.last_target_window = target_window
        state.last_target_index = stable_index
        self._drag_trace(
            "drag_index_stabilized",
            widget=self._widget_label(state.widget),
            previous_index=previous_index,
            raw_index=clamped,
            stable_index=stable_index,
            local_x=local_x,
        )
        return stable_index

    def active_drag_window(self) -> Optional[WorkspaceWindow]:
        return None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        state = self._external_drag
        if state is None:
            return False
        event_type = event.type()
        if event_type == QEvent.Type.MouseMove:
            buttons = getattr(event, "buttons", lambda: Qt.MouseButton.NoButton)()
            global_pos = self._event_global_pos(event) or QCursor.pos()
            if not (buttons & Qt.MouseButton.LeftButton):
                # If release happened outside app widgets, finalize when pointer re-enters.
                self._debug_log("drag_finish_no_button")
                self._drag_trace(
                    "drag_event_no_button",
                    global_x=global_pos.x(),
                    global_y=global_pos.y(),
                )
                self.finish_external_tab_drag(global_pos)
                return False
            self.update_external_tab_drag(global_pos)
            return False
        if event_type == QEvent.Type.MouseButtonRelease:
            button = getattr(event, "button", lambda: Qt.MouseButton.NoButton)()
            if button == Qt.MouseButton.LeftButton:
                global_pos = self._event_global_pos(event) or QCursor.pos()
                self.finish_external_tab_drag(global_pos)
            return False
        return False

    def _ensure_drag_event_filter(self) -> None:
        if self._drag_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._drag_filter_installed = True

    def _remove_drag_event_filter(self) -> None:
        if not self._drag_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._drag_filter_installed = False

    def _set_external_drag_cursor_polling(self, enabled: bool) -> None:
        if not enabled:
            timer = self._drag_cursor_poll_timer
            if timer is not None and timer.isActive():
                timer.stop()
            self._drag_cursor_poll_last_pos = None
            return

        timer = self._drag_cursor_poll_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(False)
            timer.setInterval(self._EXTERNAL_DRAG_CURSOR_POLL_MS)
            timer.timeout.connect(self._poll_external_drag_cursor)
            self._drag_cursor_poll_timer = timer
        self._drag_cursor_poll_last_pos = None
        if not timer.isActive():
            timer.start()

    def _poll_external_drag_cursor(self) -> None:
        state = self._external_drag
        if state is None or not state.cursor_polling:
            self._set_external_drag_cursor_polling(False)
            return
        global_pos = QPoint(QCursor.pos())
        if (
            self._drag_cursor_poll_last_pos is not None
            and global_pos == self._drag_cursor_poll_last_pos
        ):
            return
        self._drag_cursor_poll_last_pos = QPoint(global_pos)
        self._drag_trace(
            "drag_poll_cursor",
            global_x=global_pos.x(),
            global_y=global_pos.y(),
        )
        self.update_external_tab_drag(global_pos)

    def _event_global_pos(self, event: QEvent) -> Optional[QPoint]:
        global_position = getattr(event, "globalPosition", None)
        if callable(global_position):
            return global_position().toPoint()
        global_pos = getattr(event, "globalPos", None)
        if callable(global_pos):
            return global_pos()
        return None

    def _set_external_drag_overlay_for_bar(
        self,
        target_bar: DetachableTabBar,
        widget: QWidget,
        global_pos: QPoint,
        *,
        hot_x: int,
    ) -> None:
        identity = int(id(widget))
        for window in list(self.registered_windows):
            tabs = window.workspace_tabs()
            bar = tabs.tabBar()
            if not isinstance(bar, DetachableTabBar):
                continue
            if bar is target_bar:
                bar.set_external_drag_overlay(identity, global_pos, hot_x=hot_x)
            else:
                bar.clear_external_drag_overlay()

    def _clear_external_drag_overlays(self) -> None:
        for window in list(self.registered_windows):
            tabs = window.workspace_tabs()
            bar = tabs.tabBar()
            if isinstance(bar, DetachableTabBar):
                bar.clear_external_drag_overlay()

    def _show_drag_ghost(self, state: _ExternalTabDragState, global_pos: QPoint) -> None:
        ghost = state.ghost
        if ghost is None:
            return
        top_left = QPoint(global_pos) - state.hot_spot
        ghost.move(top_left.x(), top_left.y())
        if not ghost.isVisible():
            ghost.show()
        ghost.raise_()

    def _hide_drag_ghost(self, state: _ExternalTabDragState) -> None:
        ghost = state.ghost
        if ghost is None:
            return
        ghost.hide()

    def _destroy_drag_ghost(self, state: _ExternalTabDragState) -> None:
        ghost = state.ghost
        if ghost is None:
            return
        ghost.hide()
        ghost.deleteLater()
        state.ghost = None

    def _remove_widget_from_window_for_drag(
        self,
        widget: QWidget,
        *,
        close_empty_window: bool,
    ) -> Optional[WorkspaceWindow]:
        source_window = self.window_by_widget.get(widget)
        if source_window is None:
            return None
        source_tabs = source_window.workspace_tabs()
        source_index = source_tabs.indexOf(widget)
        if source_index != -1:
            source_tabs.removeTab(source_index)
            self.sync_tab_bar_extent(source_window)
            self._enforce_home_pinned(source_window)
        self.window_by_widget.pop(widget, None)
        if (
            close_empty_window
            and not source_window.is_primary_window()
            and source_tabs.count() == 0
            and hasattr(source_window, "close")
        ):
            source_window.close()
        return source_window

    def _attach_floating_widget_to_window(
        self,
        widget: QWidget,
        target_window: WorkspaceWindow,
        *,
        target_index: int,
        focus: bool,
    ) -> bool:
        if self.is_home_widget(widget):
            return False
        target_tabs = target_window.workspace_tabs()
        insert_at = max(0, min(int(target_index), target_tabs.count()))
        title = self.title_by_widget.get(widget, "")
        target_tabs.insertTab(insert_at, widget, title)
        target_tabs.tabBar().setTabData(insert_at, int(id(widget)))
        self.window_by_widget[widget] = target_window
        self.sync_tab_bar_extent(target_window)
        self._enforce_home_pinned(target_window)
        if focus:
            target_tabs.setCurrentWidget(widget)
            self.focus_widget(target_window, widget)
        return True

    def _tab_bar_from_global_pos(
        self,
        global_pos: QPoint,
        *,
        exclude_window: Optional[WorkspaceWindow] = None,
    ) -> Optional[DetachableTabBar]:
        _ = exclude_window
        scan_parts: list[str] = []
        for window in list(self.registered_windows):
            window_visible = not hasattr(window, "isVisible") or bool(window.isVisible())
            tabs = window.workspace_tabs()
            count = tabs.count()
            if not window_visible:
                scan_parts.append(f"{self._window_label(window)}:hidden")
                continue
            if count <= 0:
                scan_parts.append(f"{self._window_label(window)}:empty")
                continue
            bar = tabs.tabBar()
            if not isinstance(bar, DetachableTabBar):
                scan_parts.append(f"{self._window_label(window)}:non-detachable")
                continue
            if not bar.isVisible():
                scan_parts.append(f"{self._window_label(window)}:bar-hidden")
                continue
            top_left = bar.mapToGlobal(QPoint(0, 0))
            global_rect = QRect(top_left, bar.size())
            strip_rect = self._drop_target_strip_rect(
                window,
                tabs,
                bar,
                bottom_slop_px=self._DROP_TARGET_BOTTOM_SLOP_PX,
            )
            if strip_rect.width() <= 0:
                scan_parts.append(f"{self._window_label(window)}:zero-width")
                continue
            in_global = global_rect.contains(global_pos)
            in_strip = strip_rect.contains(global_pos)
            scan_parts.append(
                f"{self._window_label(window)}:g={int(in_global)} s={int(in_strip)} "
                f"bar=({global_rect.x()},{global_rect.y()},{global_rect.width()},{global_rect.height()}) "
                f"strip=({strip_rect.x()},{strip_rect.y()},{strip_rect.width()},{strip_rect.height()})"
            )
            if in_global or in_strip:
                self._drag_trace(
                    "target_lookup",
                    global_x=global_pos.x(),
                    global_y=global_pos.y(),
                    match=self._window_label(window),
                    scan=" | ".join(scan_parts),
                )
                return bar
        self._drag_trace(
            "target_lookup",
            global_x=global_pos.x(),
            global_y=global_pos.y(),
            match="none",
            scan=" | ".join(scan_parts),
        )
        return None

    def _sticky_target_bar_from_owner(
        self,
        owner_window: WorkspaceWindow,
        global_pos: QPoint,
    ) -> Optional[DetachableTabBar]:
        tabs = owner_window.workspace_tabs()
        bar = tabs.tabBar()
        if not isinstance(bar, DetachableTabBar):
            return None
        if not bar.isVisible():
            return None
        sticky_rect = self._drop_target_strip_rect(
            owner_window,
            tabs,
            bar,
            bottom_slop_px=self._DROP_TARGET_STICKY_BOTTOM_SLOP_PX,
        )
        if sticky_rect.width() <= 0:
            return None
        if sticky_rect.contains(global_pos):
            self._drag_trace(
                "target_lookup_sticky_owner",
                global_x=global_pos.x(),
                global_y=global_pos.y(),
                owner=self._window_label(owner_window),
            )
            return bar
        return None

    def _use_full_tab_strip_drop_target_width(self, window: WorkspaceWindow) -> bool:
        _ = window
        return True

    def _drop_target_strip_rect(
        self,
        window: WorkspaceWindow,
        tabs: QTabWidget,
        bar: QTabBar,
        *,
        bottom_slop_px: int,
    ) -> QRect:
        strip_top_left = bar.mapToGlobal(QPoint(0, 0))
        strip_width = max(1, int(bar.width()))
        if self._use_full_tab_strip_drop_target_width(window):
            tabs_top_left = tabs.mapToGlobal(QPoint(0, 0))
            strip_top_left = QPoint(tabs_top_left.x(), strip_top_left.y())
            strip_width = max(strip_width, int(tabs.width()))
        strip_origin = strip_top_left - QPoint(
            self._DROP_TARGET_SIDE_SLOP_PX,
            self._DROP_TARGET_TOP_SLOP_PX,
        )
        strip_height = bar.height() + self._DROP_TARGET_TOP_SLOP_PX + int(bottom_slop_px)
        return QRect(
            strip_origin,
            QSize(strip_width + (2 * self._DROP_TARGET_SIDE_SLOP_PX), max(1, strip_height)),
        )

    def _set_external_drag_width_lock(self, enabled: bool) -> None:
        for window in list(self.registered_windows):
            tabs = window.workspace_tabs()
            bar = tabs.tabBar()
            if not isinstance(bar, DetachableTabBar):
                continue
            if enabled:
                bar.begin_external_drag_width_lock()
            else:
                bar.end_external_drag_width_lock()

    def _register_widget(
        self,
        key: str,
        widget: QWidget,
        window: WorkspaceWindow,
        title: str,
    ) -> None:
        self.tab_by_key[key] = widget
        self.key_by_widget[widget] = key
        self.title_by_widget[widget] = title
        self.window_by_widget[widget] = window

    def _enforce_home_pinned(self, window: WorkspaceWindow) -> None:
        home = self._home_widget
        if home is None:
            return
        tabs = window.workspace_tabs()
        if tabs.indexOf(home) == -1:
            return
        home_index = tabs.indexOf(home)
        if home_index > 0:
            tabs.tabBar().moveTab(home_index, 0)
        disable = getattr(window, "_disable_tab_close", None)
        if callable(disable):
            disable(0)

    def sync_tab_bar_extent(self, window: WorkspaceWindow) -> None:
        tabs = window.workspace_tabs()
        bar = tabs.tabBar()
        if not isinstance(bar, QTabBar):
            return
        if bar.expanding():
            bar.setExpanding(False)
        target_width = max(0, int(tabs.width()))
        if target_width <= 0:
            return
        if bar.minimumWidth() != target_width or bar.maximumWidth() != target_width:
            bar.setMinimumWidth(target_width)
            bar.setMaximumWidth(target_width)
            bar.updateGeometry()

    def _debug_log(self, event: str, **fields: object) -> None:
        if os.environ.get("DMT_TEST_MODE", "").strip() != "1":
            return
        payload = {"event": str(event)}
        for key in sorted(fields):
            payload[key] = str(fields[key])
        line = " ".join(f"{key}={value}" for key, value in payload.items())
        self._debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._debug_log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _window_label(self, window: Optional[WorkspaceWindow]) -> str:
        if window is None:
            return "none"
        try:
            tabs = window.workspace_tabs()
            count = tabs.count()
            current = tabs.currentIndex()
            visible = bool(window.isVisible()) if hasattr(window, "isVisible") else False
            return f"{type(window).__name__}@{id(window):x}[vis={int(visible)} count={count} cur={current}]"
        except Exception:
            return f"{type(window).__name__}@{id(window):x}[unavailable]"

    def _widget_label(self, widget: Optional[QWidget]) -> str:
        if widget is None:
            return "none"
        key = self.key_by_widget.get(widget, "")
        return f"{type(widget).__name__}@{id(widget):x}[key={key}]"

    def _drag_trace(self, event: str, **fields: object) -> None:
        if not self._drag_trace_enabled:
            return
        self._drag_trace_seq += 1
        payload = {
            "seq": str(self._drag_trace_seq),
            "t_ms": str(int(time.time() * 1000)),
            "event": str(event),
        }
        for key in sorted(fields):
            payload[key] = str(fields[key])
        line = " ".join(f"{key}={value}" for key, value in payload.items())
        self._drag_trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self._drag_trace_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
