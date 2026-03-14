import os
import socket
import sys
import time

from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWidgets import QApplication

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import online_session.protocol as protocol_module
from online_session.client import OnlineSessionClient
from online_session.protocol import FrameDecoder, encode_message
from online_session.controllers import (
    ClientSessionController,
    HostSessionController,
    _RECONNECT_MAX_ATTEMPTS,
)
from online_session.server import OnlineSessionServer, _ConnectionState


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _spin_for(milliseconds: int) -> None:
    deadline = time.monotonic() + (max(0, int(milliseconds)) / 1000.0)
    while time.monotonic() < deadline:
        QApplication.processEvents()


class _SocketStub:
    def __init__(self):
        self.writes = []
        self._state = QAbstractSocket.SocketState.ConnectedState
        self._read_payload = b""

    def state(self):
        return self._state

    def write(self, payload):
        self.writes.append(payload)
        return len(payload)

    def readAll(self):
        payload = self._read_payload
        self._read_payload = b""
        return payload

    def set_read_payload(self, payload: bytes) -> None:
        self._read_payload = payload


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
        _spin_for(120)
        client.connect_to_host("127.0.0.1", port, "Mira")
        qtbot.waitUntil(lambda: client.player_id is not None, timeout=4000)
        assert str(client.player_id) == first_id
        assert str(client.session_token) == first_token
    finally:
        client.disconnect()
        server.stop()


def test_disconnected_name_match_without_token_or_persistent_id_gets_new_identity(qtbot):
    port = _free_tcp_port()
    server = OnlineSessionServer()
    ok, err = server.start(port)
    assert ok, err

    first = OnlineSessionClient()
    second = OnlineSessionClient()
    try:
        first.connect_to_host("127.0.0.1", port, "Mira")
        qtbot.waitUntil(lambda: first.player_id is not None, timeout=4000)
        first_id = str(first.player_id)
        assert first_id
        first.disconnect()
        _spin_for(120)

        second.connect_to_host("127.0.0.1", port, "Mira")
        qtbot.waitUntil(lambda: second.player_id is not None, timeout=4000)

        assert str(second.player_id) != first_id
    finally:
        first.disconnect()
        second.disconnect()
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


def test_client_drops_session_token_when_joining_with_new_persistent_identity(qtbot):
    port = _free_tcp_port()
    server = OnlineSessionServer()
    ok, err = server.start(port)
    assert ok, err

    client = OnlineSessionClient()
    try:
        client.connect_to_host("127.0.0.1", port, "Alice", persistent_player_id="pid-1")
        qtbot.waitUntil(lambda: client.player_id is not None, timeout=4000)
        first_token = str(client.session_token)
        assert str(client.player_id) == "pid-1"
        assert first_token

        client.disconnect()
        _spin_for(120)

        client.connect_to_host("127.0.0.1", port, "Bob", persistent_player_id="pid-2")
        qtbot.waitUntil(lambda: client.player_id is not None, timeout=4000)

        assert str(client.player_id) == "pid-2"
        assert str(client.session_token) != first_token
        assert server.players.get("pid-2") == "Bob"
        assert server.players.get("pid-1") != "Bob"
    finally:
        client.disconnect()
        server.stop()


def test_persistent_player_id_cannot_take_over_connected_identity(qtbot):
    port = _free_tcp_port()
    server = OnlineSessionServer()
    ok, err = server.start(port)
    assert ok, err

    first = OnlineSessionClient()
    second = OnlineSessionClient()
    first_logs = []
    second_logs = []
    first.log_line.connect(first_logs.append)
    second.log_line.connect(second_logs.append)
    persistent_id = "player_fixed_security_probe_1"
    try:
        first.connect_to_host("127.0.0.1", port, "Alice", persistent_player_id=persistent_id)
        qtbot.waitUntil(lambda: first.player_id is not None, timeout=4000)
        first_id = str(first.player_id)
        assert first_id == persistent_id
        assert first.is_connected()

        second.connect_to_host("127.0.0.1", port, "Mallory", persistent_player_id=persistent_id)
        _spin_for(250)

        assert first.is_connected()
        assert str(first.player_id) == first_id
        assert second.player_id is None
        assert any("[ERROR]" in line for line in second_logs)
        assert server.players.get(persistent_id) == "Alice"
    finally:
        first.disconnect()
        second.disconnect()
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


def test_client_controller_sends_backpack_loot_transfer_without_retry_tracking(qtbot, monkeypatch):
    _ = qtbot
    controller = ClientSessionController()
    sent_packets = []
    monkeypatch.setattr(controller.client, "is_connected", lambda: True)
    monkeypatch.setattr(controller.client, "send", lambda payload: sent_packets.append(dict(payload)))

    assert controller.send_command(
        "add_loot_from_inventory",
        {"sheet_id": "sheet-1", "items": [{"item_id": "item-a"}]},
        request_id="req-loot-add-1",
    ) is True

    assert sent_packets
    assert sent_packets[-1]["type"] == "command"
    assert sent_packets[-1]["action"] == "add_loot_from_inventory"
    assert sent_packets[-1]["request_id"] == "req-loot-add-1"
    assert not hasattr(controller, "_pending_commands")
    controller.disconnect()


def test_client_controller_send_command_returns_false_when_client_send_fails(monkeypatch):
    controller = ClientSessionController()
    monkeypatch.setattr(controller.client, "is_connected", lambda: True)
    monkeypatch.setattr(controller.client, "send", lambda payload: False)

    assert (
        controller.send_command(
            "add_loot_from_inventory",
            {"sheet_id": "sheet-1", "items": [{"item_id": "item-a"}]},
            request_id="req-loot-add-fail",
        )
        is False
    )


def test_client_simulated_ping_delays_outbound_send(monkeypatch, qtbot):
    monkeypatch.setenv("DMT_ONLINE_SIMULATED_PING_MS", "80")
    monkeypatch.delenv("DMT_ONLINE_SIMULATED_PACKET_LOSS_PERCENT", raising=False)

    client = OnlineSessionClient()
    client._socket = _SocketStub()

    payload = {"type": "chat", "text": "slow"}
    assert client.send(payload) is True
    assert client._socket.writes == []

    qtbot.waitUntil(lambda: len(client._socket.writes) == 1, timeout=1000)
    assert client._socket.writes == [encode_message(payload)]


def test_client_simulated_packet_loss_drops_inbound_message(monkeypatch):
    monkeypatch.delenv("DMT_ONLINE_SIMULATED_PING_MS", raising=False)
    monkeypatch.setenv("DMT_ONLINE_SIMULATED_PACKET_LOSS_PERCENT", "100")

    client = OnlineSessionClient()
    client._socket = _SocketStub()
    received = []
    logs = []
    client.message_received.connect(lambda _epoch, message: received.append(dict(message)))
    client.log_line.connect(logs.append)

    client._socket.set_read_payload(encode_message({"type": "chat", "text": "lost"}))
    client._on_ready_read()
    _spin_for(100)

    assert received == []
    assert any("Simulated inbound packet loss for 'chat'" in line for line in logs)


def test_client_simulated_packet_loss_does_not_drop_hello_ack(monkeypatch):
    monkeypatch.delenv("DMT_ONLINE_SIMULATED_PING_MS", raising=False)
    monkeypatch.setenv("DMT_ONLINE_SIMULATED_PACKET_LOSS_PERCENT", "100")

    client = OnlineSessionClient()
    client._socket = _SocketStub()

    client._socket.set_read_payload(
        encode_message(
            {
                "type": "hello_ack",
                "player_id": "player-lossless",
                "session_token": "token-lossless",
                "resumed": False,
            }
        )
    )
    client._on_ready_read()
    _spin_for(100)

    assert client.player_id == "player-lossless"
    assert client.session_token == "token-lossless"


def test_client_send_chunks_large_messages_when_inline_limit_is_lowered(monkeypatch):
    monkeypatch.setattr(protocol_module, "_INLINE_MESSAGE_JSON_LIMIT_BYTES", 32)
    monkeypatch.setattr(protocol_module, "_CHUNKED_MESSAGE_SLICE_BYTES", 64)

    client = OnlineSessionClient()
    client._socket = _SocketStub()
    payload = {"type": "command", "action": "sync_character_inventory", "archive_b64": "A" * 512}

    assert client.send(payload) is True
    assert len(client._socket.writes) > 1

    decoder = FrameDecoder()
    frames = decoder.feed(b"".join(client._socket.writes))
    assert len(frames) == len(client._socket.writes)
    assert all(str(frame.get("type") or "") == "chunked_message_part" for frame in frames)


def test_client_reassembles_chunked_inbound_messages(monkeypatch):
    monkeypatch.setattr(protocol_module, "_INLINE_MESSAGE_JSON_LIMIT_BYTES", 32)
    monkeypatch.setattr(protocol_module, "_CHUNKED_MESSAGE_SLICE_BYTES", 64)

    client = OnlineSessionClient()
    client._socket = _SocketStub()
    received = []
    client.message_received.connect(lambda _epoch, message: received.append(dict(message)))

    payload = {"type": "command_result", "ok": True, "data": {"archive_b64": "A" * 512}}
    parts = protocol_module.prepare_outbound_transport_messages(payload)
    assert len(parts) > 1
    client._socket.set_read_payload(b"".join(encode_message(part) for part in parts))

    client._on_ready_read()

    assert received == [payload]


def test_server_reassembles_chunked_command_messages(monkeypatch):
    class _ServerSocketStub:
        def __init__(self, payload: bytes):
            self._payload = payload
            self.disconnect_calls = 0

        def readAll(self):
            payload = self._payload
            self._payload = b""
            return payload

        def disconnectFromHost(self):
            self.disconnect_calls += 1

    monkeypatch.setattr(protocol_module, "_INLINE_MESSAGE_JSON_LIMIT_BYTES", 32)
    monkeypatch.setattr(protocol_module, "_CHUNKED_MESSAGE_SLICE_BYTES", 64)

    server = OnlineSessionServer()
    received = []
    server.message_received.connect(lambda player_id, message: received.append((player_id, dict(message))))
    payload = {
        "type": "command",
        "action": "sync_character_inventory",
        "payload": {"archive_b64": "A" * 512},
        "request_id": "req-large-1",
    }
    parts = protocol_module.prepare_outbound_transport_messages(payload)
    socket = _ServerSocketStub(b"".join(encode_message(part) for part in parts))
    server._connections[socket] = _ConnectionState(
        socket=socket,
        decoder=FrameDecoder(),
        player_id="player-1",
        name="Alice",
        session_token="token-1",
    )
    server._inbound_chunked_messages[socket] = {}

    server._on_ready_read(socket)

    assert received == [("player-1", payload)]
    assert socket.disconnect_calls == 0


def test_server_send_socket_message_chunks_large_messages(monkeypatch):
    class _ServerSocketStub:
        def __init__(self):
            self.writes = []
            self.disconnect_calls = 0

        def write(self, payload):
            self.writes.append(payload)
            return len(payload)

        def disconnectFromHost(self):
            self.disconnect_calls += 1

    monkeypatch.setattr(protocol_module, "_INLINE_MESSAGE_JSON_LIMIT_BYTES", 32)
    monkeypatch.setattr(protocol_module, "_CHUNKED_MESSAGE_SLICE_BYTES", 64)

    server = OnlineSessionServer()
    socket = _ServerSocketStub()
    server._send_socket_message(
        socket,
        {"type": "command_result", "ok": True, "data": {"archive_b64": "A" * 512}},
    )

    assert len(socket.writes) > 1
    assert socket.disconnect_calls == 0
    decoder = FrameDecoder()
    frames = decoder.feed(b"".join(socket.writes))
    assert all(str(frame.get("type") or "") == "chunked_message_part" for frame in frames)


def test_host_controller_kick_player_only_broadcasts_after_disconnect_starts(monkeypatch):
    controller = HostSessionController()
    controller.server._players["player-1"] = "Alice"
    broadcasts = []
    disconnect_calls = []

    monkeypatch.setattr(
        controller,
        "broadcast_chat",
        lambda **kwargs: broadcasts.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        controller.server,
        "disconnect_player",
        lambda player_id, message="": disconnect_calls.append((player_id, message)) or False,
    )

    assert controller.kick_player("player-1", message="Removed.") is False
    assert broadcasts == []

    monkeypatch.setattr(
        controller.server,
        "disconnect_player",
        lambda player_id, message="": disconnect_calls.append((player_id, message)) or True,
    )

    assert controller.kick_player("player-1", message="Removed.") is True
    assert disconnect_calls == [
        ("player-1", "Removed."),
        ("player-1", "Removed."),
    ]
    assert broadcasts == [
        {
            "actor_name": "System",
            "text": "Alice was kicked: Removed.",
            "system": True,
        }
    ]


def test_server_send_socket_message_does_not_disconnect_on_local_encode_failure(monkeypatch):
    class _SocketStub:
        def __init__(self) -> None:
            self.disconnect_calls = 0
            self.write_calls = 0

        def write(self, _payload):
            self.write_calls += 1
            return 0

        def disconnectFromHost(self):
            self.disconnect_calls += 1

    server = OnlineSessionServer()
    logs = []
    server.log_line.connect(logs.append)
    socket = _SocketStub()

    monkeypatch.setattr("online_session.server.encode_message", lambda _message: (_ for _ in ()).throw(ValueError("message too large")))

    server._send_socket_message(socket, {"type": "snapshot"})

    assert socket.write_calls == 0
    assert socket.disconnect_calls == 0
    assert any("Send failed: message too large" in line for line in logs)


def test_server_send_socket_message_swallows_deleted_socket_cleanup_failure():
    class _DeletedSocketStub:
        def write(self, _payload):
            raise RuntimeError("Internal C++ object (PySide6.QtNetwork.QTcpSocket) already deleted.")

        def disconnectFromHost(self):
            raise RuntimeError("Internal C++ object (PySide6.QtNetwork.QTcpSocket) already deleted.")

    server = OnlineSessionServer()
    logs = []
    server.log_line.connect(logs.append)

    server._send_socket_message(_DeletedSocketStub(), {"type": "snapshot"})

    assert any("already deleted" in line for line in logs)


def test_client_controller_pauses_auto_reconnect_after_max_attempts():
    controller = ClientSessionController()
    controller._manual_disconnect = False
    controller._connect_host = "127.0.0.1"
    controller._connect_port = 9010
    controller._reconnect_paused = False
    controller._reconnect_attempt = _RECONNECT_MAX_ATTEMPTS

    states = []
    controller.reconnect_state_changed.connect(states.append)

    controller._schedule_reconnect()

    assert controller._reconnect_paused is True
    assert not controller._reconnect_timer.isActive()
    assert states
    assert states[-1]["status"] == "paused"
    assert states[-1]["manual_retry_available"] is True


def test_client_controller_manual_retry_restarts_reconnect_cycle_with_unlimited_retries(monkeypatch):
    controller = ClientSessionController()
    sent_connect_calls = []
    monkeypatch.setattr(
        controller.client,
        "connect_to_host",
        lambda host, port, name, persistent_player_id=None: sent_connect_calls.append(
            (host, port, name, persistent_player_id)
        ),
    )
    controller._manual_disconnect = False
    controller._connect_host = "127.0.0.1"
    controller._connect_port = 9010
    controller._connect_name = "Mira"
    controller._connect_persistent_player_id = "pid-1"
    controller._reconnect_paused = True
    controller._reconnect_attempt = _RECONNECT_MAX_ATTEMPTS

    ok = controller.retry_reconnect()
    controller._reconnect_paused = True
    ok_second = controller.retry_reconnect()

    assert ok is True
    assert ok_second is True
    assert controller._reconnect_paused is False
    assert sent_connect_calls == [
        ("127.0.0.1", 9010, "Mira", "pid-1"),
        ("127.0.0.1", 9010, "Mira", "pid-1"),
    ]


def test_client_controller_reconnect_failures_after_established_session_do_not_force_manual_disconnect():
    controller = ClientSessionController()
    controller._manual_disconnect = False
    controller._connect_host = "127.0.0.1"
    controller._connect_port = 9010
    controller._session_established = True

    controller._on_disconnected()
    assert controller._manual_disconnect is False

    controller._reconnect_timer.stop()
    controller._on_disconnected()

    assert controller._manual_disconnect is False


def test_client_controller_connect_timeout_forces_next_reconnect_attempt(monkeypatch):
    controller = ClientSessionController()
    disconnect_calls = []
    monkeypatch.setattr(controller.client, "is_connected", lambda: False)
    monkeypatch.setattr(controller.client, "is_connecting", lambda: True)
    monkeypatch.setattr(controller.client, "disconnect", lambda: disconnect_calls.append(True))

    controller._manual_disconnect = False
    controller._reconnect_paused = False
    controller._on_reconnect_connect_timeout()

    assert disconnect_calls == [True]


def test_client_controller_connected_transport_without_hello_ack_still_forces_retry(monkeypatch):
    controller = ClientSessionController()
    disconnect_calls = []
    monkeypatch.setattr(controller.client, "is_connected", lambda: True)
    monkeypatch.setattr(controller.client, "is_connecting", lambda: False)
    monkeypatch.setattr(controller.client, "disconnect", lambda: disconnect_calls.append(True))

    controller._manual_disconnect = False
    controller._reconnect_paused = False
    controller._session_established = False
    controller._on_reconnect_connect_timeout()

    assert disconnect_calls == [True]


def test_client_controller_hello_ack_clears_reconnect_timeout_and_marks_connected():
    controller = ClientSessionController()
    states = []
    connected_events = []
    hello_acks = []
    controller.reconnect_state_changed.connect(states.append)
    controller.connected.connect(lambda: connected_events.append(True))
    controller.hello_ack_received.connect(
        lambda player_id, resumed: hello_acks.append((player_id, resumed))
    )

    controller._active_transport_epoch = 4
    controller._reconnect_attempt = 3
    controller._reconnect_paused = True
    controller._reconnect_connect_timeout_timer.start()

    controller._on_hello_ack(4, "player-7", True)

    assert controller._session_established is True
    assert controller._reconnect_attempt == 0
    assert controller._reconnect_paused is False
    assert not controller._reconnect_connect_timeout_timer.isActive()
    assert states
    assert states[-1]["status"] == "connected"
    assert connected_events == [True]
    assert hello_acks == [("player-7", True)]


def test_client_controller_ignores_stale_transport_snapshot_message():
    controller = ClientSessionController()
    controller._active_transport_epoch = 2
    received = []
    controller.snapshot_received.connect(received.append)

    controller._on_message(
        1,
        {"type": "snapshot", "state": {"items": [], "fog": {"path": []}}},
    )

    assert received == []


def test_client_controller_ignores_stale_transport_hello_ack():
    controller = ClientSessionController()
    controller._active_transport_epoch = 2
    hello_acks = []
    controller.hello_ack_received.connect(lambda player_id, resumed: hello_acks.append((player_id, resumed)))

    controller._on_hello_ack(1, "player-1", False)

    assert hello_acks == []
