import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QTabBar, QTabWidget, QWidget

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
    map_index = window.workspace_tabs().indexOf(map_widget)
    start_pos = window.workspace_tabs().tabBar().mapToGlobal(
        window.workspace_tabs().tabBar().tabRect(map_index).center()
    )
    started = controller.start_external_tab_drag(window, map_widget, start_pos)
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


def test_external_drag_hides_ghost_on_preview_attach_and_restores_only_after_far_exit(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
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
    _debug_log("ghost_state phase=off_bar visible=1")

    on_bar = bar.mapToGlobal(bar.tabRect(max(0, tabs.count() - 1)).center())
    controller.update_external_tab_drag(on_bar)
    qtbot.wait(20)
    _debug_log(
        f"ghost_state phase=on_bar visible={int(state.ghost.isVisible())} "
        f"owner_is_window={int(controller.window_by_widget.get(map_widget) is window)}"
    )
    assert state.ghost.isVisible() is False

    near_bar = tabs.mapToGlobal(QPoint(bar.tabRect(1).center().x(), bar.height() + 24))
    controller.update_external_tab_drag(near_bar)
    qtbot.wait(20)
    _debug_log(f"ghost_state phase=near_bar visible={int(state.ghost.isVisible())}")
    assert state.ghost.isVisible() is False

    far_away = tabs.mapToGlobal(
        QPoint(
            bar.tabRect(1).center().x(),
            bar.height() + controller._DROP_TARGET_STICKY_BOTTOM_SLOP_PX + 100,
        )
    )
    controller.update_external_tab_drag(far_away)
    qtbot.wait(20)
    _debug_log(f"ghost_state phase=far_away visible={int(state.ghost.isVisible())}")
    assert state.ghost.isVisible() is True


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

    off_bar = QPoint(-1200, -900)
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


def test_drop_target_uses_full_tab_strip_width(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    qtbot.wait(20)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()

    outside_right = tabs.mapToGlobal(QPoint(tabs.width() - 8, max(2, bar.height() // 2)))
    owner_outside = window._workspace_controller._tab_bar_from_global_pos(outside_right)
    assert owner_outside is bar

    inside_bar = bar.mapToGlobal(QPoint(max(2, bar.width() - 6), max(2, bar.height() // 2)))
    owner_inside = window._workspace_controller._tab_bar_from_global_pos(inside_bar)
    assert owner_inside is bar


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
    qtbot.wait(20)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    widths = [bar.tabRect(i).width() for i in range(tabs.count())]

    assert bar.expanding() is False
    assert max(widths) < (tabs.width() // 2)


def test_tab_bar_fills_full_strip_width_to_prevent_reorder_cutoff(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)
    qtbot.wait(20)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    _debug_log(
        f"bar_full_strip_check bar_w={bar.width()} tabs_w={tabs.width()} "
        f"bar_x={bar.x()} tabs_x={tabs.x()}"
    )

    assert abs(bar.width() - tabs.width()) <= 2


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


def test_external_drag_from_detached_reorders_smoothly_near_strip(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("dungeon_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]

    detached = controller.detach_widget_to_new_window(map_widget, QPoint(520, 200))
    assert detached is not None
    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)

    hover_keys = ["session_creator", "dungeon_creator", "npc_database"]
    observed_indices: list[int] = []
    for key in hover_keys:
        target_idx = tabs.indexOf(window._tab_by_key[key])
        near_strip = tabs.mapToGlobal(
            QPoint(bar.tabRect(target_idx).center().x(), bar.height() + 20)
        )
        controller.update_external_tab_drag(near_strip)
        qtbot.wait(20)
        idx = tabs.indexOf(map_widget)
        observed_indices.append(idx)
        _debug_log(f"smooth_hover key={key} map_index={idx}")

    assert all(index != -1 for index in observed_indices)
    assert observed_indices == sorted(observed_indices)


def test_external_drag_attached_overlay_tracks_cursor_smoothly(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)
    qtbot.wait(30)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    detached = controller.detach_widget_to_new_window(map_widget, QPoint(520, 200))
    assert detached is not None

    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)

    overlay_x_samples: list[int] = []
    cursor_x_samples: list[int] = []
    for x in range(40, tabs.width() - 20, 10):
        probe = tabs.mapToGlobal(QPoint(x, max(2, bar.height() // 2)))
        controller.update_external_tab_drag(probe)
        qtbot.wait(8)

        idx = tabs.indexOf(map_widget)
        if idx == -1:
            continue
        overlay = getattr(bar, "_title_overlay_by_index", {}).get(idx)
        if overlay is None or not overlay.isVisible():
            continue
        overlay_x_samples.append(int(overlay.geometry().x()))
        cursor_x_samples.append(int(x))

    unique_overlay_x = sorted(set(overlay_x_samples))
    _debug_log(
        "external_drag_overlay_smooth_probe "
        f"samples={len(overlay_x_samples)} unique_overlay_x={len(unique_overlay_x)} "
        f"overlay={overlay_x_samples} cursor={cursor_x_samples}"
    )

    assert len(overlay_x_samples) >= 20
    assert len(unique_overlay_x) >= 10, (
        "External drag stayed slot-snappy after attach; expected smooth overlay tracking under cursor."
    )


def test_external_drag_attached_close_button_tracks_cursor_smoothly(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)
    qtbot.wait(30)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    detached = controller.detach_widget_to_new_window(map_widget, QPoint(520, 200))
    assert detached is not None

    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)

    close_x_samples: list[int] = []
    for x in range(40, tabs.width() - 20, 10):
        probe = tabs.mapToGlobal(QPoint(x, max(2, bar.height() // 2)))
        controller.update_external_tab_drag(probe)
        qtbot.wait(8)

        idx = tabs.indexOf(map_widget)
        if idx == -1:
            continue
        close_btn = bar.tabButton(idx, QTabBar.ButtonPosition.RightSide)
        if close_btn is None or not close_btn.isVisible():
            continue
        close_x_samples.append(int(close_btn.geometry().x()))

    unique_close_x = sorted(set(close_x_samples))
    _debug_log(
        "external_drag_close_smooth_probe "
        f"samples={len(close_x_samples)} unique_close_x={len(unique_close_x)} "
        f"close_x={close_x_samples}"
    )

    assert len(close_x_samples) >= 20
    assert len(unique_close_x) >= 10, (
        "External drag close button stayed slot-snappy after attach; expected smooth cursor tracking."
    )


def test_external_attach_drag_pushes_neighbor_tabs_smoothly_like_internal_drag(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)
    qtbot.wait(30)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    observed_widget = window._tab_by_key["session_creator"]
    detached = controller.detach_widget_to_new_window(map_widget, QPoint(520, 200))
    assert detached is not None

    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)

    close_x_samples: list[int] = []
    for x in range(28, tabs.width() - 24, 8):
        probe = tabs.mapToGlobal(QPoint(x, max(2, bar.height() // 2)))
        controller.update_external_tab_drag(probe)
        qtbot.wait(8)
        idx = tabs.indexOf(observed_widget)
        if idx == -1:
            continue
        close_btn = bar.tabButton(idx, QTabBar.ButtonPosition.RightSide)
        if close_btn is None or not close_btn.isVisible():
            continue
        close_x_samples.append(int(close_btn.geometry().x()))

    unique_close_x = sorted(set(close_x_samples))
    _debug_log(
        "external_attach_neighbor_push_probe "
        f"samples={len(close_x_samples)} unique_close_x={len(unique_close_x)} "
        f"close_x={close_x_samples}"
    )
    assert len(close_x_samples) >= 20
    assert len(unique_close_x) >= 3, (
        "Neighbor tabs still move slot-snappy during external attach drag; expected smoother push behavior."
    )


def test_external_drag_release_settles_close_button_instead_of_popping(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)
    qtbot.wait(30)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    detached = controller.detach_widget_to_new_window(map_widget, QPoint(520, 200))
    assert detached is not None

    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)

    release_pos = tabs.mapToGlobal(QPoint(tabs.width() - 8, max(2, bar.height() // 2)))
    controller.update_external_tab_drag(release_pos)
    qtbot.wait(12)
    idx = tabs.indexOf(map_widget)
    assert idx != -1
    close_btn = bar.tabButton(idx, QTabBar.ButtonPosition.RightSide)
    assert close_btn is not None and close_btn.isVisible()
    x_pre = int(close_btn.geometry().x())

    controller.finish_external_tab_drag(release_pos)
    x0 = int(close_btn.geometry().x())
    x_samples = [x0]
    for _ in range(8):
        qtbot.wait(14)
        x_samples.append(int(close_btn.geometry().x()))

    x_final = x_samples[-1]
    immediate_jump = abs(x_pre - x0)
    total_delta = abs(x_pre - x_final)
    _debug_log(
        "external_release_close_settle "
        f"x_pre={x_pre} x_samples={x_samples} immediate_jump={immediate_jump} total_delta={total_delta}"
    )
    assert immediate_jump <= max(40, int(total_delta * 0.45)), (
        "Close button snapped too far immediately on release before settle animation."
    )
    assert len(set(x_samples)) >= 2, (
        "Close button popped directly to final slot position on release; expected short smooth settle."
    )


def test_detach_new_window_places_tab_hotspot_under_cursor(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    qtbot.wait(20)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    start_idx = tabs.indexOf(map_widget)
    start_rect = bar.tabRect(start_idx)
    hot_spot = QPoint(max(6, start_rect.width() // 4), max(6, start_rect.height() // 2))
    start_global = bar.mapToGlobal(start_rect.topLeft() + hot_spot)

    assert controller.start_external_tab_drag(window, map_widget, start_global, hot_spot=hot_spot) is True
    drop_global = window.mapToGlobal(QPoint(window.width() + 240, 180))
    assert controller.finish_external_tab_drag(drop_global) is True
    qtbot.wait(30)

    owner = controller.window_by_widget.get(map_widget)
    assert owner is not None
    assert owner is not window
    owner_tabs = owner.workspace_tabs()
    owner_bar = owner_tabs.tabBar()
    idx = owner_tabs.indexOf(map_widget)
    assert idx != -1
    rect = owner_bar.tabRect(idx)
    clamped_hot = QPoint(
        max(1, min(hot_spot.x(), max(1, rect.width() - 1))),
        max(1, min(hot_spot.y(), max(1, rect.height() - 1))),
    )
    actual_global = owner_bar.mapToGlobal(rect.topLeft() + clamped_hot)
    dx = abs(actual_global.x() - drop_global.x())
    dy = abs(actual_global.y() - drop_global.y())
    _debug_log(
        "detach_hotspot_alignment "
        f"drop=({drop_global.x()},{drop_global.y()}) actual=({actual_global.x()},{actual_global.y()}) "
        f"dx={dx} dy={dy}"
    )
    assert dx <= 4 and dy <= 4


def test_external_drag_target_switches_after_first_quarter_of_tab_width(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)
    qtbot.wait(20)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    target_idx = tabs.indexOf(window._tab_by_key["session_creator"])
    rect = bar.tabRect(target_idx)
    before_quarter = bar.mapToGlobal(QPoint(rect.left() + max(1, int(rect.width() * 0.10)), rect.center().y()))
    after_quarter = bar.mapToGlobal(QPoint(rect.left() + max(2, int(rect.width() * 0.30)), rect.center().y()))

    idx_before = bar.insertion_index_for_global_pos(before_quarter)
    idx_after = bar.insertion_index_for_global_pos(after_quarter)
    assert idx_before == target_idx
    assert idx_after == target_idx + 1


def test_external_drop_insertion_ignores_home_tab_region(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    qtbot.wait(20)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    home_rect = bar.tabRect(0)
    home_center = bar.mapToGlobal(home_rect.center())
    left_of_bar = bar.mapToGlobal(QPoint(home_rect.left() - 12, home_rect.center().y()))

    idx_at_home = bar.insertion_index_for_global_pos(home_center)
    idx_left = bar.insertion_index_for_global_pos(left_of_bar)
    _debug_log(
        "home_insertion_ignore_probe "
        f"idx_at_home={idx_at_home} idx_left={idx_left} home_rect=({home_rect.x()},{home_rect.y()},"
        f"{home_rect.width()},{home_rect.height()})"
    )

    assert idx_at_home == 1
    assert idx_left == 1


def test_internal_drag_detaches_when_cursor_exits_horizontal_bounds(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    qtbot.wait(20)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    start = bar.tabRect(tabs.indexOf(map_widget)).center()
    outside_left = QPoint(-36, start.y())

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    qtbot.wait(12)
    qtbot.mouseMove(bar, outside_left)
    qtbot.wait(24)

    state = getattr(controller, "_external_drag")
    _debug_log(
        "horizontal_detach_probe "
        f"outside_left=({outside_left.x()},{outside_left.y()}) started={int(state is not None)}"
    )

    if state is not None:
        drop = window.mapToGlobal(QPoint(-220, start.y()))
        controller.finish_external_tab_drag(drop)
    else:
        qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=outside_left)

    assert state is not None, "Horizontal out-of-bounds drag should detach/start external drag."


def test_dragging_home_tab_does_not_move_or_shift_active_indicator(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    qtbot.wait(20)

    tabs = window.workspace_tabs()
    tabs.setCurrentIndex(0)
    bar = tabs.tabBar()
    home_center = bar.tabRect(0).center()
    moved_events: list[tuple[int, int]] = []
    bar.tabMoved.connect(lambda frm, to: moved_events.append((int(frm), int(to))))

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=home_center)
    qtbot.wait(12)
    for x in range(home_center.x() + 20, home_center.x() + 260, 16):
        qtbot.mouseMove(bar, QPoint(x, home_center.y()))
        qtbot.wait(6)
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(home_center.x() + 240, home_center.y()))
    qtbot.wait(20)

    _debug_log(
        "home_drag_block_probe "
        f"moved_events={moved_events} current_index={tabs.currentIndex()}"
    )
    assert moved_events == [], "Home drag emitted tabMoved events even though Home should be non-draggable."
    assert tabs.currentIndex() == 0, "Dragging Home shifted active indicator away from Home."


def test_dragging_non_home_across_home_region_has_no_rejection_jitter(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    qtbot.wait(20)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    start = bar.tabRect(tabs.indexOf(map_widget)).center()
    home_rect = bar.tabRect(0)

    moved_events: list[tuple[int, int]] = []
    sampled_indices: list[int] = []
    bar.tabMoved.connect(lambda frm, to: moved_events.append((int(frm), int(to))))

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    qtbot.wait(12)
    for x in range(start.x(), max(2, home_rect.left() + 2), -10):
        qtbot.mouseMove(bar, QPoint(x, start.y()))
        qtbot.wait(8)
        sampled_indices.append(tabs.indexOf(map_widget))
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(max(2, home_rect.left() + 2), start.y()))
    qtbot.wait(20)

    _debug_log(
        "home_cross_rejection_probe "
        f"events={moved_events} sampled_indices={sampled_indices} final_idx={tabs.indexOf(map_widget)}"
    )
    assert sampled_indices, "Did not capture any samples while crossing Home region."
    assert set(sampled_indices) == {1}, "Dragged tab index jittered while crossing Home; expected Home to be ignored."
    assert tabs.indexOf(map_widget) == 1, "Dragged tab did not settle back to the pinned-home-adjacent slot."


def test_internal_release_in_far_right_empty_strip_keeps_title_overlay_visible(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)
    qtbot.wait(30)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    start = bar.tabRect(tabs.indexOf(map_widget)).center()
    far_right = QPoint(tabs.width() - 8, start.y())

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    qtbot.wait(12)
    qtbot.mouseMove(bar, far_right)
    qtbot.wait(12)
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=far_right)

    visible_nonempty_samples = 0
    widths: list[int] = []
    for _ in range(12):
        qtbot.wait(14)
        idx = tabs.indexOf(map_widget)
        if idx == -1:
            continue
        overlay = getattr(bar, "_title_overlay_by_index", {}).get(idx)
        if overlay is None:
            continue
        widths.append(int(overlay.geometry().width()))
        if overlay.isVisible() and overlay.text().strip():
            visible_nonempty_samples += 1

    _debug_log(
        "internal_far_right_release_overlay "
        f"visible_nonempty_samples={visible_nonempty_samples} widths={widths}"
    )
    assert visible_nonempty_samples >= 6, (
        "Title overlay disappeared while tab slid back from far-right empty strip release."
    )
    assert all(width >= 6 for width in widths), "Overlay width collapsed to zero during slide-back."


def test_vertical_fast_move_after_source_close_does_not_hang_on_target_border(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("dungeon_creator"), focus_if_new=True)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    detached = controller.detach_widget_to_new_window(map_widget, QPoint(560, 220))
    assert detached is not None
    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True

    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)
    qtbot.waitUntil(lambda: detached.isVisible() is False, timeout=1500)

    target_idx = tabs.indexOf(window._tab_by_key["session_creator"])
    x = bar.tabRect(target_idx).center().x()
    points = [
        tabs.mapToGlobal(QPoint(x, bar.height() - 1)),
        tabs.mapToGlobal(QPoint(x, bar.height() + 20)),
        tabs.mapToGlobal(QPoint(x, bar.height() - 2)),
        tabs.mapToGlobal(QPoint(x, bar.height() + 20)),
    ]
    for i, point in enumerate(points):
        controller.update_external_tab_drag(point)
        qtbot.wait(15)
        owner = controller.window_by_widget.get(map_widget)
        idx = tabs.indexOf(map_widget)
        _debug_log(
            f"vertical_move step={i} owner_is_main={owner is window} map_index={idx}"
        )
        assert owner is window
        assert idx != -1


def test_external_drag_attaches_across_full_primary_tab_strip_width(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("dungeon_creator"), focus_if_new=True)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]

    detached = controller.detach_widget_to_new_window(map_widget, QPoint(560, 220))
    assert detached is not None
    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True

    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)
    assert controller.window_by_widget.get(map_widget) is None

    probe_x = max(8, tabs.width() - 8)
    probe = tabs.mapToGlobal(QPoint(probe_x, bar.height() + 20))
    controller.update_external_tab_drag(probe)
    qtbot.wait(20)

    owner = controller.window_by_widget.get(map_widget)
    _debug_log(
        f"primary_full_width_hover owner_is_main={owner is window} owner_exists={owner is not None} "
        f"probe_x={probe_x} bar_w={bar.width()} tabs_w={tabs.width()}"
    )
    assert owner is window
    assert tabs.indexOf(map_widget) != -1


def test_external_drag_attaches_across_full_detached_tab_strip_width(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)

    controller = window._workspace_controller
    map_widget = window._tab_by_key["map_library"]
    session_widget = window._tab_by_key["session_creator"]
    detached = controller.detach_widget_to_new_window(map_widget, QPoint(560, 220))
    assert detached is not None

    start = window.workspace_tabs().tabBar().mapToGlobal(
        window.workspace_tabs().tabBar().tabRect(window.workspace_tabs().indexOf(session_widget)).center()
    )
    assert controller.start_external_tab_drag(window, session_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)
    assert controller.window_by_widget.get(session_widget) is None

    target_tabs = detached.workspace_tabs()
    target_bar = target_tabs.tabBar()
    probe_x = max(8, target_tabs.width() - 8)
    far_right_attach = target_tabs.mapToGlobal(QPoint(probe_x, max(2, target_bar.height() // 2)))
    controller.update_external_tab_drag(far_right_attach)
    qtbot.wait(20)

    owner = controller.window_by_widget.get(session_widget)
    _debug_log(
        f"detached_full_width_attach owner_is_detached={int(owner is detached)} "
        f"bar_w={target_bar.width()} tabs_w={target_tabs.width()} "
        f"probe_x={probe_x}"
    )
    assert owner is detached
    assert detached.workspace_tabs().indexOf(session_widget) != -1


def test_external_drag_same_probe_point_does_not_flip_tab_index(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("dungeon_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    session_widget = window._tab_by_key["session_creator"]
    dungeon_widget = window._tab_by_key["dungeon_creator"]

    detached = controller.detach_widget_to_new_window(map_widget, QPoint(560, 220))
    assert detached is not None
    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)

    session_index = tabs.indexOf(session_widget)
    attach_pos = bar.mapToGlobal(bar.tabRect(session_index).center())
    controller.update_external_tab_drag(attach_pos)
    qtbot.wait(20)
    assert tabs.indexOf(map_widget) != -1

    session_index = tabs.indexOf(session_widget)
    dungeon_index = tabs.indexOf(dungeon_widget)
    session_rect = bar.tabRect(session_index)
    dungeon_rect = bar.tabRect(dungeon_index)
    probe_x = (session_rect.center().x() + dungeon_rect.center().x()) // 2
    probe_y = session_rect.center().y()
    probe = bar.mapToGlobal(QPoint(probe_x, probe_y))

    observed: list[int] = []
    for _ in range(14):
        controller.update_external_tab_drag(probe)
        qtbot.wait(10)
        observed.append(tabs.indexOf(map_widget))

    _debug_log(f"same_probe_indices probe_x={probe_x} observed={observed}")
    tail = observed[4:]
    assert all(index != -1 for index in observed)
    assert len(set(tail)) == 1


def test_drop_into_window_keeps_existing_active_tab_selected(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("dungeon_creator"), focus_if_new=True)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    map_widget = window._tab_by_key["map_library"]
    session_widget = window._tab_by_key["session_creator"]
    dungeon_widget = window._tab_by_key["dungeon_creator"]
    tabs.setCurrentWidget(dungeon_widget)
    active_before = tabs.currentWidget()

    detached = controller.detach_widget_to_new_window(map_widget, QPoint(520, 200))
    assert detached is not None
    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True

    drop_pos = tabs.tabBar().mapToGlobal(
        tabs.tabBar().tabRect(tabs.indexOf(session_widget)).center()
    )
    controller.update_external_tab_drag(drop_pos)
    qtbot.wait(20)
    controller.finish_external_tab_drag(drop_pos)
    qtbot.wait(20)

    _debug_log(
        f"active_tab_keep before={id(active_before)} after={id(tabs.currentWidget())} "
        f"map_current={tabs.currentWidget() is map_widget}"
    )
    assert tabs.currentWidget() is active_before


def test_external_drag_reentry_without_left_button_finishes_drag(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)

    controller = window._workspace_controller
    map_widget = window._tab_by_key["map_library"]
    bar = window.workspace_tabs().tabBar()
    start = bar.mapToGlobal(bar.tabRect(window.workspace_tabs().indexOf(map_widget)).center())

    assert controller.start_external_tab_drag(window, map_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)

    class _NoButtonMoveEvent:
        def __init__(self, global_pos: QPoint) -> None:
            self._global_pos = QPoint(global_pos)

        def type(self) -> QEvent.Type:
            return QEvent.Type.MouseMove

        def buttons(self) -> Qt.MouseButtons:
            return Qt.MouseButton.NoButton

        def globalPosition(self) -> QPointF:
            return QPointF(self._global_pos)

    reentry = window.mapToGlobal(QPoint(80, 80))
    controller.eventFilter(window, _NoButtonMoveEvent(reentry))
    qtbot.wait(30)

    owner = controller.window_by_widget.get(map_widget)
    _debug_log(
        f"no_button_reentry active_drag={getattr(controller, '_external_drag') is not None} "
        f"owner_is_window={owner is window} owner_exists={owner is not None}"
    )

    assert getattr(controller, "_external_drag") is None
    assert owner is not None


def test_external_drag_stays_attached_when_hovering_below_bar_border(qtbot) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("dungeon_creator"), focus_if_new=True)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    detached = controller.detach_widget_to_new_window(map_widget, QPoint(520, 200))
    assert detached is not None
    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)

    target_idx = tabs.indexOf(window._tab_by_key["session_creator"])
    attach_pos = tabs.mapToGlobal(QPoint(bar.tabRect(target_idx).center().x(), bar.height() + 20))
    controller.update_external_tab_drag(attach_pos)
    qtbot.wait(20)
    assert controller.window_by_widget.get(map_widget) is window

    below_bar = tabs.mapToGlobal(QPoint(bar.tabRect(target_idx).center().x(), bar.height() + 28))
    controller.update_external_tab_drag(below_bar)
    qtbot.wait(20)

    assert controller.window_by_widget.get(map_widget) is window
    assert tabs.indexOf(map_widget) != -1


def test_external_drag_from_bottom_far_below_bar_stays_ghost(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)

    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    map_widget = window._tab_by_key["map_library"]
    detached = controller.detach_widget_to_new_window(map_widget, QPoint(520, 200))
    assert detached is not None
    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert controller.start_external_tab_drag(detached, map_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)
    assert controller.window_by_widget.get(map_widget) is None

    target_idx = tabs.indexOf(window._tab_by_key["session_creator"])
    far_below = tabs.mapToGlobal(QPoint(bar.tabRect(target_idx).center().x(), bar.height() + 75))
    controller.update_external_tab_drag(far_below)
    qtbot.wait(20)

    state = getattr(controller, "_external_drag")
    _debug_log(
        "bottom_far_probe "
        f"owner_is_window={int(controller.window_by_widget.get(map_widget) is window)} "
        f"owner_exists={int(controller.window_by_widget.get(map_widget) is not None)} "
        f"ghost_visible={int(bool(state is not None and state.ghost is not None and state.ghost.isVisible()))}"
    )
    assert controller.window_by_widget.get(map_widget) is None
    assert state is not None
    assert state.ghost is not None and state.ghost.isVisible() is True


def test_internal_tab_reorder_title_overlay_moves_smoothly_with_close_button(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)
    qtbot.wait(30)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()

    dragged_index = tabs.indexOf(window._tab_by_key["map_library"])
    dragged_center = bar.tabRect(dragged_index).center()
    drag_y = dragged_center.y()

    observed_label = "NPCs"
    title_x_samples: list[int] = []
    close_x_samples: list[int] = []

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=dragged_center)
    qtbot.wait(15)
    for x in range(dragged_center.x() + 12, dragged_center.x() + 300, 5):
        qtbot.mouseMove(bar, QPoint(x, drag_y))
        qtbot.wait(8)
        observed_index = next(
            (i for i in range(tabs.count()) if tabs.tabText(i) == observed_label),
            -1,
        )
        if observed_index == -1:
            continue
        title_overlay_by_index = getattr(bar, "_title_overlay_by_index", {})
        title_overlay = title_overlay_by_index.get(observed_index)
        if title_overlay is not None and title_overlay.isVisible():
            title_x_samples.append(int(title_overlay.geometry().x()))
        close_btn = bar.tabButton(observed_index, QTabBar.ButtonPosition.RightSide)
        if close_btn is not None:
            close_x_samples.append(int(close_btn.geometry().x()))
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(dragged_center.x() + 300, drag_y))
    qtbot.wait(30)

    title_unique = sorted(set(title_x_samples))
    close_unique = sorted(set(close_x_samples))
    _debug_log(
        "tab_reorder_title_overlay_vs_close "
        f"title_unique={title_unique} close_unique={close_unique} "
        f"title_samples={title_x_samples} close_samples={close_x_samples}"
    )

    assert len(close_unique) >= 4, (
        "Probe failed to capture smooth close-button movement; expected at least 4 unique x samples, "
        f"got {len(close_unique)}."
    )
    assert len(title_unique) >= 4, (
        "Tab title overlay did not move smoothly during reorder; "
        f"captured only {len(title_unique)} unique positions vs {len(close_unique)} for close button."
    )


def test_dragged_tab_title_does_not_get_stuck_or_hard_clipped_against_neighbors(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)
    long_key = "custom_long_drag_overlay_probe"
    window.open_applet(
        {
            "key": long_key,
            "tab": "Join: The Ridiculously Long Campaign Name For Drag Probe",
            "title": "Custom",
            "actions": [],
            "panels": [],
        },
        focus_if_new=True,
    )
    qtbot.wait(40)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    dragged_widget = window._tab_by_key[long_key]
    start_index = tabs.indexOf(dragged_widget)
    start_center = bar.tabRect(start_index).center()

    samples: list[tuple[int, int, int]] = []
    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start_center)
    qtbot.wait(20)
    for x in range(start_center.x() - 10, start_center.x() - 620, -6):
        qtbot.mouseMove(bar, QPoint(x, start_center.y()))
        qtbot.wait(8)
        current_index = tabs.indexOf(dragged_widget)
        if current_index == -1:
            continue
        close_btn = bar.tabButton(current_index, QTabBar.ButtonPosition.RightSide)
        if close_btn is None:
            continue
        overlay = getattr(bar, "_title_overlay_by_index", {}).get(current_index)
        if overlay is None or not overlay.isVisible():
            continue
        samples.append(
            (
                int(close_btn.geometry().x()),
                int(overlay.geometry().x()),
                int(overlay.geometry().width()),
            )
        )
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(start_center.x() - 620, start_center.y()))
    qtbot.wait(30)

    static_close_motion = 0
    max_static_close_motion = 0
    for (prev_close, prev_title_x, _), (close_x, title_x, _) in zip(samples, samples[1:]):
        if title_x == prev_title_x:
            static_close_motion += abs(close_x - prev_close)
            if static_close_motion > max_static_close_motion:
                max_static_close_motion = static_close_motion
        else:
            static_close_motion = 0

    widths = [entry[2] for entry in samples]
    baseline_width = widths[0] if widths else 0
    min_width = min(widths) if widths else 0
    _debug_log(
        "dragged_tab_overlay_neighbor_clip_probe "
        f"samples={samples} max_static_close_motion={max_static_close_motion} "
        f"baseline_width={baseline_width} min_width={min_width}"
    )

    assert len(samples) >= 20, f"Probe did not collect enough drag samples; got {len(samples)}."
    assert max_static_close_motion <= 36, (
        "Dragged title overlay got stuck while close button kept moving, indicating neighbor-edge clipping."
    )
    assert min_width >= max(24, baseline_width - 100), (
        "Dragged title overlay width collapsed too much during drag, indicating hard clipping into ellipsis."
    )


def test_internal_drag_disables_hover_highlight_on_other_tabs(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)
    qtbot.wait(30)

    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    dragged_widget = window._tab_by_key["map_library"]
    sibling_widget = window._tab_by_key["session_creator"]

    drag_start = bar.tabRect(tabs.indexOf(dragged_widget)).center()
    sibling_index = tabs.indexOf(sibling_widget)
    hover_pos = bar.tabRect(sibling_index).center()

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=drag_start)
    qtbot.wait(10)
    qtbot.mouseMove(bar, hover_pos)
    qtbot.wait(20)

    sibling_index = tabs.indexOf(sibling_widget)
    overlay = getattr(bar, "_title_overlay_by_index", {}).get(sibling_index)
    hover_index = getattr(bar, "_hover_index", -1)
    overlay_style = overlay.styleSheet() if overlay is not None else ""
    _debug_log(
        "drag_hover_highlight_probe "
        f"hover_index={hover_index} sibling_index={sibling_index} "
        f"overlay_visible={int(bool(overlay is not None and overlay.isVisible()))} "
        f"overlay_style={overlay_style}"
    )

    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=hover_pos)
    qtbot.wait(20)

    assert hover_index == -1
    assert "#e6edf3" not in overlay_style


def test_plain_qtabbar_matches_jump_pattern_seen_in_workspace_tabbar(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    tabs.resize(1400, 900)
    tabs.show()
    tabs.setMovable(True)
    tabs.setTabsClosable(True)
    bar = tabs.tabBar()
    bar.setTabsClosable(True)
    bar.setExpanding(False)
    bar.setElideMode(Qt.TextElideMode.ElideRight)

    labels = ["Home", "Maps", "Sessions", "Dungeons", "NPCs"]
    for label in labels:
        tabs.addTab(QWidget(), label)
    bar.setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
    bar.setTabButton(0, QTabBar.ButtonPosition.LeftSide, None)
    qtbot.wait(20)

    maps_index = next(i for i in range(tabs.count()) if tabs.tabText(i) == "Maps")
    maps_center = bar.tabRect(maps_index).center()
    drag_y = maps_center.y()

    observed_label = "Dungeons"
    rect_x_samples: list[int] = []
    close_x_samples: list[int] = []

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=maps_center)
    qtbot.wait(15)
    for x in range(maps_center.x() + 12, maps_center.x() + 300, 5):
        qtbot.mouseMove(bar, QPoint(x, drag_y))
        qtbot.wait(8)
        observed_index = next(
            (i for i in range(tabs.count()) if tabs.tabText(i) == observed_label),
            -1,
        )
        if observed_index == -1:
            continue
        rect_x_samples.append(int(bar.tabRect(observed_index).x()))
        close_btn = bar.tabButton(observed_index, QTabBar.ButtonPosition.RightSide)
        if close_btn is not None:
            close_x_samples.append(int(close_btn.geometry().x()))
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(maps_center.x() + 300, drag_y))
    qtbot.wait(30)

    rect_unique = sorted(set(rect_x_samples))
    close_unique = sorted(set(close_x_samples))
    _debug_log(
        "plain_tabbar_text_vs_close "
        f"rect_unique={rect_unique} close_unique={close_unique} "
        f"rect_samples={rect_x_samples} close_samples={close_x_samples}"
    )

    assert len(close_unique) >= 4
    assert len(rect_unique) <= 2
