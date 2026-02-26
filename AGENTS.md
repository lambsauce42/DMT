## How to handle bugs
All bugs should first be thoroughly investigated and then be reproduced by tests which fail and reproduce the bug, the goal should be to fix the bug and the test should pass, these tests then serve as regression tests. Important: Make the test BEFORE you fix the bug. It can also be useful to introduce temporary debug logging that trigger during tests.

For making the bug failing tests: Try to make them as fundamental as possible, dont think something like "maybe function xy is causing this lets make a test that fails when function xy is called": that is cheating. Think what **actually** measures the concrete failure mode and design the test around that - not based on assumptions what could fix the bug. You may sumplement with tests that are based on such assumptions, but for each bug there most be one *fundamental* test.

You may open the app with a script. Never interact with mouse events, you may use keyborad events. Do not make screenshots. You can introduce temporary debug keys that can be used to navigate the app during the inspection. Each inspection should be accompagnied by debug logs that fire during the test.

Put logging and any other debug artifacts in debug folder.

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

## Other
In case you get stuck somewhere, you can have a look at quirks.md it contains solutions to some reoccuring issues.


## Small Fix Exception
If the change is super small (for example tiny visual polish or trivial wording), you usually do not need to write a fail-first test before applying the fix.
If a bug is persistent or keeps reappearing, fall back to the fail-first regression-test workflow to lock it down.
