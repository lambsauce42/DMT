import os
import sys
from pathlib import Path

from PySide6.QtCore import QPoint

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import APPLET_DEFINITIONS, MainLauncherWindow

_DEBUG_LOG = Path(ROOT) / "debug" / "test_workspace_tabs_detach_attach.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def _applet(key: str) -> dict[str, object]:
    return next(a for a in APPLET_DEFINITIONS if str(a.get("key")) == key)


def test_drag_outside_strip_detaches_to_floating_state(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    controller = window._workspace_controller
    host = window.workspace_tabs()
    strip = host.tabBar()
    dragged = window._tab_by_key["map_library"]
    start = strip.mapToGlobal(strip.tab_rect_for_index(host.indexOf(dragged)).center())
    outside = window.mapToGlobal(QPoint(window.width() + 220, window.height() + 140))

    assert controller.start_external_tab_drag(window, dragged, start, hot_spot=QPoint(12, 12)) is True
    controller.update_external_tab_drag(outside)
    qtbot.wait(20)
    owner = controller.window_by_widget.get(dragged)
    _debug_log(f"detach_floating owner={type(owner).__name__ if owner is not None else 'none'}")
    controller.finish_external_tab_drag(outside)
    qtbot.wait(20)

    assert owner is None


def test_drag_into_other_window_strip_attaches_tab(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    controller = window._workspace_controller
    main_host = window.workspace_tabs()
    dragged = window._tab_by_key["map_library"]
    anchor = window._tab_by_key["session_creator"]

    detached = controller.detach_widget_to_new_window(anchor, QPoint(560, 200))
    assert detached is not None
    detached_host = detached.workspace_tabs()
    detached_strip = detached_host.tabBar()

    start = main_host.tabBar().mapToGlobal(main_host.tabBar().tab_rect_for_index(main_host.indexOf(dragged)).center())
    outside = window.mapToGlobal(QPoint(window.width() + 180, window.height() + 120))
    attach_probe = detached_strip.mapToGlobal(
        QPoint(
            max(12, detached_strip.tab_rect_for_index(0).center().x()),
            detached_strip.height() // 2,
        )
    )

    assert controller.start_external_tab_drag(window, dragged, start, hot_spot=QPoint(12, 12)) is True
    controller.update_external_tab_drag(outside)
    qtbot.wait(20)
    assert controller.window_by_widget.get(dragged) is None
    controller.update_external_tab_drag(attach_probe)
    qtbot.wait(20)
    owner = controller.window_by_widget.get(dragged)
    controller.finish_external_tab_drag(attach_probe)
    qtbot.wait(20)

    _debug_log(
        "attach_other_window "
        f"owner_is_detached={int(owner is detached)} "
        f"detached_index={detached_host.indexOf(dragged)}"
    )
    assert owner is detached
    assert detached_host.indexOf(dragged) != -1


def test_drop_outside_creates_new_detached_window_with_only_dragged_tab(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    controller = window._workspace_controller
    host = window.workspace_tabs()
    strip = host.tabBar()
    dragged = window._tab_by_key["map_library"]
    start = strip.mapToGlobal(strip.tab_rect_for_index(host.indexOf(dragged)).center())
    outside = window.mapToGlobal(QPoint(window.width() + 260, window.height() + 180))

    assert controller.start_external_tab_drag(window, dragged, start, hot_spot=QPoint(12, 12)) is True
    controller.update_external_tab_drag(outside)
    qtbot.wait(20)
    assert controller.finish_external_tab_drag(outside) is True
    qtbot.wait(30)

    owner = controller.window_by_widget.get(dragged)
    _debug_log(
        "drop_outside_new_window "
        f"owner_is_main={int(owner is window)} "
        f"count={owner.workspace_tabs().count() if owner is not None else -1}"
    )
    assert owner is not None
    assert owner is not window
    assert owner.workspace_tabs().count() == 1
    assert owner.workspace_tabs().currentWidget() is dragged
