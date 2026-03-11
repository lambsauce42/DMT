## UI Guidelines
For substantial Qt/UI/frontend work, use `$qt-frontend-design`.

Keep only these repo-level always-on rules here:
- Treat UI changes as layout work, not just widget insertion.
- Reuse the local UI pattern before inventing a new one.
- Buttons containing square icons must be square unless explicitly specified otherwise.
- Do not ship clipped, overlapping, ragged, default-looking, or placeholder-looking UI.
- If the user asks for something polished, beautiful, intuitive, or UX-focused, provide a short UI plan and wait for approval before coding.
- For complex Qt geometry/layout work, verify with an actual render diagnostic or offscreen Qt diagnostic. These are usually ad hoc checks, not permanent tests.
- If visual verification was not done, say that explicitly.

The detailed workflow, diagnostics, quirks, and design rules live in `$qt-frontend-design`.

## Fallbacks and backwards compatability
Unless specifically instructed there you shall **never** add backwards compatability - it just produces code bloat while this repo is in early dev. Also fallbacks should never be "silent", they must be seen somewhere, maybe not in the active frontend but terminal or logging outputs are suitable (prefer terminal).

For refactors, schema changes, storage format changes, or internal API cleanups:
- Do **not** add legacy readers, legacy writers, migration shims, dual-format support, compatibility branches, or “accept both old and new” logic unless the user explicitly asks for it.
- Prefer updating all call sites and tests to the new contract directly.
- If old data or old files stop working after the refactor, that is acceptable by default in this repo.
- If a compatibility layer seems unavoidable, stop and ask first instead of adding it on your own.
