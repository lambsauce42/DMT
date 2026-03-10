# Dungeon Online Philosophy

Date: 2026-03-04

## Core rule

The assigned player is authoritative for their linked character during active control.  
The DM-hosted collection stores the canonical session state.  
Character data in the collection is updated if and only if the assigned player makes character changes.

## Authority

1. Character state authority belongs to the player currently assigned to that entity.
2. While that player is connected and assigned, the DM does not overwrite that player's linked character state.
3. The DM controls assignment and session orchestration, not live character-content authority.
4. Item-library authority for DM local storage remains with the DM (import or dismiss decisions).
5. Lootpool unknown-item acceptance remains a DM decision.

## Character linking and assignment

1. A player can only link and sync for entities currently assigned to that player.
2. If an assigned entity already has a linked character and the player already has a local character, the player may overwrite the entity-linked character immediately. No DM approval popup.
3. If an assigned entity has a linked character and the player has no local copy, the player receives an identical managed local copy automatically.
4. After link/receive, all player edits sync directly to the session character state (atomic update).
5. If the DM tries to assign the same character from outdated DM-local data while the owning player is connected, that action is a no-op.
6. A connected owning player's character is never overwritten by DM-local character data.

## Persistence

1. The DM collection-linked character package is the canonical persisted online state.
2. The collection stores enough data for restart and handoff:
   - full playable character package
   - in-play item documents known to session authority
   - revision/content metadata
3. The collection-backed character package is rewritten only when the assigned player commits character changes.
4. No silent overwrite of unrelated personal local files (DM or player).

## Character item policy

1. Player-owned character sync is not blocked by DM-library unknown items.
2. Unknown-to-DM items present in active characters are detectable and reviewable by the DM.
3. DM review options for such items:
   - copy/import item definitions into DM local storage
   - dismiss (do not copy into DM local storage)
4. Dismiss means "not copied to DM local storage now"; it does not retroactively block current owner's active character.
5. On player handoff/takeover, item transfer is filtered:
   - items present in the character and known in DM storage transfer to the new player copy
   - items not known in DM storage are dropped during takeover

## Lootpool item policy

1. Players can submit items to lootpool.
2. If the DM already knows an item definition, submission is auto-accepted.
3. If item definitions are unknown to the DM, the DM must explicitly accept or reject those entries.
4. Rejected lootpool entries are not transferred out of the source character and are treated as never submitted.
5. Other players viewing lootpool may encounter unknown items:
   - they can opt to create local copies
   - if they decline, items are shown as temporary text entries and remain claimable through existing text-item flow

## Sync behavior

1. Character updates are atomic.
2. No DM approval popup is required for normal assigned-player character edits.
3. If nothing materially changed, no collection rewrite is performed.
4. Reconnect always pulls latest host collection-backed state before further sync.

## Prompt behavior

1. No prompt spam.
2. Approval prompts are limited to explicit DM decision points (unknown item import/reject decisions).
3. Repeated unchanged unresolved decisions must be deduplicated.

## Disconnect and recovery

1. Stale client updates must never overwrite newer host state after reconnect.
2. Collection-backed character state survives host save/restart and is used for resume and handoff.
3. Handoff always starts from latest collection-backed character state, then applies takeover item filter rules.

## Handoff

1. When player A leaves, the latest collection-backed character state remains on host.
2. When player B is assigned that entity, player B receives a local managed copy.
3. Transfer to player B includes only items currently in that character that the DM also knows in local item storage.
4. Items in that character that the DM does not know are removed during takeover transfer.

## Cleanup

1. Managed linked-character files and managed linked-item caches should exist only for characters actively linked in the current collection.
2. If a managed sheet or managed item cache is no longer referenced by any linked entity in the collection, it should be removed.
3. Cleanup applies only to managed collection-backed artifacts, never unrelated personal files.

## Safety invariants

1. Assigned-player character authority is respected during active ownership.
2. DM-local outdated character data cannot silently overwrite an actively owned player character.
3. Collection remains the canonical persisted session state.
4. Unknown items can exist in active play, but cross-player takeover transfer includes only DM-known items.
5. Restart, reconnect, and handoff resolve through collection-backed state with deterministic takeover filtering.
