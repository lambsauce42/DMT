## How to handle bugs
Bug fixes should be investigated first. Do **not** require a fail-first test for every bug by default.

Fail-first regression tests are required only for:
- High-impact bugs (crash, data loss/corruption, security/privacy issues, major broken flow).
- Persistent/reappearing bugs.
- Bugs where root cause or fix confidence is low without automated reproduction.

For routine low-risk bug fixes, it is acceptable to:
- Fix directly without adding a new test.
- Validate with targeted existing tests and/or manual verification.
- Add temporary debug logging when it helps inspection.

When a fail-first bug test is required, make it as fundamental as possible. Dont think something like "maybe function xy is causing this lets make a test that fails when function xy is called": that is cheating. Think what **actually** measures the concrete failure mode and design the test around that - not based on assumptions what could fix the bug. You may sumplement with tests that are based on such assumptions, but there should be at least one *fundamental* test for that bug.

You may open the app with a script. Never interact with mouse events, you may use keyborad events. Do not make screenshots. You can introduce temporary debug keys that can be used to navigate the app during the inspection. Each inspection should be accompagnied by debug logs that fire during the test.

Put logging and any other debug artifacts in debug folder.

## Test Gating (Important)

- Do **not** add new tests by default.
- Add a new test only when at least one of these is true:
  - The bug/regression is high-impact or persistent.
  - Behavior/logic changed in a risky way that could realistically break again.
  - Core flows, data integrity, or cross-module contracts changed.
- For tiny edits (wording, visual polish, copy changes, simple layout nudge, minor refactor with no behavior change), avoid creating new tests.
- Do not create speculative tests for "maybe this could fail" cases without concrete evidence.
- Prefer running existing related tests first; only add tests when current coverage is clearly missing for the actual failure mode.
- If adding a test is optional and the change is low risk, skip adding it and keep scope focused.

## Test Organization

- Prefer **small, focused test files** grouped by feature or behavior.
- Avoid monolithic or “mega” test files.
- Add new tests to the most specific existing location.
- Create new focused files when needed to allow parallel agent work with minimal merge conflicts.

## Test Tiers

- Every test must belong to exactly one tier: `tier0`, `tier1`, or `tier2`.
- `tier0`: fast logic/unit checks.
- `tier1`: standard feature/widget integration checks.
- `tier2`: heavy/slow/full-flow checks (online flows, long UI interactions, large integration scenarios).
- Run selection:
  - Small local logic change: `pytest --tier-max=0`
  - Normal bugfix/feature change: `pytest --tier-max=1` (default)
  - Cross-cutting/risky UI+network+persistence change: `pytest --tier-max=2`
- Explicit subset when needed: `pytest --tiers 0,2`
- New test files must be tiered explicitly (`@pytest.mark.tier0|tier1|tier2`) or registered in `tests/conftest.py`.

## Test Save Data

- Test save data should be temporary/isolated by default.
- If persistent fixture save files are required, keep them very small and few.
- Never let tests accumulate generated save files across runs.


## Testing Discipline (Multi-Agent Environment)

During testing, failures may occur because multiple agents are working in parallel.

Rule:

- **Only fix errors directly caused by your own changes.**

This avoids cross-agent interference and accidental scope creep.

## Environment Notes
- Dont use cat to edit.
- Dont commit or add anything unless you are instructed to do so.
- If you are a "Gemini" mdoel you are not allowed to use git at all.

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


## Small Fix Exception
If the change is super small (for example tiny visual polish or trivial wording), you usually should not add a new test.
Fail-first tests are mainly for high-impact or recurring bugs, not for routine low-risk fixes.
If a bug is persistent or keeps reappearing, fall back to the fail-first regression-test workflow to lock it down.
