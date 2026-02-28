from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget


TAB_STRIP_HEIGHT = 36
TAB_MIN_WIDTH = 88
TAB_TEXT_LEFT_PADDING = 12
TAB_TEXT_RIGHT_PADDING = 10
TAB_CLOSE_RIGHT_PADDING = 6
TAB_CLOSE_GAP = 8
TAB_CLOSE_SIZE = 12
TAB_ACTIVE_LINE_HEIGHT = 2

DROP_TARGET_TOP_SLOP_PX = 4
DROP_TARGET_SIDE_SLOP_PX = 8
DROP_TARGET_BOTTOM_SLOP_PX = 40

ANIMATION_TICK_MS = 16
ANIMATION_BLEND = 0.35
ANIMATION_SETTLE_EPSILON = 0.6
ANIMATION_VISIBLE_SETTLE_EPSILON = 1.5


def compute_workspace_tab_width(font_metrics: QFontMetrics, title: str, *, closable: bool) -> int:
    text = str(title or "")
    text_width = max(0, int(font_metrics.horizontalAdvance(text)))
    width = TAB_TEXT_LEFT_PADDING + text_width + TAB_TEXT_RIGHT_PADDING
    if closable:
        width += TAB_CLOSE_GAP + TAB_CLOSE_SIZE + TAB_CLOSE_RIGHT_PADDING
    return max(TAB_MIN_WIDTH, int(width))


def compute_workspace_tab_close_rect(tab_rect: QRect) -> QRect:
    if tab_rect.width() <= 0 or tab_rect.height() <= 0:
        return QRect()
    close_x = int(tab_rect.right() - TAB_CLOSE_RIGHT_PADDING - TAB_CLOSE_SIZE + 1)
    close_y = int(tab_rect.y() + max(0, (tab_rect.height() - TAB_CLOSE_SIZE) // 2))
    return QRect(close_x, close_y, TAB_CLOSE_SIZE, TAB_CLOSE_SIZE)


def compute_workspace_tab_name_rect(tab_rect: QRect, *, closable: bool) -> QRect:
    if tab_rect.width() <= 0 or tab_rect.height() <= 0:
        return QRect()
    right_cut = TAB_TEXT_RIGHT_PADDING
    if closable:
        right_cut += TAB_CLOSE_GAP + TAB_CLOSE_SIZE + TAB_CLOSE_RIGHT_PADDING
    left = int(tab_rect.x() + TAB_TEXT_LEFT_PADDING)
    right = int(tab_rect.right() - right_cut)
    width = max(8, right - left + 1)
    return QRect(left, tab_rect.y(), width, tab_rect.height())


@dataclass
class WorkspaceTabItem:
    tab_id: int
    widget: QWidget
    title: str
    closable: bool
    pinned: bool


@dataclass
class _StripTabLayout:
    outer: QRect
    name_rect: QRect
    close_rect: QRect


@dataclass
class _DragSession:
    widget: QWidget
    tab_id: int
    title: str
    source_window: "WorkspaceWindow"
    current_window: Optional["WorkspaceWindow"]
    hot_x: int
    floating_item: Optional[WorkspaceTabItem] = None
    floating_preview: Optional["_FloatingTabPreview"] = None
    previous_active_by_window: Optional[Dict["WorkspaceWindow", Optional[QWidget]]] = None
    cursor_polling: bool = False


class WorkspaceWindow(Protocol):
    def workspace_host(self) -> "WorkspaceTabsHost":
        ...

    def is_primary_window(self) -> bool:
        ...

    def begin_applet_load(self, key: str, title: str) -> None:
        ...

    def end_applet_load(self, key: str) -> None:
        ...

    def build_applet_widget(self, key: str, applet: Dict[str, object]) -> Optional[QWidget]:
        ...


class _FloatingTabPreview(QWidget):
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
        width = max(100, int(size.width()))
        width = max(width, int(self.fontMetrics().horizontalAdvance(self._title)) + 48)
        height = max(TAB_STRIP_HEIGHT, int(size.height()))
        self.resize(width, height)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        _ = event
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(88, 166, 255, 210), 1.0))
        painter.setBrush(QColor(31, 111, 235, 120))
        painter.drawRoundedRect(rect, 6, 6)
        name_rect = compute_workspace_tab_name_rect(rect, closable=True)
        close_rect = compute_workspace_tab_close_rect(rect)
        painter.setPen(QColor(230, 237, 243))
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignCenter,
            self.fontMetrics().elidedText(self._title, Qt.TextElideMode.ElideRight, name_rect.width()),
        )
        painter.drawText(close_rect, Qt.AlignmentFlag.AlignCenter, "x")
        painter.fillRect(
            QRect(rect.x(), rect.bottom() - TAB_ACTIVE_LINE_HEIGHT + 1, rect.width(), TAB_ACTIVE_LINE_HEIGHT),
            QColor(88, 166, 255),
        )


class WorkspaceTabsHost(QWidget):
    currentChanged = Signal(int)
    tabCloseRequested = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorkspaceTabHost")
        self._entries: List[WorkspaceTabItem] = []
        self._tab_data_by_id: Dict[int, object] = {}
        self._id_seq = 1

        self._strip = WorkspaceTabStrip(self)
        self._stack = QStackedWidget(self)
        self._stack.setObjectName("WorkspaceTabStack")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._strip, 0)
        layout.addWidget(self._stack, 1)

        self._strip.tabActivated.connect(self._on_strip_tab_activated)
        self._strip.tabCloseRequested.connect(self._on_strip_tab_close)

    def configure(self, controller: "TabWorkspaceController", owner_window: WorkspaceWindow) -> None:
        self._strip.configure(controller, owner_window)

    def workspace_strip(self) -> "WorkspaceTabStrip":
        return self._strip

    def count(self) -> int:
        return len(self._entries)

    def currentIndex(self) -> int:
        return int(self._stack.currentIndex())

    def currentWidget(self) -> Optional[QWidget]:
        widget = self._stack.currentWidget()
        return widget if isinstance(widget, QWidget) else None

    def widget(self, index: int) -> Optional[QWidget]:
        if index < 0 or index >= len(self._entries):
            return None
        return self._entries[index].widget

    def tabText(self, index: int) -> str:
        if index < 0 or index >= len(self._entries):
            return ""
        return str(self._entries[index].title)

    def indexOf(self, widget: Optional[QWidget]) -> int:
        if widget is None:
            return -1
        for index, item in enumerate(self._entries):
            if item.widget is widget:
                return index
        return -1

    def tabBar(self) -> "WorkspaceTabStrip":
        return self._strip

    def tab_id_for_index(self, index: int) -> Optional[int]:
        if index < 0 or index >= len(self._entries):
            return None
        return int(self._entries[index].tab_id)

    def tab_id_for_widget(self, widget: QWidget) -> Optional[int]:
        index = self.indexOf(widget)
        if index == -1:
            return None
        return int(self._entries[index].tab_id)

    def index_for_tab_id(self, tab_id: Optional[int]) -> int:
        if tab_id is None:
            return -1
        wanted = int(tab_id)
        for index, item in enumerate(self._entries):
            if int(item.tab_id) == wanted:
                return index
        return -1

    def entry_for_tab_id(self, tab_id: int) -> Optional[WorkspaceTabItem]:
        index = self.index_for_tab_id(tab_id)
        if index == -1:
            return None
        return self._entries[index]

    def is_tab_pinned(self, tab_id: int) -> bool:
        item = self.entry_for_tab_id(tab_id)
        return bool(item.pinned) if item is not None else False

    def addTab(
        self,
        widget: QWidget,
        title: str,
        *,
        closable: bool = True,
        pinned: bool = False,
    ) -> int:
        insert_at = len(self._entries)
        return self.insertTab(
            insert_at,
            widget,
            title,
            closable=closable,
            pinned=pinned,
            preserve_current=True,
        )

    def insertTab(
        self,
        index: int,
        widget: QWidget,
        title: str,
        *,
        closable: bool = True,
        pinned: bool = False,
        preserve_current: bool = True,
    ) -> int:
        tab_id = self._next_tab_id()
        item = WorkspaceTabItem(
            tab_id=tab_id,
            widget=widget,
            title=str(title or ""),
            closable=bool(closable),
            pinned=bool(pinned),
        )
        return self.insert_existing_tab(index, item, preserve_current=preserve_current)

    def insert_existing_tab(self, index: int, item: WorkspaceTabItem, *, preserve_current: bool) -> int:
        old_count = len(self._entries)
        old_current = self.currentWidget() if preserve_current else None
        insert_at = self._clamp_insert_index(index, item)
        self._entries.insert(insert_at, item)
        self._stack.insertWidget(insert_at, item.widget)
        item.widget.setParent(self._stack)
        if old_count == 0:
            self.setCurrentIndex(0)
        elif old_current is not None and self.indexOf(old_current) != -1:
            self.setCurrentWidget(old_current)
        else:
            # Keep existing current index stable if possible.
            current = self.currentIndex()
            if current < 0:
                self.setCurrentIndex(0)
        self._strip.request_layout_sync()
        return insert_at

    def take_tab(self, index: int) -> Optional[WorkspaceTabItem]:
        if index < 0 or index >= len(self._entries):
            return None
        old_current = self.currentWidget()
        item = self._entries.pop(index)
        self._stack.removeWidget(item.widget)
        new_count = len(self._entries)
        if new_count <= 0:
            self.currentChanged.emit(-1)
        elif old_current is not None and old_current is not item.widget and self.indexOf(old_current) != -1:
            self.setCurrentWidget(old_current)
        else:
            self.setCurrentIndex(max(0, min(index, new_count - 1)))
        self._strip.request_layout_sync()
        return item

    def removeTab(self, index: int) -> None:
        item = self.take_tab(index)
        if item is None:
            return

    def move_tab(self, from_index: int, to_index: int) -> bool:
        if from_index < 0 or from_index >= len(self._entries):
            return False
        tab_id = int(self._entries[from_index].tab_id)
        return self.move_tab_by_id(tab_id, to_index)

    def move_tab_by_id(self, tab_id: int, target_index: int) -> bool:
        from_index = self.index_for_tab_id(tab_id)
        if from_index == -1:
            return False
        item = self._entries[from_index]
        if item.pinned:
            return False
        target_index = max(0, min(int(target_index), len(self._entries)))
        first_movable = self._first_movable_index()
        target_index = max(first_movable, target_index)
        if target_index == from_index or target_index == from_index + 1:
            return False
        current = self.currentWidget()
        popped = self._entries.pop(from_index)
        if target_index > from_index:
            target_index -= 1
        self._entries.insert(target_index, popped)
        self._stack.removeWidget(popped.widget)
        self._stack.insertWidget(target_index, popped.widget)
        if current is not None and self.indexOf(current) != -1:
            self.setCurrentWidget(current)
        self._strip.request_layout_sync()
        return True

    def setCurrentIndex(self, index: int) -> None:
        if len(self._entries) <= 0:
            self.currentChanged.emit(-1)
            return
        clamped = max(0, min(int(index), len(self._entries) - 1))
        if self._stack.currentIndex() == clamped:
            self._strip.update()
            return
        self._stack.setCurrentIndex(clamped)
        self.currentChanged.emit(clamped)
        self._strip.update()

    def setCurrentWidget(self, widget: QWidget) -> None:
        index = self.indexOf(widget)
        if index == -1:
            return
        self.setCurrentIndex(index)

    def setTabText(self, index: int, text: str) -> None:
        if index < 0 or index >= len(self._entries):
            return
        self._entries[index].title = str(text or "")
        self._strip.request_layout_sync()

    def setTabClosable(self, index: int, closable: bool) -> None:
        if index < 0 or index >= len(self._entries):
            return
        self._entries[index].closable = bool(closable)
        self._strip.request_layout_sync()

    def setTabPinned(self, index: int, pinned: bool) -> None:
        if index < 0 or index >= len(self._entries):
            return
        self._entries[index].pinned = bool(pinned)
        self._strip.request_layout_sync()

    def setTabData(self, index: int, data: object) -> None:
        tab_id = self.tab_id_for_index(index)
        if tab_id is None:
            return
        self._tab_data_by_id[int(tab_id)] = data

    def tabData(self, index: int) -> Optional[object]:
        tab_id = self.tab_id_for_index(index)
        if tab_id is None:
            return None
        return self._tab_data_by_id.get(int(tab_id))

    # Compatibility shims used by older call sites.
    def setDocumentMode(self, enabled: bool) -> None:
        _ = enabled

    def setMovable(self, enabled: bool) -> None:
        _ = enabled

    def setTabsClosable(self, enabled: bool) -> None:
        _ = enabled

    def _next_tab_id(self) -> int:
        next_id = int(self._id_seq)
        self._id_seq += 1
        return next_id

    def _first_movable_index(self) -> int:
        for index, item in enumerate(self._entries):
            if not item.pinned:
                return index
        return len(self._entries)

    def _clamp_insert_index(self, index: int, item: WorkspaceTabItem) -> int:
        if len(self._entries) <= 0:
            return 0
        clamped = max(0, min(int(index), len(self._entries)))
        if item.pinned:
            # Pinned tabs stay before all movable tabs.
            for i, existing in enumerate(self._entries):
                if not existing.pinned:
                    return min(clamped, i)
            return min(clamped, len(self._entries))
        first_movable = self._first_movable_index()
        return max(first_movable, clamped)

    def _on_strip_tab_activated(self, tab_id: int) -> None:
        index = self.index_for_tab_id(tab_id)
        if index == -1:
            return
        self.setCurrentIndex(index)

    def _on_strip_tab_close(self, tab_id: int) -> None:
        index = self.index_for_tab_id(tab_id)
        if index == -1:
            return
        self.tabCloseRequested.emit(index)


class WorkspaceTabStrip(QWidget):
    tabActivated = Signal(int)
    tabCloseRequested = Signal(int)

    def __init__(self, host: WorkspaceTabsHost) -> None:
        super().__init__(host)
        self.setObjectName("WorkspaceTabStrip")
        self.setMouseTracking(True)
        self.setFixedHeight(TAB_STRIP_HEIGHT)

        self._host = host
        self._controller: Optional[TabWorkspaceController] = None
        self._owner_window: Optional[WorkspaceWindow] = None

        self._ordered_tab_ids: List[int] = []
        self._target_layouts: Dict[int, _StripTabLayout] = {}
        self._display_left_by_id: Dict[int, float] = {}
        self._layout_dirty = True

        self._hover_tab_id: Optional[int] = None
        self._press_tab_id: Optional[int] = None
        self._press_on_close = False
        self._suppress_release_activation = False
        self._press_pos = QPoint()
        self._pointer_dragging = False

        self._drag_tab_id: Optional[int] = None
        self._drag_global_pos = QPoint()
        self._drag_hot_x = 0
        self._drag_draws_background = False
        self._settle_pending: set[int] = set()
        self._last_paint_order: List[int] = []

        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(ANIMATION_TICK_MS)
        self._animation_timer.timeout.connect(self._animate_step)

    def configure(self, controller: "TabWorkspaceController", owner_window: WorkspaceWindow) -> None:
        self._controller = controller
        self._owner_window = owner_window
        self.request_layout_sync()

    def request_layout_sync(self) -> None:
        self._layout_dirty = True
        self.update()

    def strip_drop_rect_global(self) -> QRect:
        top_left = self.mapToGlobal(QPoint(0, 0))
        origin = top_left - QPoint(DROP_TARGET_SIDE_SLOP_PX, DROP_TARGET_TOP_SLOP_PX)
        width = int(self.width()) + (2 * DROP_TARGET_SIDE_SLOP_PX)
        height = int(self.height()) + DROP_TARGET_TOP_SLOP_PX + DROP_TARGET_BOTTOM_SLOP_PX
        return QRect(origin, QSize(max(1, width), max(1, height)))

    def tab_rect_for_index(self, index: int) -> QRect:
        self._sync_layouts()
        tab_id = self._host.tab_id_for_index(index)
        if tab_id is None:
            return QRect()
        layout = self._target_layouts.get(int(tab_id))
        return QRect(layout.outer) if layout is not None else QRect()

    def tab_layout_for_index(self, index: int) -> Optional[_StripTabLayout]:
        self._sync_layouts()
        tab_id = self._host.tab_id_for_index(index)
        if tab_id is None:
            return None
        layout = self._target_layouts.get(int(tab_id))
        if layout is None:
            return None
        return _StripTabLayout(QRect(layout.outer), QRect(layout.name_rect), QRect(layout.close_rect))

    def active_line_visible_for_index(self, index: int) -> bool:
        tab_id = self._host.tab_id_for_index(index)
        if tab_id is None:
            return False
        current = self._host.currentIndex()
        current_id = self._host.tab_id_for_index(current)
        return current_id is not None and int(current_id) == int(tab_id)

    def visual_left(self, tab_id: int) -> Optional[float]:
        value = self._display_left_by_id.get(int(tab_id))
        return float(value) if value is not None else None

    def target_left(self, tab_id: int) -> Optional[int]:
        self._sync_layouts()
        layout = self._target_layouts.get(int(tab_id))
        if layout is None:
            return None
        return int(layout.outer.x())

    def last_paint_order(self) -> List[int]:
        return list(self._last_paint_order)

    def is_dragged_tab_background_visible(self) -> bool:
        return False

    def is_tab_background_visible(self, tab_id: int) -> bool:
        _ = tab_id
        return False

    def current_drag_left(self, tab_id: int) -> Optional[int]:
        if self._drag_tab_id is None or int(self._drag_tab_id) != int(tab_id):
            return None
        self._sync_layouts()
        layout = self._target_layouts.get(int(tab_id))
        if layout is None:
            return None
        left = int(self.mapFromGlobal(self._drag_global_pos).x() - self._drag_hot_x)
        width = int(layout.outer.width())
        return max(-width + 12, min(left, max(12, self.width() - 12)))

    def set_drag_preview(self, tab_id: int, global_pos: QPoint, *, hot_x: int) -> None:
        self._drag_tab_id = int(tab_id)
        self._drag_global_pos = QPoint(global_pos)
        self._drag_hot_x = int(max(1, hot_x))
        self.update()

    def clear_drag_preview(self, tab_id: Optional[int] = None, *, settle: bool) -> None:
        if tab_id is not None and self._drag_tab_id is not None and int(tab_id) != int(self._drag_tab_id):
            return
        if self._pointer_dragging and self._press_tab_id is not None:
            self._suppress_release_activation = True
        self._sync_layouts()
        if self._drag_tab_id is not None and settle:
            drag_id = int(self._drag_tab_id)
            layout = self._target_layouts.get(drag_id)
            if layout is not None:
                current_left = int(self.mapFromGlobal(self._drag_global_pos).x() - self._drag_hot_x)
                width = int(layout.outer.width())
                current_left = max(-width + 12, min(current_left, max(12, self.width() - 12)))
                self._display_left_by_id[drag_id] = float(current_left)
        if self._drag_tab_id is not None and settle:
            self._settle_pending.add(int(self._drag_tab_id))
        self._drag_tab_id = None
        self._drag_hot_x = 0
        self._drag_global_pos = QPoint()
        self._drag_draws_background = False
        self._pointer_dragging = False
        self._ensure_animation_timer()
        self.update()

    def insertion_index_for_global_pos(
        self,
        global_pos: QPoint,
        *,
        ignore_home: bool,
        dragged_tab_id: Optional[int],
    ) -> int:
        self._sync_layouts()
        local_x = int(self.mapFromGlobal(global_pos).x())
        movable: List[Tuple[int, _StripTabLayout]] = []
        for index in range(self._host.count()):
            tab_id = self._host.tab_id_for_index(index)
            if tab_id is None:
                continue
            if dragged_tab_id is not None and int(tab_id) == int(dragged_tab_id):
                continue
            entry = self._host.entry_for_tab_id(int(tab_id))
            layout = self._target_layouts.get(int(tab_id))
            if entry is None or layout is None:
                continue
            if ignore_home and entry.pinned:
                continue
            movable.append((int(tab_id), layout))

        if not movable:
            return self._host.count()

        for tab_id, layout in movable:
            mid = int(layout.outer.x() + (layout.outer.width() / 2))
            if local_x < mid:
                target = self._host.index_for_tab_id(tab_id)
                return max(self._host._first_movable_index(), max(0, target))
        return self._host.count()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        _ = event
        self._sync_layouts()
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(13, 17, 23, 0))

        draw_order: List[int] = []
        drag_id = self._drag_tab_id
        for tab_id in self._ordered_tab_ids:
            if drag_id is not None and int(tab_id) == int(drag_id):
                continue
            self._draw_single_tab(painter, int(tab_id), dragged=False)
            draw_order.append(int(tab_id))

        if drag_id is not None and drag_id in self._ordered_tab_ids:
            self._draw_single_tab(painter, int(drag_id), dragged=True)
            draw_order.append(int(drag_id))
        self._last_paint_order = draw_order

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        tab_id, on_close = self._hit_test(event.position().toPoint())
        self._press_tab_id = tab_id
        self._press_on_close = on_close
        self._suppress_release_activation = False
        self._press_pos = self._event_global_pos(event)
        self._pointer_dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        local_pos = event.position().toPoint()
        tab_id, _ = self._hit_test(local_pos)
        if tab_id != self._hover_tab_id:
            self._hover_tab_id = tab_id
            self.update()

        if self._press_tab_id is None:
            return super().mouseMoveEvent(event)

        global_pos = self._event_global_pos(event)
        if not self._pointer_dragging:
            distance = (global_pos - self._press_pos).manhattanLength()
            threshold = max(4, int(QApplication.startDragDistance()))
            if distance < threshold:
                return super().mouseMoveEvent(event)
            if self._host.is_tab_pinned(int(self._press_tab_id)):
                self._press_tab_id = None
                self._press_on_close = False
                return super().mouseMoveEvent(event)
            if self._controller is None or self._owner_window is None:
                return super().mouseMoveEvent(event)
            widget = self._host.entry_for_tab_id(int(self._press_tab_id))
            if widget is None:
                return super().mouseMoveEvent(event)
            tab_layout = self._target_layouts.get(int(self._press_tab_id))
            if tab_layout is None:
                return super().mouseMoveEvent(event)
            local_hot_x = int(max(1, min(local_pos.x() - tab_layout.outer.x(), tab_layout.outer.width() - 1)))
            started = self._controller.start_tab_drag(
                self._owner_window,
                widget.widget,
                global_pos,
                hot_x=local_hot_x,
                cursor_polling=True,
            )
            self._pointer_dragging = bool(started)
            if not started:
                self._press_tab_id = None
                self._press_on_close = False
        else:
            if self._controller is not None:
                self._controller.update_tab_drag(global_pos)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        global_pos = self._event_global_pos(event)
        if self._pointer_dragging:
            if self._controller is not None:
                self._controller.finish_tab_drag(global_pos)
            self._pointer_dragging = False
            self._press_tab_id = None
            self._press_on_close = False
            self._suppress_release_activation = False
            return super().mouseReleaseEvent(event)

        if self._suppress_release_activation:
            self._press_tab_id = None
            self._press_on_close = False
            self._suppress_release_activation = False
            return super().mouseReleaseEvent(event)

        released_tab_id, released_on_close = self._hit_test(event.position().toPoint())
        if self._press_tab_id is not None and self._press_on_close and released_on_close:
            if released_tab_id is not None and int(released_tab_id) == int(self._press_tab_id):
                self.tabCloseRequested.emit(int(self._press_tab_id))
        elif self._press_tab_id is not None:
            if released_tab_id is not None and int(released_tab_id) == int(self._press_tab_id):
                self.tabActivated.emit(int(self._press_tab_id))
        self._press_tab_id = None
        self._press_on_close = False
        self._suppress_release_activation = False
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        _ = event
        self._hover_tab_id = None
        self.update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.request_layout_sync()

    def _event_global_pos(self, event: QMouseEvent) -> QPoint:
        global_position = getattr(event, "globalPosition", None)
        if callable(global_position):
            return global_position().toPoint()
        global_pos = getattr(event, "globalPos", None)
        if callable(global_pos):
            return global_pos()
        return QPoint(QCursor.pos())

    def _sync_layouts(self) -> None:
        if not self._layout_dirty:
            return
        self._layout_dirty = False
        self._ordered_tab_ids = []
        self._target_layouts = {}
        x = 0
        fm = self.fontMetrics()
        for index in range(self._host.count()):
            tab_id = self._host.tab_id_for_index(index)
            entry = self._host.entry_for_tab_id(int(tab_id)) if tab_id is not None else None
            if tab_id is None or entry is None:
                continue
            width = compute_workspace_tab_width(fm, entry.title, closable=entry.closable)
            rect = QRect(x, 0, width, TAB_STRIP_HEIGHT)
            name_rect = compute_workspace_tab_name_rect(rect, closable=entry.closable)
            close_rect = compute_workspace_tab_close_rect(rect) if entry.closable else QRect()
            self._ordered_tab_ids.append(int(tab_id))
            self._target_layouts[int(tab_id)] = _StripTabLayout(rect, name_rect, close_rect)
            if int(tab_id) not in self._display_left_by_id:
                self._display_left_by_id[int(tab_id)] = float(rect.x())
            x += width

        alive = set(self._ordered_tab_ids)
        for stale_id in list(self._display_left_by_id.keys()):
            if stale_id not in alive:
                self._display_left_by_id.pop(stale_id, None)
        self._ensure_animation_timer()

    def _ensure_animation_timer(self) -> None:
        self._sync_layouts_if_needed_no_reentry()
        moving = False
        for tab_id in self._ordered_tab_ids:
            target = self._target_layouts.get(tab_id)
            if target is None:
                continue
            current_left = self._display_left_by_id.get(tab_id, float(target.outer.x()))
            if abs(float(target.outer.x()) - float(current_left)) > ANIMATION_SETTLE_EPSILON:
                moving = True
                break
        if self._settle_pending:
            moving = True
        if moving:
            if not self._animation_timer.isActive():
                self._animation_timer.start()
        else:
            if self._animation_timer.isActive():
                self._animation_timer.stop()

    def _sync_layouts_if_needed_no_reentry(self) -> None:
        if self._layout_dirty:
            self._sync_layouts()

    def _is_tab_still_settling(self, tab_id: int) -> bool:
        if int(tab_id) not in self._settle_pending:
            return False
        target = self._target_layouts.get(int(tab_id))
        if target is None:
            return False
        current_left = float(self._display_left_by_id.get(int(tab_id), float(target.outer.x())))
        return abs(float(target.outer.x()) - current_left) > ANIMATION_VISIBLE_SETTLE_EPSILON

    def _is_tab_transparent_shell(self, tab_id: int) -> bool:
        if self._drag_tab_id is not None and int(self._drag_tab_id) == int(tab_id):
            return True
        return self._is_tab_still_settling(int(tab_id))

    def _animate_step(self) -> None:
        self._sync_layouts()
        changed = False
        for tab_id in self._ordered_tab_ids:
            if self._drag_tab_id is not None and int(tab_id) == int(self._drag_tab_id):
                continue
            target = self._target_layouts.get(tab_id)
            if target is None:
                continue
            current_left = float(self._display_left_by_id.get(tab_id, float(target.outer.x())))
            goal = float(target.outer.x())
            delta = goal - current_left
            if abs(delta) <= ANIMATION_SETTLE_EPSILON:
                if current_left != goal:
                    self._display_left_by_id[tab_id] = goal
                    changed = True
                self._settle_pending.discard(tab_id)
                continue
            next_left = current_left + (delta * ANIMATION_BLEND)
            self._display_left_by_id[tab_id] = next_left
            changed = True
        if changed:
            self.update()
        self._ensure_animation_timer()

    def _draw_single_tab(self, painter: QPainter, tab_id: int, *, dragged: bool) -> None:
        entry = self._host.entry_for_tab_id(tab_id)
        layout = self._target_layouts.get(tab_id)
        if entry is None or layout is None:
            return
        if dragged:
            left = int(self.mapFromGlobal(self._drag_global_pos).x() - self._drag_hot_x)
            width = int(layout.outer.width())
            left = max(-width + 12, min(left, max(12, self.width() - 12)))
            self._drag_draws_background = False
        else:
            left = int(round(self._display_left_by_id.get(tab_id, float(layout.outer.x()))))
            self._display_left_by_id[tab_id] = float(left)
        rect = QRect(left, int(layout.outer.y()), int(layout.outer.width()), int(layout.outer.height()))
        name_rect = compute_workspace_tab_name_rect(rect, closable=entry.closable)
        close_rect = compute_workspace_tab_close_rect(rect) if entry.closable else QRect()

        is_active = (self._host.tab_id_for_index(self._host.currentIndex()) == tab_id)
        is_hover = (self._hover_tab_id == tab_id) and not dragged and self._drag_tab_id is None

        text_color = QColor(139, 148, 158)
        if is_active:
            text_color = QColor(224, 232, 241)
        elif is_hover:
            text_color = QColor(212, 220, 227)
        painter.setPen(text_color)
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignCenter,
            painter.fontMetrics().elidedText(entry.title, Qt.TextElideMode.ElideRight, name_rect.width()),
        )

        if entry.closable and not close_rect.isNull():
            painter.setPen(QColor(189, 198, 207))
            painter.drawText(close_rect, Qt.AlignmentFlag.AlignCenter, "x")

        if is_active:
            line_rect = QRect(rect.x(), rect.bottom() - TAB_ACTIVE_LINE_HEIGHT + 1, rect.width(), TAB_ACTIVE_LINE_HEIGHT)
            painter.fillRect(line_rect, QColor(88, 166, 255))

    def _hit_test(self, pos: QPoint) -> Tuple[Optional[int], bool]:
        self._sync_layouts()
        for tab_id in reversed(self._ordered_tab_ids):
            layout = self._target_layouts.get(tab_id)
            entry = self._host.entry_for_tab_id(tab_id)
            if layout is None or entry is None:
                continue
            left = int(round(self._display_left_by_id.get(tab_id, float(layout.outer.x()))))
            rect = QRect(left, layout.outer.y(), layout.outer.width(), layout.outer.height())
            if not rect.contains(pos):
                continue
            if entry.closable:
                close_rect = compute_workspace_tab_close_rect(rect)
                if close_rect.contains(pos):
                    return int(tab_id), True
            return int(tab_id), False
        return None, False


class TabWorkspaceController(QObject):
    _EXTERNAL_DRAG_CURSOR_POLL_MS = 16

    def __init__(self) -> None:
        super().__init__()
        self.tab_by_key: Dict[str, QWidget] = {}
        self.key_by_widget: Dict[QWidget, str] = {}
        self.title_by_widget: Dict[QWidget, str] = {}
        self.window_by_widget: Dict[QWidget, WorkspaceWindow] = {}
        self.registered_windows: List[WorkspaceWindow] = []
        self.loading_keys: set[str] = set()
        self.is_shutting_down: bool = False
        self._primary_window: Optional[WorkspaceWindow] = None
        self._home_widget: Optional[QWidget] = None
        self._detached_window_factory: Optional[Callable[[], WorkspaceWindow]] = None

        self._drag_session: Optional[_DragSession] = None
        self._drag_filter_installed = False
        self._drag_cursor_poll_timer: Optional[QTimer] = None
        self._drag_cursor_poll_last_pos: Optional[QPoint] = None

        self._debug_log_path = Path(__file__).resolve().parents[1] / "debug" / "tab_workspace.log"

    def set_detached_window_factory(self, factory: Callable[[], WorkspaceWindow]) -> None:
        self._detached_window_factory = factory

    def set_home_widget(self, widget: QWidget) -> None:
        self._home_widget = widget

    def register_window(self, window: WorkspaceWindow, *, primary: bool = False) -> None:
        if window not in self.registered_windows:
            self.registered_windows.append(window)
        if primary:
            self._primary_window = window
        setattr(window, "_tab_by_key", self.tab_by_key)
        host = window.workspace_host()
        host.configure(self, window)
        host.tabCloseRequested.connect(lambda index: self.close_tab_by_index(window, index))

    def unregister_window(self, window: WorkspaceWindow) -> None:
        if window in self.registered_windows:
            self.registered_windows.remove(window)
        if self._primary_window is window:
            self._primary_window = None

    def sync_tab_bar_extent(self, window: WorkspaceWindow) -> None:
        _ = window

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
                primary.workspace_host().setCurrentIndex(0)
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
            self._debug_log("open_applet_skip_loading", key=key)
            return
        self.loading_keys.add(key)
        self._debug_log("open_applet_begin", key=key)

        widget: Optional[QWidget] = None
        try:
            window.begin_applet_load(key, str(applet.get("title", "applet")))
            widget = window.build_applet_widget(key, applet)
            if widget is None:
                self._debug_log("open_applet_builder_empty", key=key)
                return
            title = str(applet.get("tab", applet.get("title", key)))
            self._register_widget(key, widget, window, title)
            host = window.workspace_host()
            index = host.addTab(
                widget,
                title,
                closable=not self.is_home_widget(widget),
                pinned=self.is_home_widget(widget),
            )
            if focus_if_new:
                host.setCurrentIndex(index)
            self._debug_log("open_applet_ready", key=key)
        finally:
            self.loading_keys.discard(key)
            window.end_applet_load(key)
            self._debug_log("open_applet_end", key=key, opened=widget is not None)

    def focus_widget(self, window: WorkspaceWindow, widget: QWidget) -> None:
        host = window.workspace_host()
        index = host.indexOf(widget)
        if index == -1:
            return
        host.setCurrentIndex(index)
        if hasattr(window, "show"):
            window.show()
        if hasattr(window, "raise_"):
            window.raise_()
        if hasattr(window, "activateWindow"):
            window.activateWindow()

    def close_tab_by_index(self, window: WorkspaceWindow, index: int, *, auto_close_window: bool = True) -> bool:
        host = window.workspace_host()
        if index < 0 or index >= host.count():
            return False
        widget = host.widget(index)
        if widget is None or self.is_home_widget(widget):
            return False
        try:
            closed = bool(widget.close())
        except RuntimeError:
            closed = True
        if not closed:
            self._debug_log("close_tab_veto", key=str(self.key_by_widget.get(widget, "")))
            return False

        key = self.key_by_widget.pop(widget, None)
        if key:
            self.tab_by_key.pop(key, None)
        self.title_by_widget.pop(widget, None)
        self.window_by_widget.pop(widget, None)
        host.removeTab(index)
        self._debug_log("close_tab", key=str(key or ""))
        try:
            widget.deleteLater()
        except RuntimeError:
            pass
        if auto_close_window and not window.is_primary_window() and host.count() == 0 and hasattr(window, "close"):
            window.close()
        return True

    def close_all_tabs_in_window(self, window: WorkspaceWindow) -> None:
        host = window.workspace_host()
        while host.count() > 0:
            closed_any = False
            for index in range(host.count() - 1, -1, -1):
                widget = host.widget(index)
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
        source_host = source_window.workspace_host()
        source_index = source_host.indexOf(widget)
        if source_index == -1:
            return False

        if source_window is target_window:
            moved = source_host.move_tab(source_index, target_index)
            if focus:
                source_host.setCurrentWidget(widget)
            return moved or source_index == max(0, min(target_index, source_host.count() - 1))

        target_host = target_window.workspace_host()
        source_current_before = source_host.currentWidget()
        target_current_before = target_host.currentWidget()

        item = source_host.take_tab(source_index)
        if item is None:
            return False
        insert_at = max(0, min(int(target_index), target_host.count()))
        target_host.insert_existing_tab(insert_at, item, preserve_current=True)
        self.window_by_widget[widget] = target_window

        self._restore_previous_active(source_host, source_current_before)
        self._restore_previous_active(target_host, target_current_before)

        if focus:
            target_host.setCurrentWidget(widget)
            self.focus_widget(target_window, widget)

        if (
            auto_close_source_if_empty
            and not source_window.is_primary_window()
            and source_host.count() == 0
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

        moved = self.move_widget_to_window(widget, new_window, target_index=0, focus=True)
        if not moved:
            if hasattr(new_window, "close"):
                new_window.close()
            return None

        if hot_spot is not None:
            host = new_window.workspace_host()
            index = host.indexOf(widget)
            strip = host.tabBar()
            rect = strip.tab_rect_for_index(index)
            if rect.width() > 0 and rect.height() > 0:
                clamped = QPoint(
                    max(1, min(int(hot_spot.x()), max(1, rect.width() - 1))),
                    max(1, min(int(hot_spot.y()), max(1, rect.height() - 1))),
                )
                actual_global = strip.mapToGlobal(rect.topLeft() + clamped)
                dx = int(global_pos.x() - actual_global.x())
                dy = int(global_pos.y() - actual_global.y())
                if (dx != 0 or dy != 0) and hasattr(new_window, "move"):
                    new_window.move(new_window.x() + dx, new_window.y() + dy)

        self._debug_log("detach_widget", key=str(self.key_by_widget.get(widget, "")))
        return new_window

    def begin_primary_shutdown(self, primary_window: WorkspaceWindow) -> bool:
        if self.is_shutting_down:
            return True
        if self._drag_session is not None:
            self.finish_tab_drag(QCursor.pos(), detach_on_invalid_drop=False)
        self.is_shutting_down = True
        for window in list(self.registered_windows):
            if window is primary_window:
                continue
            if hasattr(window, "close"):
                closed = bool(window.close())
                if not closed or window in self.registered_windows:
                    self.is_shutting_down = False
                    return False
        return True

    def prepare_window_close(self, window: WorkspaceWindow) -> bool:
        session = self._drag_session
        if session is not None:
            owner = self.window_by_widget.get(session.widget)
            if owner is window:
                self.finish_tab_drag(QCursor.pos(), detach_on_invalid_drop=False)
        host = window.workspace_host()
        for index in range(host.count() - 1, -1, -1):
            widget = host.widget(index)
            if widget is None or self.is_home_widget(widget):
                continue
            if not self.close_tab_by_index(window, index, auto_close_window=False):
                return False
        return True

    def start_tab_drag(
        self,
        source_window: WorkspaceWindow,
        widget: QWidget,
        global_pos: QPoint,
        *,
        hot_x: int,
        cursor_polling: bool = False,
    ) -> bool:
        if self._drag_session is not None:
            return False
        if not self.can_detach_widget(widget):
            return False
        source_host = source_window.workspace_host()
        source_index = source_host.indexOf(widget)
        if source_index < 0:
            return False
        tab_id = source_host.tab_id_for_index(source_index)
        if tab_id is None:
            return False
        title = source_host.tabText(source_index)
        source_current = source_host.currentWidget()
        self._drag_session = _DragSession(
            widget=widget,
            tab_id=int(tab_id),
            title=str(title or ""),
            source_window=source_window,
            current_window=source_window,
            hot_x=int(max(1, hot_x)),
            previous_active_by_window={source_window: source_current},
            cursor_polling=bool(cursor_polling),
        )
        source_host.tabBar().set_drag_preview(int(tab_id), QPoint(global_pos), hot_x=int(max(1, hot_x)))
        self._ensure_drag_event_filter()
        self._set_drag_cursor_polling(bool(self._drag_session.cursor_polling))
        self.update_tab_drag(global_pos)
        return True

    # Backwards-compatible naming kept for call sites/tests.
    def start_external_tab_drag(
        self,
        source_window: WorkspaceWindow,
        widget: QWidget,
        global_pos: QPoint,
        *,
        hot_spot: Optional[QPoint] = None,
    ) -> bool:
        hot_x = int(hot_spot.x()) if hot_spot is not None else 12
        return self.start_tab_drag(
            source_window,
            widget,
            global_pos,
            hot_x=hot_x,
            cursor_polling=False,
        )

    def update_external_tab_drag(self, global_pos: QPoint) -> None:
        self.update_tab_drag(global_pos)

    def finish_external_tab_drag(self, global_pos: QPoint, *, detach_on_invalid_drop: bool = True) -> bool:
        return self.finish_tab_drag(global_pos, detach_on_invalid_drop=detach_on_invalid_drop)

    def update_tab_drag(self, global_pos: QPoint) -> None:
        session = self._drag_session
        if session is None:
            return
        target_window = self._tab_window_from_global_pos(global_pos)
        if target_window is None:
            self._detach_for_floating_drag(session)
            self._show_floating_preview(session, global_pos)
            self._clear_strip_drag_preview(except_window=None, settle=False)
            return

        self._hide_floating_preview(session)
        target_host = target_window.workspace_host()
        target_strip = target_host.tabBar()
        if target_window not in session.previous_active_by_window:
            session.previous_active_by_window[target_window] = target_host.currentWidget()

        if session.current_window is None:
            if session.floating_item is None:
                session.floating_item = WorkspaceTabItem(
                    tab_id=int(session.tab_id),
                    widget=session.widget,
                    title=self.title_by_widget.get(session.widget, session.title),
                    closable=True,
                    pinned=False,
                )
            insert_at = target_strip.insertion_index_for_global_pos(
                global_pos,
                ignore_home=True,
                dragged_tab_id=None,
            )
            target_before = target_host.currentWidget()
            target_host.insert_existing_tab(insert_at, session.floating_item, preserve_current=True)
            self.window_by_widget[session.widget] = target_window
            session.current_window = target_window
            session.floating_item = None
            self._restore_previous_active(target_host, target_before)
        elif session.current_window is not target_window:
            self.move_widget_to_window(
                session.widget,
                target_window,
                target_index=target_host.count(),
                focus=False,
                auto_close_source_if_empty=True,
            )
            session.current_window = self.window_by_widget.get(session.widget)

        owner = self.window_by_widget.get(session.widget)
        if owner is None:
            self._detach_for_floating_drag(session)
            self._show_floating_preview(session, global_pos)
            return

        owner_host = owner.workspace_host()
        owner_strip = owner_host.tabBar()
        tab_id = owner_host.tab_id_for_widget(session.widget)
        if tab_id is None:
            return
        target_index = owner_strip.insertion_index_for_global_pos(
            global_pos,
            ignore_home=True,
            dragged_tab_id=int(tab_id),
        )
        owner_host.move_tab_by_id(int(tab_id), target_index)
        owner_strip.set_drag_preview(int(tab_id), QPoint(global_pos), hot_x=int(session.hot_x))
        session.current_window = owner
        self._clear_strip_drag_preview(except_window=owner, settle=False)
        self._restore_drag_window_active(session, owner)

    def finish_tab_drag(self, global_pos: QPoint, *, detach_on_invalid_drop: bool = True) -> bool:
        session = self._drag_session
        if session is None:
            return False
        self.update_tab_drag(global_pos)
        moved = False
        if session.current_window is None and detach_on_invalid_drop:
            detached = self._materialize_floating_drag_in_new_window(session, global_pos)
            if detached is None:
                detached = self.detach_widget_to_new_window(
                    session.widget,
                    global_pos,
                    hot_spot=QPoint(int(session.hot_x), max(1, TAB_STRIP_HEIGHT // 2)),
                )
            moved = detached is not None
        else:
            moved = self.window_by_widget.get(session.widget) is not None

        current_owner = self.window_by_widget.get(session.widget)
        self._clear_strip_drag_preview(except_window=current_owner, settle=True)
        if current_owner is not None:
            owner_host = current_owner.workspace_host()
            tab_id = owner_host.tab_id_for_widget(session.widget)
            if tab_id is not None:
                owner_host.tabBar().clear_drag_preview(int(tab_id), settle=True)
        self._hide_floating_preview(session)
        self._destroy_floating_preview(session)
        self._set_drag_cursor_polling(False)
        self._remove_drag_event_filter()
        self._drag_session = None
        return moved

    def _materialize_floating_drag_in_new_window(
        self,
        session: _DragSession,
        global_pos: QPoint,
    ) -> Optional[WorkspaceWindow]:
        if self._detached_window_factory is None:
            return None
        item = session.floating_item
        if item is None:
            return None
        new_window = self._detached_window_factory()
        if hasattr(new_window, "resize"):
            new_window.resize(1200, 700)
        if hasattr(new_window, "move"):
            new_window.move(global_pos.x(), global_pos.y())
        if hasattr(new_window, "show"):
            new_window.show()

        host = new_window.workspace_host()
        host.insert_existing_tab(0, item, preserve_current=True)
        self.window_by_widget[session.widget] = new_window
        session.current_window = new_window
        session.floating_item = None

        index = host.indexOf(session.widget)
        strip = host.tabBar()
        rect = strip.tab_rect_for_index(index)
        if rect.width() > 0 and rect.height() > 0 and hasattr(new_window, "move"):
            clamped = QPoint(
                max(1, min(int(session.hot_x), max(1, rect.width() - 1))),
                max(1, min(TAB_STRIP_HEIGHT // 2, max(1, rect.height() - 1))),
            )
            actual_global = strip.mapToGlobal(rect.topLeft() + clamped)
            dx = int(global_pos.x() - actual_global.x())
            dy = int(global_pos.y() - actual_global.y())
            if dx != 0 or dy != 0:
                new_window.move(new_window.x() + dx, new_window.y() + dy)
        return new_window

    def active_drag_window(self) -> Optional[WorkspaceWindow]:
        session = self._drag_session
        if session is None:
            return None
        return session.current_window

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        _ = watched
        session = self._drag_session
        if session is None:
            return False
        event_type = event.type()
        if event_type == QEvent.Type.MouseMove:
            buttons = getattr(event, "buttons", lambda: Qt.MouseButton.NoButton)()
            global_pos = self._event_global_pos(event) or QCursor.pos()
            if not (buttons & Qt.MouseButton.LeftButton):
                self.finish_tab_drag(global_pos)
            else:
                self.update_tab_drag(global_pos)
            return False
        if event_type == QEvent.Type.MouseButtonRelease:
            button = getattr(event, "button", lambda: Qt.MouseButton.NoButton)()
            if button == Qt.MouseButton.LeftButton:
                global_pos = self._event_global_pos(event) or QCursor.pos()
                self.finish_tab_drag(global_pos)
            return False
        return False

    def _event_global_pos(self, event: QEvent) -> Optional[QPoint]:
        global_position = getattr(event, "globalPosition", None)
        if callable(global_position):
            return global_position().toPoint()
        global_pos = getattr(event, "globalPos", None)
        if callable(global_pos):
            return global_pos()
        return None

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

    def _set_drag_cursor_polling(self, enabled: bool) -> None:
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
            timer.timeout.connect(self._poll_drag_cursor)
            self._drag_cursor_poll_timer = timer
        self._drag_cursor_poll_last_pos = None
        if not timer.isActive():
            timer.start()

    def _poll_drag_cursor(self) -> None:
        session = self._drag_session
        if session is None or not session.cursor_polling:
            self._set_drag_cursor_polling(False)
            return
        pos = QPoint(QCursor.pos())
        if self._drag_cursor_poll_last_pos is not None and pos == self._drag_cursor_poll_last_pos:
            if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                self.finish_tab_drag(pos)
            return
        self._drag_cursor_poll_last_pos = QPoint(pos)
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            self.finish_tab_drag(pos)
            return
        self.update_tab_drag(pos)

    def _tab_window_from_global_pos(self, global_pos: QPoint) -> Optional[WorkspaceWindow]:
        candidates: List[Tuple[WorkspaceWindow, float]] = []
        for window in list(self.registered_windows):
            if hasattr(window, "isVisible") and not bool(window.isVisible()):
                continue
            host = window.workspace_host()
            if host.count() <= 0:
                continue
            strip = host.tabBar()
            if not strip.isVisible():
                continue
            rect = strip.strip_drop_rect_global()
            if not rect.contains(global_pos):
                continue
            center = rect.center()
            distance = float((center.x() - global_pos.x()) ** 2 + (center.y() - global_pos.y()) ** 2)
            candidates.append((window, distance))
        if not candidates:
            return None
        active_candidates = [item for item in candidates if hasattr(item[0], "isActiveWindow") and item[0].isActiveWindow()]
        if active_candidates:
            active_candidates.sort(key=lambda item: item[1])
            return active_candidates[0][0]
        candidates.sort(key=lambda item: item[1])
        return candidates[0][0]

    def _detach_for_floating_drag(self, session: _DragSession) -> None:
        if session.current_window is None:
            return
        owner = self.window_by_widget.get(session.widget)
        if owner is None:
            session.current_window = None
            return
        host = owner.workspace_host()
        index = host.indexOf(session.widget)
        if index == -1:
            self.window_by_widget.pop(session.widget, None)
            session.current_window = None
            return
        if session.floating_item is None:
            session.floating_item = host.take_tab(index)
        else:
            host.take_tab(index)
        self.window_by_widget.pop(session.widget, None)
        session.current_window = None
        if (
            owner is not None
            and not owner.is_primary_window()
            and host.count() == 0
            and hasattr(owner, "close")
        ):
            owner.close()

    def _show_floating_preview(self, session: _DragSession, global_pos: QPoint) -> None:
        preview = session.floating_preview
        if preview is None:
            size = QSize(140, TAB_STRIP_HEIGHT)
            if session.floating_item is not None:
                size = QSize(
                    max(120, int(session.title and 96 or 96)),
                    TAB_STRIP_HEIGHT,
                )
            preview = _FloatingTabPreview(session.title, size)
            session.floating_preview = preview
        top_left = QPoint(global_pos.x() - int(session.hot_x), global_pos.y() - (TAB_STRIP_HEIGHT // 2))
        preview.move(top_left.x(), top_left.y())
        if not preview.isVisible():
            preview.show()
        preview.raise_()

    def _hide_floating_preview(self, session: _DragSession) -> None:
        preview = session.floating_preview
        if preview is None:
            return
        preview.hide()

    def _destroy_floating_preview(self, session: _DragSession) -> None:
        preview = session.floating_preview
        if preview is None:
            return
        preview.hide()
        preview.deleteLater()
        session.floating_preview = None

    def _clear_strip_drag_preview(
        self,
        *,
        except_window: Optional[WorkspaceWindow],
        settle: bool,
    ) -> None:
        for window in list(self.registered_windows):
            if except_window is not None and window is except_window:
                continue
            host = window.workspace_host()
            host.tabBar().clear_drag_preview(None, settle=settle)

    def _restore_previous_active(self, host: WorkspaceTabsHost, widget: Optional[QWidget]) -> None:
        if widget is None:
            return
        if host.indexOf(widget) == -1:
            return
        host.setCurrentWidget(widget)

    def _restore_drag_window_active(self, session: _DragSession, window: WorkspaceWindow) -> None:
        wanted = session.previous_active_by_window.get(window)
        if wanted is None:
            return
        host = window.workspace_host()
        if host.indexOf(wanted) == -1:
            return
        host.setCurrentWidget(wanted)

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

    def _debug_log(self, event: str, **fields: object) -> None:
        if os.environ.get("DMT_TEST_MODE", "").strip() != "1":
            return
        payload = {"event": str(event)}
        for key in sorted(fields):
            payload[key] = str(fields[key])
        line = " ".join(f"{k}={payload[k]}" for k in sorted(payload))
        self._debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._debug_log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
