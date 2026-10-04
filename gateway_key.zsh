#!/usr/bin/env zsh
# gateway_key.zsh — manage named API keys for the HTTP gateway.
#
#   ./gateway_key.zsh add <name>       generate a key, add it, print it once
#   ./gateway_key.zsh revoke <name>    mark a key disabled (401 immediately)
#   ./gateway_key.zsh enable <name>    re-enable a revoked key
#   ./gateway_key.zsh remove <name>    delete the entry entirely
#   ./gateway_key.zsh list             show names + status (never key values)
#
# The gateway re-reads keys.json on mtime change — no restart needed.
set -euo pipefail
cd "$(dirname "$0")"
KEYS_FILE="keys.json"

cmd="${1:-}" name="${2:-}"

[[ -f "$KEYS_FILE" ]] || { print -r -- "[]" > "$KEYS_FILE"; chmod 600 "$KEYS_FILE"; }

edit_json() {  # $1 = node expression operating on `keys`; prints new JSON
  /opt/homebrew/bin/node -e '
    const fs = require("fs");
    const keys = JSON.parse(fs.readFileSync("'"$KEYS_FILE"'", "utf8"));
    const name = process.argv[1], newKey = process.argv[2] ?? "";
    '"$1"'
    fs.writeFileSync("'"$KEYS_FILE"'", JSON.stringify(keys, null, 2) + "\n");
  ' "$name" "${3:-}"
  chmod 600 "$KEYS_FILE"
}

case "$cmd" in
  add)
    [[ -n "$name" ]] || { echo "usage: $0 add <name>" >&2; exit 1 }
    secret="$(openssl rand -base64 32 | tr -d '\n')"
    edit_json '
      if (keys.some(k => k.name === name)) { console.error(`key "${name}" already exists — revoke/remove it first`); process.exit(1); }
      keys.push({ name, key: newKey });
    ' "$name" "$secret"
    echo "Added key '$name'. Give this to them ONCE (it is not shown again):"
    echo "$secret"
    ;;
  revoke)
    [[ -n "$name" ]] || { echo "usage: $0 revoke <name>" >&2; exit 1 }
    edit_json '
      const k = keys.find(k => k.name === name);
      if (!k) { console.error(`no key named "${name}"`); process.exit(1); }
      k.disabled = true;
    '
    echo "Revoked '$name' (entry kept; use enable to restore, remove to delete)."
    ;;
  enable)
    [[ -n "$name" ]] || { echo "usage: $0 enable <name>" >&2; exit 1 }
    edit_json '
      const k = keys.find(k => k.name === name);
      if (!k) { console.error(`no key named "${name}"`); process.exit(1); }
      delete k.disabled;
    '
    echo "Enabled '$name'."
    ;;
  remove)
    [[ -n "$name" ]] || { echo "usage: $0 remove <name>" >&2; exit 1 }
    edit_json '
      const i = keys.findIndex(k => k.name === name);
      if (i === -1) { console.error(`no key named "${name}"`); process.exit(1); }
      keys.splice(i, 1);
    '
    echo "Removed '$name'."
    ;;
  list)
    /opt/homebrew/bin/node -e '
      const keys = JSON.parse(require("fs").readFileSync("'"$KEYS_FILE"'", "utf8"));
      if (!keys.length) console.log("(no named keys)");
      for (const k of keys) console.log(`${k.name}\t${k.disabled ? "REVOKED" : "active"}`);
    '
    ;;
  *)
    echo "usage: $0 {add|revoke|enable|remove|list} [name]" >&2
    exit 1
    ;;
esac
