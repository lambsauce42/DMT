import os
import socket
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import MainLauncherWindow
from online_session.server import OnlineSessionServer

pytestmark = pytest.mark.tier2

_DEBUG_LOG = Path(ROOT) / "debug" / "test_workspace_tabs_online_cleanup.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _host_applet(port: int) -> dict[str, object]:
    return {
        "key": f"online_host::{port}::workspace::{port}",
        "tab": "Host Workspace",
        "title": "Online Host",
        "subtitle": f"Port {port}",
        "actions": [],
        "panels": [],
        "online": {
            "port": int(port),
            "collection_path": "",
        },
    }


def test_closing_online_host_tab_releases_listen_port(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    port = _free_tcp_port()
    applet = _host_applet(port)
    host_key = str(applet["key"])

    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(applet, focus_if_new=True)
    qtbot.waitUntil(lambda: host_key in window._tab_by_key, timeout=5000)

    host_widget = window._tab_by_key[host_key]
    tab_index = window.workspace_tabs().indexOf(host_widget)
    assert tab_index > 0
    window._workspace_controller.close_tab_by_index(window, tab_index)
    QApplication.processEvents()
    qtbot.wait(60)

    probe = OnlineSessionServer()
    ok, err = probe.start(port)
    _debug_log(f"close_host_port ok={ok} err={err!r}")
    try:
        assert ok, f"Port {port} remained occupied after host tab close: {err}"
    finally:
        if ok:
            probe.stop()


def test_closing_primary_window_closes_detached_and_releases_port(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    port = _free_tcp_port()
    applet = _host_applet(port)
    host_key = str(applet["key"])

    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_applet(applet, focus_if_new=True)
    qtbot.waitUntil(lambda: host_key in window._tab_by_key, timeout=5000)

    host_widget = window._tab_by_key[host_key]
    detached = window._workspace_controller.detach_widget_to_new_window(host_widget, QPoint(360, 220))
    assert detached is not None
    window.close()
    QApplication.processEvents()
    qtbot.wait(80)

    probe = OnlineSessionServer()
    ok, err = probe.start(port)
    _debug_log(f"close_primary_with_detached ok={ok} err={err!r} detached_visible={detached.isVisible()}")
    try:
        assert ok, f"Port {port} remained occupied after primary close with detached host: {err}"
    finally:
        if ok:
            probe.stop()
