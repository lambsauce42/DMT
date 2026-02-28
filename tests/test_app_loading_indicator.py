import os
import sys
from pathlib import Path

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


def test_open_applet_does_not_pump_events_while_preparing_loading_indicator(
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

    assert order == ["build"]


def test_open_applet_overlay_is_visible_before_build_starts(qtbot, monkeypatch) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)

    spinner = window._loading_overlay._spinner
    build_trace: dict[str, object] = {}

    def _build(key: str, applet: dict) -> QWidget:
        build_trace["overlay_hidden"] = window._loading_overlay.isHidden()
        build_trace["spinner_active"] = spinner._timer.isActive()
        build_trace["message"] = window._loading_overlay._label.text()
        return QWidget(window.tabs)

    monkeypatch.setattr(window, "_build_applet_widget", _build)

    applet = next(item for item in APPLET_DEFINITIONS if item.get("key") == "item_creator")
    window.open_applet(applet, focus_if_new=True)

    debug_path = Path(ROOT) / "debug" / "applet_spinner_test.log"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    with debug_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "[debug] overlay-before-build probe "
            f"overlay_hidden={int(bool(build_trace['overlay_hidden']))} "
            f"spinner_active={int(bool(build_trace['spinner_active']))} "
            f"message={str(build_trace['message'])!r}\n"
        )

    assert build_trace["overlay_hidden"] is False
    assert build_trace["spinner_active"] is True
    assert build_trace["message"] == "Loading Item Creator..."
