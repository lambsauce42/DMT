## UI Guidelines
Whenever UI is changed, treat it as layout work, not just widget insertion. New widgets must fit the surrounding row/panel in size, alignment, spacing, and style. Adjacent controls should usually share the same outer height and aligned edges unless there is a clear reason not to. Reuse the local UI pattern instead of relying on default Qt sizing, and check that nothing looks tacked on, mismatched, cramped, or overlapping at any screen size. Buttons that contain square icon should always be square as well unless otherwise specified.

## Fallbacks and backwards compatability
Unless specifically instructed there you shall **never** add backwards compatability - it just produces code bloat while this repo is in early dev. Also fallbacks should never be "silent", they must be seen somewhere, maybe not in the active frontend but terminal or logging outputs are suitable (prefer terminal).

For refactors, schema changes, storage format changes, or internal API cleanups:
- Do **not** add legacy readers, legacy writers, migration shims, dual-format support, compatibility branches, or “accept both old and new” logic unless the user explicitly asks for it.
- Prefer updating all call sites and tests to the new contract directly.
- If old data or old files stop working after the refactor, that is acceptable by default in this repo.
- If a compatibility layer seems unavoidable, stop and ask first instead of adding it on your own.

## Other
In case you get stuck somewhere, you can have a look at quirks.md it contains solutions to some reoccuring issues.
