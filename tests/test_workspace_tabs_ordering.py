import os
import sys
from pathlib import Path

from PySide6.QtCore import QPoint

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import APPLET_DEFINITIONS, MainLauncherWindow

_DEBUG_LOG = Path(ROOT) / "debug" / "test_workspace_tabs_ordering.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def _applet(key: str) -> dict[str, object]:
    return next(a for a in APPLET_DEFINITIONS if str(a.get("key")) == key)


def test_home_tab_stays_first_when_moving_non_home(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    host = window.workspace_tabs()
    maps = window._tab_by_key["map_library"]
    from_index = host.indexOf(maps)
    moved = host.move_tab(from_index, 0)
    qtbot.wait(20)
    _debug_log(
        "home_pinned "
        f"moved={int(bool(moved))} home={host.tabText(0)} maps_index={host.indexOf(maps)}"
    )
    assert host.tabText(0) == "Home"
    assert host.indexOf(maps) >= 1


def test_drag_center_crossing_reorders_non_home_tabs(qtbot) -> None:
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
    sibling = window._tab_by_key["session_creator"]

    drag_index = host.indexOf(dragged)
    sibling_index = host.indexOf(sibling)
    drag_start = strip.mapToGlobal(strip.tab_rect_for_index(drag_index).center())
    sibling_rect = strip.tab_rect_for_index(sibling_index)
    left_probe = strip.mapToGlobal(QPoint(max(1, sibling_rect.left() - 8), sibling_rect.center().y()))
    right_probe = strip.mapToGlobal(QPoint(sibling_rect.center().x() + 8, sibling_rect.center().y()))

    assert controller.start_external_tab_drag(window, dragged, drag_start, hot_spot=QPoint(12, 12)) is True
    controller.update_external_tab_drag(left_probe)
    qtbot.wait(20)
    before_cross = host.indexOf(dragged)
    controller.update_external_tab_drag(right_probe)
    qtbot.wait(20)
    after_cross = host.indexOf(dragged)
    after_sibling = host.indexOf(sibling)
    controller.finish_external_tab_drag(right_probe)
    qtbot.wait(20)

    _debug_log(
        "boundary_cross "
        f"before_cross={before_cross} after_cross={after_cross} sibling_after={after_sibling}"
    )
    assert before_cross <= after_cross
    assert after_cross > after_sibling


def test_dragged_tab_is_drawn_last_while_dragging(qtbot) -> None:
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
    drag_id = host.tab_id_for_widget(dragged)
    drag_index = host.indexOf(dragged)
    start = strip.mapToGlobal(strip.tab_rect_for_index(drag_index).center())
    hover = strip.mapToGlobal(QPoint(strip.tab_rect_for_index(drag_index).center().x() + 20, 18))

    assert drag_id is not None
    assert controller.start_external_tab_drag(window, dragged, start, hot_spot=QPoint(12, 12)) is True
    controller.update_external_tab_drag(hover)
    qtbot.wait(20)
    strip.repaint()
    qtbot.wait(20)
    order = strip.last_paint_order()
    _debug_log(f"paint_order order={order} drag_id={drag_id}")
    controller.finish_external_tab_drag(hover)
    qtbot.wait(20)

    assert order
    assert int(order[-1]) == int(drag_id)
