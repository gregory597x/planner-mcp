// Thin HTTP client around the admin_router daemon.
//
// The daemon is at http://localhost:8765 by default; override with
// ADMIN_ROUTER_BASE_URL. All calls are stateless — the daemon tracks its own
// state in its own database; this is just a wire client.
//
// Every method returns { ok, status, body } so tool handlers can format
// consistent responses without swallowing errors.

const DEFAULT_BASE = "http://localhost:8765";

export interface RouterResponse<T = unknown> {
  ok: boolean;
  status: number;
  body: T;
}

function baseUrl(): string {
  return process.env.ADMIN_ROUTER_BASE_URL ?? DEFAULT_BASE;
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

export async function routerHealth(): Promise<RouterResponse<unknown>> {
  const res = await fetch(`${baseUrl()}/health`);
  return { ok: res.ok, status: res.status, body: await readJson(res) };
}

export async function routerAlign(
  q: string,
  top_k?: number,
): Promise<RouterResponse<unknown>> {
  const url = new URL(`${baseUrl()}/align`);
  url.searchParams.set("q", q);
  if (top_k !== undefined) url.searchParams.set("top_k", String(top_k));
  const res = await fetch(url);
  return { ok: res.ok, status: res.status, body: await readJson(res) };
}

export interface TaskStartPayload {
  task_name: string;
  task_description: string;
  chat_id?: string;
  account?: string;
  project_hint?: string;
  planner_task_id?: number;
}

export async function routerTaskStart(
  payload: TaskStartPayload,
): Promise<RouterResponse<unknown>> {
  const res = await fetch(`${baseUrl()}/tasks/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return { ok: res.ok, status: res.status, body: await readJson(res) };
}

export interface TaskStatusPayload {
  status: "in_progress" | "blocked" | "complete";
  blocked_by?: string;
  note?: string;
}

export async function routerTaskStatus(
  taskId: number,
  payload: TaskStatusPayload,
): Promise<RouterResponse<unknown>> {
  const res = await fetch(`${baseUrl()}/tasks/${taskId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return { ok: res.ok, status: res.status, body: await readJson(res) };
}

export interface OutputItem {
  kind: string;
  value: string;
}

export async function routerTaskComplete(
  taskId: number,
  summary: string,
  outputs?: OutputItem[],
): Promise<RouterResponse<unknown>> {
  const res = await fetch(`${baseUrl()}/tasks/${taskId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ summary, outputs: outputs ?? [] }),
  });
  return { ok: res.ok, status: res.status, body: await readJson(res) };
}

export async function routerNext(): Promise<RouterResponse<unknown>> {
  const res = await fetch(`${baseUrl()}/next`);
  return { ok: res.ok, status: res.status, body: await readJson(res) };
}
