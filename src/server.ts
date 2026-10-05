#!/usr/bin/env node
// planner-mcp — a Model Context Protocol connector for a self-hosted Planner
// HTTP backend.
//
// Transports:
//   - stdio (default) — for local registration with Claude Code, Cowork, or
//     any other MCP client that spawns the server as a subprocess.
//   - Streamable HTTP — flip on with `--http <port>` for claude.ai custom
//     connectors or cross-machine access. See README.md § Streamable HTTP.
//
// This is a thin wrapper. Every tool maps 1:1 to a Planner HTTP endpoint (or
// a filesystem "current work" projection). The Planner remains the system of
// record; nothing in this file mutates state independently.

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import {
  health,
  ingestTask,
  listTasks,
  readCurrentWork,
  type IngestPayload,
} from "./planner_client.js";

import { authConfigured, authenticate, keysFilePath } from "./api_keys.js";

import {
  routerAlign,
  routerHealth,
  routerNext,
  routerTaskComplete,
  routerTaskStart,
  routerTaskStatus,
  type TaskStartPayload,
  type TaskStatusPayload,
} from "./admin_router_client.js";

/* ===================== TOOL SCHEMAS (zod) ===================== */

const RouterAlignSchema = z.object({
  q: z.string().min(1).describe("Free-text description of the work at hand."),
  top_k: z.number().int().min(1).max(20).optional()
    .describe("How many ranked chunks to return. Daemon default applies when omitted."),
});

const RouterTaskStartSchema = z.object({
  task_name: z.string().min(1).describe("Short task name (used for tracking and retrieval)."),
  task_description: z.string().min(1).describe("What this session is about to do — drives the retrieval query."),
  chat_id: z.string().optional().describe("Stable id for this chat session. Reusing an id resumes that session's task."),
  account: z.string().optional().describe('Which chat platform/account this is (e.g. "claude", "chatgpt").'),
  project_hint: z.string().optional().describe("Optional project name to scope retrieval."),
  planner_task_id: z.number().int().optional().describe("Planner task id this work executes, if known."),
});

const RouterTaskStatusSchema = z.object({
  task_id: z.number().int().describe("Tracked task id returned by router_task_start."),
  status: z.enum(["in_progress", "blocked", "complete"]).describe("New status."),
  blocked_by: z.string().optional().describe("What this task is waiting on (when status=blocked)."),
  note: z.string().optional().describe("Free-text note recorded in the audit log."),
});

const RouterTaskCompleteSchema = z.object({
  task_id: z.number().int().describe("Tracked task id returned by router_task_start."),
  summary: z.string().min(1).describe("Close-out summary of what was actually done. Stored on the task; this is the memory the next session inherits."),
  outputs: z.array(z.object({
    kind: z.string().describe('Output type, e.g. "file", "commit", "doc", "url".'),
    value: z.string().describe("Path, hash, or URL of the output."),
  })).optional().describe("Concrete artifacts produced."),
});

const IngestSchema = z.object({
  title: z.string().min(1).describe("Task title (required)."),
  assigned_to: z
    .string()
    .min(1)
    .describe("Username to assign the task to (must exist in the Planner's users table)."),
  date: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/)
    .describe("Due date, YYYY-MM-DD."),
  due_time: z
    .string()
    .regex(/^\d{2}:\d{2}$/)
    .optional()
    .describe("Optional due time, HH:MM."),
  priority: z
    .number()
    .int()
    .min(1)
    .max(5)
    .optional()
    .describe("Priority 1 (highest) to 5 (lowest). Defaults to 3."),
  category: z
    .string()
    .optional()
    .describe('User-defined category (e.g. "JOB_FOLLOWUP", "HOME_MAINTENANCE").'),
  source: z
    .string()
    .min(1)
    .describe(
      'Worker name that produced this record (e.g. "job_search_worker"). Must be registered as a WORKER user in the Planner.',
    ),
  external_id: z
    .string()
    .optional()
    .describe(
      'Unique id within the source. Used with source for upsert. Recommended format: "linkedin-4392683290", "<slug>-<YYYY-MM-DD>", etc.',
    ),
  deduplication_key: z
    .string()
    .optional()
    .describe(
      "Optional cross-source key. Same key across sources will link records via task_aliases (per the Planner's cross-worker contract).",
    ),
  task_type: z
    .enum(["TASK", "EVENT", "NOTE"])
    .optional()
    .describe('One of TASK | EVENT | NOTE. Defaults to "TASK".'),
});

const ListTasksSchema = z.object({
  from: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/)
    .describe("Range start, YYYY-MM-DD (inclusive)."),
  to: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/)
    .describe("Range end, YYYY-MM-DD (inclusive)."),
});

/* ===================== TOOL LIST ===================== */

const TOOLS = [
  {
    name: "planner_health",
    description:
      "Ping the Planner backend at /health. Use as a first check that the server is up. Returns OK or an error.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "planner_ingest_task",
    description:
      "Insert (or upsert) a task into the Planner via POST /api/inbox/ingest. Idempotent on (source, external_id): the same key updates the existing task, a new key inserts. Use this INSTEAD of prompting the user to run curl.",
    inputSchema: {
      type: "object",
      properties: {
        title: { type: "string" },
        assigned_to: { type: "string" },
        date: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" },
        due_time: { type: "string", pattern: "^\\d{2}:\\d{2}$" },
        priority: { type: "integer", minimum: 1, maximum: 5 },
        category: { type: "string" },
        source: { type: "string" },
        external_id: { type: "string" },
        deduplication_key: { type: "string" },
        task_type: { type: "string", enum: ["TASK", "EVENT", "NOTE"] },
      },
      required: ["title", "assigned_to", "date", "source"],
      additionalProperties: false,
    },
  },
  {
    name: "planner_list_tasks",
    description:
      "List tasks in a date range via GET /tasks?from=&to=. Returns the unified read-model JSON (expanded recurring instances included).",
    inputSchema: {
      type: "object",
      properties: {
        from: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" },
        to: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" },
      },
      required: ["from", "to"],
      additionalProperties: false,
    },
  },
  {
    name: "planner_current_work",
    description:
      "Read the 'what to do next' projection written by a separate scheduler at $PLANNER_CURRENT_WORK_PATH (defaults to $HOME/planner_exports/current_work.md). Prefer this over planner_list_tasks when asking 'what should I work on next?'.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "router_health",
    description:
      "Ping the work-router daemon's /health. Reports connectivity of its planner/rag/state databases.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "router_align",
    description:
      "Ask the work-router daemon for work-context alignment: ranked prior-work chunks (source_path, title, text, score) retrieved for a free-text description of the work at hand. Read-only; no session/task state is created. Use at the start of any piece of work instead of relying on chat memory.",
    inputSchema: {
      type: "object",
      properties: {
        q: { type: "string" },
        top_k: { type: "integer", minimum: 1, maximum: 20 },
      },
      required: ["q"],
      additionalProperties: false,
    },
  },
  {
    name: "router_task_start",
    description:
      "Register the start of a work session with the work-router daemon. Returns a tracked task_id + chat_id, ranked alignment context, related prior tasks, and anything this work is waiting on. Reusing the same chat_id resumes that session. This is the canonical 'give me my context' call — the daemon, not the chat, holds the authoritative record.",
    inputSchema: {
      type: "object",
      properties: {
        task_name: { type: "string" },
        task_description: { type: "string" },
        chat_id: { type: "string" },
        account: { type: "string" },
        project_hint: { type: "string" },
        planner_task_id: { type: "integer" },
      },
      required: ["task_name", "task_description"],
      additionalProperties: false,
    },
  },
  {
    name: "router_task_status",
    description:
      "Update a tracked task's status (in_progress | blocked | complete) on the work-router daemon, with optional blocked_by and audit note.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "integer" },
        status: { type: "string", enum: ["in_progress", "blocked", "complete"] },
        blocked_by: { type: "string" },
        note: { type: "string" },
      },
      required: ["task_id", "status"],
      additionalProperties: false,
    },
  },
  {
    name: "router_task_complete",
    description:
      "Close out a tracked task on the work-router daemon with a completion summary and optional output artifacts. ALWAYS call this at the end of a work session — the summary is what future sessions (on any chat platform) will retrieve instead of remembering.",
    inputSchema: {
      type: "object",
      properties: {
        task_id: { type: "integer" },
        summary: { type: "string" },
        outputs: {
          type: "array",
          items: {
            type: "object",
            properties: {
              kind: { type: "string" },
              value: { type: "string" },
            },
            required: ["kind", "value"],
            additionalProperties: false,
          },
        },
      },
      required: ["task_id", "summary"],
      additionalProperties: false,
    },
  },
  {
    name: "router_next",
    description:
      "Ask the work-router daemon what to work on next — the live priority-ordered projection, served from the daemon rather than the exported file.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
];

/* ===================== SERVER SETUP ===================== */
// Factory: HTTP mode needs a fresh Server+transport pair PER SESSION
// (a Streamable HTTP transport instance serves exactly one session).

function buildServer(): Server {
const server = new Server(
  { name: "planner-mcp", version: "0.2.0" },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: TOOLS,
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "planner_health": {
        const r = await health();
        return {
          content: [
            {
              type: "text",
              text: r.ok
                ? `Planner is UP (${r.status}): ${r.body}`
                : `Planner is DOWN (${r.status}): ${r.body}`,
            },
          ],
          isError: !r.ok,
        };
      }

      case "planner_ingest_task": {
        const parsed = IngestSchema.parse(args ?? {});
        const r = await ingestTask(parsed as IngestPayload);
        return {
          content: [
            {
              type: "text",
              text: r.ok
                ? `Ingest OK (HTTP ${r.status}):\n${JSON.stringify(r.body, null, 2)}`
                : `Ingest FAILED (HTTP ${r.status}):\n${JSON.stringify(r.body, null, 2)}`,
            },
          ],
          isError: !r.ok,
        };
      }

      case "planner_list_tasks": {
        const parsed = ListTasksSchema.parse(args ?? {});
        const r = await listTasks(parsed);
        return {
          content: [
            {
              type: "text",
              text: r.ok
                ? `Tasks ${parsed.from} .. ${parsed.to} (HTTP ${r.status}):\n${JSON.stringify(r.body, null, 2)}`
                : `List failed (HTTP ${r.status}):\n${JSON.stringify(r.body, null, 2)}`,
            },
          ],
          isError: !r.ok,
        };
      }

      case "planner_current_work": {
        const r = await readCurrentWork();
        return {
          content: [{ type: "text", text: r.body }],
          isError: !r.ok,
        };
      }

      case "router_health": {
        const r = await routerHealth();
        return {
          content: [{ type: "text", text: `work-router ${r.ok ? "UP" : "DOWN"} (HTTP ${r.status}):\n${JSON.stringify(r.body, null, 2)}` }],
          isError: !r.ok,
        };
      }

      case "router_align": {
        const parsed = RouterAlignSchema.parse(args ?? {});
        const r = await routerAlign(parsed.q, parsed.top_k);
        return {
          content: [{ type: "text", text: r.ok ? JSON.stringify(r.body, null, 2) : `align failed (HTTP ${r.status}):\n${JSON.stringify(r.body, null, 2)}` }],
          isError: !r.ok,
        };
      }

      case "router_task_start": {
        const parsed = RouterTaskStartSchema.parse(args ?? {});
        const r = await routerTaskStart(parsed as TaskStartPayload);
        return {
          content: [{ type: "text", text: r.ok ? JSON.stringify(r.body, null, 2) : `task_start failed (HTTP ${r.status}):\n${JSON.stringify(r.body, null, 2)}` }],
          isError: !r.ok,
        };
      }

      case "router_task_status": {
        const parsed = RouterTaskStatusSchema.parse(args ?? {});
        const { task_id, ...rest } = parsed;
        const r = await routerTaskStatus(task_id, rest as TaskStatusPayload);
        return {
          content: [{ type: "text", text: r.ok ? JSON.stringify(r.body, null, 2) : `task_status failed (HTTP ${r.status}):\n${JSON.stringify(r.body, null, 2)}` }],
          isError: !r.ok,
        };
      }

      case "router_task_complete": {
        const parsed = RouterTaskCompleteSchema.parse(args ?? {});
        const r = await routerTaskComplete(parsed.task_id, parsed.summary, parsed.outputs);
        return {
          content: [{ type: "text", text: r.ok ? JSON.stringify(r.body, null, 2) : `task_complete failed (HTTP ${r.status}):\n${JSON.stringify(r.body, null, 2)}` }],
          isError: !r.ok,
        };
      }

      case "router_next": {
        const r = await routerNext();
        return {
          content: [{ type: "text", text: r.ok ? JSON.stringify(r.body, null, 2) : `next failed (HTTP ${r.status}):\n${JSON.stringify(r.body, null, 2)}` }],
          isError: !r.ok,
        };
      }

      default:
        return {
          content: [{ type: "text", text: `Unknown tool: ${name}` }],
          isError: true,
        };
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return {
      content: [{ type: "text", text: `Tool ${name} threw: ${msg}` }],
      isError: true,
    };
  }
});

return server;
}

/* ============ TRANSPORT (stdio, optional HTTP + REST proxy) ============ */
//
// HTTP mode serves two doors behind bearer auth — named keys in keys.json
// plus the legacy MCP_PUBLIC_API_KEY env fallback (see api_keys.ts):
//   - MCP Streamable HTTP           any path not listed below (use /mcp)
//   - REST proxy for OpenAPI/Actions clients (e.g. ChatGPT custom GPTs):
//       /router/*   → admin_router  (ADMIN_ROUTER_BASE_URL, :8765)
//       /planner/*  → Planner       (PLANNER_BASE_URL, :8000)
// Fail-closed: refuses to bind a non-loopback address without any key.

const REST_PREFIXES: Array<[string, () => string]> = [
  ["/router/", () => process.env.ADMIN_ROUTER_BASE_URL ?? "http://localhost:8765"],
  ["/planner/", () => process.env.PLANNER_BASE_URL ?? "http://localhost:8000"],
];

async function main() {
  const httpFlagIdx = process.argv.indexOf("--http");
  const useHttp = httpFlagIdx !== -1;
  const httpPort = useHttp
    ? Number(process.argv[httpFlagIdx + 1] ?? 8770)
    : undefined;

  if (useHttp && httpPort && !Number.isNaN(httpPort)) {
    // Lazy-load the HTTP transport so the stdio-only path stays lean.
    try {
      const { StreamableHTTPServerTransport } = await import(
        "@modelcontextprotocol/sdk/server/streamableHttp.js"
      );
      const http = await import("node:http");
      const bind = process.env.PLANNER_MCP_BIND ?? "127.0.0.1";
      const authOn = authConfigured();

      if (!authOn && bind !== "127.0.0.1" && bind !== "localhost") {
        console.error(
          `[planner-mcp] REFUSING to bind ${bind} without any API key. ` +
            `Set MCP_PUBLIC_API_KEY or create ${keysFilePath()}, or bind loopback.`,
        );
        process.exit(1);
      }
      if (!authOn) {
        console.error(
          "[planner-mcp] WARNING: no MCP_PUBLIC_API_KEY and no keys.json — auth disabled on loopback. " +
            "Anything fronting this port (e.g. a tunnel) exposes it unauthenticated.",
        );
      }

      // One Server+transport pair per MCP session, routed by mcp-session-id.
      const sessions = new Map<
        string,
        InstanceType<typeof StreamableHTTPServerTransport>
      >();

      const httpServer = http.createServer(async (req, res) => {
        try {
          const reqUrl = req.url ?? "/";
          if (authOn) {
            const keyName = authenticate(req.headers as Record<string, unknown>);
            if (keyName === null) {
              console.error(
                `[planner-mcp] ${new Date().toISOString()} auth DENIED ${req.method ?? "?"} ${reqUrl}`,
              );
              res.writeHead(401, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ error: "unauthorized" }));
              return;
            }
            console.error(
              `[planner-mcp] ${new Date().toISOString()} auth ok key=${keyName} ${req.method ?? "?"} ${reqUrl}`,
            );
          }

          const prefix = REST_PREFIXES.find(([p]) => reqUrl.startsWith(p));

          if (prefix) {
            const [pfx, base] = prefix;
            const method = req.method ?? "GET";
            if (method !== "GET" && method !== "POST") {
              res.writeHead(405, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ error: "method not allowed" }));
              return;
            }
            const chunks: Buffer[] = [];
            for await (const c of req) chunks.push(c as Buffer);
            const body = Buffer.concat(chunks);
            const target = `${base()}/${reqUrl.slice(pfx.length)}`;
            const upstream = await fetch(target, {
              method,
              headers:
                method === "POST"
                  ? { "Content-Type": "application/json" }
                  : undefined,
              body: method === "POST" && body.length ? body : undefined,
            });
            const text = await upstream.text();
            res.writeHead(upstream.status, {
              "Content-Type":
                upstream.headers.get("content-type") ?? "application/json",
            });
            res.end(text);
            return;
          }

          // ---- MCP door: session routing ----
          const sidHeader = req.headers["mcp-session-id"];
          const sid = Array.isArray(sidHeader) ? sidHeader[0] : sidHeader;

          if (sid && sessions.has(sid)) {
            await sessions.get(sid)!.handleRequest(req, res);
            return;
          }

          if (req.method === "POST") {
            // New session: expect an initialize request.
            const transport = new StreamableHTTPServerTransport({
              sessionIdGenerator: () => crypto.randomUUID(),
              onsessioninitialized: (id) => {
                sessions.set(id, transport);
              },
            });
            transport.onclose = () => {
              if (transport.sessionId) sessions.delete(transport.sessionId);
            };
            await buildServer().connect(transport);
            await transport.handleRequest(req, res);
            return;
          }

          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "unknown or missing mcp-session-id" }));
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : String(e);
          if (!res.headersSent) {
            res.writeHead(502, { "Content-Type": "application/json" });
          }
          res.end(JSON.stringify({ error: `gateway error: ${msg}` }));
        }
      });

      httpServer.listen(httpPort, bind, () => {
        console.error(
          `[planner-mcp] Streamable HTTP (MCP) + REST proxy (/router, /planner) listening on ${bind}:${httpPort}` +
            (authOn ? " [bearer auth ON]" : " [auth OFF]"),
        );
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error(
        `[planner-mcp] HTTP transport unavailable (${msg}). Falling back to stdio.`,
      );
      const transport = new StdioServerTransport();
      await buildServer().connect(transport);
    }
  } else {
    const transport = new StdioServerTransport();
    await buildServer().connect(transport);
    console.error("[planner-mcp] stdio transport ready");
  }
}

main().catch((e: unknown) => {
  const msg = e instanceof Error ? e.message : String(e);
  console.error(`[planner-mcp] fatal: ${msg}`);
  process.exit(1);
});
