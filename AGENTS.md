## Project Overview

DMT is a project to manage all sorts of DnD-related things. From session planning and hosting, items, characters etc.

## How to handle bugs
All bugs should first be thoroughly investigated and then be reproduced by tests which fail and reproduce the bug, the goal should be to fix the bug and the test should pass, these tests then serve as regression tests. Important: Make the test BEFORE you fix the bug. It can also be useful to introduce temporary debug logging that trigger during tests.

For making the bug failing tests: Try to make them as fundamental as possible, dont think something like "maybe function xy is causing this lets make a test that fails when function xy is called: that is cheating". Think what **actually** measures the concrete failure mode and design the test around that - not based on assumptions what could fix the bug. You may sumplement with tests that are based on such assumptions, but for each bug there most be one *fundamental* test.

You may open the app with a script. Never interact with mouse events, you may use keyborad events. Do not make screenshots. You can introduce temporary debug keys that can be used to navigate the app during the inspection. Each inspection should be accompagnied by debug logs that fire during the test.

Put logging and any other debug artifacts in debug folder.


## Test Organization

- Prefer **small, focused test files** grouped by feature or behavior.
- Avoid monolithic or “mega” test files.
- Add new tests to the most specific existing location.
- Create new focused files when needed to allow parallel agent work with minimal merge conflicts.



## Testing Discipline (Multi-Agent Environment)

During testing, failures may occur because multiple agents are working in parallel.

Rule:

- **Only fix errors directly caused by your own changes.**

This avoids cross-agent interference and accidental scope creep.

## Environment Notes
- Dont use cat to edit.

## UI Guidelines
Whenever new buttons are introduced. Inspect whether they are close to other buttons and if suitable, equalize the size between all buttons and align them if possible. If a button is next to a **small** other widget, it can make sense to for example adjust the height such that the button aligns with both edges of the widget (example: one line text input + a button right next to it -> button should have same height as text input box). Buttons that contain square icon should always be square as well unless otherwise specified. Also make sure buttons and widgets never overlap no matter the screen size.

## UI Memory
UI is currently still very hard for Agents. To make it more likely common pitfalls dont happen again write (high level) learnings in here that helped when you fixed seamingly easy UI things, that turned out to be hard for you, this shouldnt be language or project specific. You can also remember cruxes on how to correctly diagnose issues in the geometry or so (it seem sometimes models assume wrong things in the UI world), also remember what mislead you in you analysis (i.e. when you were trying to fix something but did an incoeect anylsis making you think you fixed something but you didnt.)

UI Memory entries:
