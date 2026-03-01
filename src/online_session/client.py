from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket

from .protocol import FrameDecoder, encode_message

_WILDCARD_LISTEN_HOSTS = {"0.0.0.0", "::", "[::]", "0:0:0:0:0:0:0:0"}


def _normalize_connect_host(host: str) -> tuple[str, bool]:
    cleaned = host.strip()
    if cleaned.lower() in _WILDCARD_LISTEN_HOSTS:
        return "127.0.0.1", True
    return cleaned, False


class OnlineSessionClient(QObject):
    log_line = Signal(str)
    connected_to_server = Signal()
    disconnected_from_server = Signal()
    hello_ack = Signal(str)
    message_received = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._socket = QTcpSocket(self)
        self._decoder = FrameDecoder()
        self._requested_name = ""
        self._player_id: Optional[str] = None
        self._session_token: str = ""
        self._persistent_player_id: str = ""

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

    def connect_to_host(
        self,
        host: str,
        port: int,
        name: str,
        persistent_player_id: str | None = None,
    ) -> None:
        self._requested_name = name.strip()
        self._player_id = None
        # Always start each transport connection with a fresh frame buffer.
        self._decoder = FrameDecoder()
        # Reset per-call so stale values from previous joins are never reused.
        self._persistent_player_id = str(persistent_player_id or "").strip()
        target_host, rewritten = _normalize_connect_host(host)
        if rewritten:
            self.log_line.emit(
                f"[WARN] '{host.strip()}' is a listen address and cannot be joined directly."
            )
            self.log_line.emit(
                f"[INFO] Using 127.0.0.1:{port} for a same-device connection."
            )
        self.log_line.emit(f"[INFO] Connecting to {target_host}:{port}...")
        self._socket.connectToHost(target_host, int(port))

    def disconnect(self) -> None:
        state = self._socket.state()
        if state == QAbstractSocket.SocketState.UnconnectedState:
            return
        # Use immediate close during teardown/reconnect flows to avoid Qt
        # wildcard-disconnect warnings from underlying native socket engines.
        self._socket.abort()

    def is_connected(self) -> bool:
        return self._socket.state() == QAbstractSocket.SocketState.ConnectedState

    def is_connecting(self) -> bool:
        return self._socket.state() in (
            QAbstractSocket.SocketState.HostLookupState,
            QAbstractSocket.SocketState.ConnectingState,
        )

    def send(self, message: dict) -> None:
        if self._socket.state() != QAbstractSocket.SocketState.ConnectedState:
            self.log_line.emit("[WARN] Cannot send while disconnected")
            return
        try:
            encoded = encode_message(message)
        except Exception as exc:
            self.log_line.emit(f"[ERROR] Failed to encode outbound message: {exc}")
            return
        self._socket.write(encoded)

    def _on_connected(self) -> None:
        self.connected_to_server.emit()
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
        self.disconnected_from_server.emit()
        self.log_line.emit("[INFO] Disconnected from host")

    def _on_error(self, _err) -> None:
        self.log_line.emit(f"[ERROR] Socket error: {self._socket.errorString()}")

    def _on_ready_read(self) -> None:
        try:
            frames = self._decoder.feed(bytes(self._socket.readAll()))
        except Exception as exc:
            self.log_line.emit(f"[ERROR] Frame decode error: {exc}")
            self.disconnect()
            return

        for message in frames:
            msg_type = message.get("type")
            if msg_type == "hello_ack":
                player_id = str(message.get("player_id", ""))
                self._player_id = player_id or None
                session_token = str(message.get("session_token", "")).strip()
                if session_token:
                    self._session_token = session_token
                if self._player_id:
                    self.hello_ack.emit(self._player_id)
                continue
            self.message_received.emit(message)
