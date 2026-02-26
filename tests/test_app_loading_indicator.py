import os
import sys
import time
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


def test_open_applet_spinner_ticks_while_build_is_busy(qtbot, monkeypatch) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)

    spinner = window._loading_overlay._spinner
    tick_counter = {"count": 0}
    spinner._timer.timeout.connect(lambda: tick_counter.__setitem__("count", tick_counter["count"] + 1))
    build_trace: dict[str, float] = {}

    def _build(key: str, applet: dict) -> QWidget:
        build_trace["start_ticks"] = float(tick_counter["count"])
        build_trace["start_angle"] = float(spinner._angle)
        start = time.perf_counter()
        end = start + 0.45
        work = 0
        while time.perf_counter() < end:
            work = (work + 3) ^ 0x55AA
        build_trace["duration_ms"] = (time.perf_counter() - start) * 1000.0
        build_trace["end_ticks"] = float(tick_counter["count"])
        build_trace["end_angle"] = float(spinner._angle)
        return QWidget(window.tabs)

    monkeypatch.setattr(window, "_build_applet_widget", _build)

    applet = next(item for item in APPLET_DEFINITIONS if item.get("key") == "item_creator")
    window.open_applet(applet, focus_if_new=True)

    ticks_during_build = int(build_trace["end_ticks"] - build_trace["start_ticks"])
    debug_path = Path(ROOT) / "debug" / "applet_spinner_test.log"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    with debug_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "[debug] spinner busy-build probe "
            f"ticks_during_build={ticks_during_build} "
            f"start_angle={int(build_trace['start_angle'])} "
            f"end_angle={int(build_trace['end_angle'])} "
            f"duration_ms={build_trace['duration_ms']:.1f}\n"
        )

    assert ticks_during_build >= 1
