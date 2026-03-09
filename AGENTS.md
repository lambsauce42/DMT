## UI Guidelines
Whenever UI is changed, treat it as layout work, not just widget insertion. New widgets must fit the surrounding row/panel in size, alignment, spacing, and style. Adjacent controls should usually share the same outer height and aligned edges unless there is a clear reason not to. Reuse the local UI pattern instead of relying on default Qt sizing, and check that nothing looks tacked on, mismatched, cramped, or overlapping at any screen size. Buttons that contain square icon should always be square as well unless otherwise specified.

### Required workflow before coding UI
- First inspect the surrounding UI code and identify the exact sizing and styling pattern already used nearby.
- Reuse existing heights, margins, spacing, border radius, fonts, and button styles from neighboring controls.
- If no local pattern exists, stop and propose one before implementing.
- Before editing, state in one short message what existing UI pattern will be reused and what the resulting layout will be.

### Hard layout constraints
- Never rely on default Qt widget sizing for new UI.
- Every newly added toolbar, header, or overlay control must have explicit size policy and margins.
- Controls placed in the same row must share aligned top and bottom edges and usually the same outer height.
- Peer rows inside the same panel section must use the same structure. If one slider row is `label + slider + value`, adjacent slider rows must use the same structure unless there is a written reason not to.
- Do not attach an extra endcap control such as a checkbox, button, or icon to only one row in a peer group. Either every peer row ends the same way or the odd control moves to its own dedicated row.
- Peer buttons in the same action row must use a normalized shared width unless the row has a documented primary action that is intentionally larger.
- A partial fix is not acceptable. If one row in a section is normalized, all sibling rows in that section must be checked and normalized in the same pass.
- Icon buttons must be visually balanced with adjacent controls and must not look tacked on.
- Buttons containing a square icon must be square. Set explicit fixed width and height.
- If a button is placed next to another session control, its height must match that control exactly unless there is a clear written reason not to.
- New overlays and panels must define explicit sections with clear visual hierarchy, not just stacked widgets.

### Interaction constraints
- "Beautiful and intuitive" means:
  - primary actions are obvious
  - destructive and secondary actions are visually quieter
  - the most common actions are one click away
  - dense features are grouped, not dumped into one panel
- Soundboards must use clickable button tiles, not plain file lists, unless explicitly requested.
- If an item is naturally represented as a trigger pad, use a button grid.
- If icons are user-facing and repeated, support choosing an icon instead of showing raw filenames only.

### Forbidden patterns unless explicitly requested
- No raw `QListWidget`, `QTabWidget`, or form dump as the main UX for a new feature just because it is fast to build.
- No default spacing or default margins.
- No mismatched button heights.
- No "admin controls at top, random controls below" layouts.
- No unlabeled icon buttons.
- No placeholder-looking UI shipped as final.

### Approval gate
- For any non-trivial UI change, do not implement immediately.
- First provide a short UI plan describing:
  - layout structure
  - primary interactions
  - reused local style pattern
  - why the chosen controls fit the feature
- If the request includes words like "beautiful", "intuitive", "polished", or "UX", wait for approval before coding.

### Verification
- After UI changes, verify:
  - button heights match adjacent controls
  - square buttons are actually square
  - peer rows share the same internal structure and ending pattern
  - labels, sliders, values, and toggles line up on common vertical centers
  - repeated labels and value pills use fixed widths where needed to prevent ragged columns
  - peer buttons in the same row share the same width unless a written exception exists
  - a local fix did not leave sibling rows in the same section inconsistent
  - spacing is consistent
  - panel works at small and large window sizes
  - nothing looks like default Qt fallback UI
- For non-trivial UI rows, inspect runtime geometry or add a UI test instead of trusting visual intent from the code alone.
- If visual verification cannot be done, say that explicitly instead of claiming polish.

## Fallbacks and backwards compatability
Unless specifically instructed there you shall **never** add backwards compatability - it just produces code bloat while this repo is in early dev. Also fallbacks should never be "silent", they must be seen somewhere, maybe not in the active frontend but terminal or logging outputs are suitable (prefer terminal).

For refactors, schema changes, storage format changes, or internal API cleanups:
- Do **not** add legacy readers, legacy writers, migration shims, dual-format support, compatibility branches, or “accept both old and new” logic unless the user explicitly asks for it.
- Prefer updating all call sites and tests to the new contract directly.
- If old data or old files stop working after the refactor, that is acceptable by default in this repo.
- If a compatibility layer seems unavoidable, stop and ask first instead of adding it on your own.

## Other
In case you get stuck somewhere, you can have a look at quirks.md it contains solutions to some reoccuring issues.
