# Dungeon Online Philosophy

Date: 2026-03-01

## Core rule

The DM approves authority, the collection stores authority, and players continuously propose updates to that authority while they control the linked entity.

## Authority

1. The DM is the sole authority for what a linked character and its items mean during online play.
2. Players may propose continuous updates to the character they currently control.
3. Those updates only become authoritative when they are valid under the DM-hosted rules.

## Character ownership

1. A linked character may be actively assigned to multiple entities only when every player-owned instance belongs to the same player; unowned instances are also allowed.
2. A player can only update the character linked to an entity they currently own.
3. The DM can create the initial collection-backed character state by linking an unlinked entity.
4. After that, the player continuously updates that same collection-backed character state while they control it.
5. The DM may still explicitly overwrite or relink when intended.

## Persistence

1. The collection-linked character is the canonical persisted online state.
2. The collection must store enough data for restart and handoff:
   - full playable character package
   - authoritative item documents for all items in play
   - revision/content metadata
3. The DM library is the source of truth for accepting item definitions, but accepted authoritative items must also be stored in the collection package.
4. The DM's personal local files must not be silently overwritten as a side effect of normal player sync.

## Item policy

1. It must be impossible for an authoritative in-play character to depend on an item the DM has not approved.
2. If a player proposes items the DM library does not know, or items that conflict with DM-local definitions, sync enters a blocked review state.
3. The DM gets one deduplicated review prompt with inspectable items.
4. For each unresolved item, the DM can:
   - accept/import it into authority
   - remove it from the incoming character update
   - reject the whole update by kicking the player
5. "Remove item" means it is discarded from the proposed incoming state, not silently merged or guessed.
6. If the DM accepts an item, that accepted definition becomes authoritative for the session and is persisted into the collection-backed character package.
7. If the DM already has a definition for the same `item_id`, the DM version wins unless the DM explicitly chooses otherwise.

## Sync behavior

1. Character updates must be atomic.
2. If an update contains unresolved item conflicts, none of that character update is committed as authoritative until resolution is complete.
3. No partial authoritative save of a conflicted character.
4. Once resolved, the whole approved update commits together.

## Prompt behavior

1. No prompt spam.
2. Conflict prompts must be deduplicated by player, character, and content fingerprint or revision.
3. If nothing materially changed, the DM is not asked again.
4. While unresolved, further sync for that character stays blocked or coalesced behind the existing prompt.

## Disconnect and recovery

1. Stale client updates must never replay after reconnect and overwrite newer host state.
2. After reconnect, the player pulls fresh authoritative state from the host.
3. If the host saves the collection and restarts, reassignment and handoff must use the saved collection-backed character package.
4. Player B should receive the latest host-approved version of player A's character, including approved item definitions.

## Session continuity

1. Continuing a trusted session on another day should stay simple.
2. A host restart should preserve collection-backed character authority, active player assignments, and normal session flow without forcing large-scale manual reassignment.
3. Safety checks should block only the conflicting part of recovery, not create unnecessary re-setup work for unchanged session state.

## Handoff

1. When player A leaves, the character remains as collection-backed authoritative state on the host.
2. When the DM assigns that entity to player B, player B pulls the hosted package.
3. If player B lacks local copies, they may create local working copies from host authority.
4. Local creation or update on the player side may require consent, but it must not change host authority.

## Cleanup

1. Managed linked-character files and managed linked-item caches should exist only for characters actively linked in the current collection.
2. If a sheet or item cache is no longer referenced by any linked entity in the collection, it should be removed.
3. Cleanup must apply only to managed collection-backed artifacts, not unrelated personal user files.

## Safety invariants

1. Nothing becomes authoritative unless the DM knows and approves it.
2. Nothing silently overwrites local personal data.
3. Nothing in active play depends on unknown item definitions.
4. Restart, reconnect, and player handoff all resolve back to the same host-approved character state.
