import os
import sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from online_session.authz import authorize_command
from online_session.types import OnlineRole


def test_dm_is_always_allowed():
    decision = authorize_command(
        role=OnlineRole.DM,
        action="any_action",
        actor_id="dm",
    )
    assert decision.allowed


def test_player_upload_icon_requires_owner_match():
    allowed = authorize_command(
        role=OnlineRole.PLAYER,
        action="upload_icon",
        actor_id="p1",
        target_owner_id="p1",
    )
    denied = authorize_command(
        role=OnlineRole.PLAYER,
        action="upload_icon",
        actor_id="p1",
        target_owner_id="p2",
    )
    assert allowed.allowed
    assert not denied.allowed


def test_player_disallowed_unknown_action():
    decision = authorize_command(
        role=OnlineRole.PLAYER,
        action="delete_collection",
        actor_id="p1",
    )
    assert not decision.allowed


def test_player_undo_redo_not_allowed():
    undo = authorize_command(
        role=OnlineRole.PLAYER,
        action="undo",
        actor_id="p1",
    )
    redo = authorize_command(
        role=OnlineRole.PLAYER,
        action="redo",
        actor_id="p1",
    )
    assert not undo.allowed
    assert not redo.allowed


@pytest.mark.parametrize(
    "action",
    [
        "sync_character_inventory",
        "claim_loot",
        "claim_loot_finalize",
        "add_loot_from_inventory",
        "initiative_update",
        "link_character_entity",
    ],
)
def test_player_new_online_actions_allowed(action):
    decision = authorize_command(
        role=OnlineRole.PLAYER,
        action=action,
        actor_id="p1",
    )
    assert decision.allowed


@pytest.mark.parametrize(
    "action",
    [
        "chat_send",
        "draw_stroke",
        "erase_at",
        "move_entity",
        "update_entity",
    ],
)
def test_removed_player_actions_are_rejected(action):
    decision = authorize_command(
        role=OnlineRole.PLAYER,
        action=action,
        actor_id="p1",
    )
    assert not decision.allowed
