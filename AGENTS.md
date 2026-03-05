## UI Guidelines
Whenever new buttons are introduced. Inspect whether they are close to other buttons and if suitable, equalize the size between all buttons and align them if possible. If a button is next to a **small** other widget, it can make sense to for example adjust the height such that the button aligns with both edges of the widget (example: one line text input + a button right next to it -> button should have same height as text input box). Buttons that contain square icon should always be square as well unless otherwise specified. Also make sure buttons and widgets never overlap no matter the screen size.

## Fallbacks and backwards compatability
Unless specifically instructed there you shall **never** add backwards compatability - it just produces code bloat while this repo is in early dev. Also fallbacks should never be "silent", they must be seen somewhere, maybe not in the active frontend but terminal or logging outputs are suitable (prefer terminal).

For refactors, schema changes, storage format changes, or internal API cleanups:
- Do **not** add legacy readers, legacy writers, migration shims, dual-format support, compatibility branches, or “accept both old and new” logic unless the user explicitly asks for it.
- Prefer updating all call sites and tests to the new contract directly.
- If old data or old files stop working after the refactor, that is acceptable by default in this repo.
- If a compatibility layer seems unavoidable, stop and ask first instead of adding it on your own.

## Other
In case you get stuck somewhere, you can have a look at quirks.md it contains solutions to some reoccuring issues.

