import os
import sys
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PySide6.QtCore import Qt
from dmt_package import list_dmt_package_assets, read_dmt_package_asset, read_dmt_package_info
import session_creator
from session_creator import SessionCreatorWidget, session_file_path


def _select_session_row(widget: SessionCreatorWidget, session_id: str) -> None:
    for row in range(widget.session_list.count()):
        item = widget.session_list.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == session_id:
            widget.session_list.setCurrentRow(row)
            widget._load_selected_session()
            return
    raise AssertionError(f"Session {session_id} not found")


def test_attached_text_edit_persists_without_touching_source(qtbot, monkeypatch, tmp_path):
    storage_path = tmp_path / "sessions.dmtindex"
    monkeypatch.setattr(session_creator, "session_storage_path", lambda: storage_path)

    source = tmp_path / "notes.txt"
    source.write_text("original source text", encoding="utf-8")

    monkeypatch.setattr(
        "session_creator.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "All Files (*)"),
    )

    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)
    widget._create_session()
    session_id = widget._current_session.id

    widget._attach_files_to_session()
    assert widget.files_table.rowCount() == 1
    widget.files_table.selectRow(0)
    widget.files_text_editor.setPlainText("edited attached text")
    widget._save_now()

    assert source.read_text(encoding="utf-8") == "original source text"

    package_path = session_file_path(widget._current_session.name, tmp_path)
    info = read_dmt_package_info(package_path)
    assert isinstance(info, dict)
    attachments = info.get("attachments") or []
    assert len(attachments) == 1
    attachment = attachments[0]
    asset_name = str(attachment.get("asset_path") or "")
    assert asset_name
    payload = read_dmt_package_asset(package_path, asset_name)
    assert payload == b"edited attached text"
    assert int(attachment.get("size_bytes") or -1) == len(payload or b"")
    assert str(attachment.get("sha256") or "")

    reopened = SessionCreatorWidget()
    qtbot.addWidget(reopened)
    _select_session_row(reopened, session_id)
    reopened.files_table.selectRow(0)
    assert reopened.files_text_editor.toPlainText() == "edited attached text"


def test_remove_attachment_persists_in_package(qtbot, monkeypatch, tmp_path):
    storage_path = tmp_path / "sessions.dmtindex"
    monkeypatch.setattr(session_creator, "session_storage_path", lambda: storage_path)

    source = tmp_path / "remove_me.txt"
    source.write_text("to be removed", encoding="utf-8")
    monkeypatch.setattr(
        "session_creator.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "All Files (*)"),
    )

    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)
    widget._create_session()
    session_id = widget._current_session.id

    widget._attach_files_to_session()
    assert widget.files_table.rowCount() == 1
    widget.files_table.selectRow(0)
    widget._remove_selected_file()
    widget._save_now()

    package_path = session_file_path(widget._current_session.name, tmp_path)
    info = read_dmt_package_info(package_path)
    assert isinstance(info, dict)
    assert info.get("attachments") == []
    assert list_dmt_package_assets(package_path) == []
