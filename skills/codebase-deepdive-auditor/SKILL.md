---
name: codebase-deepdive-auditor
description: Deep static and behavioral audits for existing codebases to uncover real bugs, dead code, and cross-system regressions that passing tests may miss. Use when asked to perform a deep-dive bug hunt, architecture interplay analysis, workflow reliability review, or pre-release risk assessment without broad feature development.
---

# Codebase Deepdive Auditor

## Overview

Run a rigorous bug-hunting review that focuses on real user workflows and subsystem interaction, not only unit-level correctness. Produce evidence-backed findings with severity, reproduction steps, and code references.

## Audit Workflow

1. Clarify scope and constraints
- Confirm what is in/out of scope, whether production code edits are allowed, and whether failing tests are expected as proof.
- Read workspace instructions (for example `AGENTS.md`) and obey local rules.

2. Build a system map before judging behavior
- Identify main entry points, core state containers, persistence/network layers, and UI/action dispatch boundaries.
- Trace critical call paths from user action to side effects.

3. Evaluate end-to-end user journeys
- Simulate realistic multi-step behavior (create/edit/delete/save/reopen/sync/undo/redo/export/import).
- Prefer failure modes a user notices: wrong state, data loss, inconsistent UI, stale data, auth bypass, or hidden crash paths.
- Use [references/user-journey-matrix.md](references/user-journey-matrix.md) to choose coverage quickly.

4. Probe subsystem interplay deliberately
- Check interactions among state management, persistence, network/auth, and UI lifecycle.
- Look for ordering bugs (event timing), partial failure handling, duplicated source-of-truth, and stale caches.
- Use [references/interplay-checklist.md](references/interplay-checklist.md) for high-signal checks.

5. Detect dead code and misleading surfaces
- Find unreachable branches, unused modules/functions, stale feature flags, mismatched UI affordances, and obsolete tests.
- Treat dead code as a risk item when it can mislead future changes or hide divergence from actual behavior.

6. Validate suspected defects with evidence
- Reproduce each high-confidence bug with a minimal, fundamental failing test when practical.
- Keep bug tests behavior-focused (what fails for the user), not implementation-coupled.
- Add temporary debug logging only as needed; place debug artifacts under a `debug/` folder when project policy requires it.

7. Report findings by severity and confidence
- Start with concrete findings, then assumptions/open questions, then optional summary.
- Include impact, reproduction, expected vs actual behavior, and exact file/line references.
- Use [references/report-template.md](references/report-template.md) structure when no explicit format is requested.

## Evidence Standards

- Prefer direct evidence: reproducible test failures, deterministic traces, or concrete control/data-flow analysis.
- Avoid speculative findings; mark uncertain items as hypotheses and state what proof is missing.
- Distinguish:
  - Confirmed bug: user-visible or contract-visible failure reproduced or proven by code path.
  - Risk: plausible failure with partial evidence.
  - Dead code: confirmed unreachable or unused path with no active references.

## Scope Guardrails

- Never write or modify production code while using this skill.
- Write code only when adding new tests for suspected issues.
- Default to analysis and tests; do not modify production behavior unless explicitly requested.
- Do not claim reliability from “all tests passing” alone.
- Do not hide unknowns; state them and provide the next strongest verification step.

## Outputs

- Deliver a detailed findings report with:
1. Findings ordered by severity
2. For each finding: title, impact, confidence, reproduction/evidence, and file references
3. Open questions or assumptions
4. Residual risk/testing gaps

## References

- [references/interplay-checklist.md](references/interplay-checklist.md)
- [references/user-journey-matrix.md](references/user-journey-matrix.md)
- [references/report-template.md](references/report-template.md)
