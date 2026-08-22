# planner-mcp

A production-deployed [Model Context Protocol](https://modelcontextprotocol.io) server, written in TypeScript against the official MCP SDK, that connects Claude (Claude Code, the Claude desktop app, claude.ai custom connectors) — and non-MCP clients like ChatGPT custom GPTs — to a self-hosted task Planner and work-context router.

It runs daily as a real service: a launchd daemon on macOS, fronted by a Cloudflare tunnel, serving multiple AI clients against the same backend.

**What this repo demonstrates**

- An MCP server with **both transports**: stdio for locally-registered clients, and **Streamable HTTP** with correct multi-session routing (one `Server` + transport pair per `mcp-session-id`).
- **Named API-key authentication**: per-person keys in a `keys.json` (0600) with hot reload — adding or revoking a key takes effect without a restart — constant-time comparison, per-key usage logging, and a legacy env-var fallback for zero-downtime migration.
- A **REST proxy door** on the same port, so OpenAPI/Actions clients (e.g. ChatGPT custom GPTs) can reach the same backend through the same auth layer.
- **Zod-validated tool boundary**: runtime schema checks guard every tool input so a model can't send malformed JSON upstream.
- Deliberate scope: fail-closed bind rules, no secrets in the repo, and a "what this is NOT" section below.

## Architecture

```
Claude Code (stdio) ──────────────► planner-mcp (stdio transport)
                                          │
claude.ai / Claude Code (HTTP) ─┐         │ tool calls (HTTP)
ChatGPT custom GPT (OpenAPI) ───┤         ▼
curl / scripts ─────────────────┘   ┌──────────────────┐     ┌─────────────────────┐
        │                           │                  │────►│ Planner backend     │
        ▼                           │                  │     │ (Axum + Postgres)   │
  Cloudflare tunnel ──► :8770 ────► │  planner-mcp     │     └─────────────────────┘
                        bearer auth │  --http mode     │     ┌─────────────────────┐
                        (keys.json) │  MCP + REST door │────►│ work-router daemon  │
                                    └──────────────────┘     │ (pgvector retrieval)│
                                                             └─────────────────────┘
```

One process, one port, two doors:

- **MCP door** — Streamable HTTP at any non-proxied path (use `/mcp`). Each session gets its own `Server` + transport pair, routed by the `mcp-session-id` header.
- **REST door** — `/router/*` proxies to the work-router daemon, `/planner/*` to the Planner backend. This is what an OpenAPI schema for ChatGPT Actions points at.

## Tools exposed

| Tool | Backs onto | Purpose |
|---|---|---|
| `planner_health` | `GET /health` | Is the Planner up? |
| `planner_ingest_task` | `POST /api/inbox/ingest` | Idempotent task upsert on `(source, external_id)` |
| `planner_list_tasks` | `GET /tasks?from=&to=` | Range read (recurring instances expanded server-side) |
| `planner_current_work` | filesystem projection | "What should I work on next?" |
| `router_health` | daemon `/health` | Connectivity of the router's databases |
| `router_align` | daemon `/align` | Ranked prior-work context for a free-text description (read-only) |
| `router_task_start` | daemon `/tasks/start` | Register a work session; returns tracked task id + retrieval context |
| `router_task_status` | daemon `/tasks/:id/status` | in_progress / blocked / complete, with audit note |
| `router_task_complete` | daemon `/tasks/:id/complete` | Close out with a summary — the memory the next session inherits |
| `router_next` | daemon `/next` | Live priority-ordered "what next" projection |

The `router_*` tools implement a session convention that replaces chat memory: start a task to pull context, update status while working, complete with a real summary. The daemon — not the chat — holds the authoritative record, so a session started in Claude can be resumed from any other client.

## Quick start

Requires Node 20+.

```bash
git clone https://github.com/gregory597x/planner-mcp.git
cd planner-mcp
npm install
npm run build
```

Register with Claude Code (stdio):

```bash
claude mcp add planner "node $(pwd)/dist/server.js"
```

Smoke test without any client or backend:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | node dist/server.js
```

prints a JSON-RPC response listing all ten tools. With a Planner backend running, `tools/call` on `planner_health` returns `Planner is UP (200): ok`.

## HTTP mode and authentication

```bash
node dist/server.js --http 8770
```

Binds `127.0.0.1:8770` by default (`PLANNER_MCP_BIND` to override). Auth is enforced whenever any credential source exists, and the server **refuses to bind a non-loopback address without one**.

Keys are named, per person, in `keys.json` (created `chmod 600`, gitignored):

```json
[
  { "name": "alice", "key": "<secret>" },
  { "name": "bob",   "key": "<secret>", "disabled": true }
]
```

Manage them with the bundled helper — no hand-editing, no restart:

```bash
./gateway_key.zsh add alice     # generates via `openssl rand -base64 32`, prints once
./gateway_key.zsh revoke bob    # takes effect on the next request
./gateway_key.zsh list          # names + status only, never key values
```

Design points (see [`src/api_keys.ts`](src/api_keys.ts)):

- **Hot reload.** `keys.json` is re-read whenever its mtime changes, so revocation doesn't need a service restart. A corrupt file keeps the last good key set rather than locking everyone out.
- **Constant-time comparison.** Presented keys are compared via sha256 + `timingSafeEqual`, and every entry is checked without early exit.
- **Accountable usage.** Every request logs the key *name* (never the value): `auth ok key=alice GET /router/health`. Failures log `auth DENIED`.
- **Migration-safe.** A legacy `MCP_PUBLIC_API_KEY` env var still authenticates (logged as `key=env`), so existing clients keep working while individual keys roll out.

Clients authenticate with `Authorization: Bearer <key>` or `x-api-key: <key>`:

```bash
claude mcp add --transport http planner https://your-host/mcp --header "Authorization: Bearer <key>"
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PLANNER_BASE_URL` | `http://localhost:8000` | Planner HTTP base URL |
| `ADMIN_ROUTER_BASE_URL` | `http://localhost:8765` | work-router daemon base URL |
| `PLANNER_MCP_BIND` | `127.0.0.1` | HTTP bind address (`--http` mode) |
| `MCP_PUBLIC_API_KEY` | — | Legacy single-key fallback (optional) |
| `MCP_PUBLIC_KEYS_FILE` | `./keys.json` | Named-keys file location |
| `PLANNER_CURRENT_WORK_PATH` | `$HOME/planner_exports/current_work.md` | `planner_current_work` projection file |

## Files

```
planner-mcp/
├── package.json
├── tsconfig.json
├── LICENSE                    # MIT
├── gateway_key.zsh            # add/revoke/enable/remove/list named keys
├── run_gateway.zsh            # service launcher (sources .env, runs --http 8770)
└── src/
    ├── server.ts              # tool wiring, transports, auth gate, REST proxy
    ├── api_keys.ts            # named keys: hot reload, constant-time match
    ├── planner_client.ts      # HTTP wrapper for the Planner backend
    └── admin_router_client.ts # HTTP wrapper for the work-router daemon
```

## Design notes

- **Runtime type-check the boundary, not the internals.** Zod schemas guard tool inputs so the model can't send malformed JSON to the backend.
- **One transport pair per session.** A Streamable HTTP transport instance serves exactly one MCP session; the server maps `mcp-session-id` → transport and builds a fresh pair on each initialize.
- **Fail closed.** Non-loopback bind with no configured key is a startup error, not a warning.
- **Lazy HTTP transport.** The streamable-HTTP module is imported only when `--http` is passed; cold stdio launches stay fast.
- **No caching layer.** Every call hits the backend. If you want lower latency, cache in the backend, not the wire adapter.

## What this is NOT

- Not a Planner. This server stores no state; it's a wire adapter plus an auth gate.
- Not a specific product's SDK. It targets the endpoint shapes above, not a particular backend implementation.
- Not an OAuth provider. claude.ai *web* custom connectors prefer OAuth; that's a planned increment. Bearer keys cover Claude Code, the desktop app, and Actions clients today.

## Contributing

Bug reports and small PRs welcome. For larger changes, open an issue first to discuss scope.

## License

MIT — see `LICENSE`.
