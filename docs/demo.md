# Live transcript: an MCP session against the real backend

Captured 2026-09-13 by driving `dist/server.js` over stdio exactly the way an
MCP client (Claude Code, the Claude desktop app) does, against the live
work-router daemon and its Postgres/pgvector store. Nothing below is mocked;
the only edits are redactions, each marked `[elided]` — the retrieval chunks
contain private knowledge-base content that doesn't belong in a public repo.

The flow shown is the connector's flagship convention: **a session starts by
asking the daemon for context, and ends by writing a summary back** — so the
next session (from any client) inherits the record instead of relying on chat
memory.

## 1. Handshake

```
→ {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"claude-code-demo","version":"1.0"}}}

← {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26",
     "capabilities":{"tools":{}},
     "serverInfo":{"name":"planner-mcp","version":"0.2.0"}}}

→ {"jsonrpc":"2.0","method":"notifications/initialized"}
```

## 2. `router_task_start` — register the session, get context back

```
→ {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
     "name":"router_task_start",
     "arguments":{
       "task_name":"planner-mcp demo transcript",
       "task_description":"Capture a real MCP request/response transcript of the planner-mcp connector for the public repo's docs/demo.md",
       "chat_id":"planner-mcp-demo-01",
       "account":"claude"}}}
```

The daemon registers a tracked task and answers with ranked retrieval context
pulled from the knowledge base — note it surfaced the project-planning docs
that actually discuss this repo:

```
← {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"{
     \"task_id\": 8,
     \"chat_id\": \"planner-mcp-demo-01\",
     \"alignment_context\": [
       {
         \"source_path\": \"[elided]/md_staging/TCS-Planner/project-plan-with-estimates-2026-07-15.md\",
         \"document_title\": \"TCS Project Plan — 2026-07-15\",
         \"chunk_text\": \"[elided — private knowledge-base content]\",
         \"canonical_rank\": 100,
         \"score\": 0.0396
       },
       {
         \"source_path\": \"[elided]/md_staging/TCS-Planner/master-project-list-2026-07-15.md\",
         \"document_title\": \"Master project list — 2026-07-15\",
         \"chunk_text\": \"[elided — private knowledge-base content]\",
         \"canonical_rank\": 100,
         \"score\": 0.0334
       }
       // … 8 further ranked chunks elided …
     ],
     \"related_prior_tasks\": [],
     \"suggested_project\": null,
     \"rag_query_used\": \"q=Capture a real MCP request/response transcript of the planner-mcp connector for the public repo's docs/demo.md [lexical-or: 10 chunks]\",
     \"rag_unavailable\": false,
     \"resumed\": false,
     \"waiting_on\": []
   }"}],"isError":false}}
```

## 3. `router_task_complete` — write the memory the next session inherits

```
→ {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
     "name":"router_task_complete",
     "arguments":{
       "task_id":8,
       "summary":"Captured a live MCP stdio transcript (initialize, router_task_start, router_task_complete) for planner-mcp docs/demo.md.",
       "outputs":[{"kind":"doc","value":"docs/demo.md"}]}}}

← {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{
     \"ok\": true,
     \"task_id\": 8,
     \"completed_at\": \"2026-09-14T01:40:47.015197Z\"
   }"}],"isError":false}}
```

## What this shows

- The server speaks real, current MCP (Streamable-HTTP-era protocol version,
  proper initialize lifecycle) — this transcript is reproducible with three
  lines of JSON on stdin.
- Tool calls hit a live backend: the task id, timestamps, and retrieval scores
  above came back from a running daemon, not fixtures.
- The session convention is closed-loop: task 8 now exists in the daemon's
  audit log with a start row, a completion row, and a summary any future
  session can retrieve.
