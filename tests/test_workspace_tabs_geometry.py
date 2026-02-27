import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QLabel, QWidget

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from tab_workspace import (
    TAB_CLOSE_GAP,
    TAB_CLOSE_RIGHT_PADDING,
    TAB_CLOSE_SIZE,
    WorkspaceTabsHost,
    compute_workspace_tab_close_rect,
    compute_workspace_tab_name_rect,
    compute_workspace_tab_width,
)

pytestmark = pytest.mark.tier0

_DEBUG_LOG = Path(ROOT) / "debug" / "test_workspace_tabs_geometry.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def test_tab_width_reserves_close_region(qapp) -> None:
    _ = qapp
    label = QLabel()
    fm = label.fontMetrics()
    with_close = compute_workspace_tab_width(fm, "Session Creator", closable=True)
    no_close = compute_workspace_tab_width(fm, "Session Creator", closable=False)
    delta = int(with_close - no_close)
    expected_min = TAB_CLOSE_SIZE + TAB_CLOSE_RIGHT_PADDING + TAB_CLOSE_GAP
    _debug_log(f"width_delta with_close={with_close} no_close={no_close} delta={delta}")
    assert delta >= expected_min


def test_name_rect_is_left_of_close_button() -> None:
    rect = QRect(10, 2, 220, 32)
    close_rect = compute_workspace_tab_close_rect(rect)
    name_rect = compute_workspace_tab_name_rect(rect, closable=True)
    _debug_log(
        "name_close_layout "
        f"name=({name_rect.x()},{name_rect.y()},{name_rect.width()},{name_rect.height()}) "
        f"close=({close_rect.x()},{close_rect.y()},{close_rect.width()},{close_rect.height()})"
    )
    assert name_rect.right() < close_rect.left()


def test_active_line_visibility_tracks_current_tab(qtbot) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    host = WorkspaceTabsHost()
    qtbot.addWidget(host)
    host.resize(900, 600)
    host.show()
    host.addTab(QWidget(), "Home", closable=False, pinned=True)
    host.addTab(QWidget(), "Maps")
    host.addTab(QWidget(), "Session")
    host.setCurrentIndex(0)
    strip = host.tabBar()
    qtbot.wait(20)

    first = strip.active_line_visible_for_index(0)
    second_before = strip.active_line_visible_for_index(1)
    host.setCurrentIndex(1)
    qtbot.wait(20)
    first_after = strip.active_line_visible_for_index(0)
    second_after = strip.active_line_visible_for_index(1)
    _debug_log(
        "active_line "
        f"first={int(first)} second_before={int(second_before)} "
        f"first_after={int(first_after)} second_after={int(second_after)}"
    )
    assert first is True
    assert second_before is False
    assert first_after is False
    assert second_after is True
