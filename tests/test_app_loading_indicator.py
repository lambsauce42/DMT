import os
import sys

from PySide6.QtWidgets import QWidget

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import APPLET_DEFINITIONS, MainLauncherWindow


def test_open_applet_wraps_build_with_loading_indicator(qtbot, monkeypatch) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)

    calls: list[tuple[str, str]] = []

    def _show(message: str) -> None:
        calls.append(("show", str(message)))

    def _hide() -> None:
        calls.append(("hide", ""))

    def _build(key: str, applet: dict) -> QWidget:
        calls.append(("build", key))
        return QWidget(window.tabs)

    monkeypatch.setattr(window, "_show_applet_loading_overlay", _show)
    monkeypatch.setattr(window, "_hide_applet_loading_overlay", _hide)
    monkeypatch.setattr(window, "_build_applet_widget", _build)

    applet = next(item for item in APPLET_DEFINITIONS if item.get("key") == "item_creator")
    window.open_applet(applet, focus_if_new=True)

    assert calls[0][0] == "show"
    assert calls[1] == ("build", "item_creator")
    assert calls[-1][0] == "hide"


def test_open_applet_processes_events_before_build_for_loading_animation(
    qtbot, monkeypatch
) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)

    order: list[str] = []

    def _process_events(*args, **kwargs) -> None:
        order.append("process")

    def _build(key: str, applet: dict) -> QWidget:
        order.append("build")
        return QWidget(window.tabs)

    monkeypatch.setattr("app.QApplication.processEvents", _process_events)
    monkeypatch.setattr(window, "_build_applet_widget", _build)

    applet = next(item for item in APPLET_DEFINITIONS if item.get("key") == "item_creator")
    window.open_applet(applet, focus_if_new=True)

    assert "process" in order
    assert "build" in order
    assert order.index("process") < order.index("build")
