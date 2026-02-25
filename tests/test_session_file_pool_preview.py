import os
import sys
from pathlib import Path

from PySide6.QtGui import QImage

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import session_creator
from session_creator import SessionCreatorWidget
from maps_applet import MapViewPanel


def _attach_single_file(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(
        "session_creator.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(path)], "All Files (*)"),
    )


def _build_widget_with_session(qtbot, monkeypatch, tmp_path) -> SessionCreatorWidget:
    storage_path = tmp_path / "sessions.dmtindex"
    monkeypatch.setattr(session_creator, "session_storage_path", lambda: storage_path)
    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)
    widget._create_session()
    return widget


def test_image_attachment_shows_image_preview(qtbot, monkeypatch, tmp_path):
    widget = _build_widget_with_session(qtbot, monkeypatch, tmp_path)
    source = tmp_path / "preview.png"
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(0xFF224466)
    assert image.save(str(source), "PNG")

    _attach_single_file(monkeypatch, source)
    widget._attach_files_to_session()
    widget.files_table.selectRow(0)

    assert widget.files_preview_stack.currentWidget() is widget.files_image_page
    pixmap = widget.files_image_view._pixmap_item.pixmap()
    assert not pixmap.isNull()


def test_text_attachment_shows_editable_text_preview(qtbot, monkeypatch, tmp_path):
    widget = _build_widget_with_session(qtbot, monkeypatch, tmp_path)
    source = tmp_path / "story.md"
    source.write_text("# Chapter 1", encoding="utf-8")

    _attach_single_file(monkeypatch, source)
    widget._attach_files_to_session()
    widget.files_table.selectRow(0)

    assert widget.files_preview_stack.currentWidget() is widget.files_text_page
    assert widget.files_text_editor.toPlainText() == "# Chapter 1"
    assert not widget.files_text_editor.isReadOnly()


def test_unsupported_attachment_shows_fallback_preview(qtbot, monkeypatch, tmp_path):
    widget = _build_widget_with_session(qtbot, monkeypatch, tmp_path)
    source = tmp_path / "blob.xyz"
    source.write_bytes(b"\x00\x01\x02\x03\xff")

    _attach_single_file(monkeypatch, source)
    widget._attach_files_to_session()
    widget.files_table.selectRow(0)

    assert widget.files_preview_stack.currentWidget() is widget.files_unsupported_page
    assert "Preview unavailable" in widget.files_unsupported_page.text()


def test_pdf_attachment_shows_pdf_fallback_when_viewer_unavailable(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(session_creator, "PDFIUM_VIEW_AVAILABLE", False)
    widget = _build_widget_with_session(qtbot, monkeypatch, tmp_path)

    source = tmp_path / "sheet.pdf"
    source.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n")

    _attach_single_file(monkeypatch, source)
    widget._attach_files_to_session()
    widget.files_table.selectRow(0)

    assert widget.files_preview_stack.currentWidget() is widget.files_pdf_page
    assert widget.files_pdf_viewer is None
    assert widget.files_pdf_unavailable is not None
    assert "pypdfium2" in widget.files_pdf_unavailable.text()


def test_image_attachment_uses_map_like_pan_zoom_viewer(qtbot, monkeypatch, tmp_path):
    widget = _build_widget_with_session(qtbot, monkeypatch, tmp_path)
    source = tmp_path / "zoom.png"
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    image.fill(0xFF446688)
    assert image.save(str(source), "PNG")

    _attach_single_file(monkeypatch, source)
    widget._attach_files_to_session()
    widget.files_table.selectRow(0)

    assert hasattr(widget, "files_image_view")
    assert isinstance(widget.files_image_view, MapViewPanel)
    assert hasattr(widget, "files_zoom_in_button")
    assert hasattr(widget, "files_zoom_out_button")
