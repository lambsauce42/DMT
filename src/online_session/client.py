from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket

from .protocol import (
    CHUNKED_MESSAGE_TYPE,
    FrameDecoder,
    decode_chunked_payload_bytes,
    encode_message,
    prepare_outbound_transport_messages,
    restore_chunked_transport_message,
)

_WILDCARD_LISTEN_HOSTS = {"0.0.0.0", "::", "[::]", "0:0:0:0:0:0:0:0"}
_LOSSLESS_MESSAGE_TYPES = {"error", "hello", "hello_ack", "kicked"}
_CHUNKED_MESSAGE_TIMEOUT_SECONDS = 60.0


@dataclass(slots=True)
class _QueuedOutboundMessage:
    due_ms: int
    encoded: bytes
    message_type: str


@dataclass(slots=True)
class _QueuedInboundMessage:
    due_ms: int
    message: dict


@dataclass(slots=True)
class _TransportSimulationConfig:
    ping_ms: int = 0
    packet_loss_percent: float = 0.0
    warnings: tuple[str, ...] = ()

    @property
    def one_way_delay_ms(self) -> int:
        ping_ms = max(0, int(self.ping_ms))
        return (ping_ms + 1) // 2

    @property
    def enabled(self) -> bool:
        return self.one_way_delay_ms > 0 or self.packet_loss_percent > 0.0


def _parse_transport_simulation_config() -> _TransportSimulationConfig:
    warnings: list[str] = []

    raw_ping = str(os.environ.get("DMT_ONLINE_SIMULATED_PING_MS", "")).strip()
    ping_ms = 0
    if raw_ping:
        try:
            ping_ms = int(float(raw_ping))
        except ValueError:
            warnings.append(
                f"[WARN] Ignoring invalid DMT_ONLINE_SIMULATED_PING_MS={raw_ping!r}; expected a number."
            )
            ping_ms = 0
        else:
            if ping_ms < 0:
                warnings.append(
                    f"[WARN] Clamped DMT_ONLINE_SIMULATED_PING_MS from {ping_ms} to 0."
                )
                ping_ms = 0

    raw_loss = str(os.environ.get("DMT_ONLINE_SIMULATED_PACKET_LOSS_PERCENT", "")).strip()
    packet_loss_percent = 0.0
    if raw_loss:
        try:
            packet_loss_percent = float(raw_loss)
        except ValueError:
            warnings.append(
                "[WARN] Ignoring invalid DMT_ONLINE_SIMULATED_PACKET_LOSS_PERCENT="
                f"{raw_loss!r}; expected a number between 0 and 100."
            )
            packet_loss_percent = 0.0
        else:
            if packet_loss_percent < 0.0:
                warnings.append(
                    "[WARN] Clamped DMT_ONLINE_SIMULATED_PACKET_LOSS_PERCENT "
                    f"from {packet_loss_percent} to 0."
                )
                packet_loss_percent = 0.0
            elif packet_loss_percent > 100.0:
                warnings.append(
                    "[WARN] Clamped DMT_ONLINE_SIMULATED_PACKET_LOSS_PERCENT "
                    f"from {packet_loss_percent} to 100."
                )
                packet_loss_percent = 100.0

    return _TransportSimulationConfig(
        ping_ms=ping_ms,
        packet_loss_percent=packet_loss_percent,
        warnings=tuple(warnings),
    )


def _normalize_connect_host(host: str) -> tuple[str, bool]:
    cleaned = host.strip()
    if cleaned.lower() in _WILDCARD_LISTEN_HOSTS:
        return "127.0.0.1", True
    return cleaned, False


class OnlineSessionClient(QObject):
    log_line = Signal(str)
    connected_to_server = Signal(int)
    disconnected_from_server = Signal(int)
    hello_ack = Signal(int, str, bool)
    socket_error = Signal(int, str)
    message_received = Signal(int, dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._socket = QTcpSocket(self)
        self._decoder = FrameDecoder()
        self._requested_name = ""
        self._player_id: Optional[str] = None
        self._session_token: str = ""
        self._persistent_player_id: str = ""
        self._transport_epoch: int = 0
        self._transport_simulation = _parse_transport_simulation_config()
        self._transport_simulation_announced = False
        self._transport_rng = random.Random()
        self._pending_outbound_messages: list[_QueuedOutboundMessage] = []
        self._pending_inbound_messages: list[_QueuedInboundMessage] = []
        self._inbound_chunked_messages: dict[str, dict] = {}
        self._next_outbound_due_ms = 0
        self._next_inbound_due_ms = 0
        self._outbound_timer = QTimer(self)
        self._outbound_timer.setSingleShot(True)
        self._outbound_timer.timeout.connect(self._flush_outbound_queue)
        self._inbound_timer = QTimer(self)
        self._inbound_timer.setSingleShot(True)
        self._inbound_timer.timeout.connect(self._flush_inbound_queue)

        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.readyRead.connect(self._on_ready_read)
        self._socket.errorOccurred.connect(self._on_error)

    @property
    def player_id(self) -> Optional[str]:
        return self._player_id

    @property
    def session_token(self) -> str:
        return str(self._session_token or "")

    @property
    def transport_epoch(self) -> int:
        return int(self._transport_epoch)

    def connect_to_host(
        self,
        host: str,
        port: int,
        name: str,
        persistent_player_id: str | None = None,
    ) -> None:
        next_name = name.strip()
        previous_name = self._requested_name
        previous_persistent_player_id = str(self._persistent_player_id or "").strip()
        self._requested_name = next_name
        self._player_id = None
        # Always start each transport connection with a fresh frame buffer.
        self._decoder = FrameDecoder()
        self._reset_transport_simulation_queues()
        # Reset per-call so stale values from previous joins are never reused.
        self._persistent_player_id = str(persistent_player_id or "").strip()
        if (
            self._persistent_player_id != previous_persistent_player_id
            or (persistent_player_id is None and previous_name and previous_name != next_name)
        ):
            self._session_token = ""
        self._transport_epoch += 1
        target_host, rewritten = _normalize_connect_host(host)
        if rewritten:
            self.log_line.emit(
                f"[WARN] '{host.strip()}' is a listen address and cannot be joined directly."
            )
            self.log_line.emit(
                f"[INFO] Using 127.0.0.1:{port} for a same-device connection."
            )
        self._announce_transport_simulation_if_needed()
        self.log_line.emit(f"[INFO] Connecting to {target_host}:{port}...")
        self._socket.connectToHost(target_host, int(port))

    def disconnect(self) -> None:
        state = self._socket.state()
        if state == QAbstractSocket.SocketState.UnconnectedState:
            self._reset_transport_simulation_queues()
            return
        # Use immediate close during teardown/reconnect flows to avoid Qt
        # wildcard-disconnect warnings from underlying native socket engines.
        self._reset_transport_simulation_queues()
        self._socket.abort()

    def is_connected(self) -> bool:
        return self._socket.state() == QAbstractSocket.SocketState.ConnectedState

    def is_connecting(self) -> bool:
        return self._socket.state() in (
            QAbstractSocket.SocketState.HostLookupState,
            QAbstractSocket.SocketState.ConnectingState,
        )

    def send(self, message: dict) -> bool:
        if self._socket.state() != QAbstractSocket.SocketState.ConnectedState:
            self.log_line.emit("[WARN] Cannot send while disconnected")
            return False
        try:
            transport_messages = prepare_outbound_transport_messages(message)
        except Exception as exc:
            self.log_line.emit(f"[ERROR] Failed to encode outbound message: {exc}")
            return False
        message_type = str(message.get("type") or "unknown")
        if len(transport_messages) > 1:
            self.log_line.emit(
                f"[INFO] Sending '{message_type}' in {len(transport_messages)} chunks."
            )
        for transport_message in transport_messages:
            try:
                encoded = encode_message(transport_message)
            except Exception as exc:
                self.log_line.emit(f"[ERROR] Failed to encode outbound message: {exc}")
                return False
            transport_message_type = str(transport_message.get("type") or message_type or "unknown")
            if self._should_drop_message(transport_message_type):
                self.log_line.emit(
                    f"[WARN] Simulated outbound packet loss for '{transport_message_type}'"
                )
                continue
            if self._transport_simulation.one_way_delay_ms > 0:
                self._queue_outbound_message(encoded, transport_message_type)
                continue
            written = int(self._socket.write(encoded))
            if written <= 0:
                self.log_line.emit("[ERROR] Failed to queue outbound message for send")
                return False
        return True

    def _on_connected(self) -> None:
        self.connected_to_server.emit(self._transport_epoch)
        self.log_line.emit("[INFO] Connected. Sending hello...")
        payload = {"type": "hello", "name": self._requested_name}
        if self._session_token:
            payload["session_token"] = self._session_token
        if self._persistent_player_id:
            payload["persistent_player_id"] = self._persistent_player_id
        self.send(payload)

    def _on_disconnected(self) -> None:
        self._player_id = None
        # Drop any partial frame bytes from the previous socket lifetime.
        self._decoder = FrameDecoder()
        self._inbound_chunked_messages.clear()
        self._reset_transport_simulation_queues()
        self.disconnected_from_server.emit(self._transport_epoch)
        self.log_line.emit("[INFO] Disconnected from host")

    def _on_error(self, _err) -> None:
        reason = str(self._socket.errorString() or "").strip() or "Unknown socket error"
        self.log_line.emit(f"[ERROR] Socket error: {reason}")
        self.socket_error.emit(self._transport_epoch, reason)

    def _on_ready_read(self) -> None:
        try:
            frames = self._decoder.feed(bytes(self._socket.readAll()))
        except Exception as exc:
            self.log_line.emit(f"[ERROR] Frame decode error: {exc}")
            self.disconnect()
            return

        for message in frames:
            if str(message.get("type") or "") == CHUNKED_MESSAGE_TYPE:
                try:
                    message = self._accumulate_chunked_message(message)
                except Exception as exc:
                    self.log_line.emit(f"[ERROR] Chunk decode error: {exc}")
                    self.disconnect()
                    return
                if message is None:
                    continue
            message_type = str(message.get("type") or "unknown")
            if self._should_drop_message(message_type):
                self.log_line.emit(
                    f"[WARN] Simulated inbound packet loss for '{message_type}'"
                )
                continue
            if self._transport_simulation.one_way_delay_ms > 0:
                self._queue_inbound_message(message)
                continue
            self._deliver_inbound_message(message)

    def _purge_stale_chunked_messages(self) -> None:
        now = time.monotonic()
        expired_ids = [
            chunk_id
            for chunk_id, entry in self._inbound_chunked_messages.items()
            if (now - float(entry.get("updated_monotonic") or 0.0)) > _CHUNKED_MESSAGE_TIMEOUT_SECONDS
        ]
        for chunk_id in expired_ids:
            self._inbound_chunked_messages.pop(chunk_id, None)

    def _accumulate_chunked_message(self, message: dict) -> dict | None:
        self._purge_stale_chunked_messages()
        chunk_id = str(message.get("chunk_id") or "").strip()
        if not chunk_id:
            raise ValueError("missing chunk id")
        try:
            chunk_index = int(message.get("chunk_index"))
            chunk_count = int(message.get("chunk_count"))
            packed_size = int(message.get("packed_size"))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid chunk metadata") from exc
        if chunk_index < 0 or chunk_count <= 0 or chunk_index >= chunk_count:
            raise ValueError("invalid chunk bounds")
        packed_sha256 = str(message.get("packed_sha256") or "").strip()
        if not packed_sha256:
            raise ValueError("missing chunk checksum")
        payload_bytes = decode_chunked_payload_bytes(payload_b64=str(message.get("payload_b64") or ""))
        entry = self._inbound_chunked_messages.get(chunk_id)
        if entry is None:
            entry = {
                "chunk_count": chunk_count,
                "packed_size": packed_size,
                "packed_sha256": packed_sha256,
                "chunks": {},
                "updated_monotonic": time.monotonic(),
            }
            self._inbound_chunked_messages[chunk_id] = entry
        elif (
            int(entry.get("chunk_count") or 0) != chunk_count
            or int(entry.get("packed_size") or 0) != packed_size
            or str(entry.get("packed_sha256") or "") != packed_sha256
        ):
            self._inbound_chunked_messages.pop(chunk_id, None)
            raise ValueError("conflicting chunk metadata")
        chunks = entry.get("chunks")
        if not isinstance(chunks, dict):
            chunks = {}
            entry["chunks"] = chunks
        chunks[chunk_index] = payload_bytes
        entry["updated_monotonic"] = time.monotonic()
        if len(chunks) < chunk_count:
            return None
        packed_payload = b"".join(chunks[index] for index in range(chunk_count))
        self._inbound_chunked_messages.pop(chunk_id, None)
        return restore_chunked_transport_message(
            packed_payload=packed_payload,
            packed_sha256=packed_sha256,
            packed_size=packed_size,
        )

    def _announce_transport_simulation_if_needed(self) -> None:
        if self._transport_simulation_announced:
            return
        self._transport_simulation_announced = True
        for warning in self._transport_simulation.warnings:
            self.log_line.emit(warning)
        if not self._transport_simulation.enabled:
            return
        self.log_line.emit(
            "[WARN] Simulating network conditions: "
            f"+{self._transport_simulation.ping_ms} ms ping, "
            f"{self._transport_simulation.packet_loss_percent:g}% packet loss."
        )

    def _reset_transport_simulation_queues(self) -> None:
        self._pending_outbound_messages.clear()
        self._pending_inbound_messages.clear()
        self._next_outbound_due_ms = 0
        self._next_inbound_due_ms = 0
        self._outbound_timer.stop()
        self._inbound_timer.stop()

    @staticmethod
    def _now_ms() -> int:
        return int(time.monotonic() * 1000)

    def _should_drop_message(self, message_type: str) -> bool:
        loss_percent = float(self._transport_simulation.packet_loss_percent)
        if loss_percent <= 0.0:
            return False
        if str(message_type or "unknown") in _LOSSLESS_MESSAGE_TYPES:
            return False
        return self._transport_rng.random() < (loss_percent / 100.0)

    def _queue_outbound_message(self, encoded: bytes, message_type: str) -> None:
        delay_ms = int(self._transport_simulation.one_way_delay_ms)
        due_ms = max(self._now_ms(), self._next_outbound_due_ms) + delay_ms
        self._next_outbound_due_ms = due_ms
        self._pending_outbound_messages.append(
            _QueuedOutboundMessage(
                due_ms=due_ms,
                encoded=encoded,
                message_type=str(message_type or "unknown"),
            )
        )
        self._arm_queue_timer(self._outbound_timer, self._pending_outbound_messages[0].due_ms)

    def _queue_inbound_message(self, message: dict) -> None:
        delay_ms = int(self._transport_simulation.one_way_delay_ms)
        due_ms = max(self._now_ms(), self._next_inbound_due_ms) + delay_ms
        self._next_inbound_due_ms = due_ms
        self._pending_inbound_messages.append(
            _QueuedInboundMessage(due_ms=due_ms, message=dict(message))
        )
        self._arm_queue_timer(self._inbound_timer, self._pending_inbound_messages[0].due_ms)

    def _arm_queue_timer(self, timer: QTimer, due_ms: int) -> None:
        delay_ms = max(0, int(due_ms - self._now_ms()))
        if timer.isActive():
            remaining = int(timer.remainingTime())
            if remaining >= 0 and remaining <= delay_ms:
                return
        timer.start(delay_ms)

    def _flush_outbound_queue(self) -> None:
        if self._socket.state() != QAbstractSocket.SocketState.ConnectedState:
            self._reset_transport_simulation_queues()
            return
        now_ms = self._now_ms()
        while self._pending_outbound_messages and self._pending_outbound_messages[0].due_ms <= now_ms:
            queued = self._pending_outbound_messages.pop(0)
            written = int(self._socket.write(queued.encoded))
            if written <= 0:
                self.log_line.emit(
                    f"[ERROR] Failed to queue delayed outbound '{queued.message_type}' message"
                )
                self.disconnect()
                return
        if self._pending_outbound_messages:
            self._arm_queue_timer(self._outbound_timer, self._pending_outbound_messages[0].due_ms)

    def _flush_inbound_queue(self) -> None:
        now_ms = self._now_ms()
        while self._pending_inbound_messages and self._pending_inbound_messages[0].due_ms <= now_ms:
            queued = self._pending_inbound_messages.pop(0)
            self._deliver_inbound_message(queued.message)
        if self._pending_inbound_messages:
            self._arm_queue_timer(self._inbound_timer, self._pending_inbound_messages[0].due_ms)

    def _deliver_inbound_message(self, message: dict) -> None:
        msg_type = message.get("type")
        if msg_type == "hello_ack":
            player_id = str(message.get("player_id", ""))
            self._player_id = player_id or None
            resumed = bool(message.get("resumed", False))
            session_token = str(message.get("session_token", "")).strip()
            if session_token:
                self._session_token = session_token
            if self._player_id:
                self.hello_ack.emit(self._transport_epoch, self._player_id, resumed)
            return
        self.message_received.emit(self._transport_epoch, message)
