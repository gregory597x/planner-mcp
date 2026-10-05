# qa/smoke_test.sh — rationale (sidecar)

Lean-code + sidecar convention (`_done/codegen-rules.md` §"Comment placement").

## What it does

Re-runnable QA for the admin-router task-reasoning stack. Two checks:

1. **tasks_actionable elevation + blocking** — inserts a 3-tier chain `demo-A → demo-B →
   demo-C` (A high WSJF, B/C low) inside `BEGIN … ROLLBACK`, so it touches the DB but
   **persists nothing**. Asserts the feature: `demo-C` is `actionable + elevated + not
   blocked` (the root, do first); `demo-A`/`demo-B` are `is_blocked`; and all three carry
   `effective_wsjf = 7.00` (B and C elevated to A's priority). Emits `VERDICT: t/f`, which
   the script greps for pass/fail.
2. **daemon endpoints** — `GET /health` and `/next`, skipped (not failed) if the daemon
   isn't reachable, so the DB check still runs standalone.

## Run

    bash ~/TCS-Planner/admin_router/qa/smoke_test.sh

Env overrides: `PG_CONTAINER` (default `<PG-CONTAINER>`), `PLANNER_DB` (default
`role-planner`), `ADMIN_ROUTER_URL` (default `http://127.0.0.1:8765`). Exit 0 = pass.

## Why it's built this way

- **Non-destructive by construction.** All inserts are inside a single transaction ended by
  `ROLLBACK`; `ON_ERROR_STOP=1` aborts on any SQL error. Safe to run against the live role-planner
  DB anytime, even with real tasks present (the demo rows never commit).
- **Self-checking, not just visual.** The `VERDICT` row encodes the expected
  elevation/blocking outcome, so re-runs are pass/fail rather than eyeball-only. The
  human-readable table is still printed for context.
- **WSJF math:** A = (8+8+5)/3 = 7.00; B,C = 3/3 = 1.00 own, but both inherit A's 7.00 as
  `effective_wsjf` because A transitively depends on them.
- **Daemon check is optional** so the script doubles as a DB-only migration verifier when the
  daemon isn't running yet.

## Validation

`bash -n qa/smoke_test.sh` (syntax). Live run needs the Docker Postgres up; daemon section
needs the daemon running.
