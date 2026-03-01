# Dungeon Online Deepdive Report

Date: 2026-03-01
Scope: dungeon online sync, reconnect/disconnect behavior, handoff robustness, local overwrite consent boundaries, and permission-spam handling.

## Corrected framing

Player-to-host propagation is not inherently wrong in this product.

Given the handoff requirement, the host does need an authoritative copy of the character state that survives player departure and can later be reassigned to another player.

The real questions are:
- where that authoritative copy lives
- whether it survives reconnect/restart correctly
- whether it contains the full character data needed for handoff
- whether using DM-local storage as that authority is acceptable for your overwrite/consent rules

## Findings

### [P1] Reconnect replays stale player state after the host snapshot and can overwrite newer host-side changes

Impact:
After a disconnect or lost command result, the client keeps the last pending `state_update`, clears only its in-flight request id, and resends that stale payload on the first post-reconnect snapshot. Because the payload is resent after the newer host snapshot is applied, it can silently roll the host back to an older player-owned entity state.

Evidence:
- Pending player state is retained and only the request id is cleared on disconnect: `src/dungeon_applet.py:7218-7245`, `src/dungeon_applet.py:7506-7516`.
- The first player snapshot re-enables the session and later flushes pending updates: `src/dungeon_applet.py:10231-10238`, `src/dungeon_applet.py:10401-10413`.
- Confirmed by the failing proof test `tests/test_dungeon_online_reconnect_consistency.py:26-153`.
- Debug trace from `debug/test_dungeon_online_reconnect_consistency.log` shows the exact sequence: host snapshot arrives with `hp=9`, then the client resends stale `hp=5`, and the host ends at `hp=5`.

Consequence:
If the host changes a player-owned entity while that player is disconnected, reconnect can still revert the host to stale state.

### [P1] Full player handoff currently depends on DM-local character persistence, not just the collection/session state

Impact:
If player B must be able to take over player A's character after player A leaves and after a host restart, the system needs a full authoritative character copy on the host. The current collection only stores the linked/runtime subset embedded into entities, not the full sheet artifact.

Evidence:
- Collections serialize entity link metadata, linked inventory, sync metadata, and copied gameplay stats: `src/dungeon_applet.py:12097-12198`.
- Collections do not serialize the full local sheet/archive/PDF payload.
- On reload, only that linked subset is reconstructed into entities: `src/dungeon_applet.py:12223-12266`.

Consequence:
Manual collection save/reload preserves the linked/runtime character subset, but not the full sheet in the strong sense required for lossless handoff.

### [P1] Inventory sync and linked-character handoff do not carry full item definitions

Impact:
Even if the host has the latest linked inventory, that inventory is mostly a set of canonical item references, not a portable item-definition bundle. If player B does not already have player A's custom items locally, the handoff is incomplete. If player B has a conflicting local item definition with the same `item_id`, the system can silently bind to the wrong local item.

Evidence:
- Canonical inventory entries store `item_id`, `normalized_item_name`, and `quantity`: `src/player_sheets.py:165-178`, `src/player_sheets.py:1447-1466`.
- Item lookup resolves by local library `item_id`; if no local item exists, resolution falls back to a raw path or `None`: `src/player_sheets.py:815-825`.
- Linked inventory stored on entities and in collections is just normalized inventory payload, not full item documents: `src/dungeon_applet.py:12126-12156`, `src/dungeon_applet.py:12261-12265`.
- The only place that robustly carries and resolves full item documents is the loot-transfer/claim pipeline, where `item_document` is shipped and persisted with explicit overwrite handling: `src/dungeon_applet.py:5405-5597`, `src/dungeon_applet.py:8935-9005`, `src/dungeon_applet.py:6360-6389`.

Consequence:
- Unknown custom item on player B's machine: player B can inherit the inventory reference, but not the full item definition.
- Conflicting local item with same `item_id`: player B's machine can resolve to the wrong local item with no consent/conflict prompt.

This is the biggest remaining handoff gap after the character-state discussion.

### [P2] The current host-authority model uses DM-local player-sheet persistence as the online backing store

Impact:
This is not automatically wrong for your product goal. In fact, it is currently what makes stronger handoff continuity possible. But it means the DM's personal local character storage is being used as shared online authority.

Evidence:
- Player-side inventory saves dispatch `sync_character_inventory` automatically in online player mode: `src/dungeon_applet.py:11914-11953`.
- Host-side handling persists that payload into local player-sheet storage: `src/dungeon_applet.py:8170-8261`.
- The storage helper mutates the target entry, syncs the archive, and saves entries to disk: `src/player_sheets.py:1997-2042`.
- Existing test coverage already codifies this behavior as expected: `tests/test_dungeon_online_state.py:1613-1722`.

Corrected interpretation:
This is only a bug if your rule is "players may update the live hosted runtime copy but may not write into DM-local persistent sheet storage without explicit approval."

If your intended design is "the DM-hosted local sheet store is the authoritative online backing store," then this is not an implementation bug. It is an architectural/product choice with consent implications.

### [P2] First-snapshot override sync can mutate the DM-hosted linked copy automatically

Impact:
On `hello_ack`, the client arms `_pending_join_character_override_sync`. On the first player snapshot, if no conflict is detected, the client auto-pushes local linked-character data back to the host. This mutates the host copy without a separate approval step.

Evidence:
- Join arms the override sync automatically: `src/dungeon_applet.py:7556-7564`.
- First snapshot runs the override push when no conflict is detected: `src/dungeon_applet.py:10401-10413`.
- The push sends `link_character_entity` with local stats/inventory: `src/dungeon_applet.py:10134-10229`.
- Host-side handler explicitly documents that player edits are allowed to overwrite the host copy for that linked entity: `src/dungeon_applet.py:8371-8385`.

Consequence:
This helps continuity, but it is another place where the host copy can change automatically during reconnect/join flows.

## Verified good paths

- Duplicate DM overwrite prompts are throttled on the host side: `tests/test_dungeon_online_state.py::test_host_duplicate_overwrite_requests_are_throttled`.
- Unchanged host conflicts do not keep reprompting the player: `tests/test_dungeon_online_state.py::test_snapshot_does_not_reprompt_suppressed_conflict_with_unchanged_host_payload`.
- Missing local character data is prompted before creating a local copy from the host snapshot: `tests/test_dungeon_online_state.py::test_snapshot_missing_local_character_prompts_before_creating_local_copy`.

Validation run:
- `pytest -q --tier-max=2 tests/test_dungeon_online_state.py::test_host_sync_character_inventory_persists_authoritative_sheet_state tests/test_dungeon_online_state.py::test_host_duplicate_overwrite_requests_are_throttled tests/test_dungeon_online_state.py::test_snapshot_missing_local_character_prompts_before_creating_local_copy tests/test_dungeon_online_state.py::test_snapshot_does_not_reprompt_suppressed_conflict_with_unchanged_host_payload tests/test_dungeon_online_state.py::test_player_state_update_retries_after_disconnect_before_ack`
- Result: 5 passed in 1.14s

## Design implication

If your actual requirement is:
- player B must get the full sheet after player A leaves
- this must still work after host disconnect/restart
- custom items must survive handoff correctly
- item-id conflicts on player B must be handled safely

then the current model is still incomplete.

The robust solution is not just "store linked inventory." It needs a host-owned portable character package that includes:
- full sheet data needed for play/handoff
- portable item definitions for all referenced custom items
- deterministic conflict handling when a receiving player already has a different local item under the same id/name

Right now only the loot pipeline has anything close to that item-document transport/conflict behavior.

## Residual risk

- Loot-claim reconciliation looks reasonably robust while the app stays open, but I did not add a proof test for process-exit mid-claim.
- Autosave writes a sidecar collection file, but session restart only reloads the path the host chooses to reopen. So continuity after crash/restart depends on reopening the right saved/autosaved collection file.

## Implementation update

Date: 2026-03-01

The issues above were addressed with the following changes:

- Reconnect no longer replays stale pending player state after disconnect. The client now drops the unacknowledged `state_update` payload instead of resending stale local state on the first reconnect snapshot.
- Linked characters now persist a fuller authoritative package in hosted/collection state:
  - linked inventory now carries referenced `item_documents`
  - linked entities now carry `linked_sheet_archive_b64`
- Host-side `sync_character_inventory` no longer writes into the DM's personal local Player Sheets storage. The host now updates the linked entity/package directly.
- DM authority for items is now explicit:
  - if the DM already has an item definition for a referenced `item_id`, that definition wins
  - conflicting player-side item documents do not silently overwrite the DM definition
  - missing custom item documents are carried in the linked package so they can survive handoff
- Local Player Sheets archives now retain referenced `item_documents`, and those documents are materialized into a sheet-scoped cache so custom inventory items resolve locally without relying on the global item library.

### Outcome

- Player B can receive a linked character package that includes the sheet archive plus custom item definitions.
- Saving and reopening the collection now preserves that hosted package because it lives on the linked entity state that is serialized into the collection.
- The DM no longer silently accumulates or mutates personal local sheet archives just because a remote player updated their character during online play.
- Permission-spam protections for overwrite prompts remain in place.

### Validation

- `pytest -q --tier-max=2 tests/test_player_sheets_archive.py`
- `pytest -q --tier-max=2 tests/test_dungeon_online_reconnect_consistency.py tests/test_dungeon_online_reconnect_behavior.py tests/test_dungeon_online_state.py::test_host_sync_character_inventory_updates_owned_linked_entities tests/test_dungeon_online_state.py::test_host_sync_character_inventory_uses_authoritative_item_canonicalization tests/test_dungeon_online_state.py::test_host_sync_character_inventory_rejects_unowned_character_target tests/test_dungeon_online_state.py::test_client_loot_add_result_syncs_local_inventory_payload tests/test_dungeon_online_state.py::test_client_loot_add_result_ignores_uncorrelated_response tests/test_dungeon_online_state.py::test_sync_local_sheet_inventory_creates_missing_character_entry tests/test_dungeon_online_state.py::test_snapshot_missing_local_character_prompts_before_creating_local_copy tests/test_dungeon_online_state.py::test_snapshot_does_not_reprompt_suppressed_conflict_with_unchanged_host_payload tests/test_dungeon_online_state.py::test_join_snapshot_prompts_resolution_instead_of_auto_overwrite_push tests/test_dungeon_online_state.py::test_snapshot_conflict_replaces_local_sheet_without_auto_host_overwrite tests/test_dungeon_online_state.py::test_player_state_update_is_dropped_on_disconnect_before_reconnect`
- `pytest -q --tier-max=2 tests/test_dungeon_online_state.py::test_host_duplicate_overwrite_requests_are_throttled tests/test_dungeon_online_state.py::test_snapshot_does_not_reprompt_suppressed_conflict_with_unchanged_host_payload tests/test_dungeon_online_state.py::test_snapshot_missing_local_character_prompts_before_creating_local_copy tests/test_dungeon_online_state.py::test_host_can_ignore_player_overwrite_requests_for_current_session tests/test_dungeon_online_state.py::test_host_link_character_sync_allows_claim_for_player_owned_entity`
