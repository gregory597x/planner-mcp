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

/* ===================== TOOL SCHEMAS (zod) ===================== */

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
];

/* ===================== SERVER SETUP ===================== */

const server = new Server(
  { name: "planner-mcp", version: "0.1.0" },
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

/* ===================== TRANSPORT (stdio, optional HTTP) ===================== */

async function main() {
  const httpFlagIdx = process.argv.indexOf("--http");
  const useHttp = httpFlagIdx !== -1;
  const httpPort = useHttp
    ? Number(process.argv[httpFlagIdx + 1] ?? 8765)
    : undefined;

  if (useHttp && httpPort && !Number.isNaN(httpPort)) {
    // Lazy-load the HTTP transport so the stdio-only path stays lean.
    try {
      const { StreamableHTTPServerTransport } = await import(
        "@modelcontextprotocol/sdk/server/streamableHttp.js"
      );
      const http = await import("node:http");
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => crypto.randomUUID(),
      });
      const httpServer = http.createServer(async (req, res) => {
        await transport.handleRequest(req, res);
      });
      const bind = process.env.PLANNER_MCP_BIND ?? "127.0.0.1";
      httpServer.listen(httpPort, bind, () => {
        console.error(
          `[planner-mcp] Streamable HTTP transport listening on ${bind}:${httpPort}`,
        );
      });
      await server.connect(transport);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error(
        `[planner-mcp] HTTP transport unavailable (${msg}). Falling back to stdio.`,
      );
      const transport = new StdioServerTransport();
      await server.connect(transport);
    }
  } else {
    const transport = new StdioServerTransport();
    await server.connect(transport);
    console.error("[planner-mcp] stdio transport ready");
  }
}

main().catch((e: unknown) => {
  const msg = e instanceof Error ? e.message : String(e);
  console.error(`[planner-mcp] fatal: ${msg}`);
  process.exit(1);
});
