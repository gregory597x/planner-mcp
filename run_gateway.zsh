#!/usr/bin/env zsh
# Gateway launcher — sources the key from .env, then runs the
# MCP + REST gateway on 127.0.0.1:8770. Expose it only over a private network.
set -euo pipefail
cd "$(dirname "$0")"
set -a; source ./.env; set +a
# NODE may be set in .env when node is not on PATH (e.g. under a service manager).
NODE="${NODE:-$(command -v node || true)}"
[[ -n "$NODE" && -x "$NODE" ]] || { echo "node not found: put it on PATH or set NODE in .env" >&2; exit 1; }
exec "$NODE" dist/server.js --http 8770
