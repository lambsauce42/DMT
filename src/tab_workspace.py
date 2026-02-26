from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol, Set

from PySide6.QtCore import QEvent, QEventLoop, QObject, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QApplication, QTabBar, QTabWidget, QWidget


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

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._press_index = self.tabAt(self._press_pos)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self._press_index = -1
        self._press_pos = QPoint()
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._press_index < 0 or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        current_pos = event.position().toPoint()
        distance = (current_pos - self._press_pos).manhattanLength()
        threshold = max(3, min(int(QApplication.startDragDistance()), 4))
        if distance < threshold:
            super().mouseMoveEvent(event)
            return
        vertical_pull = 0
        if current_pos.y() < 0:
            vertical_pull = -current_pos.y()
        elif current_pos.y() > self.height():
            vertical_pull = current_pos.y() - self.height()
        if vertical_pull < 24:
            super().mouseMoveEvent(event)
            return
        widget = self._tab_widget.widget(self._press_index)
        if widget is None or not self._controller.can_detach_widget(widget):
            super().mouseMoveEvent(event)
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
        self._press_index = -1
        self._press_pos = QPoint()
        if started:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _insertion_index_from_pos(self, pos: QPoint) -> int:
        if self.count() <= 0:
            return 0
        x = pos.x()
        for index in range(self.count()):
            rect = self.tabRect(index)
            if x < rect.center().x():
                return index
        return self.count()

    def owner_window(self) -> WorkspaceWindow:
        return self._owner_window

    def show_external_drop_indicator(self, global_pos: QPoint, title: str) -> None:
        _ = (global_pos, title)

    def hide_external_drop_indicator(self) -> None:
        return

    def insertion_index_for_global_pos(self, global_pos: QPoint) -> int:
        return self._insertion_index_from_pos(self.mapFromGlobal(global_pos))


class TabWorkspaceController(QObject):
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
        self._detached_window_factory: Optional[Callable[[], WorkspaceWindow]] = None
        self._debug_log_path = Path(__file__).resolve().parents[1] / "debug" / "tab_workspace.log"

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
        key = self.key_by_widget.pop(widget, None)
        if key:
            self.tab_by_key.pop(key, None)
        self.title_by_widget.pop(widget, None)
        self.window_by_widget.pop(widget, None)
        title = tabs.tabText(index)
        tabs.removeTab(index)
        self.sync_tab_bar_extent(window)
        self._debug_log("close_tab", key=str(key or ""), title=title)
        try:
            widget.close()
        finally:
            widget.deleteLater()
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
                self.close_tab_by_index(window, index, auto_close_window=False)
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

    def detach_widget_to_new_window(self, widget: QWidget, global_pos: QPoint) -> Optional[WorkspaceWindow]:
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
        title = source_tabs.tabText(source_index) if source_index != -1 else self.title_by_widget.get(widget, "")
        tab_rect = source_tabs.tabBar().tabRect(source_index)
        ghost = _FloatingTabGhost(str(title or ""), tab_rect.size())
        centered_hot_spot = QPoint(max(1, ghost.width() // 2), max(1, ghost.height() // 2))
        self._external_drag = _ExternalTabDragState(
            widget=widget,
            title=str(title or ""),
            source_window=source_window,
            current_host_window=source_window,
            hot_spot=centered_hot_spot,
            ghost=ghost,
        )
        QApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)
        self._ensure_drag_event_filter()
        self.update_external_tab_drag(global_pos)
        self._debug_log("drag_begin", key=str(self.key_by_widget.get(widget, "")))
        return True

    def update_external_tab_drag(self, global_pos: QPoint) -> None:
        state = self._external_drag
        if state is None:
            return
        target_bar = self._tab_bar_from_global_pos(global_pos)
        if target_bar is not None:
            target_window = target_bar.owner_window()
            target_index = target_bar.insertion_index_for_global_pos(global_pos)
            self.move_widget_to_window(
                state.widget,
                target_window,
                target_index=int(target_index),
                focus=False,
                auto_close_source_if_empty=True,
            )
            state.current_host_window = target_window
            self._hide_drag_ghost(state)
            return
        self._show_drag_ghost(state, global_pos)

    def finish_external_tab_drag(self, global_pos: QPoint, *, detach_on_invalid_drop: bool = True) -> bool:
        state = self._external_drag
        if state is None:
            return False
        self.update_external_tab_drag(global_pos)
        target_bar = self._tab_bar_from_global_pos(global_pos)
        moved = False
        current_owner = self.window_by_widget.get(state.widget)
        if target_bar is None and detach_on_invalid_drop:
            detached = self.detach_widget_to_new_window(state.widget, global_pos)
            moved = detached is not None
            if moved and detached is not None:
                self.focus_widget(detached, state.widget)
                self._debug_log("drag_detach_finish", key=str(self.key_by_widget.get(state.widget, "")))
        elif current_owner is not None:
            moved = True
            self.focus_widget(current_owner, state.widget)
            if target_bar is not None:
                self._debug_log("drag_attach", key=str(self.key_by_widget.get(state.widget, "")))
        self._hide_drag_ghost(state)
        self._destroy_drag_ghost(state)
        QApplication.restoreOverrideCursor()
        self._external_drag = None
        self._remove_drag_event_filter()
        return moved

    def active_drag_window(self) -> Optional[WorkspaceWindow]:
        return None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        state = self._external_drag
        if state is None:
            return False
        event_type = event.type()
        if event_type == QEvent.Type.MouseMove:
            buttons = getattr(event, "buttons", lambda: Qt.MouseButton.NoButton)()
            if not (buttons & Qt.MouseButton.LeftButton):
                return False
            global_pos = self._event_global_pos(event)
            if global_pos is not None:
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

    def _event_global_pos(self, event: QEvent) -> Optional[QPoint]:
        global_position = getattr(event, "globalPosition", None)
        if callable(global_position):
            return global_position().toPoint()
        global_pos = getattr(event, "globalPos", None)
        if callable(global_pos):
            return global_pos()
        return None

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

    def _tab_bar_from_global_pos(
        self,
        global_pos: QPoint,
        *,
        exclude_window: Optional[WorkspaceWindow] = None,
    ) -> Optional[DetachableTabBar]:
        _ = exclude_window
        for window in list(self.registered_windows):
            tabs = window.workspace_tabs()
            bar = tabs.tabBar()
            if not isinstance(bar, DetachableTabBar):
                continue
            if not bar.isVisible():
                continue
            top_left = bar.mapToGlobal(QPoint(0, 0))
            global_rect = QRect(top_left, bar.size())
            tabs = window.workspace_tabs()
            strip_top_left = tabs.mapToGlobal(QPoint(0, 0))
            strip_rect = QRect(strip_top_left, QSize(tabs.width(), bar.height()))
            if global_rect.contains(global_pos) or strip_rect.contains(global_pos):
                return bar
        return None

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
