from __future__ import annotations

import json

import pytest

from online_logging import (
    OnlineSessionLogger,
    append_active_online_session_crash_event,
    set_runtime_logging_enabled,
)

pytestmark = pytest.mark.tier0


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _reset_runtime_logging():
    set_runtime_logging_enabled(True)
    yield
    set_runtime_logging_enabled(True)


def test_online_session_logger_writes_persistent_jsonl(tmp_path):
    logger = OnlineSessionLogger(
        role="player",
        session_id="join_127.0.0.1_5000",
        base_dir=tmp_path,
        initial_context={"player_name": "Alice"},
    )

    logger.write_event("snapshot_received", snapshot_bytes=1234)
    logger.close(reason="finished")

    entries = _read_jsonl(logger.path)
    assert logger.path.parent == tmp_path
    assert [entry["event"] for entry in entries] == [
        "session_log_opened",
        "snapshot_received",
        "session_log_closed",
    ]
    assert entries[0]["player_name"] == "Alice"
    assert entries[1]["snapshot_bytes"] == 1234
    assert entries[2]["reason"] == "finished"


def test_active_online_session_crash_event_is_written_to_open_logs(tmp_path):
    logger = OnlineSessionLogger(
        role="host",
        session_id="host_5000",
        base_dir=tmp_path,
        initial_context={"dm_name": "DM"},
    )

    append_active_online_session_crash_event(
        "uncaught_exception",
        exception_type="RuntimeError",
        error="boom",
    )
    logger.close(reason="after_crash")

    entries = _read_jsonl(logger.path)
    crash_entries = [entry for entry in entries if entry["event"] == "uncaught_exception"]
    assert len(crash_entries) == 1
    assert crash_entries[0]["exception_type"] == "RuntimeError"
    assert crash_entries[0]["error"] == "boom"


def test_runtime_logging_flag_suppresses_session_log_writes(tmp_path):
    logger = OnlineSessionLogger(
        role="player",
        session_id="join_127.0.0.1_5000",
        base_dir=tmp_path,
    )

    set_runtime_logging_enabled(False)
    logger.write_event("should_not_be_written")
    logger.close(reason="disabled")

    entries = _read_jsonl(logger.path)
    assert [entry["event"] for entry in entries] == ["session_log_opened"]
