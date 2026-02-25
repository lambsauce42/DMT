import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dungeon_applet import DungeonAppletWidget


_DEBUG_LOG = Path(ROOT) / "debug" / "test_dungeon_join_connect_fallback.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def test_join_does_not_silently_retry_after_runtime_typeerror(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)

    class _ClientControllerStub:
        def __init__(self):
            self.calls = []

        def connect_to_host(self, host, port, name, persistent_player_id=None):
            self.calls.append(
                {
                    "host": host,
                    "port": int(port),
                    "name": name,
                    "persistent_player_id": persistent_player_id,
                }
            )
            if persistent_player_id is not None:
                raise TypeError("runtime connect bug with persistent id path")

        def disconnect(self):
            return None

    stub = _ClientControllerStub()
    widget._client_controller = stub

    _debug_log("act: join online session with client that throws runtime TypeError")
    with pytest.raises(TypeError, match="runtime connect bug"):
        widget.join_online_session("127.0.0.1", 8765, "Mira")

    _debug_log("assert: no fallback retry call without persistent id")
    assert len(stub.calls) == 1
    assert stub.calls[0]["persistent_player_id"] is not None
