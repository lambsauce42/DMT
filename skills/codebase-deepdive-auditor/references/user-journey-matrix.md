# User Journey Matrix

Use this matrix to force realistic multi-step coverage.

## Core CRUD Journey

- Create entity
- Edit multiple fields
- Save
- Reopen
- Confirm persisted values and derived views

## Destructive Journey

- Create or load entity
- Delete or clear
- Undo (if supported)
- Redo (if supported)
- Confirm no ghost references remain

## Multi-Entity Journey

- Create two or more related entities
- Modify one entity that should update others
- Confirm references/summaries update correctly
- Delete one entity and verify referential cleanup

## Import/Export Journey

- Export data
- Reset local state
- Import exported data
- Confirm semantic equivalence, not only shape equality

## Online/Offline Journey

- Start online and perform edits
- Simulate disconnect/reconnect
- Continue edits
- Confirm no data loss, duplicate actions, or auth bypass
