import os
import sys
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QPushButton

import session_creator
from session_creator import SessionCreatorWidget


def _write_geometry_debug(widget: SessionCreatorWidget, debug_path: Path) -> None:
    table = widget.files_table
    header = table.horizontalHeader()
    lines = []
    lines.append(f"window={widget.width()}x{widget.height()}")
    controls_parent = widget.add_file_btn.parentWidget()
    lines.append(f"controls_parent={controls_parent.geometry()}")
    for button in (widget.add_file_btn, widget.remove_file_btn, widget.open_file_external_btn):
        lines.append(f"button:{button.text()} geom={button.geometry()}")
    lines.append(
        f"zoom_buttons in={widget.files_zoom_in_button.geometry()} out={widget.files_zoom_out_button.geometry()}"
    )
    lines.append(
        f"edge_toggle geom={widget.files_edge_toggle_btn.geometry()} text='{widget.files_edge_toggle_btn.text()}'"
    )
    lines.append(f"table_frame_shape={int(table.frameShape())}")
    if table.rowCount() > 0:
        for col in range(table.columnCount()):
            section_x = header.sectionViewportPosition(col)
            section_w = header.sectionSize(col)
            cell_rect = table.visualRect(table.model().index(0, col))
            lines.append(
                f"col={col} header_x={section_x} header_w={section_w} "
                f"cell_x={cell_rect.x()} cell_w={cell_rect.width()}"
            )
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_caret_debug(
    widget: SessionCreatorWidget,
    debug_path: Path,
    details: list[str],
) -> None:
    button = widget.files_edge_toggle_btn
    lines = [f"button_size={button.width()}x{button.height()} text='{button.text()}'"]
    lines.extend(details)
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _caret_bright_bbox(button: QPushButton, *, luminance_threshold: int = 180) -> tuple[int, int, int]:
    image = button.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    xs: list[int] = []
    ys: list[int] = []
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            luminance = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
            if luminance >= luminance_threshold:
                xs.append(x)
                ys.append(y)
    if not xs or not ys:
        return (0, 0, 0)
    return (max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, len(xs))


def test_file_pool_layout_buttons_not_cut_off_and_headers_align(qtbot, monkeypatch, tmp_path):
    storage_path = tmp_path / "sessions.dmtindex"
    monkeypatch.setattr(session_creator, "session_storage_path", lambda: storage_path)

    source = tmp_path / "layout.txt"
    source.write_text("layout", encoding="utf-8")
    monkeypatch.setattr(
        "session_creator.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "All Files (*)"),
    )

    app = QApplication.instance() or QApplication([])
    previous_stylesheet = app.styleSheet()
    try:
        import app as app_module

        app.setStyleSheet(app_module.DARK_STYLESHEET)
    except Exception:
        pass

    try:
        widget = SessionCreatorWidget()
        qtbot.addWidget(widget)
        widget.resize(900, 500)
        widget.show()
        widget._create_session()
        widget._attach_files_to_session()
        widget.ref_tabs.setCurrentIndex(1)
        widget.files_table.selectRow(0)
        app.processEvents()

        debug_path = Path(ROOT) / "debug" / "session_file_pool_geometry.log"
        _write_geometry_debug(widget, debug_path)

        controls_parent = widget.add_file_btn.parentWidget()
        for button in (widget.add_file_btn, widget.remove_file_btn, widget.open_file_external_btn):
            assert button.geometry().bottom() <= controls_parent.height() - 1
            assert isinstance(button, QPushButton)
            assert button.icon().isNull()
            assert button.text().strip() != ""

        assert widget.files_zoom_in_button.width() == widget.files_zoom_in_button.height()
        assert widget.files_zoom_out_button.width() == widget.files_zoom_out_button.height()

        assert widget.files_table.frameShape() == widget.files_table.frameShape().NoFrame

        header = widget.files_table.horizontalHeader()
        for col in range(widget.files_table.columnCount()):
            section_x = header.sectionViewportPosition(col)
            section_w = header.sectionSize(col)
            cell_rect = widget.files_table.visualRect(widget.files_table.model().index(0, col))
            assert cell_rect.x() == section_x
            assert cell_rect.width() == section_w
    finally:
        app.setStyleSheet(previous_stylesheet)


def test_file_pool_has_smooth_collapse_expand_edge_toggle(qtbot, monkeypatch, tmp_path):
    storage_path = tmp_path / "sessions.dmtindex"
    monkeypatch.setattr(session_creator, "session_storage_path", lambda: storage_path)

    source = tmp_path / "collapse.txt"
    source.write_text("collapse", encoding="utf-8")
    monkeypatch.setattr(
        "session_creator.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "All Files (*)"),
    )

    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)
    widget.resize(1200, 700)
    widget.show()
    widget._create_session()
    widget._attach_files_to_session()
    widget.ref_tabs.setCurrentIndex(1)
    qtbot.wait(30)

    assert hasattr(widget, "files_edge_toggle_btn")
    assert widget.files_edge_toggle_btn.isVisible()
    assert widget.files_edge_toggle_btn.width() >= 28

    initial_left = widget.files_splitter.sizes()[0]
    widget.files_edge_toggle_btn.click()
    qtbot.wait(30)
    assert widget.files_edge_toggle_btn.text() == ">"
    qtbot.wait(260)
    collapsed_left = widget.files_splitter.sizes()[0]
    collapse_debug_path = Path(ROOT) / "debug" / "session_file_pool_collapse.log"
    collapse_debug_path.parent.mkdir(parents=True, exist_ok=True)
    collapse_debug_path.write_text(
        "\n".join(
            [
                f"initial_left={initial_left}",
                f"collapsed_left={collapsed_left}",
                f"collapsed_handle_width={widget.files_splitter.handleWidth()}",
                f"toggle_parent={widget.files_edge_toggle_btn.parentWidget().__class__.__name__}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert collapsed_left < max(60, initial_left // 4)
    assert collapsed_left <= 2
    assert widget.files_splitter.handleWidth() == 0
    assert widget.files_list_panel.isVisible()
    assert hasattr(widget, "files_list_content")
    assert not widget.files_list_content.isVisible()
    assert widget.files_edge_toggle_btn.parentWidget() is widget.files_splitter.widget(1)

    widget.files_edge_toggle_btn.click()
    qtbot.wait(30)
    assert widget.files_edge_toggle_btn.text() == "<"
    qtbot.wait(260)
    restored_left = widget.files_splitter.sizes()[0]
    assert restored_left > collapsed_left + 80
    assert widget.files_list_content.isVisible()
    assert widget.files_splitter.handleWidth() == 10


def test_file_pool_edge_toggle_uses_standard_button_style(qtbot, monkeypatch, tmp_path):
    storage_path = tmp_path / "sessions.dmtindex"
    monkeypatch.setattr(session_creator, "session_storage_path", lambda: storage_path)

    source = tmp_path / "caret_box.txt"
    source.write_text("caret", encoding="utf-8")
    monkeypatch.setattr(
        "session_creator.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "All Files (*)"),
    )

    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)
    widget.resize(1100, 700)
    widget.show()
    widget._create_session()
    widget._attach_files_to_session()
    widget.ref_tabs.setCurrentIndex(1)
    qtbot.wait(60)

    button = widget.files_edge_toggle_btn
    _write_caret_debug(
        widget,
        Path(ROOT) / "debug" / "session_file_pool_caret_button.log",
        [
            f"class={button.__class__.__name__}",
            f"object_name={button.objectName()}",
            f"style_sheet_len={len(button.styleSheet())}",
        ],
    )

    assert isinstance(button, QPushButton)
    assert button.objectName() == "SecondaryButton"


def test_file_pool_edge_toggle_has_large_caret_footprint(qtbot, monkeypatch, tmp_path):
    storage_path = tmp_path / "sessions.dmtindex"
    monkeypatch.setattr(session_creator, "session_storage_path", lambda: storage_path)

    source = tmp_path / "caret_size.txt"
    source.write_text("caret-size", encoding="utf-8")
    monkeypatch.setattr(
        "session_creator.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "All Files (*)"),
    )

    app = QApplication.instance() or QApplication([])
    previous_stylesheet = app.styleSheet()
    try:
        import app as app_module

        app.setStyleSheet(app_module.DARK_STYLESHEET)
    except Exception:
        pass

    try:
        widget = SessionCreatorWidget()
        qtbot.addWidget(widget)
        widget.resize(1200, 700)
        widget.show()
        widget._create_session()
        widget._attach_files_to_session()
        widget.ref_tabs.setCurrentIndex(1)
        qtbot.wait(60)

        button = widget.files_edge_toggle_btn
        caret_width, caret_height, caret_pixels = _caret_bright_bbox(button)
        _write_caret_debug(
            widget,
            Path(ROOT) / "debug" / "session_file_pool_caret_size.log",
            [
                f"caret_width={caret_width}",
                f"caret_height={caret_height}",
                f"caret_pixels={caret_pixels}",
            ],
        )

        assert caret_width >= 10
        assert caret_height >= 18
        assert caret_pixels >= 48
    finally:
        app.setStyleSheet(previous_stylesheet)
