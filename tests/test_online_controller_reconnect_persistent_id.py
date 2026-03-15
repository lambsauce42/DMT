import os
import socket
import sys
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from online_session.controllers import ClientSessionController, HostSessionController
from online_session.server import OnlineSessionServer


_DEBUG_LOG = Path(ROOT) / "debug" / "test_online_controller_reconnect_persistent_id.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_controller_reconnect_keeps_configured_persistent_player_id_after_host_restart(qtbot):
    port = _free_tcp_port()
    persistent_id = "player_persistent_reconnect_regression_1"
    server_a = OnlineSessionServer()
    ok, err = server_a.start(port)
    assert ok, err

    controller = ClientSessionController()
    server_b = None
    try:
        _debug_log(f"connect phase: port={port} persistent_id={persistent_id}")
        controller.connect_to_host(
            "127.0.0.1",
            port,
            "Alice",
            persistent_player_id=persistent_id,
        )
        qtbot.waitUntil(lambda: controller.player_id is not None, timeout=4000)
        first_player_id = str(controller.player_id)
        _debug_log(f"initial hello_ack player_id={first_player_id!r}")
        assert first_player_id == persistent_id

        _debug_log("stop first host to force disconnect/reconnect path")
        server_a.stop()
        qtbot.waitUntil(lambda: not controller.client.is_connected(), timeout=4000)

        server_b = OnlineSessionServer()
        ok, err = server_b.start(port)
        assert ok, err
        _debug_log("restart host and trigger reconnect attempt")
        controller._reconnect_timer.stop()
        controller._attempt_reconnect()
        qtbot.waitUntil(
            lambda: controller.client.is_connected() and controller.player_id is not None,
            timeout=4000,
        )

        reconnected_player_id = str(controller.player_id)
        _debug_log(f"reconnect hello_ack player_id={reconnected_player_id!r}")
        assert reconnected_player_id == persistent_id
    finally:
        controller.disconnect()
        if server_b is not None:
            server_b.stop()
        server_a.stop()


def test_host_controller_replays_cached_command_results_without_reprocessing():
    controller = HostSessionController()
    emitted_commands = []
    sent_messages = []
    controller.command_received.connect(lambda player_id, message: emitted_commands.append((player_id, dict(message))))
    controller.server.send_to_player = lambda player_id, payload: sent_messages.append((player_id, dict(payload)))
    try:
        controller.send_command_result(
            "player-1",
            ok=True,
            message="Synced",
            request_id="req-1",
            data={"action": "sync_character_inventory"},
        )
        sent_messages.clear()

        controller._on_server_message(
            "player-1",
            {
                "type": "command",
                "action": "sync_character_inventory",
                "payload": {"sheet_id": "sheet-1"},
                "request_id": "req-1",
            },
        )

        assert emitted_commands == []
        assert sent_messages == [
            (
                "player-1",
                {
                    "type": "command_result",
                    "ok": True,
                    "message": "Synced",
                    "request_id": "req-1",
                    "data": {"action": "sync_character_inventory"},
                },
            )
        ]
    finally:
        controller.stop()
