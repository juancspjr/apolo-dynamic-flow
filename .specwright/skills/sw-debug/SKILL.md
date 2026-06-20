---
name: sw-debug
description: >-
  Investigation-first debugging workflow. Scopes the problem, delegates root
  cause analysis, produces a diagnosis report, and applies fix/log/defer autonomously.
argument-hint: "[problem description]"
allowed-tools:
  - read
  - write
  - bash
  - glob
  - grep
  - Task
---

# Specwright Debug

## Goal

First-class debugging path. Scope the problem, investigate concurrently,
diagnose with evidence, then decide: fix it now, log it, or defer. Operates
autonomously, applying `.specwright/protocols/decision.md` for the fix/log/defer decision.

## Inputs

- Problem description (argument or recent error context)
- Initial evidence: error messages, logs, failing test output
- `{projectArtifactsRoot}/config.json` — `backlog.type` and `backlog.label`
- Codebase files — read during investigation

## Outputs

- `diagnosis.md` at `{workArtifactsRoot}/{id}/diagnosis.md` — always produced
- `spec.md` at `{workArtifactsRoot}/{id}/spec.md` — Fix path only (2-3 acceptance criteria)
- `decisions.md` at `{workArtifactsRoot}/{id}/decisions.md` — fix/log/defer decision recorded per `.specwright/protocols/decision.md`

## Constraints

**Stage boundary (LOW freedom):**
Follow `.specwright/protocols/stage-boundary.md`. Investigate and diagnose. NEVER write code,
run tests, branch, or commit. Fix path: produce spec.md, handoff to `/sw-build`.

**Scope (MEDIUM freedom):**
- If argument provided, use it. If no argument, infer from recent error context
  (last failed command, error output in conversation). If genuinely undetermined,
  apply DISAMBIGUATION: choose the most likely problem from available context.
- Collect evidence: error messages, stack traces, failing tests. Define boundary.

**Investigate (HIGH freedom):**
Delegate concurrently per `.specwright/protocols/delegation.md`: `specwright-researcher` (code
context, call paths) and `specwright-architect` (root cause, blast radius).

**Diagnose (MEDIUM freedom):**
Write `diagnosis.md`: Problem (observed vs expected), Root Cause (confidence level,
file:line evidence), Blast Radius (affected / not affected), Fix Approach (high-level),
Alternatives Considered. If agents return insufficient evidence: produce low-confidence
diagnosis and note the gap in decisions.md.

**Decision (MEDIUM freedom):**
Apply `.specwright/protocols/decision.md` DISAMBIGUATION + reversibility:
- Fix spans ≤3 files with local architectural scope → **Fix it now** (Type 2). Write
  spec.md, handoff to `/sw-build`.
- Fix spans >3 files or crosses architectural boundaries → **halt and recommend
  `/sw-design`** (Type 1 — structural scope).
- Known pattern (matches patterns.md entry) → **Log it** as BL-{n} per `.specwright/protocols/backlog.md`.
- Requires design-level decisions → **Defer** as BL-{n} with `defer` tag.
Record the decision in decisions.md.

**State (LOW freedom):**
Follow `.specwright/protocols/state.md`. Work ID: `debug-{short-description}`.

## Protocol References

- `.specwright/protocols/stage-boundary.md` -- scope and handoff
- `.specwright/protocols/decision.md` -- autonomous decision framework (fix/log/defer)
- `.specwright/protocols/state.md` -- workflow state updates
- `.specwright/protocols/delegation.md` -- concurrent delegation
- `.specwright/protocols/backlog.md` -- backlog items

## Failure Modes

| Condition | Action |
|-----------|--------|
| No problem description or context | Apply DISAMBIGUATION from conversation history. Record interpretation. |
| Agents return no evidence | Low-confidence diagnosis. Apply fix/log/defer per reversibility. |
| Fix is architectural (>3 files) | Halt. Recommend `/sw-design`. |
| Compaction during investigation | Re-run investigation; diagnosis.md rebuilt from scratch |
