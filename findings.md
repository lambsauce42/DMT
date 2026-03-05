# Findings (Online Dungeons Deep Dive)

### 1) [HIGH] Reconnect can incorrectly drop player back to local mode after one failed retry
- Area: Player reconnect lifecycle (`DungeonAppletWidget` + `ClientSessionController`)
- Files:
  - `src/dungeon_applet.py:8284`
  - `src/dungeon_applet.py:8348`
  - `src/dungeon_applet.py:8361`
- What happens:
  - After a real in-session disconnect, the first `on_client_disconnected` call behaves correctly (keeps player mode and waits for reconnect).
  - If a later reconnect transport attempt fails before `hello_ack`, `was_ready` is already `False`, so the same handler takes the initial join-failure branch and forces `_set_online_mode(ONLINE_MODE_LOCAL_DM)`.
- Why this is wrong:
  - The transport/controller is still in auto-reconnect mode, but the applet tears down player mode prematurely. Users lose session context after a transient reconnect-attempt failure.
- Reproduction (runtime check run during this investigation):
  - First disconnect call: mode stays `online_player`.
  - Second disconnect call (simulating failed reconnect attempt): mode switches to `local_dm`.

### 2) [HIGH] Pending link/unlink requests survive disconnect and can block character-sync resolution indefinitely
- Area: Linked-character sync / reconnect interplay
- Files:
  - `src/dungeon_applet.py:4397`
  - `src/dungeon_applet.py:4398`
  - `src/dungeon_applet.py:8284`
  - `src/dungeon_applet.py:12601`
- What happens:
  - `_pending_link_entity_requests` / `_pending_unlink_entity_requests` are used as inflight correlation state.
  - They are only removed on command results, but are not cleared on disconnect/session interruption.
  - Later, `_sync_local_sheet_inventory_from_host(...)` sees that pending state and returns: `"Awaiting linked character relink/unlink response."`
- Why this is wrong:
  - If the original request result was lost during disconnect, the stale pending entry becomes a durable blocker for that entity’s missing-local-character resolution flow.
- Reproduction (runtime check run during this investigation):
  - Before disconnect: returns awaiting-link message.
  - After disconnect: same awaiting-link message persists, and pending request count remains `1`.

### 3) [MEDIUM] Command dispatch reports success even when payload encoding fails and nothing is sent
- Area: Client command delivery contract
- Files:
  - `src/online_session/controllers.py:287`
  - `src/online_session/controllers.py:301`
  - `src/online_session/client.py:91`
  - `src/online_session/client.py:98`
- What happens:
  - `ClientSessionController.send_command(...)` returns `True` once connected, without checking whether `OnlineSessionClient.send(...)` actually transmitted bytes.
  - `OnlineSessionClient.send(...)` swallows encode failures (`message too large`) and only logs an error.
- Why this is wrong:
  - Callers treat the command as sent. For large payloads (notably large `state_update` payloads), no frame reaches host, but UI/app logic proceeds as if the request was delivered.
- Reproduction (runtime check run during this investigation):
  - Sending a >8MB command payload produced:
    - `send_command_return True`
    - server received no matching command (`has_req_oversized False`)
    - client logged encode failure (`Failed to encode outbound message`).

### 4) [LOW] Kick chat can claim success even when disconnect fails
- Area: Host moderation feedback
- File:
  - `src/online_session/controllers.py:74`
- What happens:
  - `kick_player(...)` broadcasts `"<name> was kicked"` before confirming `disconnect_player(...)` succeeded.
- Why this is wrong:
  - On disconnect races/failures, chat can show a successful kick even though the operation returned `False`.

### 5) [HIGH] Failed link/unlink command results can leave requests permanently pending
- Area: Linked-character command/result correlation
- Files:
  - `src/dungeon_applet.py:13076`
  - `src/dungeon_applet.py:13232`
  - `src/dungeon_applet.py:13235`
  - `src/dungeon_applet.py:9348`
  - `src/dungeon_applet.py:9599`
  - `src/dungeon_applet.py:12601`
- What happens:
  - Pending link/unlink entries are removed by parsing `result.data.action`.
  - Multiple host rejection paths for link/unlink send `ok=False` without `data.action`.
  - The stale request entry remains forever and later logic still treats the entity as awaiting link-resolution.
- Why this is wrong:
  - A one-time rejected request can create a persistent blocker for downstream sync/relink flows, even without reconnect.

### 6) [HIGH] Snapshot reconciliation can overwrite newer local linked-character inventory if push-back dispatch fails
- Area: Player snapshot/local inventory reconciliation
- Files:
  - `src/dungeon_applet.py:12875`
  - `src/dungeon_applet.py:12881`
  - `src/dungeon_applet.py:12893`
- What happens:
  - When local revision is newer than host, code tries local->host sync.
  - If that dispatch returns no request id, logic falls through and applies host->local sync anyway.
- Why this is wrong:
  - Newer local inventory can be clobbered by older host snapshot data on transient send/race failures.

### 7) [LOW] Failed add-loot command results can leak pending request bookkeeping
- Area: Loot transfer command/result correlation
- Files:
  - `src/dungeon_applet.py:6434`
  - `src/dungeon_applet.py:13076`
  - `src/dungeon_applet.py:13236`
  - `src/dungeon_applet.py:10135`
- What happens:
  - Pending add-loot requests are keyed by request id.
  - Cleanup on failure depends on parsed `data.action`.
  - Host rejection paths without `data.action` leave stale pending entries.
- Why this is wrong:
  - Creates avoidable stale state and weakens correlation reliability over long sessions.

### 8) [HIGH] Collection save strips authoritative linked item documents, so restart/handoff can silently lose session item definitions
- Area: Collection persistence + player-side linked-character package apply
- Files:
  - `src/dungeon_applet.py:15916`
  - `src/dungeon_applet.py:15919`
  - `src/player_sheets.py:2278`
  - `src/player_sheets.py:2294`
- What happens:
  - `_build_collection_payload(...)` rewrites every linked entity inventory with `item_documents = {}` before saving the collection.
  - After reload/restart, the host snapshot carries that stripped `linked_inventory`.
  - On the player side, `apply_remote_character_package_for_character_id(...)` loads the archive bytes and then immediately reapplies the stripped inventory payload, so the restored local managed copy ends up with no item documents.
- Why this is wrong:
  - `onlinephilosophy.md` requires the collection-backed state to persist the playable character package and the in-play item documents known to session authority.
  - A restart/handoff path can therefore erase authoritative item definitions from the managed local copy, so the post-reconnect character is no longer identical to the host-authoritative package.
- Reproduction (runtime check run during this investigation):
  - Applied a valid archive containing `item_unknown` plus a stripped host inventory payload.
  - Result: sync succeeded, but the stored local inventory ended with `"item_documents": {}`.

### 9) [HIGH] Managed linked-character cleanup is scoped to one widget, but deletes global data used by other open collections/sessions
- Area: Managed linked artifact lifecycle / multi-workspace interaction
- Files:
  - `src/dungeon_applet.py:11732`
  - `src/dungeon_applet.py:13330`
  - `src/dungeon_applet.py:16201`
  - `src/player_sheets.py:2007`
- What happens:
  - `_cleanup_unlinked_managed_character_artifacts()` computes active character ids from only the current widget/collection.
  - It then calls global `cleanup_managed_linked_entries(active_character_ids)`, which deletes every managed linked entry not in that local set.
  - Snapshot receipt, collection load, save, unlink, and delete flows all trigger this cleanup.
- Why this is wrong:
  - Managed linked storage lives in the shared Player Sheets cache, not per widget.
  - In a normal multi-tab or multi-window workflow, one open collection can delete another still-active online session’s managed linked character files.
  - That breaks reconnect/handoff expectations and violates the cleanup invariant that only artifacts no longer referenced by the relevant active session state should be removed.
- Reproduction (runtime check run during this investigation):
  - Created managed entries for `char-a` and `char-b`, then instantiated two widgets referencing one character each.
  - Calling cleanup from widget A left `char-a` intact and deleted `char-b`.

### 10) [MEDIUM] Rejecting local import of unknown synced items is not deduplicated and re-prompts on every identical snapshot
- Area: Player local sync / unknown-item prompt behavior
- Files:
  - `src/dungeon_applet.py:12710`
  - `src/dungeon_applet.py:12748`
  - `src/dungeon_applet.py:13026`
  - `src/dungeon_applet.py:13045`
- What happens:
  - `_prepare_incoming_host_inventory_for_local_sync(...)` asks the player whether to copy unknown items locally or convert them to notes.
  - If the player chooses convert-to-notes, no decision cache is stored.
  - `_sync_local_sheet_inventory_from_host(...)` compares future snapshots against the original host payload fingerprint, not the converted local payload fingerprint, so the same unchanged host snapshot re-enters the same prompt path.
- Why this is wrong:
  - `onlinephilosophy.md` explicitly calls for prompt deduplication on repeated unchanged decisions.
  - A player who already resolved the prompt by choosing note conversion still gets prompted again on the next identical host snapshot.
- Reproduction (runtime check run during this investigation):
  - Forced the local prompt to choose note conversion and called `_sync_local_sheet_inventory_from_host(...)` twice with the same host payload.
  - Prompt count increased from `1` to `2` across identical syncs.

## Codex Pass Findings Added (2026-03-05)
- This pass’s validated findings are entries **#1, #2, #3, and #4** above.
- This pass also added new entries **#8, #9, and #10** above.
