#!/usr/bin/env zsh
# Gateway launcher — sources the key from .env, then runs the
# MCP + REST gateway on 127.0.0.1:8770. Expose it only over a private network.
set -euo pipefail
cd "$(dirname "$0")"
set -a; source ./.env; set +a
exec /opt/homebrew/bin/node dist/server.js --http 8770
