import os
import sys
from pathlib import Path

from PySide6.QtCore import QPoint

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import APPLET_DEFINITIONS, MainLauncherWindow

_DEBUG_LOG = Path(ROOT) / "debug" / "test_workspace_tabs_drag_within_window.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def _applet(key: str) -> dict[str, object]:
    return next(a for a in APPLET_DEFINITIONS if str(a.get("key")) == key)


def test_previous_active_tab_stays_active_during_drag(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)

    host = window.workspace_tabs()
    strip = host.tabBar()
    controller = window._workspace_controller
    dragged = window._tab_by_key["map_library"]
    active_before = window._tab_by_key["session_creator"]
    host.setCurrentWidget(active_before)
    drag_index = host.indexOf(dragged)
    start = strip.mapToGlobal(strip.tab_rect_for_index(drag_index).center())
    probe = strip.mapToGlobal(QPoint(strip.width() - 20, strip.height() // 2))

    assert controller.start_external_tab_drag(window, dragged, start, hot_spot=QPoint(12, 12)) is True
    controller.update_external_tab_drag(probe)
    qtbot.wait(20)
    active_mid = host.currentWidget()
    controller.finish_external_tab_drag(probe)
    qtbot.wait(20)
    active_after = host.currentWidget()

    _debug_log(
        "active_hold "
        f"before={id(active_before)} mid={id(active_mid)} after={id(active_after)} "
        f"drag_index={host.indexOf(dragged)}"
    )
    assert active_mid is active_before
    assert active_after is active_before


def test_release_animates_dragged_tab_into_target_slot(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)

    host = window.workspace_tabs()
    strip = host.tabBar()
    controller = window._workspace_controller
    dragged = window._tab_by_key["map_library"]
    start_index = host.indexOf(dragged)
    drag_id = host.tab_id_for_widget(dragged)
    assert drag_id is not None

    start = strip.mapToGlobal(strip.tab_rect_for_index(start_index).center())
    drop = strip.mapToGlobal(QPoint(strip.width() - 18, strip.height() // 2))

    assert controller.start_external_tab_drag(window, dragged, start, hot_spot=QPoint(12, 12)) is True
    controller.update_external_tab_drag(drop)
    qtbot.wait(20)
    controller.finish_external_tab_drag(drop)
    qtbot.wait(20)

    end_index = host.indexOf(dragged)
    qtbot.waitUntil(
        lambda: (
            strip.visual_left(int(drag_id)) is not None
            and strip.target_left(int(drag_id)) is not None
            and abs(float(strip.visual_left(int(drag_id))) - float(strip.target_left(int(drag_id)))) <= 1.5
        ),
        timeout=700,
    )
    final_visual = strip.visual_left(int(drag_id))
    final_target = strip.target_left(int(drag_id))
    _debug_log(
        "settle "
        f"start_index={start_index} end_index={end_index} "
        f"visual={final_visual} target={final_target}"
    )
    assert end_index > start_index


def test_release_uses_live_drag_position_before_settling(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)

    host = window.workspace_tabs()
    strip = host.tabBar()
    controller = window._workspace_controller
    dragged = window._tab_by_key["map_library"]
    drag_id = host.tab_id_for_widget(dragged)
    assert drag_id is not None

    start = strip.mapToGlobal(strip.tab_rect_for_index(host.indexOf(dragged)).center())
    drop = strip.mapToGlobal(QPoint(strip.width() - 18, strip.height() // 2))

    assert controller.start_external_tab_drag(window, dragged, start, hot_spot=QPoint(12, 12)) is True
    controller.update_external_tab_drag(drop)
    qtbot.wait(20)
    live_left = strip.current_drag_left(int(drag_id))
    target_left = strip.target_left(int(drag_id))
    controller.finish_external_tab_drag(drop)
    visual_after_release = strip.visual_left(int(drag_id))
    qtbot.wait(20)

    _debug_log(
        "live_release_settle "
        f"live_left={live_left} visual_after_release={visual_after_release} target_left={target_left}"
    )
    assert live_left is not None
    assert visual_after_release is not None
    assert target_left is not None
    assert abs(float(visual_after_release) - float(target_left)) > 1.5
    assert abs(float(visual_after_release) - float(live_left)) <= 2.0


def test_dragged_tab_background_stays_transparent_inside_strip(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)

    host = window.workspace_tabs()
    strip = host.tabBar()
    controller = window._workspace_controller
    dragged = window._tab_by_key["map_library"]
    start = strip.mapToGlobal(strip.tab_rect_for_index(host.indexOf(dragged)).center())
    probe = strip.mapToGlobal(QPoint(strip.width() - 22, strip.height() // 2))

    assert controller.start_external_tab_drag(window, dragged, start, hot_spot=QPoint(12, 12)) is True
    controller.update_external_tab_drag(probe)
    qtbot.wait(20)
    strip.repaint()
    qtbot.wait(20)
    background_visible = strip.is_dragged_tab_background_visible()
    controller.finish_external_tab_drag(probe)
    qtbot.wait(20)

    _debug_log(f"transparent_drag background_visible={int(background_visible)}")
    assert background_visible is False


def test_tab_background_stays_transparent_before_during_and_after_drag(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)

    host = window.workspace_tabs()
    strip = host.tabBar()
    controller = window._workspace_controller
    dragged = window._tab_by_key["map_library"]
    drag_id = host.tab_id_for_widget(dragged)
    assert drag_id is not None
    initial_visible = strip.is_tab_background_visible(int(drag_id))

    start = strip.mapToGlobal(strip.tab_rect_for_index(host.indexOf(dragged)).center())
    drop = strip.mapToGlobal(QPoint(strip.width() - 18, strip.height() // 2))

    assert controller.start_external_tab_drag(window, dragged, start, hot_spot=QPoint(12, 12)) is True
    controller.update_external_tab_drag(drop)
    qtbot.wait(20)
    visible_during_settle = strip.is_tab_background_visible(int(drag_id))
    controller.finish_external_tab_drag(drop)
    strip.repaint()
    qtbot.wait(20)
    visible_after_release = strip.is_tab_background_visible(int(drag_id))
    qtbot.waitUntil(
        lambda: (
            strip.visual_left(int(drag_id)) is not None
            and strip.target_left(int(drag_id)) is not None
            and abs(float(strip.visual_left(int(drag_id))) - float(strip.target_left(int(drag_id)))) <= 1.5
        ),
        timeout=700,
    )
    strip.repaint()
    qtbot.wait(20)
    visible_after_settle = strip.is_tab_background_visible(int(drag_id))

    _debug_log(
        "tab_shell_transparent "
        f"initial={int(initial_visible)} during_drag={int(visible_during_settle)} "
        f"after_release={int(visible_after_release)} after_settle={int(visible_after_settle)}"
    )
    assert initial_visible is False
    assert visible_during_settle is False
    assert visible_after_release is False
    assert visible_after_settle is False


def test_dragging_non_home_left_does_not_cross_home_slot(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)

    host = window.workspace_tabs()
    strip = host.tabBar()
    controller = window._workspace_controller
    dragged = window._tab_by_key["map_library"]
    start = strip.mapToGlobal(strip.tab_rect_for_index(host.indexOf(dragged)).center())
    home_rect = strip.tab_rect_for_index(0)
    left_drop = strip.mapToGlobal(home_rect.center())

    assert controller.start_external_tab_drag(window, dragged, start, hot_spot=QPoint(12, 12)) is True
    controller.update_external_tab_drag(left_drop)
    qtbot.wait(20)
    controller.finish_external_tab_drag(left_drop)
    qtbot.wait(20)

    index_after = host.indexOf(dragged)
    _debug_log(f"home_guard index_after={index_after} home_text={host.tabText(0)}")
    assert host.tabText(0) == "Home"
    assert index_after >= 1
