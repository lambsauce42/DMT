import os
import sys
import hashlib
import base64
import io
import json
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QGraphicsPathItem

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dungeon_applet import (
    DungeonAppletWidget,
    ONLINE_MODE_DM_HOST,
    ONLINE_MODE_LOCAL_DM,
    ONLINE_MODE_PLAYER,
    ToolType,
)
from dungeon_constants import ROLE_ENTITY_ID, ROLE_KIND, ROLE_LINKED_CHARACTER_ID, ROLE_OWNER_PLAYER_ID
from dungeon_items import EntityItem
from item_file_format import build_item_document, load_item_document, write_item_document


pytestmark = pytest.mark.tier2


@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    return widget


def _valid_archive_b64() -> str:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sheet.pdf", b"%PDF-1.4\n%test\n")
        archive.writestr("inventory.json", json.dumps({"inventory": []}))
        archive.writestr(
            "info.json",
            json.dumps({"archive_version": 2, "updated_at": "2026-03-03T00:00:00+00:00"}),
        )
    return base64.b64encode(payload.getvalue()).decode("ascii")


def test_player_inventory_save_does_not_forward_while_link_conflict_pending(
    dungeon_widget, monkeypatch
):
    calls = []

    class _ClientStub:
        def send_command(self, action, payload, request_id=None):
            calls.append((action, dict(payload), request_id))
            return True

        def disconnect(self):
            return None

    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._player_connection_ready = True
    dungeon_widget._pending_link_conflicts["d1::entity-1::character-1"] = {
        "character_id": "character-1",
    }

    monkeypatch.setattr("player_sheets.character_id_for_sheet_id", lambda _sheet_id: "character-1")
    monkeypatch.setattr("player_sheets.inventory_payload_for_sheet_id", lambda _sheet_id: {"inventory": []})

    dungeon_widget._on_external_character_inventory_saved(
        "sheet-1",
        {"inventory": [{"item_id": "item-1", "quantity": 1}]},
    )

    assert calls == []


def test_host_sync_character_inventory_rejects_invalid_archive_payload(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-1",
                        "linked_inventory": {"inventory": []},
                        "pos": [0.0, 0.0],
                    }
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]

    dungeon_widget._handle_host_sync_character_inventory(
        "player-1",
        {
            "sheet_id": "sheet-1",
            "character_id": "character-1",
            "inventory": {"inventory": []},
            "stats": {"name": "Hero"},
            "archive_b64": "%%%not-base64%%%",
        },
        request_id="invalid-archive-sync",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is False
    assert "archive payload is invalid" in str(result.get("message") or "").lower()


def test_host_sync_character_inventory_rejects_mismatched_content_hash(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._players_dungeon_id = "d1"
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-1",
                        "linked_inventory": {"inventory": []},
                        "pos": [0.0, 0.0],
                    }
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]

    dungeon_widget._handle_host_sync_character_inventory(
        "player-1",
        {
            "sheet_id": "sheet-1",
            "character_id": "character-1",
            "inventory": {"inventory": [{"item_id": "item-1", "quantity": 1}]},
            "stats": {"name": "Hero"},
            "content_hash": hashlib.sha256(b"wrong").hexdigest(),
        },
        request_id="mismatched-hash-sync",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is False
    assert "claimed content hash" in str(result.get("message") or "").lower()


def test_conflicting_known_item_definition_enters_review_before_sync(
    dungeon_widget, monkeypatch, tmp_path
):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    review_calls = []

    monkeypatch.setattr("dungeon_applet.items_dir", lambda: tmp_path)

    existing_item_path = tmp_path / "existing_item.dmtitem"
    write_item_document(
        existing_item_path,
        build_item_document(
            {"item_id": "item_x", "title": "DM Sword", "rarity": "common"},
            None,
        ),
    )

    def _review(**kwargs):
        entries = kwargs.get("entries") or []
        review_calls.append([dict(entry) for entry in entries if isinstance(entry, dict)])
        return {
            "action": "use_authority",
            "selected_item_ids": [str(entry.get("item_id") or "") for entry in entries],
            "signature": "reviewed",
        }

    monkeypatch.setattr(dungeon_widget, "_review_unknown_linked_items", _review)

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._broadcast_snapshot_if_host = lambda: None
    dungeon_widget._players_dungeon_id = "d1"
    dungeon_widget._active_dungeon_id = "d1"
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-1",
                        "linked_inventory": {},
                        "pos": [0.0, 0.0],
                    }
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]

    dungeon_widget._handle_host_sync_character_inventory(
        "player-1",
        {
            "sheet_id": "sheet-1",
            "character_id": "character-1",
            "inventory": {
                "inventory": [{"item_id": "item_x", "quantity": 1}],
                "item_documents": {
                    "item_x": {
                        "format": "dmtitem.v2",
                        "payload": {"item_id": "item_x", "title": "Player Sword", "rarity": "rare"},
                    }
                },
            },
            "stats": {"name": "Hero"},
        },
        request_id="review-conflict",
    )

    assert review_calls
    assert review_calls[0][0]["item_id"] == "item_x"
    assert review_calls[0][0]["conflicts_with_authority"] is True
    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is True
    linked_inventory = dungeon_widget._dungeons[0]["state"]["items"][0]["linked_inventory"]
    assert linked_inventory["item_documents"]["item_x"]["payload"]["title"] == "DM Sword"


def test_conflicting_known_item_definition_can_explicitly_overwrite_dm_authority(
    dungeon_widget, monkeypatch, tmp_path
):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    monkeypatch.setattr("dungeon_applet.items_dir", lambda: tmp_path)

    existing_item_path = tmp_path / "existing_item.dmtitem"
    write_item_document(
        existing_item_path,
        build_item_document(
            {"item_id": "item_x", "title": "DM Sword", "rarity": "common"},
            None,
        ),
    )

    monkeypatch.setattr(
        dungeon_widget,
        "_review_unknown_linked_items",
        lambda **kwargs: {
            "action": "import",
            "selected_item_ids": [
                str(entry.get("item_id") or "")
                for entry in (kwargs.get("entries") or [])
                if isinstance(entry, dict)
            ],
            "signature": "overwrite-dm",
        },
    )

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._broadcast_snapshot_if_host = lambda: None
    dungeon_widget._players_dungeon_id = "d1"
    dungeon_widget._active_dungeon_id = "d1"
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-1",
                        "linked_inventory": {
                            "inventory": [{"item_id": "item_x", "quantity": 1}],
                            "item_documents": {
                                "item_x": build_item_document(
                                    {"item_id": "item_x", "title": "DM Sword", "rarity": "common"},
                                    None,
                                )
                            },
                        },
                        "pos": [0.0, 0.0],
                    }
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]

    dungeon_widget._handle_host_sync_character_inventory(
        "player-1",
        {
            "sheet_id": "sheet-1",
            "character_id": "character-1",
            "inventory": {
                "inventory": [{"item_id": "item_x", "quantity": 1}],
                "item_documents": {
                    "item_x": {
                        "format": "dmtitem.v2",
                        "payload": {"item_id": "item_x", "title": "Player Sword", "rarity": "rare"},
                    }
                },
            },
            "stats": {"name": "Hero"},
        },
        request_id="review-conflict-overwrite",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is True
    linked_inventory = dungeon_widget._dungeons[0]["state"]["items"][0]["linked_inventory"]
    assert linked_inventory["item_documents"]["item_x"]["payload"]["title"] == "Player Sword"
    saved_document = load_item_document(existing_item_path)
    assert isinstance(saved_document, dict)
    assert saved_document["payload"]["title"] == "Player Sword"


def test_player_mode_collection_autosave_is_suspended(dungeon_widget, tmp_path):
    dungeon_widget._online_mode = ONLINE_MODE_PLAYER
    dungeon_widget._autosave_enabled = True
    dungeon_widget._collection_dirty = True
    dungeon_widget._collection_path = tmp_path / "campaign.dmtcollection"

    dungeon_widget._run_collection_autosave()

    assert not (tmp_path / "campaign_autosave.dmtcollection").exists()


def test_invalid_requested_collection_blocks_host_start(dungeon_widget, monkeypatch, tmp_path):
    invalid_collection = tmp_path / "invalid.dmtcollection"
    invalid_collection.write_text('{"format":"wrong"}', encoding="utf-8")
    messages = []
    monkeypatch.setattr(
        "dungeon_applet.QMessageBox.critical",
        lambda *args, **kwargs: messages.append((args[1], args[2])),
    )

    started = dungeon_widget.start_online_host(8765, str(invalid_collection))

    assert started is False
    assert dungeon_widget._online_mode == ONLINE_MODE_LOCAL_DM
    assert messages == [("Load Failed", "Collection file is invalid.")]


def test_dirty_dm_collection_close_is_vetoed_when_unsaved_changes_are_cancelled(
    dungeon_widget, monkeypatch
):
    dungeon_widget.show()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._collection_dirty = True
    monkeypatch.setattr(dungeon_widget, "_confirm_unsaved_changes", lambda: False)

    closed = dungeon_widget.close()

    assert closed is False
    assert dungeon_widget.isVisible() is True
    dungeon_widget._collection_dirty = False


def test_join_online_session_clears_previous_collection_path(dungeon_widget):
    class _ClientStub:
        def __init__(self):
            self.disconnected = False
            self.connect_args = None

        def disconnect(self):
            self.disconnected = True

        def connect_to_host(self, host, port, name, persistent_player_id=None):
            self.connect_args = (host, port, name, persistent_player_id)

    client_stub = _ClientStub()
    dungeon_widget._client_controller = client_stub
    dungeon_widget._collection_path = Path("C:/tmp/existing_collection.dmtcollection")

    dungeon_widget.join_online_session("192.168.1.10", 8765, "Mira")

    assert client_stub.disconnected is True
    assert dungeon_widget._collection_path is None


def test_player_eraser_only_deletes_local_player_strokes(dungeon_widget):
    own_stroke = QGraphicsPathItem()
    own_path = own_stroke.path()
    own_path.moveTo(20.0, 20.0)
    own_path.lineTo(30.0, 20.0)
    own_stroke.setPath(own_path)
    own_stroke.setData(ROLE_KIND, "stroke")
    own_stroke.setData(ROLE_OWNER_PLAYER_ID, "player-local")

    other_stroke = QGraphicsPathItem()
    other_path = other_stroke.path()
    other_path.moveTo(0.0, 0.0)
    other_path.lineTo(10.0, 0.0)
    other_stroke.setPath(other_path)
    other_stroke.setData(ROLE_KIND, "stroke")
    other_stroke.setData(ROLE_OWNER_PLAYER_ID, "player-other")

    scene = dungeon_widget.canvas.scene()
    scene.addItem(own_stroke)
    scene.addItem(other_stroke)

    dungeon_widget.canvas.set_stroke_owner_player_id("player-local")
    eraser_state = dungeon_widget.canvas._states[ToolType.ERASER]

    eraser_state._erase_at(QPointF(5.0, 0.0))
    assert other_stroke.scene() is scene

    eraser_state._erase_at(QPointF(25.0, 20.0))
    assert own_stroke.scene() is None


def test_host_link_character_sync_triggers_managed_cleanup(dungeon_widget, monkeypatch):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    cleanup_calls = []
    monkeypatch.setattr(
        dungeon_widget,
        "_cleanup_unlinked_managed_character_artifacts",
        lambda: cleanup_calls.append(True),
    )
    monkeypatch.setattr(
        dungeon_widget,
        "_resolve_unknown_linked_items_for_host",
        lambda **kwargs: ("ok", dict(kwargs.get("inventory_payload") or {}), ""),
    )
    monkeypatch.setattr(
        dungeon_widget,
        "_canonicalize_linked_inventory_payload",
        lambda inventory_payload, **kwargs: (dict(inventory_payload), []),
    )
    monkeypatch.setattr(dungeon_widget, "_broadcast_snapshot_if_host", lambda: None)

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._players_dungeon_id = "players-dungeon"
    dungeon_widget._active_dungeon_id = "players-dungeon"
    dungeon_widget._dungeons = [
        {
            "id": "players-dungeon",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_sheet_name": "Hero",
                        "linked_character_id": "character-1",
                        "linked_inventory": {"inventory": []},
                        "pos": [0.0, 0.0],
                    },
                    {
                        "type": "entity",
                        "entity_id": "entity-2",
                        "owner_player_id": "player-1",
                        "pos": [0.0, 0.0],
                    }
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]

    dungeon_widget._handle_host_link_character_entity(
        "player-1",
        {
            "entity_id": "entity-2",
            "sheet_id": "sheet-1",
            "sheet_name": "Hero",
            "character_id": "character-1",
            "inventory": {"inventory": []},
            "stats": {"name": "Hero"},
            "dungeon_id": "players-dungeon",
        },
        request_id="req-link-cleanup",
    )

    assert cleanup_calls == [True]


def test_delete_linked_entity_triggers_managed_cleanup_and_undo_recovery(dungeon_widget, monkeypatch):
    cleanup_calls = []

    def _record_cleanup(active_character_ids):
        cleanup_calls.append(set(active_character_ids))
        return 0

    monkeypatch.setattr("player_sheets.cleanup_managed_linked_entries", _record_cleanup)

    entity = EntityItem(QPointF(20.0, 20.0))
    entity.setData(ROLE_ENTITY_ID, "entity-delete")
    entity.setData(ROLE_LINKED_CHARACTER_ID, "character-delete")
    dungeon_widget.canvas.scene().addItem(entity)
    entity.setSelected(True)

    dungeon_widget.canvas.delete_selected_items()

    assert cleanup_calls
    assert cleanup_calls[-1] == set()

    dungeon_widget.canvas.undo()

    assert cleanup_calls[-1] == {"character-delete"}


def test_host_link_conflict_response_cache_replays_without_time_expiry(dungeon_widget, monkeypatch):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._cache_host_link_conflict_response(
        "player-1::conflict-1",
        "sig-1",
        ok=False,
        message="DM denied overwrite request.",
        data={"action": "resolve_linked_character_conflict"},
    )
    monkeypatch.setattr("dungeon_applet.time.monotonic", lambda: 10_000.0)

    replayed = dungeon_widget._replay_host_link_conflict_response(
        "player-1",
        "player-1::conflict-1",
        "sig-1",
        request_id="req-cache-replay",
    )

    assert replayed is True
    assert dungeon_widget._host_controller.results[-1][1]["request_id"] == "req-cache-replay"
    assert dungeon_widget._host_controller.results[-1][1]["message"] == "DM denied overwrite request."


def test_host_add_loot_from_inventory_uses_authoritative_item_document(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._players_dungeon_id = "d1"
    dungeon_widget._active_dungeon_id = "d1"
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_sheet_name": "Hero",
                        "linked_character_id": "character-1",
                        "linked_inventory": {
                            "inventory": [{"item_id": "item_a", "quantity": 1}],
                            "item_documents": {
                                "item_a": build_item_document(
                                    {"item_id": "item_a", "title": "DM Sword", "rarity": "common"},
                                    None,
                                )
                            },
                        },
                        "pos": [0.0, 0.0],
                    }
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]

    dungeon_widget._handle_host_add_loot_from_inventory(
        "player-1",
        {
            "sheet_id": "sheet-1",
            "items": [
                {
                    "item_id": "item_a",
                    "title": "DM Sword",
                    "path": "C:/fake/player-copy.dmtitem",
                    "source": "backpack",
                    "source_index": 0,
                    "item_document": build_item_document(
                        {"item_id": "item_a", "title": "Forged Sword", "rarity": "legendary"},
                        None,
                    ),
                }
            ],
        },
        request_id="req-authority-loot",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is True
    assert len(dungeon_widget._session_loot_pool) == 1
    item_document = dungeon_widget._session_loot_pool[0].get("item_document")
    assert isinstance(item_document, dict)
    assert item_document["payload"]["title"] == "DM Sword"


def test_linked_item_lookup_does_not_trust_arbitrary_filesystem_paths(dungeon_widget, tmp_path):
    rogue_item_path = tmp_path / "rogue_item.dmtitem"
    write_item_document(
        rogue_item_path,
        build_item_document(
            {"item_id": "rogue-item", "title": "Rogue Draft", "rarity": "rare"},
            None,
        ),
    )

    resolved = dungeon_widget._linked_item_document_by_id(str(rogue_item_path))

    assert resolved is None


def test_player_snapshot_redacts_other_players_linked_character_payload(dungeon_widget):
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._players_dungeon_id = "d1"
    dungeon_widget._active_dungeon_id = "d2"
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-a",
                        "owner_player_id": "player-a",
                        "linked_sheet_id": "sheet-a",
                        "linked_sheet_name": "Alpha",
                        "linked_character_id": "character-a",
                        "linked_save_revision": 3,
                        "linked_last_saved_at": "2026-03-03T00:00:00+00:00",
                        "linked_content_hash": "hash-a",
                        "linked_sheet_archive_b64": "ARCHIVE_A",
                        "linked_inventory": {"inventory": [{"item_id": "item-a", "quantity": 1}]},
                        "pos": [0.0, 0.0],
                    },
                    {
                        "type": "entity",
                        "entity_id": "entity-b",
                        "owner_player_id": "player-b",
                        "linked_sheet_id": "sheet-b",
                        "linked_sheet_name": "Bravo",
                        "linked_character_id": "character-b",
                        "linked_save_revision": 4,
                        "linked_last_saved_at": "2026-03-03T00:00:01+00:00",
                        "linked_content_hash": "hash-b",
                        "linked_sheet_archive_b64": "ARCHIVE_B",
                        "linked_inventory": {"inventory": [{"item_id": "item-b", "quantity": 1}]},
                        "pos": [1.0, 1.0],
                    },
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        },
        {
            "id": "d2",
            "name": "DM",
            "state": {"items": [], "fog": {"path": []}},
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        },
    ]

    snapshot = dungeon_widget._build_online_snapshot(for_player_id="player-b")

    dungeons = snapshot.get("dungeons") or []
    assert len(dungeons) == 1
    items = dungeons[0]["state"]["items"]
    entity_a = next(entry for entry in items if entry.get("entity_id") == "entity-a")
    entity_b = next(entry for entry in items if entry.get("entity_id") == "entity-b")
    assert entity_a.get("linked_character_id") == ""
    assert entity_a.get("linked_sheet_archive_b64") == ""
    assert entity_a.get("linked_inventory") == {
        "inventory": [],
        "inventory_notes": "",
        "equipment": {},
        "gold": 0,
        "silver": 0,
        "copper": 0,
        "item_documents": {},
    }
    assert entity_b.get("linked_character_id") == "character-b"
    assert entity_b.get("linked_sheet_archive_b64") == "ARCHIVE_B"


def test_host_sync_character_inventory_requires_archive_payload(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self.results = []

        def send_command_result(self, player_id, **kwargs):
            self.results.append((player_id, kwargs))

        def stop(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._online_mode = ONLINE_MODE_DM_HOST
    dungeon_widget._players_dungeon_id = "d1"
    dungeon_widget._dungeons = [
        {
            "id": "d1",
            "name": "Players",
            "state": {
                "items": [
                    {
                        "type": "entity",
                        "entity_id": "entity-1",
                        "owner_player_id": "player-1",
                        "linked_sheet_id": "sheet-1",
                        "linked_character_id": "character-1",
                        "linked_inventory": {"inventory": []},
                        "linked_sheet_archive_b64": "",
                        "pos": [0.0, 0.0],
                    }
                ],
                "fog": {"path": []},
            },
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }
    ]

    dungeon_widget._handle_host_sync_character_inventory(
        "player-1",
        {
            "sheet_id": "sheet-1",
            "character_id": "character-1",
            "inventory": {"inventory": []},
            "stats": {"name": "Hero"},
            "archive_b64": "",
        },
        request_id="missing-archive-sync",
    )

    result = dungeon_widget._host_controller.results[-1][1]
    assert result["ok"] is False
    assert "archive payload is required" in str(result.get("message") or "").lower()


def test_start_online_host_clears_unknown_item_review_cache(dungeon_widget):
    class _HostStub:
        def __init__(self):
            self._players = {}

        @property
        def players(self):
            return dict(self._players)

        def stop(self):
            return None

        def start(self, _port):
            return True, ""

    class _ClientStub:
        def disconnect(self):
            return None

    dungeon_widget._host_controller = _HostStub()
    dungeon_widget._client_controller = _ClientStub()
    dungeon_widget._host_unknown_item_review_cache["player-1::character-1::sig"] = {"action": "blocked"}
    dungeon_widget._broadcast_snapshot_if_host = lambda: None

    started = dungeon_widget.start_online_host(0)

    assert started is True
    assert dungeon_widget._host_unknown_item_review_cache == {}
