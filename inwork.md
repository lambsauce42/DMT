## In Progress

Date: 2026-03-03

### Confirmed issues

1. Players can create the initial authoritative linked-character state without explicit DM approval.
2. If the host rejects a player link request, the player client keeps the optimistic local link until a later snapshot corrects it.
3. The host accepts syntactically valid base64 for linked character archives without validating that the payload is a real character archive or that it matches the claimed sync metadata.
4. Inventory normalization merges distinct items by `normalized_item_name` instead of preserving them by `item_id`, which can collapse separate approved items and drop their authoritative item documents.
5. Managed linked-character cleanup is not triggered by normal in-scene entity deletion, so stale managed artifacts can remain on disk.
6. Client-side online icon ingestion accepted oversized payloads and wrote them to session cache, allowing unbounded per-asset disk growth.
7. Host icon upload accepted any base64 byte payload without image validation, allowing non-image data to be persisted and broadcast as entity icons.
8. Unknown-item DM review could be re-opened on repeated identical unresolved sync attempts when import selected but no items were actually imported.
9. Legacy online character-override sync scaffolding remained in code but was no longer reachable, creating misleading maintenance surface.

### Fixed in this pass

1. Tightened the online authority flow so a player cannot create a new authoritative linked character without an already-owned authoritative character in the assigned players dungeon.
2. Scoped that authority guard to initial-link cases only, so existing host-authoritative links still support DM reassignment/handoff to another player.
3. Removed the optimistic local link application on the player client path, so rejected `link_character_entity` requests no longer leave the player UI in a false linked state.
4. Hardened linked-character archive validation and sync metadata verification so malformed archives and mismatched claimed `content_hash` values are rejected.
5. Fixed inventory normalization so distinct `item_id` values remain distinct even when they share the same normalized item name, and their `item_documents` are preserved.
6. Wired linked-character cleanup into normal entity delete/undo flows so managed artifacts stay aligned with actual linked entities.
7. Enforced shared icon payload validation for host and client paths: payload must be a decodable image and at most 2 MiB before persistence/broadcast.
8. Added host-side rejection for invalid icon image bytes so non-image uploads no longer enter online session state.
9. Added unresolved-item review cache short-circuiting on the host resolution path so repeated unresolved submissions do not reprompt for the same signature.
10. Removed dead join-override sync internals and stale conflict bookkeeping that no longer participates in runtime online flows.

### Validation completed

1. Added focused regression coverage for archive rejection without entry creation, same-name item preservation, mismatched sync hash rejection, delete-triggered cleanup, and the updated player link flow.
2. Added targeted icon-payload hardening tests, philosophy-guard tests (including snapshot redaction/archive requirement), and unresolved-review dedup coverage.
3. Existing test suites were not run in this pass per instruction; only source-level validation (`py_compile`) was executed for syntax safety.
