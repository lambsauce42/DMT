import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from online_session.client import OnlineSessionClient
from online_session.protocol import encode_message


_DEBUG_LOG = Path(ROOT) / "debug" / "test_online_client_decoder_reset.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def test_disconnect_resets_decoder_buffer_for_next_connection_frame():
    client = OnlineSessionClient()
    partial = encode_message({"type": "chat", "text": "leftover"})[:1]
    hello_ack = {"type": "hello_ack", "player_id": "player-1", "session_token": "token-1"}

    _debug_log("prepare: feed partial frame byte from previous connection")
    assert client._decoder.feed(partial) == []

    _debug_log("act: simulate disconnect boundary")
    client._on_disconnected()

    _debug_log("assert: next full frame on fresh connection must decode cleanly")
    try:
        frames = client._decoder.feed(encode_message(hello_ack))
    except Exception as exc:  # pragma: no cover - this is the bug evidence path
        pytest.fail(f"decoder leaked stale bytes across disconnect boundary: {exc}")
    assert frames == [hello_ack]
