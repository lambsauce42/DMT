import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QTabBar

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import APPLET_DEFINITIONS, MainLauncherWindow

pytestmark = pytest.mark.tier1

_DEBUG_LOG = Path(ROOT) / "debug" / "test_tab_workspace_drag_instability_regressions.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def _applet(key: str) -> dict[str, object]:
    return next(a for a in APPLET_DEFINITIONS if str(a.get("key")) == key)


def _open_drag_probe_window(qtbot) -> MainLauncherWindow:
    window = MainLauncherWindow()
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.open_applet(_applet("map_library"), focus_if_new=True)
    window.open_applet(_applet("session_creator"), focus_if_new=True)
    window.open_applet(_applet("npc_database"), focus_if_new=True)
    qtbot.wait(30)
    return window


def test_external_attach_neighbor_push_moves_in_small_continuous_steps(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = _open_drag_probe_window(qtbot)
    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    dragged_widget = window._tab_by_key["map_library"]
    observed_widget = window._tab_by_key["session_creator"]

    detached = controller.detach_widget_to_new_window(dragged_widget, QPoint(520, 220))
    assert detached is not None
    detached_bar = detached.workspace_tabs().tabBar()
    start = detached_bar.mapToGlobal(detached_bar.tabRect(0).center())
    assert controller.start_external_tab_drag(detached, dragged_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)

    overlay_x: list[int] = []
    close_x: list[int] = []
    for x in range(30, tabs.width() - 16, 8):
        probe = tabs.mapToGlobal(QPoint(x, max(2, bar.height() // 2)))
        controller.update_external_tab_drag(probe)
        qtbot.wait(8)
        index = tabs.indexOf(observed_widget)
        if index == -1:
            continue
        overlay = getattr(bar, "_title_overlay_by_index", {}).get(index)
        if overlay is not None and overlay.isVisible():
            overlay_x.append(int(overlay.geometry().x()))
        close_btn = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if close_btn is not None and close_btn.isVisible():
            close_x.append(int(close_btn.geometry().x()))

    controller.finish_external_tab_drag(
        tabs.mapToGlobal(QPoint(max(20, tabs.width() // 2), max(2, bar.height() // 2)))
    )
    qtbot.wait(20)

    unique_overlay = sorted(set(overlay_x))
    overlay_jumps = [abs(b - a) for a, b in zip(overlay_x, overlay_x[1:])]
    max_jump = max(overlay_jumps) if overlay_jumps else 0
    _debug_log(
        "external_neighbor_push_continuity "
        f"samples={len(overlay_x)} unique={len(unique_overlay)} "
        f"max_jump={max_jump} overlay={overlay_x[:60]} close={close_x[:60]}"
    )

    assert len(overlay_x) >= 20
    assert len(unique_overlay) >= 8, (
        "External attach drag still snap-moves neighbor titles instead of continuous push motion."
    )
    assert max_jump <= 24, (
        "External attach drag produced coarse single-frame title jumps (slot snapping)."
    )


@pytest.mark.parametrize("mode", ["same_window", "detached_reintegrated"])
def test_tab_title_overlays_stay_visible_and_near_native_tabs_during_drag(qtbot, mode: str) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = _open_drag_probe_window(qtbot)
    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    dragged_widget = window._tab_by_key["map_library"]

    missing_samples: list[str] = []
    large_offset_samples: list[str] = []

    def sample(stage: str, x: int) -> None:
        for index in range(tabs.count()):
            widget = tabs.widget(index)
            if widget is dragged_widget:
                continue
            rect = bar.tabRect(index)
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            overlay = getattr(bar, "_title_overlay_by_index", {}).get(index)
            if overlay is None or not overlay.isVisible() or not overlay.text().strip():
                missing_samples.append(f"{stage}:x={x}:idx={index}:missing")
                continue
            offset = abs(int(overlay.geometry().x()) - int(rect.x()))
            if offset > 96:
                large_offset_samples.append(
                    f"{stage}:x={x}:idx={index}:offset={offset}:rect_x={int(rect.x())}:overlay_x={int(overlay.geometry().x())}"
                )

    y = max(2, bar.height() // 2)
    path = list(range(max(18, tabs.width() - 24), 18, -10))

    if mode == "same_window":
        start = bar.tabRect(tabs.indexOf(dragged_widget)).center()
        qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
        qtbot.wait(12)
        for x in path:
            qtbot.mouseMove(bar, QPoint(x, y))
            qtbot.wait(8)
            sample("same_window", x)
        qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(path[-1], y))
        qtbot.wait(20)
    else:
        detached = controller.detach_widget_to_new_window(dragged_widget, QPoint(520, 220))
        assert detached is not None
        detached_bar = detached.workspace_tabs().tabBar()
        start = detached_bar.mapToGlobal(detached_bar.tabRect(0).center())
        assert controller.start_external_tab_drag(detached, dragged_widget, start) is True
        controller.update_external_tab_drag(QPoint(-1200, -900))
        qtbot.wait(20)
        for x in path:
            probe = tabs.mapToGlobal(QPoint(x, y))
            controller.update_external_tab_drag(probe)
            qtbot.wait(8)
            sample("detached_reintegrated", x)
        controller.finish_external_tab_drag(tabs.mapToGlobal(QPoint(path[-1], y)))
        qtbot.wait(20)

    _debug_log(
        "tab_overlay_visibility_alignment "
        f"mode={mode} missing={missing_samples[:24]} large_offsets={large_offset_samples[:24]}"
    )

    assert not missing_samples, (
        "Tab title overlays disappeared during drag transitions, producing stuck/missing title artifacts."
    )
    assert not large_offset_samples, (
        "Tab title overlays drifted far from native tab geometry during drag transitions."
    )


def test_external_drag_near_bottom_strip_boundary_does_not_flap_attach_state(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = _open_drag_probe_window(qtbot)
    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    dragged_widget = window._tab_by_key["map_library"]
    anchor_widget = window._tab_by_key["session_creator"]

    detached = controller.detach_widget_to_new_window(dragged_widget, QPoint(520, 220))
    assert detached is not None
    detached_bar = detached.workspace_tabs().tabBar()
    start = detached_bar.mapToGlobal(detached_bar.tabRect(0).center())
    assert controller.start_external_tab_drag(detached, dragged_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)

    x = bar.tabRect(tabs.indexOf(anchor_widget)).center().x()
    y_inside = bar.height() + 39
    y_outside = bar.height() + 43
    inside = tabs.mapToGlobal(QPoint(x, y_inside))
    outside = tabs.mapToGlobal(QPoint(x, y_outside))

    attached_samples: list[int] = []
    for step in range(34):
        probe = inside if (step % 2 == 0) else outside
        controller.update_external_tab_drag(probe)
        qtbot.wait(8)
        attached = int(controller.window_by_widget.get(dragged_widget) is window)
        attached_samples.append(attached)

    controller.finish_external_tab_drag(inside)
    qtbot.wait(20)

    transitions = sum(
        1 for previous, current in zip(attached_samples, attached_samples[1:]) if previous != current
    )
    _debug_log(
        "external_boundary_flap_probe "
        f"attached_samples={attached_samples} transitions={transitions} "
        f"inside_y={y_inside} outside_y={y_outside}"
    )

    assert attached_samples, "Did not capture attach-state samples near strip boundary."
    assert transitions <= 6, (
        "External drag rapidly flapped between attached and detached states near the strip boundary."
    )


def test_clicking_tabs_does_not_shift_overlay_text_against_tab_anchor(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = _open_drag_probe_window(qtbot)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()

    def sample_offsets() -> dict[int, int]:
        offsets: dict[int, int] = {}
        overlays = getattr(bar, "_title_overlay_by_index", {})
        for index in range(tabs.count()):
            rect = bar.tabRect(index)
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            overlay = overlays.get(index)
            if overlay is None or not overlay.isVisible():
                continue
            offsets[index] = int(overlay.geometry().x()) - int(rect.x())
        return offsets

    qtbot.wait(20)
    before = sample_offsets()

    for key in ("session_creator", "npc_database", "map_library"):
        widget = window._tab_by_key[key]
        index = tabs.indexOf(widget)
        assert index != -1
        qtbot.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(index).center())
        qtbot.wait(20)

    after = sample_offsets()
    shared = sorted(set(before).intersection(after))
    deltas = {idx: abs(after[idx] - before[idx]) for idx in shared}
    _debug_log(f"click_shift_probe before={before} after={after} deltas={deltas}")

    assert shared, "No overlay offset samples captured for click-shift probe."
    assert all(delta <= 2 for delta in deltas.values()), (
        "Click-only tab selection shifted overlay text relative to the tab anchor/underline."
    )


def test_click_after_home_hover_drag_keeps_overlay_anchor_stable(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = _open_drag_probe_window(qtbot)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    dragged_widget = window._tab_by_key["map_library"]

    start = bar.tabRect(tabs.indexOf(dragged_widget)).center()
    home_rect = bar.tabRect(0)
    home_probe = QPoint(max(2, home_rect.left() + 2), start.y())
    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    qtbot.wait(12)
    for x in range(start.x(), home_probe.x(), -10):
        qtbot.mouseMove(bar, QPoint(x, start.y()))
        qtbot.wait(6)
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=home_probe)
    qtbot.wait(30)

    def sample_offsets() -> dict[int, int]:
        offsets: dict[int, int] = {}
        overlays = getattr(bar, "_title_overlay_by_index", {})
        for index in range(tabs.count()):
            rect = bar.tabRect(index)
            overlay = overlays.get(index)
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            if overlay is None or not overlay.isVisible():
                continue
            offsets[index] = int(overlay.geometry().x()) - int(rect.x())
        return offsets

    before = sample_offsets()
    session_idx = tabs.indexOf(window._tab_by_key["session_creator"])
    qtbot.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(session_idx).center())
    qtbot.wait(20)
    after = sample_offsets()

    shared = sorted(set(before).intersection(after))
    deltas = {idx: abs(after[idx] - before[idx]) for idx in shared}
    _debug_log(f"click_after_home_hover_probe before={before} after={after} deltas={deltas}")

    assert shared, "No offset samples captured after home-hover drag click probe."
    assert all(delta <= 2 for delta in deltas.values()), (
        "Tab click shifted overlay text/x anchor after hovering drag over Home."
    )


def test_click_after_external_reintegrated_drag_keeps_overlay_anchor_stable(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = _open_drag_probe_window(qtbot)
    controller = window._workspace_controller
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    dragged_widget = window._tab_by_key["map_library"]

    detached = controller.detach_widget_to_new_window(dragged_widget, QPoint(520, 220))
    assert detached is not None
    detached_bar = detached.workspace_tabs().tabBar()
    start = detached_bar.mapToGlobal(detached_bar.tabRect(0).center())
    assert controller.start_external_tab_drag(detached, dragged_widget, start) is True
    controller.update_external_tab_drag(QPoint(-1200, -900))
    qtbot.wait(20)

    for x in range(24, tabs.width() - 20, 14):
        probe = tabs.mapToGlobal(QPoint(x, max(2, bar.height() // 2)))
        controller.update_external_tab_drag(probe)
        qtbot.wait(6)
    drop = tabs.mapToGlobal(QPoint(max(30, tabs.width() // 2), max(2, bar.height() // 2)))
    controller.finish_external_tab_drag(drop)
    qtbot.wait(30)

    def sample_offsets() -> dict[int, int]:
        offsets: dict[int, int] = {}
        overlays = getattr(bar, "_title_overlay_by_index", {})
        for index in range(tabs.count()):
            rect = bar.tabRect(index)
            overlay = overlays.get(index)
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            if overlay is None or not overlay.isVisible():
                continue
            offsets[index] = int(overlay.geometry().x()) - int(rect.x())
        return offsets

    before = sample_offsets()
    npc_idx = tabs.indexOf(window._tab_by_key["npc_database"])
    qtbot.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(npc_idx).center())
    qtbot.wait(20)
    after = sample_offsets()

    shared = sorted(set(before).intersection(after))
    deltas = {idx: abs(after[idx] - before[idx]) for idx in shared}
    _debug_log(f"click_after_external_probe before={before} after={after} deltas={deltas}")

    assert shared, "No offset samples captured after external reintegrated drag click probe."
    assert all(delta <= 2 for delta in deltas.values()), (
        "Tab click shifted overlay text/x anchor after detached->reintegrated drag."
    )


def test_plain_press_without_drag_does_not_shift_tab_overlay_text_x(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = _open_drag_probe_window(qtbot)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    target_idx = tabs.indexOf(window._tab_by_key["session_creator"])
    assert target_idx != -1

    def offset_for(index: int) -> int:
        overlay = getattr(bar, "_title_overlay_by_index", {}).get(index)
        assert overlay is not None and overlay.isVisible()
        rect = bar.tabRect(index)
        return int(overlay.geometry().x()) - int(rect.x())

    qtbot.wait(20)
    before = offset_for(target_idx)
    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(target_idx).center())
    qtbot.wait(20)
    during_press = offset_for(target_idx)
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(target_idx).center())
    qtbot.wait(20)
    after = offset_for(target_idx)

    _debug_log(
        "plain_press_shift_probe "
        f"idx={target_idx} before={before} during_press={during_press} after={after}"
    )

    assert abs(during_press - before) <= 2, (
        "Plain tab press (without drag) shifted title overlay x position."
    )
    assert abs(after - before) <= 2


def test_internal_drag_start_does_not_jump_overlay_text_x(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = _open_drag_probe_window(qtbot)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    target_widget = window._tab_by_key["session_creator"]
    target_idx = tabs.indexOf(target_widget)
    assert target_idx != -1

    def offset_for(index: int) -> int:
        overlay = getattr(bar, "_title_overlay_by_index", {}).get(index)
        assert overlay is not None and overlay.isVisible()
        rect = bar.tabRect(index)
        return int(overlay.geometry().x()) - int(rect.x())

    start = bar.tabRect(target_idx).center()
    before = offset_for(target_idx)
    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    qtbot.wait(10)
    qtbot.mouseMove(bar, QPoint(start.x() + 6, start.y()))
    qtbot.wait(20)
    current_idx = tabs.indexOf(target_widget)
    assert current_idx != -1
    after_first_drag = offset_for(current_idx)
    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(start.x() + 6, start.y()))
    qtbot.wait(20)

    _debug_log(
        "internal_drag_start_jump_probe "
        f"before={before} after_first_drag={after_first_drag} current_idx={current_idx}"
    )
    assert abs(after_first_drag - before) <= 4, (
        "Internal drag start caused an immediate title-overlay x jump."
    )


def test_internal_drag_release_does_not_pop_overlay_text_x(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = _open_drag_probe_window(qtbot)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    target_widget = window._tab_by_key["session_creator"]
    target_idx = tabs.indexOf(target_widget)
    assert target_idx != -1
    start = bar.tabRect(target_idx).center()

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    qtbot.wait(10)
    qtbot.mouseMove(bar, QPoint(start.x() + 120, start.y()))
    qtbot.wait(25)

    drag_idx = tabs.indexOf(target_widget)
    assert drag_idx != -1
    drag_overlay = getattr(bar, "_title_overlay_by_index", {}).get(drag_idx)
    assert drag_overlay is not None and drag_overlay.isVisible()
    x_pre_release = int(drag_overlay.geometry().x())

    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(start.x() + 120, start.y()))
    qtbot.wait(8)

    x_samples: list[int] = []
    for _ in range(8):
        idx = tabs.indexOf(target_widget)
        if idx == -1:
            qtbot.wait(12)
            continue
        overlay = getattr(bar, "_title_overlay_by_index", {}).get(idx)
        if overlay is not None and overlay.isVisible():
            x_samples.append(int(overlay.geometry().x()))
        qtbot.wait(12)

    assert x_samples, "No post-release overlay samples captured."
    immediate_jump = abs(x_samples[0] - x_pre_release)
    _debug_log(
        "internal_release_pop_probe "
        f"x_pre_release={x_pre_release} x_samples={x_samples} immediate_jump={immediate_jump}"
    )

    assert immediate_jump <= 20, "Internal drag release popped title overlay x in a single frame."
    assert len(set(x_samples)) >= 2, (
        "Internal drag release snapped title overlay directly to final position without settle."
    )


def test_internal_drag_overlay_stays_near_native_selected_tab_anchor(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    window = _open_drag_probe_window(qtbot)
    tabs = window.workspace_tabs()
    bar = tabs.tabBar()
    target_widget = window._tab_by_key["session_creator"]
    target_idx = tabs.indexOf(target_widget)
    assert target_idx != -1
    start = bar.tabRect(target_idx).center()

    qtbot.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    qtbot.wait(12)

    offsets: list[int] = []
    for x in range(start.x(), start.x() + 300, 6):
        qtbot.mouseMove(bar, QPoint(x, start.y()))
        qtbot.wait(8)
        idx = tabs.indexOf(target_widget)
        if idx == -1:
            continue
        overlay = getattr(bar, "_title_overlay_by_index", {}).get(idx)
        if overlay is None or not overlay.isVisible():
            continue
        rect = bar.tabRect(idx)
        offsets.append(int(overlay.geometry().x()) - int(rect.x()))

    qtbot.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(start.x() + 300, start.y()))
    qtbot.wait(20)

    _debug_log(
        "internal_drag_anchor_drift_probe "
        f"samples={len(offsets)} min={min(offsets) if offsets else 'na'} max={max(offsets) if offsets else 'na'} "
        f"offsets={offsets[:80]}"
    )
    assert offsets, "No drag offset samples captured."
    assert max(abs(v - 20) for v in offsets) <= 48, (
        "Dragged tab title drifted too far from its native selected-tab anchor (blue underline)."
    )
