import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QTabBar

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import APPLET_DEFINITIONS, MainLauncherWindow
from tab_workspace import DetachableTabBar

pytestmark = pytest.mark.tier1

_DEBUG_LOG = Path(ROOT) / "debug" / "test_tab_workspace_detach_attach.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def _applet(key: str) -> dict[str, object]:
    return next(a for a in APPLET_DEFINITIONS if str(a.get("key")) == key)


def _window_count_with_widget(controller, widget) -> int:
    count = 0
    for window in list(controller.registered_windows):
        if window.workspace_tabs().indexOf(widget) != -1:
            count += 1
    return count


def test_reorder_non_home_tabs_keeps_home_pinned(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()

    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)

    tabs = window.workspace_tabs()
    maps_widget = window._tab_by_key["map_library"]
    maps_idx = tabs.indexOf(maps_widget)
    assert maps_idx > 0

    tabs.tabBar().moveTab(maps_idx, 0)
    qtbot.wait(10)

    assert tabs.tabText(0) == "Home"
    assert tabs.indexOf(maps_widget) == 1


def test_detach_tab_creates_new_window_and_preserves_widget_identity(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()

    window.open_applet(_applet("map_library"), focus_if_new=True)
    widget = window._tab_by_key["map_library"]
    before_id = id(widget)

    controller = window._workspace_controller
    detached = controller.detach_widget_to_new_window(widget, QPoint(320, 180))
    qtbot.wait(10)

    assert detached is not None
    assert detached is not window
    assert id(controller.tab_by_key["map_library"]) == before_id
    assert window.workspace_tabs().indexOf(widget) == -1
    assert detached.workspace_tabs().indexOf(widget) == 0


def test_attach_tab_back_to_primary_preserves_identity_and_mapping(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()

    window.open_applet(_applet("map_library"), focus_if_new=True)
    widget = window._tab_by_key["map_library"]
    before_id = id(widget)

    controller = window._workspace_controller
    detached = controller.detach_widget_to_new_window(widget, QPoint(320, 180))
    assert detached is not None

    moved = controller.move_widget_to_window(widget, window, target_index=1, focus=True)
    qtbot.wait(10)

    assert moved is True
    assert id(window._tab_by_key["map_library"]) == before_id
    assert window.workspace_tabs().indexOf(widget) == 1
    assert _window_count_with_widget(controller, widget) == 1


def test_open_existing_applet_from_other_window_focuses_existing_no_duplicate(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()

    applet = _applet("map_library")
    window.open_applet(applet, focus_if_new=True)
    widget = window._tab_by_key["map_library"]

    controller = window._workspace_controller
    detached = controller.detach_widget_to_new_window(widget, QPoint(320, 180))
    assert detached is not None
    detached_tabs = detached.workspace_tabs()

    window.open_applet(applet, focus_if_new=True)
    qtbot.wait(10)

    assert controller.tab_by_key["map_library"] is widget
    assert _window_count_with_widget(controller, widget) == 1
    assert detached_tabs.currentWidget() is widget


def test_external_drag_uses_real_tab_window_not_qdrag(qtbot, monkeypatch) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    map_index = tabs.indexOf(map_widget)
    start = bar.tabRect(map_index).center()
    target = QPoint(start.x() + 2, -14)

    def _qdrag_exec_forbidden(self, *args, **kwargs):
        raise AssertionError("QDrag.exec must not be used for external tab dragging")

    monkeypatch.setattr(QDrag, "exec", _qdrag_exec_forbidden)

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(bar, target)
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=target)


def test_external_drag_does_not_detach_until_release_outside_tab_bar(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    controller = window._workspace_controller
    map_widget = window._tab_by_key["map_library"]
    started = controller.start_external_tab_drag(window, map_widget, QPoint(400, 120))
    qtbot.wait(20)

    assert started is True
    assert window.workspace_tabs().indexOf(map_widget) != -1
    assert controller.active_drag_window() is None

    outside_drop = window.mapToGlobal(QPoint(window.width() + 180, 120))
    assert controller.finish_external_tab_drag(outside_drop) is True
    qtbot.wait(20)

    owner = controller.window_by_widget.get(map_widget)
    assert owner is not None
    assert owner is not window
    assert owner.workspace_tabs().indexOf(map_widget) != -1


def test_external_drag_uses_real_tab_preview_without_overlay_ghost(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    assert isinstance(bar, DetachableTabBar)

    map_widget = window._tab_by_key["map_library"]
    controller = window._workspace_controller
    assert controller.start_external_tab_drag(window, map_widget, QPoint(360, 120)) is True
    controller.update_external_tab_drag(QPoint(bar.mapToGlobal(bar.tabRect(0).center())))
    qtbot.wait(20)

    assert tabs.indexOf(map_widget) != -1
    assert not hasattr(bar, "_drop_indicator_title")


def test_external_drag_shows_ghost_off_tab_bar_and_hides_it_on_valid_tab_bar(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    controller = window._workspace_controller

    assert controller.start_external_tab_drag(window, map_widget, QPoint(400, 120)) is True
    state = getattr(controller, "_external_drag")
    assert state is not None

    off_bar = window.mapToGlobal(QPoint(window.width() + 160, bar.height() + 80))
    controller.update_external_tab_drag(off_bar)
    qtbot.wait(20)
    assert state.ghost is not None
    assert state.ghost.isVisible() is True

    on_bar = bar.mapToGlobal(bar.tabRect(max(0, tabs.count() - 1)).center())
    controller.update_external_tab_drag(on_bar)
    qtbot.wait(20)
    assert state.ghost.isVisible() is False


def test_external_drag_ghost_is_centered_under_cursor(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    controller = window._workspace_controller
    map_widget = window._tab_by_key["map_library"]

    assert controller.start_external_tab_drag(window, map_widget, QPoint(420, 140)) is True
    state = getattr(controller, "_external_drag")
    assert state is not None
    target = window.mapToGlobal(QPoint(window.width() + 140, 170))
    controller.update_external_tab_drag(target)
    qtbot.wait(20)

    assert state.ghost is not None
    center = state.ghost.frameGeometry().center()
    assert abs(center.x() - target.x()) <= 2
    assert abs(center.y() - target.y()) <= 2


def test_dragging_last_tab_out_closes_old_window_but_drag_continues(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    controller = window._workspace_controller
    map_widget = window._tab_by_key["map_library"]
    detached = controller.detach_widget_to_new_window(map_widget, QPoint(460, 180))
    assert detached is not None
    detached_bar = detached.workspace_tabs().tabBar()
    center = detached_bar.tabRect(0).center()
    start_pos = detached_bar.mapToGlobal(center)

    assert controller.start_external_tab_drag(detached, map_widget, start_pos) is True
    session_index = window.workspace_tabs().indexOf(window._tab_by_key["session_creator"])
    hover_pos = window.workspace_tabs().tabBar().mapToGlobal(
        window.workspace_tabs().tabBar().tabRect(session_index).center()
    )
    controller.update_external_tab_drag(hover_pos)
    qtbot.wait(30)

    assert detached.isVisible() is False
    assert getattr(controller, "_external_drag") is not None

    outside = window.mapToGlobal(QPoint(window.width() + 170, 120))
    controller.finish_external_tab_drag(outside)
    qtbot.wait(30)

    owner = controller.window_by_widget.get(map_widget)
    assert owner is not None
    assert owner is not window
    assert owner is not detached


def test_off_bar_drag_hides_source_tab_and_closes_single_tab_detached_source(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    controller = window._workspace_controller
    map_widget = window._tab_by_key["map_library"]
    detached = controller.detach_widget_to_new_window(map_widget, QPoint(520, 200))
    assert detached is not None
    assert detached.workspace_tabs().indexOf(map_widget) == 0

    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True
    state = getattr(controller, "_external_drag")
    assert state is not None

    off_bar = window.mapToGlobal(QPoint(window.width() + 190, 210))
    controller.update_external_tab_drag(off_bar)
    qtbot.wait(30)

    assert detached.workspace_tabs().indexOf(map_widget) == -1
    assert detached.isVisible() is False
    assert controller.window_by_widget.get(map_widget) is None
    assert state.ghost is not None and state.ghost.isVisible() is True


def test_external_drag_hover_moves_real_tab_into_target_bar_before_release(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    controller = window._workspace_controller

    assert controller.start_external_tab_drag(window, map_widget, QPoint(360, 120)) is True
    session_index = tabs.indexOf(window._tab_by_key["session_creator"])
    hover_pos = bar.mapToGlobal(bar.tabRect(session_index).center())
    controller.update_external_tab_drag(hover_pos)
    qtbot.wait(20)

    assert tabs.indexOf(map_widget) != -1
    assert controller.active_drag_window() is None


def test_drop_event_moves_detached_tab_back_into_primary_window(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)

    controller = window._workspace_controller
    map_widget = window._tab_by_key["map_library"]
    assert controller.start_external_tab_drag(window, map_widget, QPoint(360, 120)) is True
    target_bar = window.workspace_tabs().tabBar()
    global_drop = target_bar.mapToGlobal(target_bar.tabRect(0).center())
    controller.finish_external_tab_drag(global_drop)
    qtbot.wait(20)

    _debug_log(
        f"moved_back index={window.workspace_tabs().indexOf(map_widget)} "
        f"active_drag={controller.active_drag_window() is not None}"
    )

    assert window.workspace_tabs().indexOf(map_widget) != -1
    assert controller.active_drag_window() is None


def test_non_home_tabs_keep_close_buttons_visible(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    for index in range(1, tabs.count()):
        assert (
            bar.tabButton(index, QTabBar.ButtonPosition.RightSide) is not None
        ), f"close button missing for tab index {index}"


def test_drop_target_covers_full_tab_row_even_when_tabbar_is_narrow(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    qtbot.wait(20)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    assert bar.width() < tabs.width()

    right_strip_global = tabs.mapToGlobal(QPoint(tabs.width() - 8, max(2, bar.height() // 2)))
    owner = window._workspace_controller._tab_bar_from_global_pos(right_strip_global)
    assert owner is bar


def test_small_vertical_exit_drag_does_not_detach_immediately(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()

    map_widget = window._tab_by_key["map_library"]
    map_index = tabs.indexOf(map_widget)
    start = bar.tabRect(map_index).center()
    near_target = QPoint(start.x() + 2, -14)

    controller = window._workspace_controller

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(bar, near_target)
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=near_target)

    assert controller.active_drag_window() is None
    assert window.workspace_tabs().indexOf(map_widget) != -1


def test_detach_requires_stronger_vertical_pullout(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()

    map_widget = window._tab_by_key["map_library"]
    map_index = tabs.indexOf(map_widget)
    start = bar.tabRect(map_index).center()
    stronger_target = QPoint(start.x() + 2, -34)
    controller = window._workspace_controller

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(bar, stronger_target)
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=stronger_target)

    assert controller.active_drag_window() is None
    assert window.workspace_tabs().indexOf(map_widget) == -1


def test_tabs_do_not_expand_to_equal_full_width_chunks(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("dungeon_creator"), focus_if_new=True)
    qtbot.wait(20)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    widths = [bar.tabRect(i).width() for i in range(tabs.count())]

    assert bar.expanding() is False
    assert max(widths) < (tabs.width() // 2)


def test_tab_widths_follow_content_and_are_not_forced_uniform(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(
        {
            "key": "custom_long_title",
            "tab": "Join: The Ridiculously Long Campaign Name",
            "title": "Custom",
            "actions": [],
            "panels": [],
        },
        focus_if_new=True,
    )
    qtbot.wait(20)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    widths = [bar.tabRect(i).width() for i in range(tabs.count())]
    texts = [tabs.tabText(i) for i in range(tabs.count())]
    longest_index = max(range(len(texts)), key=lambda idx: len(texts[idx]))
    shortest_index = min(range(len(texts)), key=lambda idx: len(texts[idx]))

    assert widths[longest_index] > widths[shortest_index]
