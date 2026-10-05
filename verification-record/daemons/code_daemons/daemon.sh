#!/usr/bin/env bash
set -uo pipefail

# Run from a copy, so editing this file mid-run cannot corrupt the run, and copy
# the python helpers too (both bit us on 2026-09-21). The test is where this file
# lives, never an inherited variable: exporting one made child scripts delete the
# real files.
case "$0" in
  "${TMPDIR:-/tmp}"*) ;;
  *)
    _home="$(cd "$(dirname "$0")" && pwd)"
    _snap=$(mktemp "${TMPDIR:-/tmp}/$(basename "$0").XXXXXX") || exit 1
    cat "$0" > "$_snap" && chmod +x "$_snap" || exit 1
    _tools=$(mktemp -d "${TMPDIR:-/tmp}/code_daemons_tools.XXXXXX") || exit 1
    cp "$_home"/*.py "$_home"/*.js "$_tools/" 2>/dev/null
    CD_HOME="$_home" CD_TOOLS="$_tools" CD_TOOLS_OWNER="$$" exec "$_snap" "$@"
    ;;
esac

cd_cleanup() {
  case "$0" in "${TMPDIR:-/tmp}"*) rm -f "$0" ;; esac
  if [[ "${CD_TOOLS_OWNER:-}" == "$$" && -n "${CD_TOOLS:-}" ]]; then rm -rf "$CD_TOOLS"; fi
  return 0
}
trap cd_cleanup EXIT


if [[ "${CD_SNAPSHOT:-0}" != 1 ]]; then
  _snap=$(mktemp "${TMPDIR:-/tmp}/$(basename "$0").XXXXXX") || exit 1
  cat "$0" > "$_snap" && chmod +x "$_snap" || exit 1
  CD_SNAPSHOT=1 CD_HOME="$(cd "$(dirname "$0")" && pwd)" exec "$_snap" "$@"
fi
trap 'rm -f "$0"' EXIT

HERE=${CD_HOME:-$(cd "$(dirname "$0")" && pwd)}
REGISTRY="$HERE/registry.tsv"
LOG="$HERE/work/daemon.log"
PID_FILE="$HERE/work/daemon.pid"
HUB="http://127.0.0.1:8000"
DRY_RUN=${DRY_RUN:-0}

mkdir -p "$HERE/work"
say() { echo "[$(date '+%F %H:%M:%S')] $*" | tee -a "$LOG"; }

if [[ -f "$PID_FILE" ]] && ps -p "$(cat "$PID_FILE")" >/dev/null 2>&1; then
  echo "SUMMARY daemon: NOT STARTED - already running (PID $(cat "$PID_FILE"))"
  exit 0
fi
echo $$ > "$PID_FILE"
trap 'rm -f "$PID_FILE"; cd_cleanup' EXIT

[[ -f "$REGISTRY" ]] || { echo "SUMMARY daemon: nothing to do - the registry is empty"; exit 0; }

# Tell the hub, so a quiet daemon and a broken one look different in the record.
tell_hub() {
  local kind=$1 summary=$2 detail=$3
  curl -s --max-time 15 -X POST "$HUB/chats/checkpoint" -H 'content-type: application/json' \
    -d "$(python3 -c '
import json, sys
print(json.dumps({"chat_id": "code-daemon", "kind": sys.argv[1],
                  "summary": sys.argv[2], "detail": sys.argv[3]}))' "$kind" "$summary" "$detail")" \
    >/dev/null 2>&1
}

say "start"
checked=0; updated=0; failed=0; failures=""

while IFS=$'\t' read -r lib tag on commit files gates checked_on latest_old; do
  [[ "$lib" == "library" || -z "$lib" ]] && continue
  conf="$HERE/libraries/$lib.conf"
  [[ -f "$conf" ]] || { say "$lib: no recipe, skipped"; continue; }
  # shellcheck source=/dev/null
  . "$conf"
  checked=$((checked + 1))
  latest=$(git ls-remote --tags --refs "$UPSTREAM_URL" 2>/dev/null \
           | awk -F/ '{print $NF}' | grep -E "$TAG_PATTERN" | sort -V | tail -1)
  if [[ -z "$latest" ]]; then
    say "$lib: vendor unreachable, leaving at $tag"
    continue
  fi
  if [[ "$latest" == "$tag" ]]; then
    say "$lib: up to date at $tag"
    continue
  fi
  say "$lib: NEW RELEASE $latest (registry holds $tag)"
  if [[ "$DRY_RUN" == 1 ]]; then
    say "$lib: dry run, nothing done"
    continue
  fi

  # One group's failure never stops the others; each step's own summary is logged.
  step() {
    local what=$1; shift
    local out
    out=$("$@" 2>&1 | grep -E "^SUMMARY" | tail -1)
    say "$lib $latest: $what -> ${out:-no summary}"
    [[ "$out" == *": PASS"* || "$out" == *": OK"* || "$out" == *"NOTHING TO DO"* ]]
  }
  ok=1
  step "import"    "$HERE/import_upstream.sh" "$lib" "$latest" || ok=0
  if [[ "$ok" == 1 && "${FORMAT_ENABLED:-yes}" == "yes" ]]; then
    step "reference build" "$HERE/build_reference.sh" "$lib" "$latest" || ok=0
    [[ "$ok" == 1 ]] && { step "format" "$HERE/format_pass.sh" "$lib" "$latest" || ok=0; }
  fi
  [[ "$ok" == 1 ]] && { step "analyze" "$HERE/analyze_library.sh" "$lib" "$latest" || ok=0; }
  if [[ "$ok" == 1 && "${FORMAT_ENABLED:-yes}" == "yes" ]]; then
    step "registry" "$HERE/registry.sh" add "$lib" "$latest" || ok=0
  fi
  if [[ "$ok" == 1 ]]; then
    updated=$((updated + 1))
    tell_hub progress "code daemon: $lib updated to $latest" \
      "Imported, formatted and verified; chain 2 now holds $latest. Registry updated."
  else
    failed=$((failed + 1)); failures="$failures $lib:$latest"
    tell_hub blocker "code daemon: $lib $latest needs attention" \
      "A step did not pass; the release is not in chain 2. See $LOG and the library's work folder."
  fi
done < "$REGISTRY"

# Re-analysis pass: the extractor keeps improving (streaming syntax trees,
# header preambles), so a group's YAML can be older than the tool that made it.
# One group per run, oldest first, so a night never runs away with itself.
reanalyzed=0
limit=${ANALYZE_PER_RUN:-1}
stale_list=""
for conf in "$HERE"/libraries/*.conf; do
  lib=$(basename "$conf" .conf)
  # shellcheck source=/dev/null
  ( . "$conf" ) || continue
  . "$conf"
  up="$CHAINS_ROOT/$lib/upstream"
  [[ -d "$up/.git" ]] || continue
  tag=$(git -C "$up" tag | sort -V | tail -1)
  [[ -n "$tag" ]] || continue
  yaml="$HERE/work/$lib/$tag/yaml"
  if [[ ! -d "$yaml" ]]; then
    stale_list="$stale_list $lib:$tag:0"
  elif [[ "$HERE/code_to_yaml.py" -nt "$yaml" || "$conf" -nt "$yaml" ]]; then
    stale_list="$stale_list $lib:$tag:$(stat -f %m "$yaml")"
  fi
done
for entry in $(echo "$stale_list" | tr ' ' '\n' | grep -v '^$' | sort -t: -k3 -n); do
  [[ "$reanalyzed" -lt "$limit" ]] || { say "more groups need re-analysis; next run takes them"; break; }
  lib=${entry%%:*}; rest=${entry#*:}; tag=${rest%%:*}
  if [[ "$DRY_RUN" == 1 ]]; then
    say "$lib $tag: analysis is older than the extractor (dry run)"
    reanalyzed=$((reanalyzed + 1))
    continue
  fi
  say "$lib $tag: re-analysing, its YAML predates the current extractor"
  out=$("$HERE/analyze_library.sh" "$lib" "$tag" 2>&1 | grep -E "^SUMMARY" | tail -1)
  say "$lib $tag: analyze -> ${out:-no summary}"
  case "$out" in
    *": PASS"*) reanalyzed=$((reanalyzed + 1)) ;;
    *) failed=$((failed + 1)); failures="$failures $lib:$tag(analysis)"
       tell_hub blocker "code daemon: analysis of $lib $tag needs attention" "${out:-no summary}" ;;
  esac
done

"$HERE/registry.sh" check >/dev/null 2>&1
summary="SUMMARY daemon: checked $checked | updated $updated | re-analysed $reanalyzed | needing attention $failed${failures:+ ($failures )}"
say "$summary"
[[ "$failed" == 0 ]] || tell_hub blocker "code daemon: $failed code group(s) need attention" "$summary"
echo "$summary"
