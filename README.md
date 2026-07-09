# planner-mcp

A small, focused [Model Context Protocol](https://modelcontextprotocol.io) connector for a self-hosted "Planner" HTTP backend. Lets any MCP-aware client (Claude Code, Cowork, claude.ai custom connectors, Cursor, Windsurf, and others) call your Planner's task-management endpoints as first-class tools — no more copy-pasting `curl` commands into chat.

Written in TypeScript against the official MCP SDK. Runs on **stdio** (default, for local clients) or **streamable HTTP** (for browser-based clients or cross-machine access).

## What the Planner is (context)

This connector assumes you have a locally- or LAN-hosted HTTP service that speaks a small set of JSON endpoints for tasks and projections:

- `GET /health` → `ok`
- `POST /api/inbox/ingest` → idempotent-upsert task by `(source, external_id)`
- `GET /tasks?from=YYYY-MM-DD&to=YYYY-MM-DD` → JSON list of tasks in a range
- A separately-managed filesystem projection at `$PLANNER_CURRENT_WORK_PATH` for "what to work on next"

The endpoint shapes match a household-scale Planner architecture (Axum + Postgres + optional pgvector-backed retrieval side). The connector is agnostic to how the backend is implemented — any HTTP service that speaks those endpoints will work.

## Tools exposed

| Tool | Backs onto | Purpose |
|---|---|---|
| `planner_health` | `GET /health` | Is the Planner up? |
| `planner_ingest_task` | `POST /api/inbox/ingest` | Idempotent upsert on `(source, external_id)` |
| `planner_list_tasks` | `GET /tasks?from=&to=` | Range read (recurring instances expanded server-side) |
| `planner_current_work` | filesystem read of `$PLANNER_CURRENT_WORK_PATH` | "What to work on next" projection |

The follow-on tools (task-get, task-note, workstream CRUD, state transitions) will land here as the Planner backend grows the matching JSON endpoints.

## Install

Requires Node 20+.

```bash
git clone https://github.com/gthompsn3/planner-mcp.git
cd planner-mcp
npm install
npm run build
```

## Run

### stdio (Claude Code / Cowork registration)

Add to your MCP client's registry. For Claude Code:

```bash
claude mcp add planner "node $(pwd)/dist/server.js"
```

For Cowork: MCP settings pane → **Add local MCP** → command: `node`, args: absolute path to `dist/server.js`.

### Streamable HTTP (claude.ai custom connectors, cross-machine access)

```bash
node dist/server.js --http 8765
```

Defaults to `127.0.0.1:8765`. To expose beyond localhost — for a Cloudflare tunnel to serve claude.ai — override:

```bash
PLANNER_MCP_BIND=0.0.0.0 node dist/server.js --http 8765
```

**Important:** if you expose over a tunnel, put an auth layer in front (Cloudflare Access, a bearer-token proxy, etc.). This server does no authentication of its own.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PLANNER_BASE_URL` | `http://localhost:8000` | Planner HTTP base URL |
| `PLANNER_MCP_BIND` | `127.0.0.1` | HTTP transport bind address (for `--http` mode) |
| `PLANNER_CURRENT_WORK_PATH` | `$HOME/planner_exports/current_work.md` | Where the `planner_current_work` tool reads the projection from |

## Smoke test without a client

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | node dist/server.js
```

Should print a JSON-RPC response listing the four `planner_*` tools. Ctrl-D or Ctrl-C to exit.

If your Planner backend is running:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"planner_health","arguments":{}}}' | node dist/server.js
```

Should print `Planner is UP (200): ok`.

## Files

```
planner-mcp/
├── package.json
├── tsconfig.json
├── LICENSE            # MIT
├── README.md          # this file
├── .gitignore
└── src/
    ├── server.ts          # entry — setRequestHandler wiring, stdio + optional HTTP
    └── planner_client.ts  # HTTP wrapper + current_work.md reader
```

## Design notes

- **Runtime type-check the boundary, not the internals.** Zod schemas guard the tool inputs so the model can't accidentally send malformed JSON to the Planner. Internal calls stay untyped where dynamism is desired.
- **No caching layer.** Every call hits the Planner. If you want lower latency, cache in the Planner itself, not here.
- **No authentication in this process.** stdio is inherently trusted (the client spawned the server). HTTP mode assumes you put auth *in front* if you expose beyond localhost.
- **Lazy HTTP transport.** The streamable-HTTP module is only imported when `--http` is passed. Cold stdio launches stay fast.

## What this is NOT

- Not a Planner. This connector doesn't store state. It's a wire adapter.
- Not a specific product's SDK. It targets the endpoint shapes above, not a particular backend implementation.
- Not an auth boundary. See the auth note in **Run → Streamable HTTP**.

## Contributing

Bug reports and small PRs welcome. For larger changes, open an issue first to discuss scope.

## License

MIT — see `LICENSE`.
