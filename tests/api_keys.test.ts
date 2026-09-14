// Unit tests for the named-API-key module: header parsing, named-key match,
// disabled-key rejection, env fallback, and the mtime-based hot reload that
// makes revocation work without a service restart.

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

let api: typeof import("../src/api_keys.ts");
let dir: string;
let keysFile: string;

// KEYS_FILE is resolved from the environment at module load, so the env var
// must be set before the module is first imported — hence the dynamic import.
beforeAll(async () => {
  dir = mkdtempSync(join(tmpdir(), "planner-mcp-keys-"));
  keysFile = join(dir, "keys.json");
  process.env.MCP_PUBLIC_KEYS_FILE = keysFile;
  delete process.env.MCP_PUBLIC_API_KEY;
  api = await import("../src/api_keys.ts");
});

afterAll(() => {
  rmSync(dir, { recursive: true, force: true });
  delete process.env.MCP_PUBLIC_KEYS_FILE;
  delete process.env.MCP_PUBLIC_API_KEY;
});

// The reload cache keys on mtime, which can have coarse resolution — force a
// strictly increasing mtime on every write so each change is always noticed.
let tick = 0;
function writeKeysFile(content: string) {
  writeFileSync(keysFile, content);
  const t = new Date(Date.now() + ++tick * 2000);
  utimesSync(keysFile, t, t);
}

const bearer = (key: string) => ({ authorization: `Bearer ${key}` });

describe("with no keys file and no env key", () => {
  it("reports auth as unconfigured", () => {
    expect(api.authConfigured()).toBe(false);
  });

  it("authenticates nobody", () => {
    expect(api.authenticate(bearer("anything"))).toBeNull();
    expect(api.authenticate({})).toBeNull();
  });
});

describe("named keys in keys.json", () => {
  beforeAll(() => {
    writeKeysFile(
      JSON.stringify([
        { name: "alice", key: "alice-secret" },
        { name: "bob", key: "bob-secret", disabled: true },
      ]),
    );
  });

  it("reports auth as configured once the file exists", () => {
    expect(api.authConfigured()).toBe(true);
  });

  it("accepts an enabled key via Authorization: Bearer", () => {
    expect(api.authenticate(bearer("alice-secret"))).toBe("alice");
  });

  it("accepts an enabled key via x-api-key", () => {
    expect(api.authenticate({ "x-api-key": "alice-secret" })).toBe("alice");
  });

  it("rejects a disabled key", () => {
    expect(api.authenticate(bearer("bob-secret"))).toBeNull();
  });

  it("rejects an unknown key", () => {
    expect(api.authenticate(bearer("not-a-key"))).toBeNull();
  });

  it("rejects a missing or malformed credential", () => {
    expect(api.authenticate({})).toBeNull();
    expect(api.authenticate({ authorization: "alice-secret" })).toBeNull();
    expect(api.authenticate({ authorization: "Basic alice-secret" })).toBeNull();
  });
});

describe("hot reload (revocation without restart)", () => {
  it("picks up a revocation on the next call", () => {
    writeKeysFile(JSON.stringify([{ name: "carol", key: "carol-secret" }]));
    expect(api.authenticate(bearer("carol-secret"))).toBe("carol");

    writeKeysFile(
      JSON.stringify([{ name: "carol", key: "carol-secret", disabled: true }]),
    );
    expect(api.authenticate(bearer("carol-secret"))).toBeNull();
  });

  it("picks up a newly added key on the next call", () => {
    writeKeysFile(
      JSON.stringify([
        { name: "carol", key: "carol-secret", disabled: true },
        { name: "dave", key: "dave-secret" },
      ]),
    );
    expect(api.authenticate(bearer("dave-secret"))).toBe("dave");
  });

  it("keeps the last good key set when the file is corrupt", () => {
    writeKeysFile("this is not json {");
    // dave (from the last valid write) must still work; carol stays revoked.
    expect(api.authenticate(bearer("dave-secret"))).toBe("dave");
    expect(api.authenticate(bearer("carol-secret"))).toBeNull();
  });

  it("recovers when the file becomes valid again", () => {
    writeKeysFile(JSON.stringify([{ name: "erin", key: "erin-secret" }]));
    expect(api.authenticate(bearer("erin-secret"))).toBe("erin");
    expect(api.authenticate(bearer("dave-secret"))).toBeNull();
  });
});

describe("legacy env fallback", () => {
  beforeAll(() => {
    process.env.MCP_PUBLIC_API_KEY = "legacy-env-secret";
    writeKeysFile(JSON.stringify([{ name: "alice", key: "alice-secret" }]));
  });

  it('authenticates the env key under the name "env"', () => {
    expect(api.authenticate(bearer("legacy-env-secret"))).toBe("env");
  });

  it("named keys still authenticate under their own names", () => {
    expect(api.authenticate(bearer("alice-secret"))).toBe("alice");
  });
});
