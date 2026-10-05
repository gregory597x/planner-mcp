# Chat role-coordinator daemon

Built 2026-09-23. Design: `md_staging/reference/chat-role-coordinator-daemon-design.md`.

Two jobs on one hourly tick: **track** Planner work claimed by chats, and
**route** questions a chat does not know where to send.

## Running it

    ./role-coordinator.sh                 # a tick: loads charters, then the tick
    ROLES_ARGS="" ./role-coordinator.sh   # same, but charters dry-run only
    /usr/bin/python3 role-coordinator.py --selftest
    /usr/bin/python3 roles_load.py [--apply]

It ships with `DRY_RUN=1` in `role-coordinator.conf`: it reports what it would do
and changes nothing. Set `DRY_RUN=0` to arm it.

`com.tcs.role-coordinator.plist` is written but **not installed**. Greg loads it
himself; a script never changes how this machine behaves unattended.

## What a tick does

1. **Read state** — open Planner tasks joined to `tasks_actionable`, the claims
   in `knowledge_hub.tracked_tasks`, and chat liveness.
2. **Chase** — a claimed task whose chat has been silent past `QUIET_HOURS`
   gets one mail, addressed to the chat's role when it holds one. Cooldown in
   `work/chased.tsv` stops repeat nagging.
3. **Write back** — a `complete` report with a summary closes the Planner task
   through the hub, so it is audited and fires the refresh notify. A `blocked`
   report whose `blocked_by` names a task id becomes a `task_dependencies` row.
4. **Verifiers** — see below.
5. **Route** — the daemon's own inbox, by the ladder in the design.
6. **Digest** — `work/last_run.json` plus a SUMMARY line, and a hub checkpoint
   when live.

## Verifier with no live holder

The thing this was asked for. For each open work item, each verifier role named
in the producing role's charter is classified:

| state | meaning | what happens |
|---|---|---|
| `ok` | a holder has spoken inside `VERIFIER_STALL_HOURS` | nothing; it can act |
| `holder_quiet` | someone holds the post but has gone silent | mailed, and named in the digest |
| `no_holder` | nobody holds it at all | mailed as a dead drop at `blocking` priority, and named in the digest |

A stall is never waited on quietly. The mail is sent even when nobody can
receive it, because the hub holds it and delivers the moment someone claims the
role — so the request is waiting rather than forgotten. `FALLBACK_VERIFIER`
(default `greg`) is named in the digest; a gate is never auto-waived.

The two states are counted separately in the SUMMARY line on purpose: a quiet
holder is a chat to nudge, no holder is a post nobody is standing in.

**Known gap in the hub, not here:** `required_gates()` in `coordination.rs` maps
only `role-reviewer-a` → `verify_efficiency` and `role-reviewer-b` →
`verify_security`. A charter naming any other verifier produces no required
gate, so the hub would let such an item settle unverified. This daemon reports
on the charter's verifiers regardless of gate naming, which covers the hole but
does not close it.

## Why it looks the way it does

- **Standard library only.** This machine has two pythons and only one carries
  PyYAML. A daemon must not depend on which is first on PATH.
- **Postgres through `docker exec`.** No password in a file, none in the
  environment.
- **Postgres encodes the JSON.** Rows come back as one JSON document, so no
  tab or newline in a title, summary or mail body can corrupt a parse.
- **State resolves through `CD_HOME`.** The runner executes a snapshot from a
  temp directory; without this the chase cooldown log would be deleted at exit
  and every run would re-chase every quiet chat. That bug was live in the first
  run on 2026-09-23.
- **`${ROLES_ARGS---apply}`, not `${ROLES_ARGS:---apply}`.** An empty value must
  mean "dry run", not "fall back to applying".

## Proof, 2026-09-23

- `--selftest`: 19 checks pass. Negative control: three injected defects (a
  silent verifier reading as `ok`, routing stopping excluding the sender,
  blocked work offered as actionable) produced 5 failures, each caught by the
  check meant for it.
- Verifier path end to end against two temporary work items: `holder_quiet` for
  `role-dedupe` at 30 h, `no_holder` for `role-reviewer-a` and
  `role-reviewer-b` at 50 h. Both rows removed afterwards; table back to 0.
- `roles_load.py`: parses `role-recovery`, cross-checks against PyYAML, and
  rejects an unknown field, an illegal status and a nested mapping rather than
  guessing. A deliberately wrong `display_name` was caught only on the
  interpreter with PyYAML — which is why `--apply` refuses without it.
- Live dry run: 44 open tasks, 0 claimed, 44 unclaimed, and one Planner task it
  would close — task 40, completed in the hub on 2026-09-17 and still Pending.

## Not built here

`parent_task_id`, the role-assignment table, and the two view edits are a
separate approval. The daemon runs on what exists today: claims in
`tracked_tasks`, blockers in `task_dependencies`.
