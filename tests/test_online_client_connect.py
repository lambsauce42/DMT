import os
import socket
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from online_session.client import OnlineSessionClient
from online_session.controllers import ClientSessionController
from online_session.server import OnlineSessionServer


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_client_rewrites_wildcard_host_to_loopback_and_connects(qtbot):
    port = _free_tcp_port()
    server = OnlineSessionServer()
    server_logs = []
    server.log_line.connect(server_logs.append)
    ok, err = server.start(port)
    assert ok, err

    client = OnlineSessionClient()
    client_logs = []
    client.log_line.connect(client_logs.append)

    try:
        client.connect_to_host("0.0.0.0", port, "Mira")
        qtbot.waitUntil(lambda: client.player_id is not None, timeout=4000)

        assert any("listen address" in line.lower() for line in client_logs)
        assert any(f"[INFO] Connecting to 127.0.0.1:{port}..." == line for line in client_logs)
        assert not any("[ERROR] Socket error:" in line for line in client_logs)
    finally:
        client.disconnect()
        server.stop()


def test_server_start_logs_join_guidance_for_host_addresses(qtbot):
    _ = qtbot  # Ensure Qt application exists for signal delivery.
    port = _free_tcp_port()
    server = OnlineSessionServer()
    logs = []
    server.log_line.connect(logs.append)

    ok, err = server.start(port)
    try:
        assert ok, err
        assert any(f"[INFO] Listening on 0.0.0.0:{port} (all interfaces)" == line for line in logs)
        assert any(f"[INFO] Same-device join address: 127.0.0.1:{port}" == line for line in logs)
        assert any("not 0.0.0.0" in line for line in logs)
    finally:
        server.stop()


def test_client_reconnect_preserves_player_identity_with_session_token(qtbot):
    port = _free_tcp_port()
    server = OnlineSessionServer()
    ok, err = server.start(port)
    assert ok, err

    client = OnlineSessionClient()
    try:
        client.connect_to_host("127.0.0.1", port, "Mira")
        qtbot.waitUntil(lambda: client.player_id is not None, timeout=4000)
        first_id = str(client.player_id)
        first_token = str(client.session_token)
        assert first_id
        assert first_token

        client.disconnect()
        qtbot.wait(120)
        client.connect_to_host("127.0.0.1", port, "Mira")
        qtbot.waitUntil(lambda: client.player_id is not None, timeout=4000)
        assert str(client.player_id) == first_id
        assert str(client.session_token) == first_token
    finally:
        client.disconnect()
        server.stop()


def test_client_can_supply_persistent_player_id_for_handshake(qtbot):
    port = _free_tcp_port()
    server = OnlineSessionServer()
    ok, err = server.start(port)
    assert ok, err

    client = OnlineSessionClient()
    persistent_id = "player_20260210_010203_abcd1234"
    try:
        client.connect_to_host("127.0.0.1", port, "Mira", persistent_player_id=persistent_id)
        qtbot.waitUntil(lambda: client.player_id is not None, timeout=4000)
        assert str(client.player_id) == persistent_id
    finally:
        client.disconnect()
        server.stop()


def test_client_controller_clears_presence_when_disconnected(qtbot):
    port = _free_tcp_port()
    server = OnlineSessionServer()
    ok, err = server.start(port)
    assert ok, err

    controller = ClientSessionController()
    try:
        controller.connect_to_host("127.0.0.1", port, "Mira")
        qtbot.waitUntil(lambda: controller.player_id is not None, timeout=4000)
        controller._players = {"player-1": "Mira"}
        controller._on_disconnected()
        assert controller.players == {}
    finally:
        controller.disconnect()
        server.stop()


def test_client_controller_tracks_backpack_loot_transfer_for_retry(qtbot, monkeypatch):
    _ = qtbot
    controller = ClientSessionController()
    sent_packets = []
    monkeypatch.setattr(controller.client, "is_connected", lambda: True)
    monkeypatch.setattr(controller.client, "send", lambda payload: sent_packets.append(dict(payload)))

    controller.send_command(
        "add_loot_from_inventory",
        {"sheet_id": "sheet-1", "items": [{"item_id": "item-a"}]},
        request_id="req-loot-add-1",
    )

    assert sent_packets
    assert "req-loot-add-1" in controller._pending_commands
    controller.disconnect()
