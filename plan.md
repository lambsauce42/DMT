# Character and Item Sync Plan

## Core Identity

- `character_id` is the only cross-machine identity for a character.
- `sheet_id` is local storage identity only.
- `item_id` is the exact definition/version identity of an item file.
- `normalized_item_name` is the claim-replacement identity for items.
- `normalized_item_name` must be deterministic: trim, lowercase, collapse whitespace, and use the same function everywhere.
- `save_revision` is the authoritative cross-machine ordering field for character sync.
- `last_saved_at` is informational UX metadata only and must never be the sole conflict oracle.
- DM mirror cardinality is exactly one mirror per `character_id`.
- Across player-assigned entities, a `character_id` may be actively linked only once at a time.

## Canonical Shapes

- Backpack storage uses stack entries:
  - `{ item_id, normalized_item_name, quantity }`
- Equipment storage uses equipped entries:
  - `null` or `{ item_id, normalized_item_name, quantity }`
- Equipped entries normally use `quantity = 1`.
- Backpack and equipment never duplicate the same physical quantity:
  - equipping moves quantity out of backpack into the slot
  - unequipping moves quantity back into backpack
- Character payloads and DM mirrors must use the same canonical item-entry shapes.
- There is at most one active local canonical item definition per `normalized_item_name`.
- Old replaced item definitions are non-canonical immediately after replacement and may be deleted or archived once no references remain.

## Character Package Authority

- The structured character payload is the authoritative source of truth.
- The archive/PDF or equivalent clone package is a derived transport/display artifact generated from the structured payload.
- A valid complete character package contains:
  - authoritative structured payload
  - `character_id`
  - `save_revision`
  - `last_saved_at`
  - `content_hash`
  - archive/PDF bytes or an equivalent full clone package
- `content_hash` covers the authoritative structured payload.
- The clone package may also carry its own integrity hash for transfer verification.
- If structured payload and clone content disagree:
  - the structured payload wins
  - the package is considered stale/incomplete until the clone is regenerated from it
  - claims and overwrite flows must not proceed using the stale package
- DM mirrors store the accepted character package verbatim, plus any DM-only metadata outside the authoritative payload.

## Items

- All items are stackable.
- Claims are always additive.
- Every item payload persists its `normalized_item_name`.
- Editing and saving an item while keeping the same `normalized_item_name` creates a new `item_id` in the same item family.
- If an edit changes `normalized_item_name`, that item becomes a new item family:
  - it must be saved as a new item
  - existing references do not migrate automatically
  - global replacement only happens through the explicit same-name claim-replacement flow
- Claim matching is by `normalized_item_name`, not by `item_id`.
- Claim quantity defaults to `1` when not explicitly provided.
- Claiming adds quantity into the backpack stack for that `normalized_item_name`.
- If a backpack stack for that `normalized_item_name` already exists:
  - increase `quantity`
  - update its `item_id` to the current local canonical `item_id`
- If no backpack stack exists:
  - create `{ item_id, normalized_item_name, quantity }`
- Equipment matching/migration also uses `normalized_item_name`.
- If no same-name local item exists:
  - import the DM item definition
  - add quantity to the player's linked local character
- If same-name local item exists and `item_id` is the same:
  - same definition
  - add quantity only
- If same-name local item exists and `item_id` is different:
  - player must always get a warning that the local item definition is about to be replaced by the DM version
  - options are `Claim and Replace` or `Cancel`
  - there is never a silent item-definition overwrite
- If the player confirms replacement:
  - DM version becomes the new local canonical item for that normalized name
  - all local references to the old `item_id` are migrated to the new `item_id`
  - then the claim quantity is added
- Item replacement is global on the local machine:
  - backpack references
  - equipment references
  - all local characters
- Item replacement must be atomic:
  - replace definition
  - migrate references
  - save affected sheets
  - add quantity
  - save claiming sheet
  - only then finish claim
- If canceled:
  - no replacement
  - no quantity added

## Characters

- Characters carry `character_id`, full structured character data, `save_revision`, `last_saved_at`, and `content_hash`.
- Character data includes inventory, equipment, notes, sheet/base stats, and anything needed for claims and normal local use.
- Every authoritative character save:
  - increments `save_revision`
  - updates `last_saved_at`
  - recomputes `content_hash`
  - regenerates the clone package before the save is considered complete
- Sheets are always saved immediately after claim and after character updates.
- `save_revision`, `last_saved_at`, and `content_hash` are written by the side performing the authoritative save and persisted in the character archive and DM mirror.
- Equal `save_revision` and equal `content_hash` means the two copies are considered in sync.
- Equal `save_revision` with different `content_hash` is an invalid mismatch state and must be treated as unresolved conflict, not as in sync.

## DM Mirror

- DM stores a persisted mirror copy of every linked character.
- DM mirror exists for:
  - reconnect recovery
  - reassignment to another player
  - restoring session links later
  - sending missing characters to players
- The DM mirror is not the ownership source for player characters, but it is the persisted session copy.
- The DM mirror is always a complete character package, never a partial character.
- A complete character package contains:
  - full authoritative structured character payload
  - `save_revision`
  - `last_saved_at`
  - `content_hash`
  - everything required for normal local use
  - the archive/PDF or an equivalent complete clone payload
- DM must not advertise a character as pullable unless a complete validated mirror package already exists.
- DM must validate package completeness and hash integrity before replacing an existing mirror.

## Character Sync

- `save_revision` decides which side is presented as newer by default.
- `last_saved_at` is display metadata and not an ownership override by itself.
- On player reconnect or reassignment:
  - if the player has the linked `character_id`, compare local `save_revision` with DM mirror `save_revision`
  - if local revision is newer, player pushes the local package to DM
  - if DM mirror revision is newer, player is asked whether to `Overwrite Local`, `Force Push Local`, or `Cancel`
  - if revisions match and hashes match, no action is needed
- There are never silent overwrites of player-local character data.
- If the DM mirror is newer, the player must always confirm before local overwrite.
- `Force Push Local` means the player's local character becomes the accepted version:
  - the local side performs a new authoritative save, producing a strictly newer `save_revision`
  - DM then replaces its mirror with that local package
- If the player chooses `Cancel`:
  - local character stays unchanged
  - claim-to-sheet should be blocked until sync is resolved, to avoid writing into stale character data
- If revisions match and hashes match:
  - treat both sides as in sync
  - do not prompt
- If revisions match and hashes differ:
  - log loudly
  - block claims and overwrite flows
  - require explicit conflict resolution
- If revisions differ but hashes match:
  - treat the higher revision as the accepted copy
  - log that redundant equal-content saves occurred

## Character Transfer Robustness

- Pulling a character from DM is a full-package transfer only.
- Pull writes into a temporary local package first.
- The pulled package must pass hash/integrity verification before it replaces any local file.
- Local replacement uses atomic file swap/rename only after the full package is present and verified.
- If disconnect happens during pull:
  - keep the existing local character unchanged
  - keep the pulled temp package marked incomplete
  - retry the same package revision on reconnect
  - byte-range resume is optional; restarting the full-package transfer for the same revision is acceptable
- If the player had no local copy yet and the pull is incomplete:
  - no partial character is created
  - the link stays unresolved locally
  - claim-to-sheet stays blocked for that character until the pull completes
- DM keeps the complete mirror package so reconnect retry does not depend on the original player staying online.

## Linking

- Linking an entity stores `linked_character_id` on the entity.
- Stats are copied from character to entity only on a new link.
- A new link means:
  - entity had no linked character before
  - or `linked_character_id` changed to a different character
- Different means different `character_id` only, never a newer timestamp of the same character.
- Reconnect, remap, or session reload are not new links and must not repopulate entity stats.
- The copied stats are only the initial inspector stat values currently pulled during linking.
- After linking, those entity inspector stats are entity-owned runtime state unless a different `character_id` is linked later.
- Host maintains a session-wide active-assignment registry:
  - `character_id -> assigned entity/player`
- The registry is validated on:
  - every link
  - every player assignment change
  - every reconnect
  - session restore/load

## DM Links Character

- If DM links a DM-created character:
  - ensure it has a `character_id`
  - store `linked_character_id` on the entity
  - copy stats into entity once
  - persist DM mirror
- If assigned player later has no local character with that `character_id`:
  - player pulls the full character from DM
- If assigned player already has that `character_id`:
  - bind to it
  - do not repopulate stats
- If DM tries to link a `character_id` that is already actively assigned to another player-owned entity:
  - block the link by default
  - prompt DM to either cancel or move/switch the existing assignment first
  - do not allow two active player-assigned entities to share the same `character_id`

## Player Links Character

- If player links a local character:
  - ensure it has a `character_id`
  - send full character payload to DM
  - DM stores or updates mirror
  - store `linked_character_id` on the entity
  - copy stats into entity once
- If DM did not previously have that character:
  - DM creates the mirror immediately from player data
- If player tries to link a `character_id` that is already actively assigned to another player-owned entity:
  - block the link by default
  - prompt with `Switch Character / Cancel`
  - only complete the link after the previous active assignment is removed or switched

## Pulling Character From DM

- If player is missing a linked character, DM sends a complete character package containing:
  - `character_id`
  - `save_revision`
  - name
  - `last_saved_at`
  - `content_hash`
  - inventory
  - equipment
  - notes
  - base/sheet stats
  - any other character-owned fields required for normal use
  - the archive/PDF or an equivalent full clone package
- Structured-only transfer is not allowed for missing-character recovery.

## Shared Entity

- The entity is the shared live object.
- DM and assigned player have equal rights on the entity.
- Both can edit:
  - movement
  - icon
  - all inspector-editable entity fields
  - HP and other runtime values
- Inspector is only visible to DM and assigned player.
- Shared entity updates go through the host.
- Host is authoritative for entity state.
- Conflict handling for entity edits is host last-write-wins.

## Ownership Split

- Character owns:
  - inventory
  - equipment
  - notes
  - sheet/base stats
  - claim target data
- Entity owns:
  - movement
  - icon
  - shared inspector/runtime state
  - shared combat/session state

## Notifications

- There are never silent overwrites of player-owned local data.
- Item-definition replacement warning is always shown to players, but only when an item is actually about to be replaced.
- That warning must explicitly state that replacement migrates every matching local reference on the machine, across all local characters.
- Character overwrite prompt is always shown to players when DM mirror is newer.
- DM mirror updates from player to DM may apply automatically, because DM does not own the character.
- DM should still get a non-blocking notification when a linked character mirror was updated from a player.
- DM can mute future update notifications for a specific character.
- There should be a way to re-enable muted notifications later.
- Duplicate active-assignment conflicts for a `character_id` are blocking warnings, not passive notifications.

## Transactions

- Multi-file local mutations use staged-write transactions, not in-place piecemeal writes.
- A transaction stages every affected output first:
  - replacement item definition
  - every affected local character package
  - every affected derived clone/archive artifact
- Staged outputs are validated before commit.
- Local commit happens by atomic rename/swap of all staged files that belong to the local machine.
- If local staging or validation fails:
  - discard the staged transaction
  - leave all committed local files unchanged
  - do not send DM mirror updates
- Cross-machine claim/mirror work is not a single physical distributed transaction.
- Cross-machine consistency is achieved with an idempotent transaction id:
  - the client computes the full result once
  - the local machine commits once
  - DM mirror updates are applied once per transaction id
  - loot claim finalization happens only after DM acknowledges durable mirror persistence
- Retrying the same transaction id must never duplicate item quantity or reapply mirror migrations.

## Claim Flow

- Player claims an item.
- If same-name item replacement is needed:
  - warn player
  - confirm or cancel
- If confirmed:
  - create a claim transaction id
  - stage replacement item definition
  - stage migrated local character packages
  - stage the claiming character package with the additive quantity applied
  - validate all staged local outputs
  - atomically commit the local staged outputs
  - send the resulting affected character packages to DM for mirror replacement using the same transaction id
- If no replacement needed:
  - create a claim transaction id
  - stage the claiming character package with the additive quantity applied
  - validate it
  - atomically commit it locally
  - send the resulting character package to DM using the same transaction id
- Then:
  - DM stages and durably saves every affected mirror package for that transaction id
  - if DM persistence succeeds, host finalizes the loot claim exactly once
  - if DM persistence fails, the claim remains unfinalized and retryable under the same transaction id
- Local file mutation is atomic per machine.
- Cross-machine claim completion is ack-gated and idempotent, not a best-effort fire-and-forget update.

## Claim Transaction Robustness

- Host claim reservation and client claim application are tied to a persistent `claim_id`.
- Before mutating any local item or character data, the client writes a pending claim transaction record containing:
  - `claim_id`
  - targeted `character_id`
  - affected local character ids
  - affected item ids / normalized names
  - before-state backups or reversible patches
  - intended after-state payloads
- Local file writes use temp files plus atomic rename.
- DM mirror writes use temp files plus atomic rename.
- Host removes loot entries only after it receives a successful finalize for that `claim_id`.
- If the client crashes or disconnects before finalize:
  - host keeps the loot reservation unfinalized
  - on reconnect the client resumes or replays the pending `claim_id`
  - replay must be idempotent by `claim_id`
- If local mutation did not fully commit:
  - recover from the transaction record
  - restore pre-claim local state
  - report the claim as failed
- If local mutation committed but DM mirror/finalize did not:
  - do not duplicate quantity locally
  - resume mirror update and finalize using the same `claim_id`
- A `claim_id` may be finalized only once.

## Active Assignment Uniqueness

- Exactly one player-assigned entity may actively own a given `linked_character_id` at a time.
- Unassigned entities may temporarily carry the same `linked_character_id` because they do not push character updates.
- The host must reject any operation that would create two active player-assigned entities with the same `linked_character_id`.
- This includes:
  - manual linking
  - reassignment to another player
  - reconnect restoration
  - loading/restoring a session snapshot
- If reconnect or reassignment would violate the rule:
  - do not silently accept the duplicate
  - freeze character sync and claim flow for the conflicting entity
  - prompt DM or the acting player to switch/remove the conflicting link before continuing
- Until resolved, the duplicate side is not allowed to push character updates.

## Final Rules

- No silent overwrites of player-local data, ever.
- DM mirror updates from player are the only automatic overwrite exception, but DM still gets notifications.
- Item overwrite warnings are always shown to players when replacement is about to happen.
- Character overwrite warnings are always shown to players when DM has a newer version.
- `last_saved_at` determines the default newer/older direction, but players may explicitly `Force Push Local` when DM is newer.
- Shared entity state is host-authoritative and last-write-wins.
- Linking uses stable `character_id`.
- Reconnect uses `character_id` plus `last_saved_at`.
- Claims are additive and items are globally replaced locally by normalized name only after explicit confirmation.
- DM mirror is one complete mirror per `character_id`.
- Two player-assigned entities with the same active `linked_character_id` are never allowed at the same time.
