---
id: test-cases-kb
title: "Test cases KB — what was actually run, per app"
doc_type: reference
scope: global
status: active
capabilities: [testing, verification, sharing]
rag_chunk_strategy: by_heading
---

# Test cases

Created 2026-09-24 at Greg's direction. One directory per app or project, so
deciding what can be shared is a per-directory decision rather than a file hunt.

## The rule that makes this worth keeping

**Only tests that have actually been run go in here.** A test suite nobody has
executed is a plan, not evidence, and this KB exists to answer "what do we know
works?" — not "what did someone intend to check?"

Each entry records five things:

1. **What was run** — the exact command, copy-pasteable.
2. **When**, and against which version or tag.
3. **The result**, as numbers, not adjectives.
4. **The negative control** — proof the test can fail. A green test that has
   never been seen to fail measures nothing; this project has been bitten by
   that, so the control is not optional.
5. **What it does not cover**, stated plainly.

## Layout

    test_cases/
      README.md
      role-coordinator/      the chat role-coordinator daemon
      code_daemons/     the two-chain formatter and YAML analyzer
      knowledge_hub/    hub endpoints and smoke tests
      role-planner/          Planner backend, MCP server, agent
      solver/           ctest suites under Solver
      media_dedupe/     recovery, role-dedupe and reclaim verification

A directory may also hold the **daemon that runs its tests**, because a test
case without its runner is not reproducible. The runner is part of the evidence.

## Sharing

Directory granularity is the point. Anything that names a credential, a private
path, a client, or Greg's role-owner data does not belong in a directory intended
for sharing — put it in the app's own tree instead and reference it here by
name. Before sharing any directory, check it the way a stranger would read it.

## Where the tests and runners actually live

The canonical copies stay with their apps; this KB records what was run and
points at them. Moving a test here would separate it from the code it tests.

| app | tests | runner |
|---|---|---|
| role-coordinator | `role-coordinator.py --selftest` | `role-coordinator.sh`, `com.tcs.role-coordinator.plist` |
| code_daemons | `verify_format.sh selftest`, gates A/B/C | `daemon.sh`, `com.tcs.code-daemon.plist` |
| knowledge_hub | `qa/smoke_test.sh`, Rust `#[test]` in `research.rs`, `files.rs`, `role-owner.rs`, `planner_meta.rs`, `main.rs` | `cargo test`, the smoke script |
| role-planner | `planner_agent/test_planner_agent.py`, `cloudstore_relay/test_relay.py`, `mcp_server_public/tests/*.test.ts`, `scripts/check_docs.py` | `scripts/cargo-check.command` |
| solver | `ctest` suites | CMake/ctest |
