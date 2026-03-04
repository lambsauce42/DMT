from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .types import OnlineRole


_ALLOWED_PLAYER_ACTIONS = {
    "ping",
    "upload_icon",
    "state_update",
    "sync_character_inventory",
    "claim_loot",
    "claim_loot_finalize",
    "add_loot_from_inventory",
    "initiative_update",
    "link_character_entity",
    "unlink_character_entity",
    "resolve_linked_character_conflict",
}


@dataclass(slots=True)
class PermissionDecision:
    allowed: bool
    reason: str = ""


def authorize_command(
    *,
    role: OnlineRole,
    action: str,
    actor_id: str,
    target_owner_id: Optional[str] = None,
) -> PermissionDecision:
    if role == OnlineRole.DM:
        return PermissionDecision(True, "dm")

    if action not in _ALLOWED_PLAYER_ACTIONS:
        return PermissionDecision(False, "action not allowed for players")

    if action == "upload_icon":
        if not target_owner_id:
            return PermissionDecision(False, "target has no owner")
        if target_owner_id != actor_id:
            return PermissionDecision(False, "entity owned by different player")

    return PermissionDecision(True, "ok")
