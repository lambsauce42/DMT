from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QWidget

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import MainLauncherWindow

pytestmark = pytest.mark.tier1

_DEBUG_LOG = Path(ROOT) / "debug" / "test_tab_workspace_close_veto.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


class _CloseVetoWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.close_event_calls = 0

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        self.close_event_calls += 1
        event.ignore()


def test_close_tab_respects_widget_close_veto(qtbot, monkeypatch) -> None:
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
    assert index > 0
    _debug_log(f"attempt-close key=close_veto_applet tab_index={index}")

    closed = window._workspace_controller.close_tab_by_index(window, index)
    _debug_log(
        "close-result "
        f"closed={closed} "
        f"tab_index_after={window.workspace_tabs().indexOf(widget)} "
        f"in_mapping={'close_veto_applet' in window._tab_by_key} "
        f"close_event_calls={widget.close_event_calls}"
    )

    assert closed is False
    assert window.workspace_tabs().indexOf(widget) != -1
    assert window._tab_by_key.get("close_veto_applet") is widget
    assert widget.close_event_calls >= 1


def test_close_all_tabs_stops_when_close_is_vetoed(qtbot, monkeypatch) -> None:
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

    controller = window._workspace_controller
    original_close = controller.close_tab_by_index
    calls = {"count": 0}

    def _guarded_close(*args, **kwargs):
        calls["count"] += 1
        _debug_log(f"close-all-call count={calls['count']}")
        if calls["count"] > 1:
            raise AssertionError("close_all_tabs_in_window retried close after veto")
        return original_close(*args, **kwargs)

    monkeypatch.setattr(controller, "close_tab_by_index", _guarded_close)
    controller.close_all_tabs_in_window(window)

    assert calls["count"] == 1
    assert "close_veto_applet" in window._tab_by_key
