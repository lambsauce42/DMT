from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .client import OnlineSessionClient
from .server import OnlineSessionServer

_HEARTBEAT_INTERVAL_MS = 3000
_HEARTBEAT_TIMEOUT_MS = 12000
_RECONNECT_BASE_DELAY_MS = 1200
_RECONNECT_MAX_DELAY_MS = 8000
_RECONNECT_MAX_ATTEMPTS = 5
_RECONNECT_CONNECT_TIMEOUT_MS = 6000


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HostSessionController(QObject):
    log_line = Signal(str)
    players_changed = Signal(dict)
    chat_received = Signal(str, str, bool)
    command_received = Signal(str, dict)
    snapshot_requested = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.server = OnlineSessionServer(self)
        self.server.log_line.connect(self.log_line)
        self.server.player_connected.connect(self._on_player_connected)
        self.server.player_disconnected.connect(self._on_player_disconnected)
        self.server.message_received.connect(self._on_server_message)
        self._pending_kick_messages: Dict[str, str] = {}

    @property
    def players(self) -> Dict[str, str]:
        return self.server.players

    def start(self, port: int) -> tuple[bool, str]:
        return self.server.start(port)

    def stop(self) -> None:
        self.server.stop()

    def broadcast_snapshot(self, snapshot: dict) -> None:
        self.server.broadcast({"type": "snapshot", "state": snapshot, "ts": _utc_timestamp()})

    def send_snapshot_to(self, player_id: str, snapshot: dict) -> None:
        self.server.send_to_player(player_id, {"type": "snapshot", "state": snapshot, "ts": _utc_timestamp()})

    def broadcast_player_state_patch(self, *, player_id: str, dungeon_id: str, state: dict) -> None:
        self.server.broadcast(
            {
                "type": "player_state_patch",
                "player_id": str(player_id or ""),
                "dungeon_id": str(dungeon_id or ""),
                "state": dict(state) if isinstance(state, dict) else {},
                "ts": _utc_timestamp(),
            }
        )

    def send_command_result(
        self,
        player_id: str,
        *,
        ok: bool,
        message: str,
        request_id: Optional[str] = None,
        data: Optional[dict] = None,
    ) -> None:
        payload = {
            "type": "command_result",
            "ok": bool(ok),
            "message": message,
            "request_id": request_id,
            "data": data or {},
        }
        self.server.send_to_player(player_id, payload)

    def kick_player(self, player_id: str, *, message: str) -> bool:
        clean_player_id = str(player_id or "").strip()
        player_name = self.players.get(clean_player_id, "")
        if not player_name:
            return False
        reason = str(message or "Removed from host.").strip() or "Removed from host."
        self._pending_kick_messages[clean_player_id] = reason
        ok = bool(self.server.disconnect_player(clean_player_id, message=reason))
        if not ok:
            self._pending_kick_messages.pop(clean_player_id, None)
            return False
        self.broadcast_chat(
            actor_name="System",
            text=f"{player_name} was kicked: {reason}",
            system=True,
        )
        return ok

    def broadcast_chat(self, *, actor_name: str, text: str, system: bool = False) -> None:
        packet = {
            "type": "chat",
            "actor_name": actor_name,
            "text": text,
            "system": bool(system),
            "ts": _utc_timestamp(),
        }
        self.server.broadcast(packet)
        self.chat_received.emit(actor_name, text, bool(system))

    def broadcast_ping(
        self,
        *,
        x: float,
        y: float,
        dungeon_id: str = "",
        sender_player_id: str = "",
    ) -> None:
        self.server.broadcast(
            {
                "type": "ping",
                "x": float(x),
                "y": float(y),
                "dungeon_id": str(dungeon_id or ""),
                "sender_player_id": str(sender_player_id or ""),
                "ts": _utc_timestamp(),
            }
        )

    def broadcast_media_event(self, *, action: str, payload: dict) -> None:
        self.server.broadcast(
            {
                "type": "media_event",
                "action": str(action or "").strip(),
                "payload": dict(payload or {}),
                "ts": _utc_timestamp(),
            }
        )

    def send_icon_asset(self, player_id: str, *, entity_id: str, filename: str, content_b64: str) -> None:
        self.server.send_to_player(
            player_id,
            {
                "type": "icon_asset",
                "entity_id": entity_id,
                "filename": filename,
                "content_b64": content_b64,
                "ts": _utc_timestamp(),
            },
        )

    def broadcast_icon_asset(self, *, entity_id: str, filename: str, content_b64: str) -> None:
        self.server.broadcast(
            {
                "type": "icon_asset",
                "entity_id": entity_id,
                "filename": filename,
                "content_b64": content_b64,
                "ts": _utc_timestamp(),
            }
        )

    def _on_player_connected(self, player_id: str, name: str, resumed: bool) -> None:
        self.players_changed.emit(self.players)
        self.broadcast_chat(
            actor_name="System",
            text=f"{name} reconnected" if resumed else f"{name} joined",
            system=True,
        )
        self._broadcast_presence()
        self.snapshot_requested.emit(player_id)

    def _on_player_disconnected(self, player_id: str, name: str) -> None:
        self.players_changed.emit(self.players)
        if self._pending_kick_messages.pop(str(player_id or "").strip(), None) is None:
            self.broadcast_chat(actor_name="System", text=f"{name} disconnected", system=True)
        self._broadcast_presence()

    def _on_server_message(self, player_id: str, message: dict) -> None:
        msg_type = message.get("type")
        if msg_type == "command":
            self.command_received.emit(player_id, message)
            return
        if msg_type == "chat":
            text = str(message.get("text", "")).strip()
            if not text:
                return
            actor_name = self.players.get(player_id, "Player")
            self.broadcast_chat(actor_name=actor_name, text=text, system=False)
            return
        if msg_type == "request_snapshot":
            self.snapshot_requested.emit(player_id)
            return
        self.server.send_to_player(player_id, {"type": "error", "message": "unknown message type"})

    def _broadcast_presence(self) -> None:
        self.server.broadcast({"type": "presence", "players": self.players, "ts": _utc_timestamp()})


class ClientSessionController(QObject):
    log_line = Signal(str)
    connected = Signal()
    disconnected = Signal()
    players_changed = Signal(dict)
    chat_received = Signal(str, str, bool)
    snapshot_received = Signal(dict)
    command_result = Signal(dict)
    player_state_patch_received = Signal(dict)
    icon_asset_received = Signal(str, str, str)
    ping_received = Signal(float, float, str)
    media_event_received = Signal(dict)
    reconnect_state_changed = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.client = OnlineSessionClient(self)
        self.client.log_line.connect(self.log_line)
        self.client.connected_to_server.connect(self._on_connected)
        self.client.disconnected_from_server.connect(self._on_disconnected)
        self.client.hello_ack.connect(self._on_hello_ack)
        self.client.socket_error.connect(self._on_socket_error)
        self.client.message_received.connect(self._on_message)

        self._players: Dict[str, str] = {}
        self._connect_host: str = ""
        self._connect_port: int = 0
        self._connect_name: str = ""
        self._connect_persistent_player_id: str = ""
        self._manual_disconnect = False
        self._reconnect_attempt = 0
        self._reconnect_paused = False
        self._reconnect_requires_established_session = True
        self._terminal_disconnect_message = ""
        self._session_established = False
        self._last_transport_error = ""

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setSingleShot(False)
        self._heartbeat_timer.setInterval(_HEARTBEAT_INTERVAL_MS)
        self._heartbeat_timer.timeout.connect(self._send_heartbeat)
        self._heartbeat_timeout_timer = QTimer(self)
        self._heartbeat_timeout_timer.setSingleShot(True)
        self._heartbeat_timeout_timer.setInterval(_HEARTBEAT_TIMEOUT_MS)
        self._heartbeat_timeout_timer.timeout.connect(self._on_heartbeat_timeout)
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._attempt_reconnect)
        self._reconnect_connect_timeout_timer = QTimer(self)
        self._reconnect_connect_timeout_timer.setSingleShot(True)
        self._reconnect_connect_timeout_timer.setInterval(_RECONNECT_CONNECT_TIMEOUT_MS)
        self._reconnect_connect_timeout_timer.timeout.connect(self._on_reconnect_connect_timeout)

    @property
    def player_id(self) -> Optional[str]:
        return self.client.player_id

    @property
    def players(self) -> Dict[str, str]:
        return dict(self._players)

    def connect_to_host(
        self,
        host: str,
        port: int,
        name: str,
        persistent_player_id: str | None = None,
    ) -> None:
        self._connect_host = str(host or "")
        self._connect_port = int(port)
        self._connect_name = str(name or "").strip()
        self._connect_persistent_player_id = str(persistent_player_id or "").strip()
        self._manual_disconnect = False
        self._terminal_disconnect_message = ""
        self._session_established = False
        self._last_transport_error = ""
        self._reconnect_paused = False
        self._reconnect_requires_established_session = True
        self._reconnect_timer.stop()
        self._reconnect_connect_timeout_timer.stop()
        self._emit_reconnect_state("idle")
        self.client.connect_to_host(
            host,
            port,
            name,
            persistent_player_id=self._connect_persistent_player_id,
        )

    def disconnect(self) -> None:
        self._manual_disconnect = True
        self._terminal_disconnect_message = ""
        self._session_established = False
        self._last_transport_error = ""
        self._reconnect_paused = False
        self._reconnect_attempt = 0
        self._reconnect_requires_established_session = True
        self._reconnect_timer.stop()
        self._reconnect_connect_timeout_timer.stop()
        self._heartbeat_timer.stop()
        self._heartbeat_timeout_timer.stop()
        self._players = {}
        self.players_changed.emit(self.players)
        self._emit_reconnect_state("idle")
        self.client.disconnect()

    def send_chat(self, text: str) -> None:
        self.client.send({"type": "chat", "text": text})

    def send_command(self, action: str, payload: dict, request_id: Optional[str] = None) -> bool:
        if request_id is None:
            request_id = uuid.uuid4().hex
        if not self.client.is_connected():
            self.log_line.emit(f"[WARN] Dropped '{action}' command while disconnected")
            return False
        sent = self.client.send(
            {
                "type": "command",
                "action": action,
                "payload": payload,
                "request_id": request_id,
            }
        )
        if sent is False:
            self.log_line.emit(f"[WARN] Failed to send '{action}' command")
            return False
        return True

    def request_snapshot(self) -> None:
        if self.client.is_connected():
            self.client.send({"type": "request_snapshot"})

    def _on_connected(self) -> None:
        self._reconnect_attempt = 0
        self._reconnect_paused = False
        self._terminal_disconnect_message = ""
        self._last_transport_error = ""
        self._heartbeat_timer.start()
        self._reset_heartbeat_timeout()
        self._reconnect_connect_timeout_timer.stop()
        self._emit_reconnect_state("connected")
        self.connected.emit()

    def _on_disconnected(self) -> None:
        had_session = bool(self._session_established)
        if had_session:
            # Once a session was established, reconnect attempts can continue
            # even before hello_ack arrives on the next transport.
            self._reconnect_requires_established_session = False
        self._session_established = False
        self._heartbeat_timer.stop()
        self._heartbeat_timeout_timer.stop()
        self._reconnect_connect_timeout_timer.stop()
        if (
            not self._manual_disconnect
            and not had_session
            and self._reconnect_requires_established_session
        ):
            if not self._terminal_disconnect_message:
                if self._last_transport_error:
                    self._terminal_disconnect_message = (
                        f"Unable to connect to host. {self._last_transport_error}"
                    )
                else:
                    self._terminal_disconnect_message = "Unable to connect to host."
            self._manual_disconnect = True
        if self._players:
            self._players = {}
            self.players_changed.emit(self.players)
        self.disconnected.emit()
        if not self._manual_disconnect:
            self._schedule_reconnect()
        else:
            self._emit_reconnect_state("idle")
        self._last_transport_error = ""

    def _on_hello_ack(self, player_id: str, resumed: bool) -> None:
        self._session_established = True
        self._reconnect_requires_established_session = False
        self.log_line.emit(
            f"[INFO] {'Reconnected' if resumed else 'Joined'} as {player_id}"
        )
        self._reset_heartbeat_timeout()
        self.request_snapshot()

    def _on_socket_error(self, reason: str) -> None:
        self._last_transport_error = str(reason or "").strip()

    @staticmethod
    def _friendly_join_error_message(reason: str) -> str:
        clean_reason = str(reason or "").strip()
        normalized = clean_reason.casefold()
        if normalized == "name already in use":
            return "Player name already in use. Choose a different name and reconnect."
        if normalized == "persistent id already in use":
            return "This player is already connected. Disconnect the other session or wait for it to close, then reconnect."
        if normalized == "hello required":
            return "Host rejected the connection during handshake."
        if normalized == "name required":
            return "Player name is required."
        return clean_reason or "Host rejected the connection."

    def _on_message(self, message: dict) -> None:
        self._reset_heartbeat_timeout()
        msg_type = message.get("type")
        if msg_type == "heartbeat_ack":
            return
        if msg_type == "presence":
            players = message.get("players") or {}
            if isinstance(players, dict):
                self._players = {str(k): str(v) for k, v in players.items()}
                self.players_changed.emit(self.players)
            return
        if msg_type == "chat":
            actor_name = str(message.get("actor_name", "Player"))
            text = str(message.get("text", ""))
            system = bool(message.get("system", False))
            self.chat_received.emit(actor_name, text, system)
            return
        if msg_type == "snapshot":
            state = message.get("state")
            if isinstance(state, dict):
                self.snapshot_received.emit(state)
            return
        if msg_type == "command_result":
            self.command_result.emit(message)
            return
        if msg_type == "player_state_patch":
            self.player_state_patch_received.emit(dict(message))
            return
        if msg_type == "icon_asset":
            entity_id = str(message.get("entity_id", ""))
            filename = str(message.get("filename", "icon.png"))
            content_b64 = str(message.get("content_b64", ""))
            if entity_id and content_b64:
                self.icon_asset_received.emit(entity_id, filename, content_b64)
            return
        if msg_type == "ping":
            try:
                x = float(message.get("x"))
                y = float(message.get("y"))
            except (TypeError, ValueError):
                return
            sender_player_id = str(message.get("sender_player_id", ""))
            local_player_id = str(self.player_id or "")
            if sender_player_id and local_player_id and sender_player_id == local_player_id:
                return
            dungeon_id = str(message.get("dungeon_id", ""))
            self.ping_received.emit(x, y, dungeon_id)
            return
        if msg_type == "media_event":
            self.media_event_received.emit(dict(message))
            return
        if msg_type == "error":
            reason = str(message.get("message", "")).strip() or "unknown error"
            self.log_line.emit(f"[ERROR] {reason}")
            if not self._session_established:
                self._terminal_disconnect_message = self._friendly_join_error_message(reason)
                self._manual_disconnect = True
            return
        if msg_type == "kicked":
            reason = str(message.get("message", "")).strip() or "Removed from host."
            self._manual_disconnect = True
            self._terminal_disconnect_message = reason
            self.log_line.emit(f"[ERROR] {reason}")
            self.client.disconnect()
            return

    def _send_heartbeat(self) -> None:
        if not self.client.is_connected():
            self._heartbeat_timer.stop()
            return
        self.client.send({"type": "heartbeat"})

    def _reset_heartbeat_timeout(self) -> None:
        if not self.client.is_connected():
            self._heartbeat_timeout_timer.stop()
            return
        self._heartbeat_timeout_timer.start()

    def _on_heartbeat_timeout(self) -> None:
        if not self.client.is_connected():
            return
        self.log_line.emit("[WARN] Connection heartbeat timed out")
        self.client.disconnect()

    def _schedule_reconnect(self) -> None:
        if self._manual_disconnect:
            return
        if not self._connect_host or self._connect_port <= 0:
            return
        if self._reconnect_paused:
            return
        if self._reconnect_timer.isActive():
            return
        if self._reconnect_attempt >= _RECONNECT_MAX_ATTEMPTS:
            self._reconnect_paused = True
            self.log_line.emit(
                "[WARN] Reconnect paused after repeated failures. "
                "Use manual retry to try again."
            )
            self._emit_reconnect_state(
                "paused",
                attempt=self._reconnect_attempt,
                max_attempts=_RECONNECT_MAX_ATTEMPTS,
                next_delay_ms=0,
            )
            return
        attempt = self._reconnect_attempt + 1
        delay_ms = min(_RECONNECT_MAX_DELAY_MS, _RECONNECT_BASE_DELAY_MS * attempt)
        self._reconnect_attempt = attempt
        self.log_line.emit(
            f"[WARN] Connection lost. Reconnecting in {delay_ms / 1000:.1f}s (attempt {attempt})..."
        )
        self._emit_reconnect_state(
            "scheduled",
            attempt=attempt,
            max_attempts=_RECONNECT_MAX_ATTEMPTS,
            next_delay_ms=delay_ms,
        )
        self._reconnect_timer.start(delay_ms)

    def _attempt_reconnect(self) -> None:
        if self._manual_disconnect:
            return
        if self._reconnect_paused:
            return
        if self.client.is_connected() or self.client.is_connecting():
            return
        self._emit_reconnect_state(
            "attempting",
            attempt=self._reconnect_attempt,
            max_attempts=_RECONNECT_MAX_ATTEMPTS,
            next_delay_ms=0,
        )
        self.client.connect_to_host(
            self._connect_host,
            int(self._connect_port),
            self._connect_name,
            persistent_player_id=self._connect_persistent_player_id,
        )
        self._reconnect_connect_timeout_timer.start()

    def _on_reconnect_connect_timeout(self) -> None:
        if self._manual_disconnect or self._reconnect_paused:
            return
        if self.client.is_connected():
            return
        if self.client.is_connecting():
            self.log_line.emit(
                "[WARN] Reconnect attempt timed out. Forcing reconnect retry."
            )
            self.client.disconnect()
            return
        self._schedule_reconnect()

    def retry_reconnect(self) -> bool:
        if self._manual_disconnect:
            return False
        if not self._reconnect_paused:
            return False
        self._reconnect_paused = False
        self._reconnect_attempt = 0
        self.log_line.emit("[INFO] Manual reconnect retry started.")
        self._attempt_reconnect()
        return True

    def _emit_reconnect_state(
        self,
        status: str,
        *,
        attempt: int = 0,
        max_attempts: int = _RECONNECT_MAX_ATTEMPTS,
        next_delay_ms: int = 0,
    ) -> None:
        self.reconnect_state_changed.emit(
            {
                "status": str(status or "").strip() or "idle",
                "attempt": max(0, int(attempt)),
                "max_attempts": max(1, int(max_attempts)),
                "next_delay_ms": max(0, int(next_delay_ms)),
                # -1 indicates unlimited manual retries.
                "manual_retry_budget": -1,
                "manual_retry_available": bool(self._reconnect_paused),
            }
        )

    def consume_terminal_disconnect_message(self) -> str:
        message = str(self._terminal_disconnect_message or "").strip()
        self._terminal_disconnect_message = ""
        return message
