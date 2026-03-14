from __future__ import annotations

import uuid
import time
from dataclasses import dataclass
from typing import Dict, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer, QTcpSocket

from .protocol import (
    CHUNKED_MESSAGE_TYPE,
    FrameDecoder,
    decode_chunked_payload_bytes,
    encode_message,
    prepare_outbound_transport_messages,
    restore_chunked_transport_message,
)

_RECONNECT_GRACE_SECONDS = 10 * 60
_CHUNKED_MESSAGE_TIMEOUT_SECONDS = 60.0


@dataclass(slots=True)
class _ConnectionState:
    socket: QTcpSocket
    decoder: FrameDecoder
    player_id: Optional[str] = None
    name: str = ""
    session_token: str = ""


@dataclass(slots=True)
class _IdentityState:
    player_id: str
    name: str
    normalized_name: str
    session_token: str
    persistent_player_id: str
    connected: bool = False
    last_seen_monotonic: float = 0.0


class OnlineSessionServer(QObject):
    log_line = Signal(str)
    player_connected = Signal(str, str, bool)
    player_disconnected = Signal(str, str)
    message_received = Signal(str, dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._server.acceptError.connect(self._on_accept_error)
        self._stopping = False

        self._connections: Dict[QTcpSocket, _ConnectionState] = {}
        self._names_lower: Dict[str, str] = {}
        self._players: Dict[str, str] = {}
        self._identities: Dict[str, _IdentityState] = {}
        self._name_to_identity: Dict[str, str] = {}
        self._token_to_identity: Dict[str, str] = {}
        self._persistent_to_identity: Dict[str, str] = {}
        self._inbound_chunked_messages: Dict[QTcpSocket, Dict[str, dict]] = {}

    @property
    def players(self) -> Dict[str, str]:
        return dict(self._players)

    def start(self, port: int) -> tuple[bool, str]:
        ok = self._server.listen(QHostAddress.SpecialAddress.AnyIPv4, int(port))
        if not ok:
            err = self._server.errorString()
            self.log_line.emit(f"[ERROR] Failed to listen on port {port}: {err}")
            return False, err
        self.log_line.emit(f"[INFO] Listening on 0.0.0.0:{port} (all interfaces)")
        self.log_line.emit(f"[INFO] Same-device join address: 127.0.0.1:{port}")
        self.log_line.emit("[INFO] LAN/Internet players must use your LAN/public IP (not 0.0.0.0).")
        return True, ""

    def stop(self) -> None:
        self._stopping = True
        for sock in list(self._connections.keys()):
            self._detach_socket_signals(sock)
            try:
                if sock.state() != QAbstractSocket.SocketState.UnconnectedState:
                    sock.abort()
            except RuntimeError:
                pass
            sock.deleteLater()
        self._connections.clear()
        self._players.clear()
        self._names_lower.clear()
        self._identities.clear()
        self._name_to_identity.clear()
        self._token_to_identity.clear()
        self._persistent_to_identity.clear()
        if self._server.isListening():
            self._server.close()
        self._stopping = False
        self.log_line.emit("[INFO] Server stopped")

    def send_to_player(self, player_id: str, message: dict) -> None:
        target_socket = None
        for sock, state in self._connections.items():
            if state.player_id == player_id:
                target_socket = sock
                break
        if target_socket is None:
            return
        self._send_socket_message(target_socket, message)

    def disconnect_player(self, player_id: str, *, message: str = "") -> bool:
        target_socket = self._find_socket_for_player(player_id)
        if target_socket is None:
            return False
        if message:
            self._send_socket_message(
                target_socket,
                {
                    "type": "kicked",
                    "message": str(message or "Removed from host."),
                },
            )
        target_socket.disconnectFromHost()
        return True

    def broadcast(self, message: dict) -> None:
        for sock, state in list(self._connections.items()):
            if state.player_id:
                self._send_socket_message(sock, message)

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            state = _ConnectionState(socket=socket, decoder=FrameDecoder())
            self._connections[socket] = state
            self._inbound_chunked_messages[socket] = {}
            socket.readyRead.connect(self._on_ready_read_for_socket)
            socket.disconnected.connect(self._on_socket_disconnected)
            socket.errorOccurred.connect(self._on_socket_error_signal)
            peer = f"{socket.peerAddress().toString()}:{socket.peerPort()}"
            self.log_line.emit(f"[INFO] Incoming connection from {peer}")

    def _detach_socket_signals(self, socket: QTcpSocket) -> None:
        try:
            socket.readyRead.disconnect(self._on_ready_read_for_socket)
        except (TypeError, RuntimeError):
            pass
        try:
            socket.disconnected.disconnect(self._on_socket_disconnected)
        except (TypeError, RuntimeError):
            pass
        try:
            socket.errorOccurred.disconnect(self._on_socket_error_signal)
        except (TypeError, RuntimeError):
            pass

    def _on_ready_read_for_socket(self) -> None:
        socket = self.sender()
        if isinstance(socket, QTcpSocket):
            self._on_ready_read(socket)

    def _on_socket_disconnected(self) -> None:
        socket = self.sender()
        if isinstance(socket, QTcpSocket):
            self._on_disconnected(socket)

    def _on_socket_error_signal(self, _err) -> None:
        socket = self.sender()
        if isinstance(socket, QTcpSocket):
            self._on_socket_error(socket)

    def _on_accept_error(self, _err) -> None:
        self.log_line.emit(f"[ERROR] Accept error: {self._server.errorString()}")

    def _on_socket_error(self, socket: QTcpSocket) -> None:
        self.log_line.emit(f"[WARN] Socket error: {socket.errorString()}")

    def _on_disconnected(self, socket: QTcpSocket) -> None:
        self._detach_socket_signals(socket)
        state = self._connections.pop(socket, None)
        self._inbound_chunked_messages.pop(socket, None)
        if state and state.player_id:
            self._players.pop(state.player_id, None)
            self._names_lower.pop(state.name.lower(), None)
            identity = self._identities.get(state.player_id)
            if identity is not None:
                identity.connected = False
                identity.last_seen_monotonic = time.monotonic()
            if not self._stopping:
                self.player_disconnected.emit(state.player_id, state.name)
                self.log_line.emit(f"[INFO] Disconnected: {state.name} ({state.player_id})")
        if not self._stopping:
            self._prune_expired_identities()
        socket.deleteLater()

    def _on_ready_read(self, socket: QTcpSocket) -> None:
        state = self._connections.get(socket)
        if state is None:
            return
        try:
            frames = state.decoder.feed(bytes(socket.readAll()))
        except Exception as exc:
            self.log_line.emit(f"[ERROR] Frame decode error: {exc}")
            self._send_socket_message(socket, {"type": "error", "message": "invalid frame"})
            socket.disconnectFromHost()
            return

        for message in frames:
            if str(message.get("type") or "") == CHUNKED_MESSAGE_TYPE:
                try:
                    message = self._accumulate_chunked_message(socket, message)
                except Exception as exc:
                    self.log_line.emit(f"[ERROR] Chunk decode error: {exc}")
                    socket.disconnectFromHost()
                    return
                if message is None:
                    continue
            if not state.player_id:
                self._handle_handshake(state, message)
                continue
            msg_type = str(message.get("type") or "")
            if msg_type == "heartbeat":
                self._send_socket_message(state.socket, {"type": "heartbeat_ack"})
                continue
            if msg_type == "heartbeat_ack":
                continue
            self.message_received.emit(state.player_id, message)

    def _handle_handshake(self, state: _ConnectionState, message: dict) -> None:
        if message.get("type") != "hello":
            self._send_socket_message(state.socket, {"type": "error", "message": "hello required"})
            state.socket.disconnectFromHost()
            return

        name = str(message.get("name", "")).strip()
        if not name:
            self._send_socket_message(state.socket, {"type": "error", "message": "name required"})
            state.socket.disconnectFromHost()
            return

        self._prune_expired_identities()
        normalized = name.lower()
        resume_token = str(message.get("session_token", "")).strip()
        persistent_player_id = str(message.get("persistent_player_id", "")).strip()
        identity: _IdentityState | None = None
        resumed = False

        if resume_token:
            existing_id = self._token_to_identity.get(resume_token)
            if existing_id:
                token_identity = self._identities.get(existing_id)
                if token_identity is not None:
                    identity = token_identity
                    resumed = True

        if identity is None and persistent_player_id:
            existing_id = self._persistent_to_identity.get(persistent_player_id)
            if existing_id:
                persistent_identity = self._identities.get(existing_id)
                if (
                    persistent_identity is not None
                    and (not persistent_identity.connected)
                ):
                    identity = persistent_identity
                    resumed = True

        # Never allow a new socket to claim an existing persistent id that did not
        # pass the safe resume rules above.
        if identity is None and persistent_player_id:
            existing_id = self._persistent_to_identity.get(persistent_player_id)
            if existing_id:
                self._send_socket_message(
                    state.socket,
                    {"type": "error", "message": "persistent id already in use"},
                )
                state.socket.disconnectFromHost()
                return

        active_player_id = self._names_lower.get(normalized)
        if active_player_id and (identity is None or active_player_id != identity.player_id):
            self._send_socket_message(state.socket, {"type": "error", "message": "name already in use"})
            state.socket.disconnectFromHost()
            return

        if identity is None:
            player_id = persistent_player_id or uuid.uuid4().hex
            if player_id in self._identities:
                player_id = uuid.uuid4().hex
            session_token = uuid.uuid4().hex
            persistent_id = persistent_player_id or player_id
            identity = _IdentityState(
                player_id=player_id,
                name=name,
                normalized_name=normalized,
                session_token=session_token,
                persistent_player_id=persistent_id,
                connected=False,
                last_seen_monotonic=time.monotonic(),
            )
            self._identities[player_id] = identity
            self._name_to_identity[normalized] = player_id
            self._token_to_identity[session_token] = player_id
        else:
            previous_normalized_name = str(identity.normalized_name or "").strip()
            if previous_normalized_name and previous_normalized_name != normalized:
                if self._names_lower.get(previous_normalized_name) == identity.player_id:
                    self._names_lower.pop(previous_normalized_name, None)
                if self._name_to_identity.get(previous_normalized_name) == identity.player_id:
                    self._name_to_identity.pop(previous_normalized_name, None)
            identity.name = name
            identity.normalized_name = normalized
            identity.last_seen_monotonic = time.monotonic()
            if persistent_player_id and persistent_player_id != identity.persistent_player_id:
                self.log_line.emit(
                    "[WARN] Ignored mismatched persistent id for existing identity"
                )

        if identity.connected:
            existing_socket = self._find_socket_for_player(identity.player_id)
            if existing_socket is not None and existing_socket is not state.socket:
                self._connections.pop(existing_socket, None)
                existing_socket.disconnectFromHost()
                existing_socket.deleteLater()

        identity.connected = True
        self._players[identity.player_id] = identity.name
        self._names_lower[identity.normalized_name] = identity.player_id
        self._name_to_identity[identity.normalized_name] = identity.player_id
        self._token_to_identity[identity.session_token] = identity.player_id
        self._persistent_to_identity[identity.persistent_player_id] = identity.player_id

        state.player_id = identity.player_id
        state.name = identity.name
        state.session_token = identity.session_token

        self._send_socket_message(
            state.socket,
            {
                "type": "hello_ack",
                "player_id": identity.player_id,
                "session_token": identity.session_token,
                "persistent_player_id": identity.persistent_player_id,
                "resumed": bool(resumed),
            },
        )
        self.player_connected.emit(identity.player_id, identity.name, bool(resumed))
        if resumed:
            self.log_line.emit(f"[INFO] Reconnected player '{identity.name}' ({identity.player_id})")
        else:
            self.log_line.emit(f"[INFO] Accepted player '{identity.name}' ({identity.player_id})")

    def _find_socket_for_player(self, player_id: str) -> QTcpSocket | None:
        for socket, state in self._connections.items():
            if state.player_id == player_id:
                return socket
        return None

    def _prune_expired_identities(self) -> None:
        now = time.monotonic()
        expired_ids = [
            player_id
            for player_id, identity in self._identities.items()
            if (not identity.connected)
            and (now - float(identity.last_seen_monotonic)) > _RECONNECT_GRACE_SECONDS
        ]
        for player_id in expired_ids:
            identity = self._identities.pop(player_id, None)
            if identity is None:
                continue
            if self._name_to_identity.get(identity.normalized_name) == player_id:
                self._name_to_identity.pop(identity.normalized_name, None)
            if self._token_to_identity.get(identity.session_token) == player_id:
                self._token_to_identity.pop(identity.session_token, None)
            if self._persistent_to_identity.get(identity.persistent_player_id) == player_id:
                self._persistent_to_identity.pop(identity.persistent_player_id, None)

    def _send_socket_message(self, socket: QTcpSocket, message: dict) -> None:
        try:
            transport_messages = prepare_outbound_transport_messages(message)
        except Exception as exc:
            self.log_line.emit(f"[ERROR] Send failed: {exc}")
            return
        if len(transport_messages) > 1:
            self.log_line.emit(
                f"[INFO] Sending '{str(message.get('type') or 'unknown')}' in {len(transport_messages)} chunks."
            )
        for transport_message in transport_messages:
            try:
                encoded = encode_message(transport_message)
            except Exception as exc:
                self.log_line.emit(f"[ERROR] Send failed: {exc}")
                return
            try:
                bytes_written = socket.write(encoded)
                if int(bytes_written) < 0:
                    raise RuntimeError("socket write failed")
            except Exception as exc:
                self.log_line.emit(f"[ERROR] Send failed: {exc}")
                try:
                    socket.disconnectFromHost()
                except Exception:
                    pass
                return

    def _purge_stale_chunked_messages(self, socket: QTcpSocket) -> None:
        now = time.monotonic()
        bucket = self._inbound_chunked_messages.get(socket)
        if not isinstance(bucket, dict):
            return
        expired_ids = [
            chunk_id
            for chunk_id, entry in bucket.items()
            if (now - float(entry.get("updated_monotonic") or 0.0)) > _CHUNKED_MESSAGE_TIMEOUT_SECONDS
        ]
        for chunk_id in expired_ids:
            bucket.pop(chunk_id, None)

    def _accumulate_chunked_message(self, socket: QTcpSocket, message: dict) -> dict | None:
        self._purge_stale_chunked_messages(socket)
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
        bucket = self._inbound_chunked_messages.setdefault(socket, {})
        entry = bucket.get(chunk_id)
        if entry is None:
            entry = {
                "chunk_count": chunk_count,
                "packed_size": packed_size,
                "packed_sha256": packed_sha256,
                "chunks": {},
                "updated_monotonic": time.monotonic(),
            }
            bucket[chunk_id] = entry
        elif (
            int(entry.get("chunk_count") or 0) != chunk_count
            or int(entry.get("packed_size") or 0) != packed_size
            or str(entry.get("packed_sha256") or "") != packed_sha256
        ):
            bucket.pop(chunk_id, None)
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
        bucket.pop(chunk_id, None)
        return restore_chunked_transport_message(
            packed_payload=packed_payload,
            packed_sha256=packed_sha256,
            packed_size=packed_size,
        )
