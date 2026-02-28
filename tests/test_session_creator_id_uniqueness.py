import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dmt_package import read_dmt_package_info
import session_creator
from session_creator import SESSION_FILE_EXTENSION, SessionCreatorWidget


def test_create_session_produces_unique_ids_and_files(qtbot, monkeypatch, tmp_path):
    storage_path = tmp_path / "sessions.dmtindex"
    monkeypatch.setattr(session_creator, "session_storage_path", lambda: storage_path)
    monkeypatch.setattr(session_creator, "_now_timestamp", lambda: "2026-02-26T12:00:00")

    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)

    widget._create_session()
    widget._create_session()
    ids = [session.id for session in widget.manager.sessions]
    files = sorted(tmp_path.glob(f"*{SESSION_FILE_EXTENSION}"))
    package_object_ids = [
        str((read_dmt_package_info(path) or {}).get("object_id") or "")
        for path in files
    ]
    print(f"[debug] created session ids: {ids}")
    print(f"[debug] session package files: {[path.name for path in files]}")
    print(f"[debug] session package object ids: {package_object_ids}")

    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert len(files) == 2
    assert all(session_id.startswith("Untitled_Session_") for session_id in ids)
    assert all("_session_" in session_id for session_id in ids)
    assert sorted(package_object_ids) == sorted(ids)
