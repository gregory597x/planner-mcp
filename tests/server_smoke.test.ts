// Smoke test: spawn the built server on stdio, run a real MCP handshake, and
// assert the advertised tool list. Requires `npm run build` first (CI does).

import { describe, expect, it } from "vitest";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const DIST = fileURLToPath(new URL("../dist/server.js", import.meta.url));

const EXPECTED_TOOLS = [
  "planner_health",
  "planner_ingest_task",
  "planner_list_tasks",
  "planner_current_work",
  "router_health",
  "router_align",
  "router_task_start",
  "router_task_status",
  "router_task_complete",
  "router_next",
];

function rpcLine(msg: object): string {
  return JSON.stringify(msg) + "\n";
}

describe("stdio transport", () => {
  it("initializes and lists all tools", async () => {
    expect(
      existsSync(DIST),
      "dist/server.js missing — run `npm run build` first",
    ).toBe(true);

    const child = spawn(process.execPath, [DIST], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    const reply = await new Promise<Record<string, unknown>>((resolve, reject) => {
      const timer = setTimeout(() => {
        child.kill();
        reject(new Error("timed out waiting for tools/list response"));
      }, 10_000);

      let buf = "";
      child.stdout.on("data", (chunk: Buffer) => {
        buf += chunk.toString();
        for (const line of buf.split("\n")) {
          if (!line.trim()) continue;
          try {
            const msg = JSON.parse(line);
            if (msg.id === 2) {
              clearTimeout(timer);
              child.kill();
              resolve(msg);
              return;
            }
          } catch {
            // partial line — keep buffering
          }
        }
      });
      child.on("error", (e) => {
        clearTimeout(timer);
        reject(e);
      });

      child.stdin.write(
        rpcLine({
          jsonrpc: "2.0",
          id: 1,
          method: "initialize",
          params: {
            protocolVersion: "2025-03-26",
            capabilities: {},
            clientInfo: { name: "vitest-smoke", version: "0.0.0" },
          },
        }),
      );
      child.stdin.write(rpcLine({ jsonrpc: "2.0", method: "notifications/initialized" }));
      child.stdin.write(rpcLine({ jsonrpc: "2.0", id: 2, method: "tools/list" }));
    });

    const result = reply.result as { tools: Array<{ name: string; inputSchema: unknown }> };
    const names = result.tools.map((t) => t.name);
    expect(names).toEqual(EXPECTED_TOOLS);
    for (const t of result.tools) expect(t.inputSchema).toBeTruthy();
  });
});
