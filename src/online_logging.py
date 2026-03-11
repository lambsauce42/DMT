from __future__ import annotations

import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from save_paths import default_dnd_save_dir, dnd_saves_dir

ONLINE_LOGS_DIRNAME = "online_logs"
_ACTIVE_LOGGERS_LOCK = threading.RLock()
_ACTIVE_LOGGERS: dict[str, "OnlineSessionLogger"] = {}
_RUNTIME_LOGGING_LOCK = threading.RLock()
_RUNTIME_LOGGING_ENABLED = True


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_filename_component(value: object, fallback: str, *, max_length: int = 48) -> str:
    text = str(value or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length] or fallback


def online_logs_dir() -> Path:
    try:
        return dnd_saves_dir() / ONLINE_LOGS_DIRNAME
    except Exception:
        return Path(default_dnd_save_dir()) / ONLINE_LOGS_DIRNAME


def _normalize_field_value(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_normalize_field_value(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        for key, nested in value.items():
            normalized[str(key)] = _normalize_field_value(nested)
        return normalized
    return str(value)


def is_runtime_logging_enabled() -> bool:
    with _RUNTIME_LOGGING_LOCK:
        return bool(_RUNTIME_LOGGING_ENABLED)


def set_runtime_logging_enabled(enabled: bool) -> None:
    global _RUNTIME_LOGGING_ENABLED
    with _RUNTIME_LOGGING_LOCK:
        _RUNTIME_LOGGING_ENABLED = bool(enabled)


class OnlineSessionLogger:
    def __init__(
        self,
        *,
        role: str,
        session_id: str,
        base_dir: Path | None = None,
        initial_context: dict[str, object] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._logger_id = uuid.uuid4().hex[:8]
        self._opened = False
        self._closed = False
        self._handle = None
        self._context: dict[str, object] = {}
        self._base_dir = Path(base_dir) if base_dir is not None else online_logs_dir()
        self._role = _safe_filename_component(role, "session")
        self._session_id = _safe_filename_component(session_id, "session")
        self.path = self._build_log_path(initial_context or {})
        self._open()
        self.update_context(
            role=str(role or "").strip() or "session",
            session_id=str(session_id or "").strip() or "session",
            log_id=self._logger_id,
            log_path=str(self.path),
            **(initial_context or {}),
        )
        self.write_event("session_log_opened")
        with _ACTIVE_LOGGERS_LOCK:
            _ACTIVE_LOGGERS[self._logger_id] = self

    def _build_log_path(self, initial_context: dict[str, object]) -> Path:
        timestamp = _utc_now_compact()
        name_parts = [
            timestamp,
            self._role,
            self._session_id,
        ]
        host = _safe_filename_component(initial_context.get("host"), "", max_length=32)
        player_name = _safe_filename_component(initial_context.get("player_name"), "", max_length=32)
        dm_name = _safe_filename_component(initial_context.get("dm_name"), "", max_length=32)
        if host:
            name_parts.append(host)
        if player_name:
            name_parts.append(player_name)
        elif dm_name:
            name_parts.append(dm_name)
        name_parts.append(f"pid{os.getpid()}")
        name_parts.append(self._logger_id)
        filename = "_".join(part for part in name_parts if part) + ".jsonl"
        return self._base_dir / filename

    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")
        self._opened = True

    def update_context(self, **fields: object) -> None:
        with self._lock:
            for key, value in fields.items():
                if value is None:
                    continue
                self._context[str(key)] = _normalize_field_value(value)

    def write_event(self, event: str, **fields: object) -> None:
        with self._lock:
            if not is_runtime_logging_enabled():
                return
            if self._closed or self._handle is None:
                return
            payload: dict[str, object] = {
                "ts": _utc_now_iso(),
                "pid": os.getpid(),
                "event": str(event or "unknown"),
            }
            payload.update(self._context)
            for key, value in fields.items():
                payload[str(key)] = _normalize_field_value(value)
            try:
                self._handle.write(json.dumps(payload, ensure_ascii=True))
                self._handle.write("\n")
                self._handle.flush()
                os.fsync(self._handle.fileno())
            except Exception as exc:
                print(f"[WARN] Failed to write online session log {self.path}: {exc}", file=sys.stderr)

    def close(self, *, reason: str = "") -> None:
        with self._lock:
            if self._closed:
                return
            if self._handle is not None:
                self.write_event("session_log_closed", reason=str(reason or "").strip())
            self._closed = True
            handle = self._handle
            self._handle = None
            with _ACTIVE_LOGGERS_LOCK:
                _ACTIVE_LOGGERS.pop(self._logger_id, None)
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass


def append_active_online_session_crash_event(event: str, **fields: object) -> None:
    if not is_runtime_logging_enabled():
        return
    with _ACTIVE_LOGGERS_LOCK:
        active_loggers: Iterable[OnlineSessionLogger] = tuple(_ACTIVE_LOGGERS.values())
    for logger in active_loggers:
        try:
            logger.write_event(str(event or "crash"), **fields)
        except Exception:
            continue
