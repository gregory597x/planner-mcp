---
id: test-cases-placeholders
title: "Placeholders — write the record without the specifics"
doc_type: reference
scope: global
status: active
rag_chunk_strategy: by_heading
---

# Placeholders

Greg's rule, 2026-09-24: **the record uses placeholders instead of specific
values.** Not "scrub before publishing" — *write it this way in the first
place*. A value that was never in the file cannot leak from it, and the deny
list then catches slips rather than carrying the whole job.

## The table

| real thing | placeholder |
|---|---|
| the Mac's hostname | `<HOST>` |
| the tailnet name (`*.ts.net`) | `<TAILNET>` |
| a Tailscale address (`100.x.x.x`) | `<TAILSCALE-IP>` |
| a LAN address (`192.168.x`, `10.x`) | `<LAN-IP>` |
| the home directory | `$HOME` |
| the login account name | `<USER>` |
| the Postgres container name | `<PG-CONTAINER>` |
| a database role | `<DB-ROLE>` |
| a schema name | `<SCHEMA>` |
| an email address | `<EMAIL>` |
| an owned domain | `<DOMAIN>` |
| a chat id containing any of the above | substitute inside it: `<ROLE>-<HOST>-2` |

## Kept real, deliberately

- **`127.0.0.1` and `localhost`.** Every machine has them and they are
  reachable from nowhere. Replacing them only makes examples harder to read.
- **Port numbers on loopback.** `:8000` on `127.0.0.1` is not a route in.
- **Role and project names.** These are vocabulary — the generic form is what
  gets published (`role-recovery`, `role-solver-b` and the rest of the alias
  table), and blanking them entirely makes the record useless, which is its own
  kind of failure. This document names none of the internal slugs on purpose:
  it is the table that EXPLAINS the substitution, so running it through the
  substitution turns the explanation into nonsense. Authored generic, published
  unchanged, hash-attested.
- **Numbers and results.** The whole point of a record is the evidence: 21
  checks, 5 induced failures, 30 h stall. Never generalise a measurement.

## The limit of the deny list

A scrubber only catches what it has been told to look for. A record naming a
new host, a new domain, a client, or a collaborator passes clean because
nothing lists it. So:

- authoring in placeholders is the control,
- the deny list is the net,
- and a human reads the directory before it is shared.

Three layers, because the first two are each individually insufficient.

## When a specific value is genuinely needed

Put it in the app's own tree, which is private, and reference it from the
record by name — "the reference build config at `$HOME/<app>/build.conf`".
The record says what was run and what happened; it does not have to be a
working copy of the environment.
