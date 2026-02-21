from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class OnlineRole(str, Enum):
    DM = "dm"
    PLAYER = "player"


@dataclass(slots=True)
class PlayerIdentity:
    player_id: str
    name: str
    role: OnlineRole = OnlineRole.PLAYER


@dataclass(slots=True)
class CommandEnvelope:
    action: str
    payload: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None


@dataclass(slots=True)
class CommandResult:
    ok: bool
    message: str = ""
    request_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionRuntime:
    session_id: str
    host_port: int
    players: Dict[str, PlayerIdentity] = field(default_factory=dict)
