[P2] Player snapshots still raise approval prompts for unknown item definitions, which violates `onlinephilosophy.md`'s "Approval prompts are limited to explicit DM decision points" rule and can repeat on every resync. In [`src/dungeon_applet.py`](C:\Users\Max\Desktop\Code\DMT\src\dungeon_applet.py) around lines 12918-12954, `_prepare_incoming_host_inventory_for_local_sync()` calls `_prompt_unknown_items_with_preview()` whenever the host sync contains embedded item documents unknown to the player's local library. That path runs during `_sync_local_sheet_inventory_from_host()` for normal player snapshot/apply flows, so a player taking over or reconnecting to a managed character can still get prompted to "Copy To Local Items" or "Keep Embedded" even though no DM decision is involved.

[P1] DM-local saves still overwrite the canonical online character package after the owning player disconnects, which directly violates `onlinephilosophy.md`'s "assigned player only" authority rule. In [`src/dungeon_applet.py`](C:\Users\Max\Desktop\Code\DMT\src\dungeon_applet.py) around lines 15471-15545, `_on_external_character_inventory_saved()` blocks DM-local propagation only when `_connected_owner_for_linked_character()` returns a connected owner. As soon as that player disconnects, the same handler takes the DM's local sheet payload, calls `_apply_inventory_sync_to_linked_entities()`, bumps sync metadata from the DM-local file, and broadcasts a new host snapshot. The new regression test [`tests/test_dungeon_online_state.py`](C:\Users\Max\Desktop\Code\DMT\tests\test_dungeon_online_state.py) `test_external_character_inventory_save_does_not_mutate_collection_backed_online_state_when_owner_disconnected` fails because saving `item-local` on the DM side replaces the collection-backed `item-host` state and emits a broadcast even though the last authoritative online state belonged to the player.
[P1] Handoff-created managed local characters can no longer participate in loot/claim flows because the player-side auto-create path drops the host `linked_sheet_id`. `_sync_local_sheet_inventory_from_host()` in [`src/dungeon_applet.py`](C:\Users\Max\Desktop\Code\DMT\src\dungeon_applet.py) around lines 13194-13289 receives the authoritative `sheet_id` from the snapshot, but it only calls `apply_remote_character_package_for_character_id(character_id, sheet_name, ...)` and never passes that sheet id through. When no local entry exists, `ensure_network_linked_character_entry()` in [`src/player_sheets.py`](C:\Users\Max\Desktop\Code\DMT\src\player_sheets.py) around lines 2085-2126 generates a new local `sheet_id` from the character name instead. Later, player loot actions still use the entity's host `linked_sheet_id` from `_choose_sheet_for_claim()` / `_inventory_loot_rows_for_sheet()` and `apply_claim_to_sheet()` in [`src/dungeon_applet.py`](C:\Users\Max\Desktop\Code\DMT\src\dungeon_applet.py) around lines 6831-6970, so post-handoff users see empty inventory transfer lists and `Character not found` claim failures even though the managed character was just created. Repro in an isolated temp save dir: `apply_remote_character_package_for_character_id("character-host", "Host Hero", ...)` creates local sheet `Host_Hero`; `apply_claim_to_sheet("sheet-host", ...)` then fails while `apply_claim_to_sheet("Host_Hero", ...)` succeeds.

[P1] Remote character sync can silently overwrite an unrelated personal local sheet if it happens to share the same `character_id`, violating `onlinephilosophy.md`'s "No silent overwrite of unrelated personal local files" rule. In [`src/player_sheets.py`](C:\Users\Max\Desktop\Code\DMT\src\player_sheets.py) around lines 2240-2290, `apply_remote_character_package_for_character_id()` looks up any existing entry by `character_id` and immediately applies the remote inventory/archive into that entry without checking `managed_linked` or whether the entry belongs to the current online session. The new regression test [`tests/test_player_sheets_archive.py`](C:\Users\Max\Desktop\Code\DMT\tests\test_player_sheets_archive.py) `test_apply_remote_character_package_does_not_overwrite_existing_personal_sheet_on_character_id_collision` fails because a personal sheet with `character_id="character-shared"` and inventory `item-personal` is silently mutated to the remote `item-remote` payload, and the API still reports `"Character synchronized."` instead of rejecting or isolating the managed copy.
[P1] The same handoff `sheet_id` drift breaks the core player-authoritative sync loop, because subsequent local saves go back to the host under the generated local sheet id and fail host ownership validation. In [`src/dungeon_applet.py`](C:\Users\Max\Desktop\Code\DMT\src\dungeon_applet.py) around lines 15436-15475, `_dispatch_online_character_inventory_sync()` builds the outbound sync request from the local `sheet_id` and `character_id_for_sheet_id(clean_sheet)`. On the host side, `_player_owns_linked_character()` in [`src/dungeon_applet.py`](C:\Users\Max\Desktop\Code\DMT\src\dungeon_applet.py) around lines 10071-10085 requires both the `character_id` and `sheet_id` to match the linked entity. After a handoff-created managed sheet is stored locally as `Host_Hero` instead of the host's `sheet-host`, the next player edit is rejected with `Character sync target is not linked to one of your owned entities in the assigned players dungeon.` I verified this with a direct host-side repro: an entity linked as (`sheet-host`, `character-host`) rejects `sync_character_inventory` for (`Host_Hero`, `character-host`) even though the character id is correct.

[P1] Players cannot submit embedded unknown character items to the lootpool for DM review because the player-side selection flow discards `item_documents` when no local `.dmtitem` file exists. In [`src/dungeon_applet.py`](C:\Users\Max\Desktop\Code\DMT\src\dungeon_applet.py) around lines 6396-6478, `_inventory_loot_rows_for_sheet()` only populates each row's `title` and `item_document` from `loot_item_path_for_id()` / filesystem lookups, even though `inventory_payload_for_sheet_id()` already returns embedded `item_documents` from the managed character archive. The new regression test [`tests/test_dungeon_online_state.py`](C:\Users\Max\Desktop\Code\DMT\tests\test_dungeon_online_state.py) `test_inventory_loot_rows_keep_embedded_item_documents_when_local_file_is_missing` fails because an inventory entry with embedded document title `"Embedded Blade"` is rendered as `"Unknown"` and carries `item_document=None`. That turns the later `add_loot_from_inventory` request into a host-side `"Unknown loot item definitions are missing and cannot be transferred"` rejection instead of the explicit DM accept/reject path required by `onlinephilosophy.md`.
[P1] The DM review UI for unknown active-character items still allows `Remove Selected` and `Kick Player`, which violates `onlinephilosophy.md`'s character-item rules. In [`src/dungeon_applet.py`](C:\Users\Max\Desktop\Code\DMT\src\dungeon_applet.py) around lines 12495-12580, `_review_unknown_linked_items()` explicitly offers the DM buttons to remove unknown items from the incoming character update or kick the player. `_resolve_unknown_linked_items_for_host()` then applies those actions around lines 12620-12660 by either deleting the selected items from `working_payload` or returning `"kick"`, which `_handle_host_sync_character_inventory()` / `_handle_host_link_character_entity()` convert into a rejected update plus player removal. That directly conflicts with the online philosophy rules that player-owned character sync is not blocked by DM-library unknown items, DM review options are limited to import or dismiss, and dismiss must not retroactively block the current owner's active character.
## Finding: Managed linked-character cleanup is global and deletes other active sessions' files

Severity: High

Files:
- `src/dungeon_applet.py:11954-11961`
- `src/player_sheets.py:2007-2025`

Why this is a bug:
- `_cleanup_unlinked_managed_character_artifacts()` only passes the current widget's active linked character ids into `cleanup_managed_linked_entries(...)`.
- `cleanup_managed_linked_entries(...)` then deletes every managed linked entry not present in that one set.
- There is no collection/session scoping, so opening two online sessions/tabs with different managed linked characters causes each cleanup pass to delete the other session's managed files.

Confirmed evidence:
- Inline check result:
  `before=['character-one', 'character-two']`
  `after_w1=['character-one']`
  `after_w2=[]`

Impact:
- A normal multi-tab or multi-session workflow can silently destroy another still-active online character's managed archive/cache.
- This violates the cleanup philosophy ("only for characters actively linked in the current collection") and the no-unrelated-file-destruction rule.

## Finding: DM can inject a character into a connected player's assigned entity as long as that entity is currently unlinked

Severity: High

Files:
- `src/dungeon_applet.py:15056-15068`

Why this is a bug:
- The DM-side guard only blocks local linking when the assigned entity is both owned by a connected player and already linked.
- If the entity is assigned to a connected player but currently unlinked, the DM can still run the full local link flow and attach a character package to it.

Confirmed evidence:
- Inline check result after calling `_on_link_character_requested()` on an entity owned by connected `player-1`:
  `linked_sheet_id='sheet-1'`
  `linked_character_id='character-1'`

Impact:
- The DM can author live character content for an actively assigned connected player.
- That breaks the online philosophy's authority model ("DM controls assignment, not live character-content authority").

## Finding: Host-to-local inventory sync can overwrite the wrong local character when `sheet_id` is absent

Severity: High

Files:
- `src/dungeon_applet.py:13194-13223`

Why this is a bug:
- `_sync_local_sheet_inventory_from_host()` starts from a remote `character_id`.
- When it cannot resolve that character locally and `sheet_id` is empty, it calls `character_id_for_sheet_id(clean_character)`.
- That treats the remote character id as if it were a local sheet id and can remap the sync into an unrelated local character.

Confirmed evidence:
- Inline check result:
  `applied_character_id='unrelated-character'`
  even though the remote sync target was `remote-character`.

Impact:
- A reconnect/claim recovery path that omits `sheet_id` can silently write host data into the wrong local character entry.
- This violates the no-silent-overwrite rule for unrelated personal local files.

## Finding: Loot claims force unknown embedded items into the claimant's local item library instead of offering the philosophy-required opt-out

Severity: Medium

Files:
- `src/dungeon_applet.py:5606-5635`
- `src/dungeon_applet.py:5677-5715`
- `src/dungeon_applet.py:6867-6897`

Why this is a bug:
- Loot entries with embedded `item_document`s are materialized into the online loot cache.
- Claiming those entries immediately runs `_persist_claimed_item_to_default_library(...)`.
- There is no "keep as temporary text entry / do not create a local copy" branch in the claim path.

Impact:
- Claiming unknown loot always writes a local item file (unless a conflict cancel aborts the whole claim).
- That contradicts `onlinephilosophy.md`, which explicitly says players must be able to decline local-copy creation and still keep the item claimable through text-item flow.

## Finding: Takeover snapshots still ship the pre-filter character archive, so dropped unknown items remain in the transfer payload

Severity: High

Files:
- `src/dungeon_applet.py:8868-8898`
- `src/dungeon_applet.py:10414-10437`

Why this is a bug:
- `_redact_linked_character_payload_for_player()` calls `_takeover_filtered_inventory_for_player()` for the new owner and replaces only `linked_inventory` plus `linked_content_hash`.
- `_takeover_filtered_inventory_for_player()` computes the new hash from the filtered inventory but still uses the original `linked_sheet_archive_b64`.
- The archive blob itself is never rewritten or cleared during takeover, so the snapshot still contains the full pre-filter character package.

Confirmed evidence:
- Inline check result:
  `filtered_inventory=[item_known]`
  while decoding the same snapshot's `linked_sheet_archive_b64` still yields
  `archive_inventory=[item_known, item_unknown]`.

Impact:
- Handoff/takeover packets still transfer items that the DM does not know, even though the visible inventory was filtered.
- That violates the philosophy rule that takeover transfer must include only DM-known items.

## Finding: Large linked-character archives exceed the protocol frame cap and make online sync/snapshot transfer fail before the host ever sees the package

Severity: Medium

Files:
- `src/online_session/protocol.py:8-14`
- `src/online_session/client.py:88-104`
- `src/online_session/controllers.py:292-303`
- `src/dungeon_applet.py:7689-7716`
- `src/dungeon_applet.py:15450-15458`

Why this is a bug:
- The online protocol hard-caps every JSON frame at 8 MiB.
- Character sync/link requests always include `archive_b64`, and base64 adds enough overhead that a raw archive around 7 MiB already exceeds the cap.
- When that happens, `encode_message(...)` raises `ValueError("message too large")`, `send_command(...)` returns `False`, and the higher-level dispatch path just returns `None`.
- The core online character flows call this path with `silent=True`, so the failure degrades into a warning log instead of a usable recovery path.

Confirmed evidence:
- Inline check result for a 7 MiB raw archive:
  `error='message too large'`
  `b64_len=9786712`

Impact:
- Large but otherwise valid linked-character packages cannot be linked or synchronized online.
- That breaks the philosophy requirement that the collection/session carries the full playable character package.

## Finding: "Join as an additional local player" can silently hijack the existing session instead of creating a new identity

Severity: High

Files:
- `src/dungeon_applet.py:8588-8644`
- `src/online_session/client.py:50-65`
- `src/online_session/server.py:204-285`

Why this is a bug:
- When a join retry is triggered because the current persistent id is already connected, the UI promises to retry with a different player name and a temporary local identity.
- `OnlineSessionClient.connect_to_host()` only clears `_session_token` when `persistent_player_id is None`, so the retry still sends the stale resume token from the already-connected identity.
- On the server, `_handle_handshake()` gives `session_token` precedence over the new `persistent_player_id`, resumes the old identity, disconnects the old socket, and even renames that identity to the new retry name.

Confirmed evidence:
- Direct server repro result:
  `first -> player_id='pid-1', session_token='<token>'`
  `retry -> player_id='pid-1', resumed=True, persistent_player_id='pid-1'`
  `players={'pid-1': 'Bob'}`
  `sock1_disconnected=True`

Impact:
- A user who expects to join as a second local player can instead knock the first client offline and take over its identity.
- This breaks reconnect/additional-player semantics and makes the client/server contract around persistent ids unreliable.
