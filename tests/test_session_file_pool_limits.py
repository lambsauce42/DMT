import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import session_creator
from session_creator import SessionCreatorWidget


def _build_widget_with_session(qtbot, monkeypatch, tmp_path) -> SessionCreatorWidget:
    storage_path = tmp_path / "sessions.dmtindex"
    monkeypatch.setattr(session_creator, "session_storage_path", lambda: storage_path)
    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)
    widget._create_session()
    return widget


def test_attach_rejects_file_over_per_file_limit(qtbot, monkeypatch, tmp_path):
    widget = _build_widget_with_session(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(session_creator, "MAX_ATTACHMENT_FILE_BYTES", 8)
    monkeypatch.setattr(session_creator, "MAX_TOTAL_ATTACHMENT_BYTES", 1024)

    source = tmp_path / "big.txt"
    source.write_bytes(b"123456789")

    warnings = []
    monkeypatch.setattr(
        "session_creator.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "session_creator.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "All Files (*)"),
    )

    widget._attach_files_to_session()

    assert widget.files_table.rowCount() == 0
    assert len(warnings) == 1


def test_attach_rejects_when_total_limit_would_be_exceeded(qtbot, monkeypatch, tmp_path):
    widget = _build_widget_with_session(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(session_creator, "MAX_ATTACHMENT_FILE_BYTES", 64)
    monkeypatch.setattr(session_creator, "MAX_TOTAL_ATTACHMENT_BYTES", 15)

    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"1234567890")
    second.write_bytes(b"abcdefghij")

    warnings = []
    monkeypatch.setattr(
        "session_creator.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "session_creator.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(first), str(second)], "All Files (*)"),
    )

    widget._attach_files_to_session()

    assert widget.files_table.rowCount() == 1
    assert len(warnings) == 1
