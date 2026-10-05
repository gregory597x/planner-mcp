#!/usr/bin/env bash
set -uo pipefail

# Run from a copy, so editing this file mid-run cannot corrupt the run, and copy
# the python helpers too. The test is where this file lives, never an inherited
# variable: exporting one made child scripts delete the real files (2026-09-21).
case "$0" in
  "${TMPDIR:-/tmp}"*) ;;
  *)
    _home="$(cd "$(dirname "$0")" && pwd)"
    _snap=$(mktemp "${TMPDIR:-/tmp}/$(basename "$0").XXXXXX") || exit 1
    cat "$0" > "$_snap" && chmod +x "$_snap" || exit 1
    _tools=$(mktemp -d "${TMPDIR:-/tmp}/coordinator_tools.XXXXXX") || exit 1
    cp "$_home"/*.py "$_tools/" 2>/dev/null
    CD_HOME="$_home" CD_TOOLS="$_tools" CD_TOOLS_OWNER="$$" exec "$_snap" "$@"
    ;;
esac

cd_cleanup() {
  case "$0" in "${TMPDIR:-/tmp}"*) rm -f "$0" ;; esac
  if [[ "${CD_TOOLS_OWNER:-}" == "$$" && -n "${CD_TOOLS:-}" ]]; then rm -rf "$CD_TOOLS"; fi
  return 0
}
trap cd_cleanup EXIT

HERE=${CD_HOME:-$(cd "$(dirname "$0")" && pwd)}
TOOLS=${CD_TOOLS:-$HERE}
LOG="$HERE/work/role-coordinator.log"
PID_FILE="$HERE/work/role-coordinator.pid"
mkdir -p "$HERE/work"

say() { echo "[$(date '+%F %H:%M:%S')] $*" | tee -a "$LOG"; }

if [[ -f "$PID_FILE" ]] && ps -p "$(cat "$PID_FILE")" >/dev/null 2>&1; then
  echo "SUMMARY role-coordinator: NOT STARTED - already running (PID $(cat "$PID_FILE"))"
  exit 0
fi
echo $$ > "$PID_FILE"
trap 'rm -f "$PID_FILE"; cd_cleanup' EXIT

# Pick an interpreter that carries PyYAML, because the role loader refuses to
# write without the cross-check it enables. Falling back is allowed and said
# out loud; silently loading uncross-checked charters is not.
PY=""
for cand in /usr/bin/python3 python3 /opt/homebrew/bin/python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import yaml" >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
if [[ -z "$PY" ]]; then
  PY=$(command -v python3) || { echo "SUMMARY role-coordinator: FAILED - no python3"; exit 1; }
  say "no interpreter here has PyYAML; charters will not be loaded this run"
  SKIP_ROLES=1
fi

# Postgres lives in Docker; without it there is nothing to read and nothing to
# write, and guessing is worse than stopping.
if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "<PG-CONTAINER>"; then
  echo "SUMMARY role-coordinator: FAILED - postgres container is not running"
  exit 1
fi

say "start ($PY)"

if [[ "${SKIP_ROLES:-0}" != 1 ]]; then
  # ${VAR-default}, not ${VAR:-default}: ROLES_ARGS="" must mean "dry run",
  # not "fall back to --apply".
  roles=$("$PY" "$TOOLS/roles_load.py" ${ROLES_ARGS---apply} 2>&1 | grep -E "^SUMMARY" | tail -1)
  say "roles -> ${roles:-no summary}"
fi

out=$("$PY" "$TOOLS/role-coordinator.py" 2>&1 | tee -a "$LOG" | grep -E "^SUMMARY" | tail -1)
say "${out:-SUMMARY role-coordinator: FAILED - no summary (see $LOG)}"
echo "${out:-SUMMARY role-coordinator: FAILED - no summary (see $LOG)}"
