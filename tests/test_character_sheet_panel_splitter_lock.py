import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from ui.character_sheet_panel import CharacterSheetPanel


class CharacterSheetPanelSplitterLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    @staticmethod
    def _apply_ratio(splitter: QSplitter, ratio: float) -> list[int]:
        sizes = splitter.sizes()
        total = sum(sizes)
        if total <= 2:
            return sizes
        primary = max(1, int(total * ratio))
        secondary = max(1, total - primary)
        splitter.setSizes([primary, secondary])
        QApplication.processEvents()
        return splitter.sizes()

    @staticmethod
    def _assert_sizes_close(
        test_case: unittest.TestCase,
        actual: list[int],
        expected: list[int],
        tolerance: int = 4,
    ) -> None:
        test_case.assertEqual(len(actual), len(expected))
        for a, e in zip(actual, expected):
            test_case.assertLessEqual(abs(a - e), tolerance)

    def _build_nested_splitter_harness(
        self,
    ) -> tuple[QWidget, CharacterSheetPanel, QSplitter, QSplitter]:
        host = QWidget()
        host.resize(2200, 980)
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        outer_splitter = QSplitter(Qt.Orientation.Horizontal, host)
        outer_splitter.setChildrenCollapsible(False)
        host_layout.addWidget(outer_splitter, 1)

        list_panel = QFrame(outer_splitter)
        right_container = QWidget(outer_splitter)
        right_layout = QHBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        detail_splitter = QSplitter(Qt.Orientation.Horizontal, right_container)
        detail_splitter.setChildrenCollapsible(False)
        right_layout.addWidget(detail_splitter, 1)

        sheet_panel = CharacterSheetPanel(detail_splitter)
        inventory_panel = QFrame(detail_splitter)
        detail_splitter.addWidget(sheet_panel)
        detail_splitter.addWidget(inventory_panel)

        outer_splitter.addWidget(list_panel)
        outer_splitter.addWidget(right_container)

        host.show()
        QApplication.processEvents()
        return host, sheet_panel, outer_splitter, detail_splitter

    def test_fit_width_restores_ancestor_splitters_after_relayout_drift(self) -> None:
        host, sheet_panel, outer_splitter, detail_splitter = self._build_nested_splitter_harness()
        try:
            outer_splitter.setSizes([420, 1680])
            detail_splitter.setSizes([1200, 480])
            QApplication.processEvents()

            baseline_outer = outer_splitter.sizes()
            baseline_detail = detail_splitter.sizes()

            drift_outer = self._apply_ratio(outer_splitter, 0.75)
            drift_detail = self._apply_ratio(detail_splitter, 0.35)
            self.assertNotEqual(drift_outer, baseline_outer)
            self.assertNotEqual(drift_detail, baseline_detail)

            outer_splitter.setSizes(baseline_outer)
            detail_splitter.setSizes(baseline_detail)
            QApplication.processEvents()

            original_set_fit_width = sheet_panel._viewer.set_fit_width

            def _drift_set_fit_width(_viewport_width: int) -> None:
                self._apply_ratio(outer_splitter, 0.75)
                self._apply_ratio(detail_splitter, 0.35)

            sheet_panel._viewer.set_fit_width = _drift_set_fit_width  # type: ignore[assignment]
            try:
                sheet_panel._fit_button.click()
                QTest.qWait(50)
                QApplication.processEvents()
            finally:
                sheet_panel._viewer.set_fit_width = original_set_fit_width  # type: ignore[assignment]

            self._assert_sizes_close(self, outer_splitter.sizes(), baseline_outer)
            self._assert_sizes_close(self, detail_splitter.sizes(), baseline_detail)
        finally:
            host.close()

    def test_fit_page_restores_ancestor_splitters_after_relayout_drift(self) -> None:
        host, sheet_panel, outer_splitter, detail_splitter = self._build_nested_splitter_harness()
        try:
            outer_splitter.setSizes([420, 1680])
            detail_splitter.setSizes([1200, 480])
            QApplication.processEvents()

            baseline_outer = outer_splitter.sizes()
            baseline_detail = detail_splitter.sizes()

            original_set_fit_page = sheet_panel._viewer.set_fit_page

            def _drift_set_fit_page(_viewport_width: int, _viewport_height: int) -> None:
                self._apply_ratio(outer_splitter, 0.74)
                self._apply_ratio(detail_splitter, 0.34)

            sheet_panel._viewer.set_fit_page = _drift_set_fit_page  # type: ignore[assignment]
            try:
                sheet_panel._fit_page_button.click()
                QTest.qWait(50)
                QApplication.processEvents()
            finally:
                sheet_panel._viewer.set_fit_page = original_set_fit_page  # type: ignore[assignment]

            self._assert_sizes_close(self, outer_splitter.sizes(), baseline_outer)
            self._assert_sizes_close(self, detail_splitter.sizes(), baseline_detail)
        finally:
            host.close()

    def test_viewport_resize_triggers_fit_width_sync(self) -> None:
        host, sheet_panel, _, _ = self._build_nested_splitter_harness()
        try:
            viewport = sheet_panel._scroll_area.viewport()
            viewport_width = viewport.width()
            calls: list[tuple[str, int]] = []

            original_set_viewport_width = sheet_panel._viewer.set_viewport_width
            original_update_fit_width = sheet_panel._viewer.update_fit_width
            sheet_panel._fit_width_enabled = True
            sheet_panel._fit_page_enabled = False

            def _record_set_viewport_width(width: int) -> None:
                calls.append(("set_viewport_width", width))

            def _record_update_fit_width(width: int) -> None:
                calls.append(("update_fit_width", width))

            sheet_panel._viewer.set_viewport_width = _record_set_viewport_width  # type: ignore[assignment]
            sheet_panel._viewer.update_fit_width = _record_update_fit_width  # type: ignore[assignment]
            try:
                resize_event = QResizeEvent(viewport.size(), viewport.size())
                QApplication.sendEvent(viewport, resize_event)
                QApplication.processEvents()
            finally:
                sheet_panel._viewer.set_viewport_width = original_set_viewport_width  # type: ignore[assignment]
                sheet_panel._viewer.update_fit_width = original_update_fit_width  # type: ignore[assignment]

            self.assertIn(("set_viewport_width", viewport_width), calls)
            self.assertIn(("update_fit_width", viewport_width), calls)
        finally:
            host.close()

    def test_viewport_resize_triggers_fit_page_sync(self) -> None:
        host, sheet_panel, _, _ = self._build_nested_splitter_harness()
        try:
            viewport = sheet_panel._scroll_area.viewport()
            viewport_width = viewport.width()
            viewport_height = viewport.height()
            calls: list[tuple[int, int]] = []

            original_update_fit_page = sheet_panel._viewer.update_fit_page
            original_set_viewport_width = sheet_panel._viewer.set_viewport_width
            sheet_panel._fit_page_enabled = True
            sheet_panel._fit_width_enabled = False

            def _record_update_fit_page(width: int, height: int) -> None:
                calls.append((width, height))

            def _record_set_viewport_width(_width: int) -> None:
                return

            sheet_panel._viewer.update_fit_page = _record_update_fit_page  # type: ignore[assignment]
            sheet_panel._viewer.set_viewport_width = _record_set_viewport_width  # type: ignore[assignment]
            try:
                resize_event = QResizeEvent(viewport.size(), viewport.size())
                QApplication.sendEvent(viewport, resize_event)
                QApplication.processEvents()
            finally:
                sheet_panel._viewer.update_fit_page = original_update_fit_page  # type: ignore[assignment]
                sheet_panel._viewer.set_viewport_width = original_set_viewport_width  # type: ignore[assignment]

            self.assertIn((viewport_width, viewport_height), calls)
        finally:
            host.close()


if __name__ == "__main__":
    unittest.main()
