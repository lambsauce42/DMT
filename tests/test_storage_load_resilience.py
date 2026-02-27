from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import session_creator
from dmt_package import write_dmt_package
from navigation_storage import WORLD_EXTENSION, load_navigation_world_data, navigation_objects_dir


pytestmark = pytest.mark.tier0

_DEBUG_LOG = Path(ROOT) / "debug" / "storage_load_resilience.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def test_navigation_storage_load_skips_invalid_order_and_keeps_valid_entries(tmp_path: Path) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    worlds_dir = navigation_objects_dir(base_dir=tmp_path) / "worlds"
    worlds_dir.mkdir(parents=True, exist_ok=True)
    write_dmt_package(
        worlds_dir / f"broken{WORLD_EXTENSION}",
        info={
            "format": "dmtworld.v1",
            "object_type": "world",
            "object_id": "broken",
            "name": "Broken",
            "order": "not-an-int",
        },
    )
    write_dmt_package(
        worlds_dir / f"valid{WORLD_EXTENSION}",
        info={
            "format": "dmtworld.v1",
            "object_type": "world",
            "object_id": "valid",
            "name": "Valid",
            "order": 1,
        },
    )

    loaded = load_navigation_world_data(base_dir=tmp_path)
    loaded_names = [str(entry.get("name") or "") for entry in loaded if isinstance(entry, dict)]
    _debug_log(f"navigation_loaded_names={loaded_names}")
    assert "Valid" in loaded_names


def test_session_manager_load_ignores_invalid_attachment_size_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    monkeypatch.setattr(session_creator, "session_storage_path", lambda: tmp_path / "sessions.dmtindex")
    session_file = tmp_path / "sample.dmtsession"
    asset_name = "assets/files/att_1/notes.txt"
    write_dmt_package(
        session_file,
        info={
            "format": "dmtsession.v2",
            "object_type": "session",
            "object_id": "session_1",
            "payload": {
                "id": "session_1",
                "name": "Session One",
                "session_date": "2026-02-27",
            },
            "attachments": [
                {
                    "id": "att_1",
                    "name": "notes.txt",
                    "asset_path": asset_name,
                    "mime": "text/plain",
                    "size_bytes": "bad-size-metadata",
                }
            ],
        },
        assets={asset_name: b"abc"},
    )

    manager = session_creator.SessionManager()
    _debug_log(
        "session_load_result "
        f"sessions={len(manager.sessions)} "
        f"last_error={manager.last_error!r}"
    )
    assert len(manager.sessions) == 1
    assert len(manager.sessions[0].attachments) == 1
    assert manager.sessions[0].attachments[0].size_bytes == 3
