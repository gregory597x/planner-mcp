# Verification record — multi-agent engineering system

A record of tests that have actually been run against a private system, and the
daemons that run them. **Not a runnable suite**: the system under test is not
published, and these files are evidence rather than a product.

Published because the interesting part is not that the tests pass. It is what
had to be true before a passing test meant anything.

## The rule this record is built on

> A test nobody has seen fail measures nothing.

Every entry therefore records five things: the exact command, when it ran and
against what version, the result as numbers, **the negative control that proves
the test can fail**, and what it does not cover.

The negative control is the part worth reading. For each suite, defects were
deliberately injected and the suite re-run to confirm each one was caught by the
check written for it. Examples from `test_cases/role-coordinator/selftest.md`:

| injected defect | caught by |
|---|---|
| a silent verifier reporting as able to verify | `verifier: silent holder` |
| routing stopping excluding the message's sender | `topic rung refuses a topic only the asker watches` |
| blocked work offered as actionable | `blocked work is never offered` |

21 checks, 3 injected defects, 5 resulting failures — each traceable to its own
assertion.

## What the system does

A set of daemons coordinating several concurrent AI coding sessions against one
codebase, brokered by a local service:

- **`daemons/role-coordinator/`** — tracks task ownership across sessions, chases
  ones that go quiet, writes completions and blockers back to the role-planner, and
  routes questions a session cannot address itself. Standard library only.
- **`daemons/code_daemons/`** — a two-chain vendoring model for third-party C
  and C++: upstream releases byte-for-byte in one history, reformatted code in
  a separate one, with three gates between them (token equality, compiled
  object equality against a reference build, then the library's own tests).
- **`test_cases/`** — the record itself, one directory per application.

## Things in here that were learned the hard way

Each of these is a defect found by *running* something, not by reading it:

- A daemon posted status updates but never registered an address, so its own
  inbox was empty by construction. It could never have received the messages it
  existed to route.
- A message containing the word "routing" matched the routing daemon's **own**
  subscription topic, whose only subscriber was itself. It would have mailed
  itself and re-processed the same message on every tick, forever.
- A self-snapshotting script wrote its state into the temporary directory it ran
  from, so a cooldown log was deleted at exit and every run repeated work it had
  already done.
- A parser cross-check caught a wrong value that schema validation could not
  see — but only on the interpreter that had the comparison library installed.
  Writing now refuses without it, because a check that silently does not run is
  worse than no check.

## What is deliberately not here

- The systems under test, and their configuration.
- Tests whose fixtures contain infrastructure identifiers. One test of a
  redaction routine is excluded precisely because its fixtures *are* the strings
  it redacts.
- Unit tests embedded inside application source files, which cannot be extracted
  without publishing the application.

Identifiers throughout are placeholders (`<HOST>`, `<TAILNET>`, `$HOME`) by
authoring convention, not by a scrubbing pass — see `test_cases/placeholders.md`
and `test_cases/deny_list.txt`, which is enforced by a publish step that refuses
rather than warns.

## Licence

MIT. See `LICENSE`.
