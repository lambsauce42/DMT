import os
import sys
import types
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from viewer.pdfium_viewer_widget import PdfiumViewerWidget
import viewer.pdfium_viewer_widget as pdfium_viewer_widget


def _write_cursor_debug(lines: list[str]) -> None:
    debug_path = Path(ROOT) / "debug" / "pdfium_text_cursor.log"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _MouseEventStub:
    def __init__(
        self,
        button: Qt.MouseButton = Qt.MouseButton.LeftButton,
        buttons: Qt.MouseButton = Qt.MouseButton.LeftButton,
    ) -> None:
        self._button = button
        self._buttons = buttons
        self.accepted = False

    def button(self) -> Qt.MouseButton:
        return self._button

    def buttons(self) -> Qt.MouseButton:
        return self._buttons

    def modifiers(self) -> Qt.KeyboardModifier:
        return Qt.KeyboardModifier.NoModifier

    def position(self) -> QPointF:
        return QPointF(10.0, 10.0)

    def accept(self) -> None:
        self.accepted = True


class PdfiumViewerWidgetMouseEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    @staticmethod
    def _build_widget_for_mouse_click() -> PdfiumViewerWidget:
        widget = PdfiumViewerWidget()
        widget._doc = object()
        widget._form_handle = object()
        widget._page_hit_test = lambda _pos: (0, 12.0, 34.0)  # type: ignore[method-assign]
        widget._get_page = lambda _index: types.SimpleNamespace(raw=object())  # type: ignore[method-assign]
        widget._set_current_page_index = lambda _index: None  # type: ignore[method-assign]
        widget._schedule_render = lambda: None  # type: ignore[method-assign]
        return widget

    def test_text_field_click_does_not_mark_modified(self) -> None:
        widget = self._build_widget_for_mouse_click()
        down_event = _MouseEventStub()
        up_event = _MouseEventStub()
        with patch.object(pdfium_viewer_widget.pdfium_c, "FORM_OnFocus", return_value=None), patch.object(
            pdfium_viewer_widget.pdfium_c, "FORM_OnLButtonDown", return_value=1
        ), patch.object(pdfium_viewer_widget.pdfium_c, "FORM_OnLButtonUp", return_value=1), patch.object(
            pdfium_viewer_widget.pdfium_c,
            "FPDFPage_HasFormFieldAtPoint",
            return_value=pdfium_viewer_widget.pdfium_c.FPDF_FORMFIELD_TEXTFIELD,
        ):
            widget.mousePressEvent(down_event)
            widget.mouseReleaseEvent(up_event)
        self.assertFalse(widget.modified)
        self.assertTrue(down_event.accepted)
        self.assertTrue(up_event.accepted)

    def test_checkbox_click_marks_modified(self) -> None:
        widget = self._build_widget_for_mouse_click()
        down_event = _MouseEventStub()
        up_event = _MouseEventStub()
        with patch.object(pdfium_viewer_widget.pdfium_c, "FORM_OnFocus", return_value=None), patch.object(
            pdfium_viewer_widget.pdfium_c, "FORM_OnLButtonDown", return_value=1
        ), patch.object(pdfium_viewer_widget.pdfium_c, "FORM_OnLButtonUp", return_value=1), patch.object(
            pdfium_viewer_widget.pdfium_c,
            "FPDFPage_HasFormFieldAtPoint",
            return_value=pdfium_viewer_widget.pdfium_c.FPDF_FORMFIELD_CHECKBOX,
        ):
            widget.mousePressEvent(down_event)
            widget.mouseReleaseEvent(up_event)
        self.assertTrue(widget.modified)
        self.assertTrue(down_event.accepted)
        self.assertTrue(up_event.accepted)


class PdfiumViewerWidgetRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_render_page_returns_qimage_for_loaded_character_pdf(self) -> None:
        widget = PdfiumViewerWidget()
        pdf_path = os.path.join(
            ROOT, "tests", "test_saves", "DMT", "cache", "characters", "Hero.pdf"
        )

        self.assertTrue(widget.load_document(pdf_path))
        dpr_key = max(100, int(round(widget.devicePixelRatioF() * 100)))
        image = widget._render_page(0, widget.zoom_factor(), dpr_key)

        self.assertIsNotNone(image)
        self.assertFalse(image.isNull())
        self.assertGreater(image.width(), 0)
        self.assertGreater(image.height(), 0)

    def test_pdf_text_field_cursor_stays_arrow(self) -> None:
        widget = PdfiumViewerWidget()
        initial_shape = widget.cursor().shape()

        widget._ffi_set_cursor(None, pdfium_viewer_widget.pdfium_c.FXCT_VBEAM)
        final_shape = widget.cursor().shape()

        _write_cursor_debug(
            [
                f"initial_shape={initial_shape}",
                f"final_shape={final_shape}",
                f"expected_shape={Qt.CursorShape.ArrowCursor}",
            ]
        )

        self.assertEqual(final_shape, Qt.CursorShape.ArrowCursor)


if __name__ == "__main__":
    unittest.main()
