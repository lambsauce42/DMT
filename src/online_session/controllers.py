from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Dict, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .client import OnlineSessionClient
from .server import OnlineSessionServer

_COMMAND_RESULT_CACHE_TTL_SECONDS = 180.0
_HEARTBEAT_INTERVAL_MS = 3000
_HEARTBEAT_TIMEOUT_MS = 12000
_RECONNECT_BASE_DELAY_MS = 1200
_RECONNECT_MAX_DELAY_MS = 8000
_COMMAND_RETRY_TIMEOUT_SECONDS = 2.5
_COMMAND_RETRY_MAX_ATTEMPTS = 3
_RETRYABLE_PLAYER_ACTIONS = {
    "claim_loot",
    "add_loot_from_inventory",
    "link_character_entity",
    "sync_character_inventory",
    "initiative_update",
    "upload_icon",
}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class _PendingCommand:
    action: str
    payload: dict
    attempts: int
    last_sent_monotonic: float


class HostSessionController(QObject):
    log_line = pyqtSignal(str)
    players_changed = pyqtSignal(dict)
    chat_received = pyqtSignal(str, str, bool)
    command_received = pyqtSignal(str, dict)
    snapshot_requested = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.server = OnlineSessionServer(self)
        self.server.log_line.connect(self.log_line)
        self.server.player_connected.connect(self._on_player_connected)
        self.server.player_disconnected.connect(self._on_player_disconnected)
        self.server.message_received.connect(self._on_server_message)
        self._command_result_cache: Dict[tuple[str, str], tuple[float, dict]] = {}
        self._inflight_requests: set[tuple[str, str]] = set()

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

    def send_command_result(
        self,
        player_id: str,
        *,
        ok: bool,
        message: str,
        request_id: Optional[str] = None,
        data: Optional[dict] = None,
    ) -> None:
        self._prune_command_result_cache()
        payload = {
            "type": "command_result",
            "ok": bool(ok),
            "message": message,
            "request_id": request_id,
            "data": data or {},
        }
        if request_id:
            key = (str(player_id), str(request_id))
            self._command_result_cache[key] = (time.monotonic(), dict(payload))
            self._inflight_requests.discard(key)
        self.server.send_to_player(player_id, payload)

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

    def _on_player_connected(self, player_id: str, name: str) -> None:
        self.players_changed.emit(self.players)
        self.broadcast_chat(actor_name="System", text=f"{name} joined", system=True)
        self._broadcast_presence()
        self.snapshot_requested.emit(player_id)

    def _on_player_disconnected(self, player_id: str, name: str) -> None:
        pid = str(player_id or "")
        self._inflight_requests = {key for key in self._inflight_requests if key[0] != pid}
        self._command_result_cache = {
            key: value for key, value in self._command_result_cache.items() if key[0] != pid
        }
        self.players_changed.emit(self.players)
        self.broadcast_chat(actor_name="System", text=f"{name} left", system=True)
        self._broadcast_presence()

    def _on_server_message(self, player_id: str, message: dict) -> None:
        msg_type = message.get("type")
        if msg_type == "command":
            request_id = str(message.get("request_id") or "").strip()
            if request_id:
                self._prune_command_result_cache()
                key = (str(player_id), request_id)
                cached = self._command_result_cache.get(key)
                if cached is not None:
                    self.server.send_to_player(player_id, cached[1])
                    return
                if key in self._inflight_requests:
                    return
                self._inflight_requests.add(key)
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

    def _prune_command_result_cache(self) -> None:
        now = time.monotonic()
        self._command_result_cache = {
            key: value
            for key, value in self._command_result_cache.items()
            if (now - float(value[0])) <= _COMMAND_RESULT_CACHE_TTL_SECONDS
        }


class ClientSessionController(QObject):
    log_line = pyqtSignal(str)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    players_changed = pyqtSignal(dict)
    chat_received = pyqtSignal(str, str, bool)
    snapshot_received = pyqtSignal(dict)
    command_result = pyqtSignal(dict)
    icon_asset_received = pyqtSignal(str, str, str)
    ping_received = pyqtSignal(float, float, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.client = OnlineSessionClient(self)
        self.client.log_line.connect(self.log_line)
        self.client.connected_to_server.connect(self._on_connected)
        self.client.disconnected_from_server.connect(self._on_disconnected)
        self.client.hello_ack.connect(self._on_hello_ack)
        self.client.message_received.connect(self._on_message)

        self._players: Dict[str, str] = {}
        self._pending_commands: Dict[str, _PendingCommand] = {}
        self._connect_host: str = ""
        self._connect_port: int = 0
        self._connect_name: str = ""
        self._manual_disconnect = False
        self._reconnect_attempt = 0

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
        self._pending_retry_timer = QTimer(self)
        self._pending_retry_timer.setSingleShot(False)
        self._pending_retry_timer.setInterval(600)
        self._pending_retry_timer.timeout.connect(self._on_pending_retry_tick)

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
        self._manual_disconnect = False
        self._reconnect_timer.stop()
        self.client.connect_to_host(
            host,
            port,
            name,
            persistent_player_id=persistent_player_id,
        )

    def disconnect(self) -> None:
        self._manual_disconnect = True
        self._reconnect_timer.stop()
        self._heartbeat_timer.stop()
        self._heartbeat_timeout_timer.stop()
        self._pending_retry_timer.stop()
        self._pending_commands.clear()
        self._players = {}
        self.players_changed.emit(self.players)
        self.client.disconnect()

    def send_chat(self, text: str) -> None:
        self.client.send({"type": "chat", "text": text})

    def send_command(self, action: str, payload: dict, request_id: Optional[str] = None) -> None:
        if request_id is None:
            request_id = uuid.uuid4().hex
        if not self.client.is_connected():
            self.log_line.emit(f"[WARN] Dropped '{action}' command while disconnected")
            return
        self.client.send(
            {
                "type": "command",
                "action": action,
                "payload": payload,
                "request_id": request_id,
            }
        )
        clean_request_id = str(request_id or "").strip()
        if clean_request_id and str(action or "") in _RETRYABLE_PLAYER_ACTIONS:
            self._pending_commands[clean_request_id] = _PendingCommand(
                action=str(action or ""),
                payload=dict(payload or {}),
                attempts=1,
                last_sent_monotonic=time.monotonic(),
            )
            if self.client.is_connected() and not self._pending_retry_timer.isActive():
                self._pending_retry_timer.start()

    def request_snapshot(self) -> None:
        if self.client.is_connected():
            self.client.send({"type": "request_snapshot"})

    def _on_connected(self) -> None:
        self._reconnect_attempt = 0
        self._heartbeat_timer.start()
        self._reset_heartbeat_timeout()
        if self._pending_commands and not self._pending_retry_timer.isActive():
            self._pending_retry_timer.start()
        self.connected.emit()

    def _on_disconnected(self) -> None:
        self._heartbeat_timer.stop()
        self._heartbeat_timeout_timer.stop()
        self._pending_retry_timer.stop()
        if self._players:
            self._players = {}
            self.players_changed.emit(self.players)
        self.disconnected.emit()
        if not self._manual_disconnect:
            self._schedule_reconnect()

    def _on_hello_ack(self, player_id: str) -> None:
        self.log_line.emit(f"[INFO] Joined as {player_id}")
        self._reset_heartbeat_timeout()
        self.request_snapshot()
        self._resend_pending_commands()
        if self._pending_commands and not self._pending_retry_timer.isActive():
            self._pending_retry_timer.start()

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
            request_id = str(message.get("request_id") or "").strip()
            if request_id:
                self._pending_commands.pop(request_id, None)
                if not self._pending_commands and self._pending_retry_timer.isActive():
                    self._pending_retry_timer.stop()
            self.command_result.emit(message)
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
        if msg_type == "error":
            self.log_line.emit(f"[ERROR] {message.get('message', 'unknown error')}")
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
        if self._reconnect_timer.isActive():
            return
        attempt = self._reconnect_attempt + 1
        delay_ms = min(_RECONNECT_MAX_DELAY_MS, _RECONNECT_BASE_DELAY_MS * attempt)
        self._reconnect_attempt = attempt
        self.log_line.emit(
            f"[WARN] Connection lost. Reconnecting in {delay_ms / 1000:.1f}s (attempt {attempt})..."
        )
        self._reconnect_timer.start(delay_ms)

    def _attempt_reconnect(self) -> None:
        if self._manual_disconnect:
            return
        if self.client.is_connected() or self.client.is_connecting():
            return
        self.client.connect_to_host(
            self._connect_host,
            int(self._connect_port),
            self._connect_name,
        )

    def _resend_pending_commands(self) -> None:
        if not self.client.is_connected():
            return
        now = time.monotonic()
        for request_id, pending in self._pending_commands.items():
            self.client.send(
                {
                    "type": "command",
                    "action": pending.action,
                    "payload": dict(pending.payload),
                    "request_id": request_id,
                }
            )
            pending.last_sent_monotonic = now

    def _on_pending_retry_tick(self) -> None:
        if not self.client.is_connected():
            self._pending_retry_timer.stop()
            return
        now = time.monotonic()
        expired: list[str] = []
        for request_id, pending in self._pending_commands.items():
            if (now - float(pending.last_sent_monotonic)) < _COMMAND_RETRY_TIMEOUT_SECONDS:
                continue
            if pending.attempts >= _COMMAND_RETRY_MAX_ATTEMPTS:
                expired.append(request_id)
                continue
            pending.attempts += 1
            pending.last_sent_monotonic = now
            self.client.send(
                {
                    "type": "command",
                    "action": pending.action,
                    "payload": dict(pending.payload),
                    "request_id": request_id,
                }
            )
            self.log_line.emit(
                f"[WARN] Retrying '{pending.action}' command ({pending.attempts}/{_COMMAND_RETRY_MAX_ATTEMPTS})"
            )

        for request_id in expired:
            pending = self._pending_commands.pop(request_id, None)
            if pending is None:
                continue
            self.log_line.emit(f"[ERROR] Command '{pending.action}' timed out")
            self.command_result.emit(
                {
                    "type": "command_result",
                    "ok": False,
                    "message": f"Command '{pending.action}' timed out",
                    "request_id": request_id,
                    "data": {"action": pending.action, "timed_out": True},
                }
            )
        if not self._pending_commands:
            self._pending_retry_timer.stop()
