import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QWidget

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import APPLET_DEFINITIONS, DeferredAppletHost, MainLauncherWindow


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
    assert build_trace["message"] == "Loading Items..."


def test_open_applet_does_not_pump_events_during_busy_build(qtbot, monkeypatch) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)

    order: list[str] = []

    def _build(key: str, applet: dict) -> QWidget:
        order.append(f"build:{key}")
        return QWidget(window.tabs)

    def _process_events(*args, **kwargs) -> None:
        _ = (args, kwargs)
        order.append("process")

    monkeypatch.setattr("app.QApplication.processEvents", _process_events)
    monkeypatch.setattr(window, "_build_applet_widget", _build)

    applet = next(item for item in APPLET_DEFINITIONS if item.get("key") == "item_creator")
    window.open_applet(applet, focus_if_new=True)

    assert order == ["build:item_creator"]


def test_player_sheets_builds_directly_while_spinner_is_active(qtbot, monkeypatch) -> None:
    window = MainLauncherWindow()
    qtbot.addWidget(window)

    spinner = window._loading_overlay._spinner
    spinner.start()
    calls: list[str] = []

    def _direct_build(key: str, applet: dict) -> QWidget:
        calls.append(f"direct:{key}")
        return QWidget(window.tabs)

    monkeypatch.setattr(window, "_build_applet_widget", _direct_build)

    applet = next(item for item in APPLET_DEFINITIONS if item.get("key") == "player_sheets")
    window.build_applet_widget(str(applet["key"]), applet)

    spinner.stop()

    assert calls == ["direct:player_sheets"]


def test_open_applet_blocks_other_opens_until_deferred_widget_is_ready(qtbot, monkeypatch) -> None:
    class _DeferredWidget(QWidget):
        appletReady = Signal()
        appletFailed = Signal(str)

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._loading = True

        def is_loading(self) -> bool:
            return self._loading

        def mark_ready(self) -> None:
            self._loading = False
            self.appletReady.emit()

    window = MainLauncherWindow()
    qtbot.addWidget(window)

    deferred = _DeferredWidget(window.tabs)
    built: list[str] = []

    def _build(key: str, applet: dict) -> QWidget:
        built.append(str(key))
        if key == "item_creator":
            return deferred
        return QWidget(window.tabs)

    monkeypatch.setattr(window, "_build_applet_widget", _build)

    item_applet = next(item for item in APPLET_DEFINITIONS if item.get("key") == "item_creator")
    maps_applet = next(item for item in APPLET_DEFINITIONS if item.get("key") == "map_library")

    window.open_applet(item_applet, focus_if_new=True)
    window.workspace_tabs().setCurrentIndex(0)
    window.open_applet(maps_applet, focus_if_new=True)

    assert built == ["item_creator"]

    deferred.mark_ready()
    qtbot.waitUntil(lambda: window.workspace_tabs().currentWidget() is deferred)

    window.open_applet(maps_applet, focus_if_new=True)

    assert built == ["item_creator", "map_library"]


def test_deferred_applet_host_waits_for_standardized_startup_completion(qtbot) -> None:
    class _PhasedApplet(QWidget):
        startupFinished = Signal()
        startupStatusChanged = Signal(str)

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.started = False
            self.pending = True

        def startup_in_progress(self) -> bool:
            return self.pending

        def begin_startup(self) -> None:
            self.started = True
            self.startupStatusChanged.emit("Phase 1...")
            QTimer.singleShot(0, self._finish_startup)

        def _finish_startup(self) -> None:
            self.pending = False
            self.startupFinished.emit()

    host = DeferredAppletHost(
        "Phased",
        load_fn=lambda: {"ok": True},
        build_fn=lambda parent, payload: _PhasedApplet(parent),
    )
    qtbot.addWidget(host)

    assert host.is_loading() is True
    qtbot.waitUntil(lambda: host.is_loading() is False)

    assert host._overlay.isHidden() is True
    assert isinstance(host._inner_widget, _PhasedApplet)
    assert host._inner_widget.started is True


def test_external_loading_indicator_keeps_ticking_during_blocking_encounter_open(
    qtbot, monkeypatch, tmp_path
) -> None:
    heartbeat_path = tmp_path / "loading_indicator_heartbeat.log"
    monkeypatch.setenv("DMT_TEST_EXTERNAL_LOADING_INDICATOR", "1")
    monkeypatch.setenv("DMT_LOADING_INDICATOR_HEARTBEAT_PATH", str(heartbeat_path))

    class _BlockingEncounterPanel(QWidget):
        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            time.sleep(0.9)

    monkeypatch.setattr("app.EncounterPanel", _BlockingEncounterPanel)

    window = MainLauncherWindow()
    qtbot.addWidget(window)

    applet = next(item for item in APPLET_DEFINITIONS if item.get("key") == "encounter_creator")
    window.open_applet(applet, focus_if_new=True)

    assert heartbeat_path.exists()
    lines = heartbeat_path.read_text(encoding="utf-8").splitlines()
    tick_count = sum(1 for line in lines if line.startswith("tick "))
    assert tick_count >= 2
