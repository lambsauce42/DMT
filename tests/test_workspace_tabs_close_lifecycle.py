from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QWidget

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import APPLET_DEFINITIONS, MainLauncherWindow

_DEBUG_LOG = Path(ROOT) / "debug" / "test_workspace_tabs_close_lifecycle.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def _applet(key: str) -> dict[str, object]:
    return next(a for a in APPLET_DEFINITIONS if str(a.get("key")) == key)


class _CloseVetoWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.close_calls = 0

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        self.close_calls += 1
        event.ignore()


def test_close_veto_is_respected(qtbot, monkeypatch) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    applet = {
        "key": "close_veto_applet",
        "tab": "Close Veto",
        "title": "Close Veto",
        "actions": [],
        "panels": [],
    }
    monkeypatch.setattr(window, "_build_applet_widget", lambda key, _: _CloseVetoWidget(window.tabs))
    window.open_applet(applet, focus_if_new=True)

    widget = window._tab_by_key["close_veto_applet"]
    index = window.workspace_tabs().indexOf(widget)
    closed = window._workspace_controller.close_tab_by_index(window, index)

    _debug_log(
        "close_veto "
        f"closed={int(bool(closed))} index_after={window.workspace_tabs().indexOf(widget)} "
        f"calls={widget.close_calls}"
    )
    assert closed is False
    assert window.workspace_tabs().indexOf(widget) != -1
    assert widget.close_calls >= 1


def test_window_close_veto_is_respected_during_shutdown(qtbot, monkeypatch) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    applet = {
        "key": "close_veto_applet",
        "tab": "Close Veto",
        "title": "Close Veto",
        "actions": [],
        "panels": [],
    }
    monkeypatch.setattr(window, "_build_applet_widget", lambda key, _: _CloseVetoWidget(window.tabs))
    window.open_applet(applet, focus_if_new=True)

    widget = window._tab_by_key["close_veto_applet"]
    closed = window.close()

    _debug_log(
        "window_close_veto "
        f"closed={int(bool(closed))} visible={int(window.isVisible())} "
        f"registered={int('close_veto_applet' in window._tab_by_key)} calls={widget.close_calls}"
    )
    assert closed is False
    assert window.isVisible() is True
    assert "close_veto_applet" in window._tab_by_key
    assert widget.close_calls >= 1


def test_closing_last_tab_in_detached_window_closes_window(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)

    controller = window._workspace_controller
    dragged = window._tab_by_key["map_library"]
    detached = controller.detach_widget_to_new_window(dragged, QPoint(420, 220))
    assert detached is not None
    detached_host = detached.workspace_tabs()
    assert detached_host.count() == 1

    closed = controller.close_tab_by_index(detached, 0)
    qtbot.waitUntil(lambda: not detached.isVisible(), timeout=1200)
    _debug_log(
        "close_last_detached "
        f"closed={int(bool(closed))} detached_visible={int(detached.isVisible())} count={detached_host.count()}"
    )
    assert closed is True
    assert detached.isVisible() is False
