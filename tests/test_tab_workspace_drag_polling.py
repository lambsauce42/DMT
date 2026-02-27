import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import APPLET_DEFINITIONS, MainLauncherWindow
import tab_workspace

pytestmark = pytest.mark.tier1

_DEBUG_LOG = Path(ROOT) / "debug" / "test_tab_workspace_drag_polling.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def _applet(key: str) -> dict[str, object]:
    return next(a for a in APPLET_DEFINITIONS if str(a.get("key")) == key)


def test_external_drag_from_closed_source_tracks_cursor_without_in_app_mousemove(
    qtbot, monkeypatch
) -> None:
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
    session_widget = window._tab_by_key["session_creator"]
    cursor_pos = {"value": QPoint(-1200, -900)}
    monkeypatch.setattr(
        tab_workspace.QCursor,
        "pos",
        staticmethod(lambda: QPoint(cursor_pos["value"])),
    )

    detached = controller.detach_widget_to_new_window(map_widget, QPoint(560, 220))
    assert detached is not None
    start = detached.workspace_tabs().tabBar().mapToGlobal(
        detached.workspace_tabs().tabBar().tabRect(0).center()
    )
    assert (
        controller.start_external_tab_drag(
            detached,
            map_widget,
            start,
            hot_spot=QPoint(8, 8),
        )
        is True
    )

    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(60)
    assert controller.window_by_widget.get(map_widget) is None
    assert detached.isVisible() is False

    target_idx = tabs.indexOf(session_widget)
    polled_target = tabs.mapToGlobal(
        QPoint(bar.tabRect(target_idx).center().x(), bar.height() + 20)
    )
    cursor_pos["value"] = QPoint(polled_target)

    try:
        qtbot.waitUntil(
            lambda: controller.window_by_widget.get(map_widget) is window,
            timeout=250,
        )
    except Exception:
        _debug_log(
            "polling_attach_timeout "
            f"owner_exists={controller.window_by_widget.get(map_widget) is not None} "
            f"owner_is_main={controller.window_by_widget.get(map_widget) is window} "
            f"map_index={tabs.indexOf(map_widget)}"
        )
        raise

    _debug_log(
        "polling_attach_success "
        f"owner_is_main={controller.window_by_widget.get(map_widget) is window} "
        f"map_index={tabs.indexOf(map_widget)}"
    )
    assert tabs.indexOf(map_widget) != -1
