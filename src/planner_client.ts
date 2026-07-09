// Thin HTTP client around a self-hosted Planner backend that speaks
// JSON over HTTP. The Planner is at http://localhost:8000 by default;
// override with PLANNER_BASE_URL. All calls are stateless — the Planner
// tracks its own state, this is just a wire client.
//
// Every method returns { ok, status, body } so tool handlers can format
// consistent responses to the MCP client without swallowing errors.

const DEFAULT_BASE = "http://localhost:8000";
const CURRENT_WORK_PATH =
  process.env.PLANNER_CURRENT_WORK_PATH ??
  `${process.env.HOME ?? ""}/planner_exports/current_work.md`;

export interface PlannerResponse<T = unknown> {
  ok: boolean;
  status: number;
  body: T;
}

function baseUrl(): string {
  return process.env.PLANNER_BASE_URL ?? DEFAULT_BASE;
}

async function readJson<T>(res: Response): Promise<T | string> {
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) {
    try {
      return (await res.json()) as T;
    } catch {
      return await res.text();
    }
  }
  return await res.text();
}

export async function health(): Promise<PlannerResponse<string>> {
  const res = await fetch(`${baseUrl()}/health`);
  return { ok: res.ok, status: res.status, body: await res.text() };
}

export interface IngestPayload {
  title: string;
  assigned_to: string;
  date: string;               // YYYY-MM-DD
  due_time?: string;          // HH:MM
  priority?: number;          // 1..5
  category?: string;
  source: string;
  external_id?: string;
  deduplication_key?: string;
  task_type?: "TASK" | "EVENT" | "NOTE";
}

export interface IngestResult {
  uuid: string;
  action: "created" | "updated";
}

export async function ingestTask(
  payload: IngestPayload,
): Promise<PlannerResponse<IngestResult | string>> {
  const res = await fetch(`${baseUrl()}/api/inbox/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await readJson<IngestResult>(res);
  return { ok: res.ok, status: res.status, body };
}

export interface ListTasksQuery {
  from: string;   // YYYY-MM-DD
  to: string;     // YYYY-MM-DD
}

export async function listTasks(
  q: ListTasksQuery,
): Promise<PlannerResponse<unknown>> {
  const url = new URL(`${baseUrl()}/tasks`);
  url.searchParams.set("from", q.from);
  url.searchParams.set("to", q.to);
  const res = await fetch(url);
  const body = await readJson(res);
  return { ok: res.ok, status: res.status, body };
}

// Reads a "current work" projection directly off the filesystem. This is
// typically written by a separate scheduler/daemon (see the Planner
// deployment's own docs) that produces a WSJF- or priority-ordered summary
// of what to work on next. This tool bypasses HTTP entirely.
export async function readCurrentWork(): Promise<PlannerResponse<string>> {
  const { readFile, stat } = await import("node:fs/promises");
  try {
    const stats = await stat(CURRENT_WORK_PATH);
    const content = await readFile(CURRENT_WORK_PATH, "utf8");
    return {
      ok: true,
      status: 200,
      body: `# current_work.md (mtime ${stats.mtime.toISOString()})\n\n${content}`,
    };
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return {
      ok: false,
      status: 404,
      body: `current_work.md not found at ${CURRENT_WORK_PATH}. Is the projection scheduler running? Override the path with PLANNER_CURRENT_WORK_PATH. (${msg})`,
    };
  }
}
