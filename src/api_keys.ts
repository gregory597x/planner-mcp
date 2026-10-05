// api_keys — named API keys for the HTTP gateway.
//
// Keys live in keys.json (chmod 600) next to package.json:
//   [ { "name": "alice", "key": "<secret>", "disabled": true? }, ... ]
// MCP_PUBLIC_API_KEY remains accepted as a fallback under the name "env".
// The file is re-read whenever its mtime changes, so adding or revoking a
// key takes effect without a service restart. Manage it with gateway_key.zsh.

import { createHash, timingSafeEqual } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export interface KeyEntry {
  name: string;
  key: string;
  disabled?: boolean;
}

const KEYS_FILE =
  process.env.MCP_PUBLIC_KEYS_FILE ??
  join(dirname(dirname(fileURLToPath(import.meta.url))), "keys.json");

let cachedMtimeMs = -1;
let cachedKeys: KeyEntry[] = [];

function fileKeys(): KeyEntry[] {
  let mtimeMs: number;
  try {
    mtimeMs = statSync(KEYS_FILE).mtimeMs;
  } catch {
    // No keys file — env fallback only.
    cachedMtimeMs = -1;
    return (cachedKeys = []);
  }
  if (mtimeMs === cachedMtimeMs) return cachedKeys;

  try {
    const parsed = JSON.parse(readFileSync(KEYS_FILE, "utf8"));
    if (!Array.isArray(parsed)) throw new Error("keys.json must be a JSON array");
    cachedKeys = parsed.filter(
      (e): e is KeyEntry =>
        typeof e?.name === "string" && typeof e?.key === "string" && e.key.length > 0,
    );
    cachedMtimeMs = mtimeMs;
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    // Keep the last good key set rather than locking everyone out.
    console.error(`[planner-mcp] keys.json unreadable (${msg}) — keeping previous key set`);
  }
  return cachedKeys;
}

function equal(a: string, b: string): boolean {
  // Hash both sides so timingSafeEqual gets equal-length buffers.
  return timingSafeEqual(
    createHash("sha256").update(a).digest(),
    createHash("sha256").update(b).digest(),
  );
}

/** True when at least one credential source exists (auth should be enforced). */
export function authConfigured(): boolean {
  if (process.env.MCP_PUBLIC_API_KEY) return true;
  try {
    statSync(KEYS_FILE);
    return true;
  } catch {
    return false;
  }
}

/**
 * Match a presented bearer key against enabled named keys plus the env
 * fallback. Returns the key's name on success, null on failure.
 */
export function authenticate(headers: Record<string, unknown>): string | null {
  const auth = headers["authorization"];
  const bearer =
    typeof auth === "string" && auth.startsWith("Bearer ") ? auth.slice(7) : undefined;
  const xkey = headers["x-api-key"];
  const presented = bearer ?? (typeof xkey === "string" ? xkey : undefined);
  if (!presented) return null;

  let matched: string | null = null;
  for (const entry of fileKeys()) {
    // Compare every entry (no early exit) to keep timing uniform.
    if (equal(presented, entry.key) && !entry.disabled && matched === null) {
      matched = entry.name;
    }
  }
  const envKey = process.env.MCP_PUBLIC_API_KEY;
  if (envKey && equal(presented, envKey) && matched === null) matched = "env";
  return matched;
}

export function keysFilePath(): string {
  return KEYS_FILE;
}
