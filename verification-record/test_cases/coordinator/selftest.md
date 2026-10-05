---
id: test-role-coordinator-selftest
title: "Test case — chat role-coordinator daemon self-test"
doc_type: test_case
scope: global
status: active
app: role-coordinator
rag_chunk_strategy: by_heading
---

# role-coordinator --selftest

## What was run

    /usr/bin/python3 ~/TCS-Software_Projects/_admin/role-coordinator/role-coordinator.py --selftest

## When, and against what

2026-09-23, against the daemon as first built; re-run 2026-09-23 after the
routing-loop fix. Runner: `role-coordinator.sh`, scheduled by
`com.tcs.role-coordinator.plist` (hourly, `RunAtLoad` false).

## Result

    SUMMARY role-coordinator selftest: PASS | checks 21 | failed 0

21 checks across four decisions: verifier classification, `blocked_by` parsing,
the routing ladder, and the deadline/priority/elevation ordering.

## Negative control — proof it can fail

Three defects were injected into a copy and the suite was re-run:

1. a silent verifier reporting as `ok`
2. routing stopping excluding the sender
3. blocked work offered as actionable

Result: **5 failures, each caught by the check written for it.**

    FAILED verifier: silent holder: got 'ok', wanted 'holder_quiet'
    FAILED verifier: the role-recovery case: got 'ok', wanted 'holder_quiet'
    FAILED topic rung refuses a topic only the asker watches: got 'role-dedupe', wanted None
    FAILED hard deadline first: got 4, wanted 2
    FAILED blocked work is never offered: got True, wanted False

Two of the 21 checks exist because of a defect found by *running* the daemon,
not by reading it: a question containing the word "routing" matched the
role-coordinator's own topic, whose only subscriber was the role-coordinator. It would
have mailed itself and re-routed the same message every tick, forever.

## Also verified, outside the self-test

- **Verifier path end to end**, against two temporary work items since removed:
  `holder_quiet` for `role-dedupe` at 30 h, `no_holder` for `role-reviewer-a`
  and `role-reviewer-b` at 50 h. This exercises the SQL the self-test cannot.
- **Routing, on real mailbox messages**: #249 "who owns the phase-maps export
  format?" routed to topic `phase-maps`; #250 "welding certification paperwork"
  correctly reported unroutable rather than guessed. Both acked as tests so no
  chat received test traffic.
- **Live write-back**: Planner task 40, completed in the hub 2026-09-17 and
  still `Pending`, was closed by the daemon on 2026-09-23 with the reason and
  reporting chat recorded in `knowledge_hub.router_audit_log`.

## What this does not cover

- The **blocker write-back** path has never run on real data: no chat has
  reported blocked, so `task_dependencies` is still empty. The parsing is
  unit-tested; the insert is not.
- The **chase** path has not fired: it needs a claimed task whose chat has been
  silent past 24 h, and 0 of 43 open tasks are claimed.
- The **word-evidence routing rung** has not been exercised live; both test
  messages were resolved by earlier rungs.
- Nothing here tests the hub's own `required_gates()`, which maps only
  `role-reviewer-a` and `role-reviewer-b`. A charter naming any other
  verifier produces no required gate — a known hole the daemon reports around
  but does not close.
