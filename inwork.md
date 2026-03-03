## In Progress

Date: 2026-03-03

### Confirmed issues

1. Players can create the initial authoritative linked-character state without explicit DM approval.
2. If the host rejects a player link request, the player client keeps the optimistic local link until a later snapshot corrects it.
3. The host accepts syntactically valid base64 for linked character archives without validating that the payload is a real character archive or that it matches the claimed sync metadata.
4. Inventory normalization merges distinct items by `normalized_item_name` instead of preserving them by `item_id`, which can collapse separate approved items and drop their authoritative item documents.
5. Managed linked-character cleanup is not triggered by normal in-scene entity deletion, so stale managed artifacts can remain on disk.

### Fixed in this pass

1. Tightened the online authority flow so a player cannot create a new authoritative linked character without an already-owned authoritative character in the assigned players dungeon.
2. Removed the optimistic local link application on the player client path, so rejected `link_character_entity` requests no longer leave the player UI in a false linked state.
3. Hardened linked-character archive validation and sync metadata verification so malformed archives and mismatched claimed `content_hash` values are rejected.
4. Fixed inventory normalization so distinct `item_id` values remain distinct even when they share the same normalized item name, and their `item_documents` are preserved.
5. Wired linked-character cleanup into normal entity delete/undo flows so managed artifacts stay aligned with actual linked entities.

### Validation completed

1. Added focused regression coverage for archive rejection without entry creation, same-name item preservation, mismatched sync hash rejection, delete-triggered cleanup, and the updated player link flow.
2. Re-ran targeted player-sheet archive tests, online philosophy guard tests, and the changed online dungeon authority/linking tests.
