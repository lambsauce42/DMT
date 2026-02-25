# Interplay Checklist

Use this checklist to hunt failures that appear only when systems interact.

## State vs Persistence

- Verify saved data reflects in-memory state after multi-step edits.
- Verify reload/restart restores the same effective state.
- Verify undo/redo stacks remain valid across save/load boundaries.
- Verify partial-save failures do not leave mixed old/new state.

## UI vs Domain Logic

- Verify UI actions map to the correct domain command with correct parameters.
- Verify disabled/hidden controls cannot still trigger side effects.
- Verify list/detail views stay consistent after create/edit/delete operations.
- Verify optimistic UI updates reconcile correctly on backend rejection.

## Network/Auth vs Local Actions

- Verify unauthenticated clients cannot mutate protected state.
- Verify reconnect flows do not duplicate requests or replay stale actions.
- Verify out-of-order responses cannot overwrite newer local state.
- Verify permission checks happen at the enforcement layer, not only UI.

## Lifecycle and Resource Boundaries

- Verify temporary objects are cleaned up on close, navigation, and crashes.
- Verify signal/event listeners are detached during teardown.
- Verify reopening a module does not reuse stale singleton state unintentionally.
- Verify cancellation paths do not leak pending work.
