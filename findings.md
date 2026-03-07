# Online Dungeon Findings

Updated: 2026-03-07 10:30 CET

## 1. DM-local sheet saves overwrite an actively owned player character

- Severity: Critical
- Code: `src/dungeon_applet.py:15267-15340`
- Problem: `_on_external_character_inventory_saved()` runs for DM-host mode too, sets `owner = ""`, and then calls `_apply_inventory_sync_to_linked_entities()` without any guard for active player authority. That means a DM-local Player Sheets save can rewrite the hosted linked inventory, revision, hash, and stats for a character that is currently owned by a connected player.
- Why this violates `onlinephilosophy.md`: the core rule says the assigned player is authoritative while connected, and DM-local outdated character data must not overwrite an actively owned player character.
- Confirmed behavior: I reproduced this by putting the widget in `ONLINE_MODE_DM_HOST`, marking the owner as connected, and calling `_on_external_character_inventory_saved("sheet-1", ...)`. The host-side linked inventory changed from the player-authored payload to the DM-local payload immediately.

## 2. Handoff filtering rewrites the canonical collection-backed character state

- Severity: Critical
- Code: `src/dungeon_applet.py:14722-14765`
- Problem: `_apply_takeover_filter_for_entity()` does not build a filtered transfer copy for the next player. It calls `_apply_inventory_sync_to_linked_entities()` and rewrites the linked inventory stored in the host collection itself.
- Why this violates `onlinephilosophy.md`: the philosophy says handoff starts from the latest collection-backed character state and then applies takeover filter rules to the transfer. It also says dismissing unknown items must not retroactively block the current owner's active character. The current code deletes those items from the canonical host state.
- Confirmed behavior: I reproduced this with a linked character carrying a DM-unknown item. Calling `_apply_takeover_filter_for_entity()` removed that item from `self._dungeons[...]["state"]["items"][...]["linked_inventory"]`, not just from a temporary handoff payload.

## 3. Host-generated `content_hash` metadata is not the authoritative character-package hash

- Severity: High
- Code: `src/dungeon_applet.py:10357-10373`
- Main call sites: `src/dungeon_applet.py:14744-14757`, `src/dungeon_applet.py:10746-10767`, `src/dungeon_applet.py:15314-15322`
- Problem: `_next_linked_inventory_sync_metadata()` derives `content_hash` from `_inventory_payload_fingerprint(normalized)` only. The authoritative hash for linked characters is `character_sync_content_hash(character_id, inventory_payload, archive_bytes)`, which includes the character id and archive/PDF hash.
- Why this matters: takeover, loot-transfer, and DM-side local sync paths write metadata that does not actually describe the linked character package persisted in the collection. Equal-revision conflict checks then compare against a hash with different semantics.
- Confirmed behavior: I reproduced this by comparing `_next_linked_inventory_sync_metadata(...)[\"content_hash\"]` with `character_sync_content_hash(...)` for the same inventory plus archive. They differ. Feeding the host-generated hash back into `_validated_linked_character_sync_metadata()` fails with `Linked character payload does not match the claimed content hash.`

## 4. DM-host local "Link Character" bypasses the collection-backed handoff source

- Severity: High
- Code: `src/dungeon_applet.py:14871-15015`
- Problem: in DM-host mode, `_on_link_character_requested()` pulls character state straight from local `player_sheets` (`inventory_payload_for_sheet_id`, local archive, local revision/hash) and applies it directly to the entity. It does not first resolve the latest collection-backed state for the same linked character.
- Why this violates `onlinephilosophy.md`: handoff should start from the latest collection-backed character state. This path can seed a newly assigned entity from stale DM-local data instead.
- Confirmed behavior: I reproduced this with a locally selected stale sheet payload (`dm-stale`) for `character-1`. After `_on_link_character_requested()` and `_save_active_dungeon_state()`, the hosted entity state was populated from the DM-local payload rather than the already-existing collection-backed character state.

## 5. Collection save/load drops live linked item documents, so restart can degrade active unknown items into notes

- Severity: High
- Code: `src/dungeon_applet.py:15916-15920`, `src/dungeon_applet.py:12696-12740`
- Problem: `_materialize_state_icons_for_archive()` forcibly clears `linked_inventory["item_documents"]` before collection save. On reconnect/local restore, `_prepare_incoming_host_inventory_for_local_sync()` only looks at `linked_inventory` item documents when deciding whether unknown items can stay as items. It does not recover those documents from `linked_sheet_archive_b64` first.
- Why this violates `onlinephilosophy.md`: the collection is supposed to persist enough character-package data for restart/reconnect/handoff, and active unknown items are supposed to remain playable. After a host save/restart, the same active item can degrade into a text note purely because the saved collection discarded its live item document.
- Confirmed behavior: I reproduced this by saving a linked inventory that contained an unknown item plus its `item_document`. `_build_collection_payload()` wrote that inventory back out with `item_documents = {}`. Feeding the saved payload into `_prepare_incoming_host_inventory_for_local_sync()` converted the unknown item into `Unknown synced item 'Unknown Item' x1.` notes.

## 6. Loot preview event filter dereferences deleted Qt widgets

- Severity: Medium
- Code: `src/dungeon_applet.py:325-334`
- Problem: `_LootPreviewListEventFilter.eventFilter()` unconditionally calls `self._list_widget.viewport()` and `self._list_widget.itemAt(...)`. When the underlying `QListWidget` has already been destroyed, PySide raises `RuntimeError: Internal C++ object ... already deleted.`
- User-facing effect: closing dialogs / tearing down widgets can throw Qt event-loop errors. In the current suite this shows up during `test_retry_join_with_different_player_name_retries_with_prompt_value`.
- Confirmed behavior: `pytest --tier-max 2 tests/test_dungeon_online_state.py tests/test_dungeon_online_undo_scope.py tests/test_dungeon_online_security.py tests/test_dungeon_online_philosophy_guards.py tests/test_dungeon_online_reconnect_behavior.py tests/test_dungeon_online_reconnect_consistency.py tests/test_dungeon_join_connect_fallback.py tests/test_home_online_launch.py tests/test_online_protocol.py tests/test_online_client_connect.py tests/test_online_client_decoder_reset.py tests/test_online_client_persistent_id_reuse.py tests/test_online_controller_reconnect_persistent_id.py tests/test_online_authz.py -q` currently fails with repeated `RuntimeError` traces from `src/dungeon_applet.py:326`.

## 7. Client-side host inventory sync is lossy when the local item library is missing definitions

- Severity: High
- Code: `src/dungeon_applet.py:12585-12740`, `src/dungeon_applet.py:12963-13024`
- Problem: `_prepare_incoming_host_inventory_for_local_sync()` treats any item id that is not already in the local item library as "unknown" and can convert it into inventory notes before calling `apply_remote_character_package_for_character_id()`. That happens even for normal host-sent inventory rows that are just plain item ids and even when the sync is creating or refreshing the player's own managed character.
- User-facing effect: host-authoritative inventory rows can disappear from the local managed character and come back only as notes. This is broader than the restart case above; it can also happen during ordinary online sync flows whenever the client lacks the item file locally.
- Confirmed behavior: the current online suite already fails on this. `tests/test_dungeon_online_state.py:3428-3436` and `tests/test_dungeon_online_state.py:3490-3497` expect `item_b` / `item_z` to survive the sync, but the actual payload reaching `apply_remote_character_package_for_character_id()` has an empty `inventory` list instead.
