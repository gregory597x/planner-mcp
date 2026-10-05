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




usage() {
  echo "usage: verify_format.sh <library> <tag> check <relpath> <candidate-file>" >&2
  echo "       verify_format.sh <library> <tag> final" >&2
  echo "       verify_format.sh <library> <tag> recheck   re-verify what chain 2 already holds" >&2
  echo "       verify_format.sh <library> <tag> selftest" >&2
  exit 2
}
[[ $# -ge 3 ]] || usage
LIB=$1
TAG=$2
CMD=$3

HERE=${CD_HOME:-$(cd "$(dirname "$0")" && pwd)}
WORK="$HERE/work/$LIB/$TAG"
SRC="$WORK/src"
REF="$WORK/reference"
CAND="$WORK/cand"
CSRC="$CAND/src"
CBUILD="$CAND/build"
PREV="$CAND/.prev"
LOG="$WORK/verify.log"
RESULTS="$WORK/verify_results.tsv"
PID_FILE="$WORK/verify.pid"
TOKCMP="$HERE/token_compare.py"

say()  { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }
summary() { echo "SUMMARY verify $LIB $TAG $CMD: $*" | tee -a "$LOG"; }
fail() { summary "FAILED - $*"; exit 1; }

CONF="$HERE/libraries/$LIB.conf"
if [[ ! -f "$CONF" ]]; then
  echo "SUMMARY $LIB $TAG: FAILED - no recipe at $CONF"
  exit 1
fi
# shellcheck source=/dev/null
. "$CONF"
: "${LIB_ARGS[@]}" "${CHAINS_ROOT:?CHAINS_ROOT missing in $CONF}" "${HAS_TESTS:=no}"

[[ -f "$REF/objects.sha256" && -d "$SRC" ]] \
  || { echo "SUMMARY verify $LIB $TAG: FAILED - no reference; run build_reference.sh $LIB $TAG first"; exit 1; }
[[ -f "$TOKCMP" ]] || { echo "SUMMARY verify $LIB $TAG: FAILED - missing $TOKCMP"; exit 1; }

if [[ -f "$PID_FILE" ]] && ps -p "$(cat "$PID_FILE")" >/dev/null 2>&1; then
  echo "SUMMARY verify $LIB $TAG: NOT STARTED - another verify_format.sh is running (PID $(cat "$PID_FILE"))"
  exit 0
fi
echo $$ > "$PID_FILE"
trap 'rm -f "$PID_FILE"; cd_cleanup' EXIT
say "---- $CMD ${*:4}"

configure_cand() {
  local map="-g0 -ffile-prefix-map=$CSRC=/lib-src -ffile-prefix-map=$CBUILD=/lib-build"
  cmake -S "$CSRC${SRC_SUBDIR:+/$SRC_SUBDIR}" -B "$CBUILD" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_FLAGS="$map" \
    -DCMAKE_CXX_FLAGS="$map" \
    -DCMAKE_OBJC_FLAGS="$map" \
    -DCMAKE_OBJCXX_FLAGS="$map" \
    -DFETCHCONTENT_QUIET=ON \
    "${LIB_ARGS[@]}" >>"$LOG" 2>&1
}

build_cand() { cmake --build "$CBUILD" >>"$LOG" 2>&1; }

gate_b() {
  (cd "$CBUILD" && xargs shasum -a 256 < "$REF/objects.list") > "$WORK/cand.sha256" 2>>"$LOG"
  diff "$REF/objects.sha256" "$WORK/cand.sha256" | grep '^<' | awk '{print $3}' > "$WORK/gate_b_mismatch.list"
  if [[ -s "$REF/not_reproducible.list" ]]; then
    grep -vxF -f "$REF/not_reproducible.list" "$WORK/gate_b_mismatch.list" > "$WORK/gate_b_mismatch.tmp"
    mv "$WORK/gate_b_mismatch.tmp" "$WORK/gate_b_mismatch.list"
  fi
  wc -l < "$WORK/gate_b_mismatch.list" | tr -d ' '
}

explain_mismatches() {
  local obj src unexplained=0
  : > "$WORK/gate_b_explained.list"
  : > "$WORK/gate_b_unexplained.list"
  while IFS= read -r obj; do
    src=$(echo "${obj#./}" | sed 's|CMakeFiles/[^/]*\.dir/||; s|\.o$||')
    if [[ -f "$SRC/$src" && -f "$CSRC/$src" ]] \
       && python3 "$TOKCMP" "$SRC/$src" "$CSRC/$src" "$src" >/dev/null 2>&1 \
       && grep -qE '__LINE__|assert\(|TEST_CASE|SECTION|REQUIRE|CHECK|STATIC_CHECK' "$CSRC/$src"; then
      printf '%s\t%s\n' "$obj" "$src" >> "$WORK/gate_b_explained.list"
    else
      printf '%s\t%s\n' "$obj" "${src:-unknown}" >> "$WORK/gate_b_unexplained.list"
      unexplained=$((unexplained + 1))
    fi
  done < "$WORK/gate_b_mismatch.list"
  echo "$unexplained"
}

ensure_cand() {
  if [[ ! -d "$CSRC" ]]; then
    say "creating candidate tree from $SRC"
    mkdir -p "$CAND"
    cp -Rp "$SRC" "$CSRC" || return 1
    configure_cand || { say "configure failed"; return 1; }
  fi
  build_cand || { say "candidate build failed"; return 1; }
  local m u
  m=$(gate_b)
  if [[ "$m" != 0 ]]; then
    u=$(explain_mismatches)
    if [[ "$u" != 0 ]]; then
      say "candidate tree differs from the reference in $m objects before any check, $u of them unexplained"
      return 1
    fi
    say "candidate tree: $m objects differ, all explained by line-number macros"
  fi
}

place() {
  local rel=$1 file=$2
  mkdir -p "$(dirname "$PREV/$rel")"
  cp "$CSRC/$rel" "$PREV/$rel" || return 1
  cp "$file" "$CSRC/$rel"
}

revert() {
  local rel=$1 m
  cp "$PREV/$rel" "$CSRC/$rel" || return 1
  build_cand || return 1
  m=$(gate_b)
  [[ "$m" == 0 ]] && return 0
  [[ "$(explain_mismatches)" == 0 ]]
}

record() { printf '%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$1" "$2" "$3" >> "$RESULTS"; }

cmd_check() {
  local rel=$1 file=$2 a ra m
  [[ -f "$SRC/$rel" ]] || fail "$rel is not a file in $LIB $TAG"
  [[ -f "$file" ]] || fail "candidate $file not found"
  ensure_cand || fail "candidate tree not ready (see $LOG)"
  a=$(python3 "$TOKCMP" "$SRC/$rel" "$file" "$rel"); ra=$?
  [[ "$ra" -ne 2 ]] || fail "gate A could not read $rel: $a"
  if [[ "$ra" -eq 1 ]]; then
    record "$rel" FAIL "gate A: $a"
    summary "FAIL $rel - gate A: $a"
    exit 1
  fi
  place "$rel" "$file" || fail "could not place $rel"
  if ! build_cand; then
    revert "$rel" || fail "REVERT FAILED for $rel; candidate tree needs attention"
    record "$rel" FAIL "does not compile"
    summary "FAIL $rel - does not compile"
    exit 1
  fi
  m=$(gate_b)
  local u=0 note="0 differ"
  if [[ "$m" != 0 ]]; then
    u=$(explain_mismatches)
    cp "$WORK/gate_b_mismatch.list" "$WORK/last_mismatch.list"
    if [[ "$u" != 0 ]]; then
      revert "$rel" || fail "REVERT FAILED for $rel; candidate tree needs attention"
      record "$rel" FAIL "gate B: $u of $m differing objects unexplained"
      summary "FAIL $rel - gate B: $u of $m differing objects unexplained ($(cut -f1 "$WORK/gate_b_unexplained.list" | head -3 | paste -sd' ' -))"
      exit 1
    fi
    note="$m differ, all explained by line-number macros ($(cut -f2 "$WORK/gate_b_explained.list" | head -2 | paste -sd' ' -))"
  fi
  record "$rel" PASS "gate A: $a; gate B: $note"
  summary "PASS $rel - gate A: $a; gate B: $note"
}

cmd_recheck() {
  # Re-verify a release that chain 2 already holds, against a fresh reference.
  # Used when a recipe improves (better build options) after the commit was made;
  # chain 2 is never rewritten.
  local formatted="$CHAINS_ROOT/$LIB/formatted"
  git -C "$formatted" rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1 \
    || fail "chain 2 has no tag $TAG to recheck"
  rm -rf "$CAND"
  mkdir -p "$CSRC"
  git -C "$formatted" archive "$TAG" | tar -x -C "$CSRC" || fail "could not lay out $TAG from chain 2"
  configure_cand || fail "configure (see $LOG)"
  cmd_final
}

cmd_final() {
  local m line
  ensure_cand || fail "candidate tree does not match the reference (see $LOG)"
  local tr=0
  if [[ "$HAS_TESTS" == "no" ]]; then
    line="no test suite; the recipe says so, so gates A and B stand alone"
    : > "$WORK/cand_ctest.log"
  elif [[ -n "${TEST_CMD:-}" ]]; then
    ( cd "$CBUILD" && eval "$TEST_CMD" ) > "$WORK/cand_ctest.log" 2>&1
    tr=$?
    line="recipe TEST_CMD passed: $TEST_CMD"
    [[ "$tr" -eq 0 ]] || fail "gate C: recipe TEST_CMD failed ($TEST_CMD); see $WORK/cand_ctest.log"
  else
    ctest --test-dir "$CBUILD" --output-on-failure > "$WORK/cand_ctest.log" 2>&1
    tr=$?
    line=$(grep -E "tests passed" "$WORK/cand_ctest.log" | tail -1)
    [[ "$tr" -eq 0 && -n "$line" ]] || fail "gate C: tests not clean (${line:-no test summary})"
  fi
  cat "$WORK/cand_ctest.log" >> "$LOG"
  local total m
  total=$(wc -l < "$REF/objects.list" | tr -d ' ')
  m=$(wc -l < "$WORK/gate_b_mismatch.list" | tr -d ' ')
  local bnote="0 of $total objects differ"
  [[ "$m" == 0 ]] || bnote="$m of $total objects differ, all explained by line-number macros"
  summary "PASS - gate B: $bnote; gate C: $line"
}

run_case() {
  local name=$1 rel=$2 file=$3 expect=$4 a ra m got
  a=$(python3 "$TOKCMP" "$SRC/$rel" "$file" "$rel"); ra=$?
  place "$rel" "$file" || fail "selftest could not place $rel"
  if build_cand; then m=$(gate_b); else m="build-failed"; fi
  revert "$rel" || fail "selftest REVERT FAILED for $rel; candidate tree needs attention"
  if [[ "$ra" -eq 0 && "$m" == 0 ]]; then got=pass; else got=fail; fi
  local verdict="as expected"
  if [[ "$expect" == pass && "$got" != pass ]]; then verdict=UNEXPECTED; fi
  if [[ "$expect" == fail-both && ( "$ra" -ne 1 || "$m" == 0 ) ]]; then verdict=UNEXPECTED; fi
  if [[ "$expect" == info ]]; then verdict="information only"; fi
  echo "  $name: gate A: $a | gate B: $m objects differ | expected $expect -> $verdict" | tee -a "$LOG"
  [[ "$verdict" != UNEXPECTED ]]
}

cmd_selftest() {
  local T="$WORK/selftest" target header ok=0 bad=0 fmt
  ensure_cand || fail "candidate tree not ready (see $LOG)"
  diff -rq "$SRC" "$CSRC" >/dev/null 2>&1 || fail "candidate tree already holds formatted files; self-test needs a pristine tree"
  target=$(cd "$SRC" && grep -rlE 'if \(.* < ' src/SFML --include='*.cpp' | LC_ALL=C sort | head -1)
  header=$(cd "$SRC" && ls include/SFML/System/*.hpp | LC_ALL=C sort | head -1)
  [[ -n "$target" && -n "$header" ]] || fail "could not choose self-test files"
  rm -rf "$T"; mkdir -p "$T"
  python3 - "$SRC/$target" "$SRC/$header" "$T" <<'PY' || fail "could not make self-test variants"
import re, sys, pathlib
target, header, out = map(pathlib.Path, sys.argv[1:4])
def reindent(src):
    lines = src.read_text().split("\n")
    return "\n" + "\n".join(re.match(r"[ \t]*", l).group(0) * 2 + l.lstrip(" \t") for l in lines)
t = target.read_text()
(out / "t1_whitespace").write_text(reindent(target))
(out / "t2_comments").write_text("// verifier self-test comment\n" + t + "\n/* verifier self-test block comment */\n")
lines = t.split("\n")
for i, l in enumerate(lines):
    if re.search(r"if \(.* < ", l):
        lines[i] = l.replace(" < ", " <= ", 1)
        break
(out / "t3_mutation").write_text("\n".join(lines))
(out / "t4_header_whitespace").write_text(reindent(header))
PY
  cmp -s "$SRC/$target" "$T/t3_mutation" && fail "mutation did not change $target"
  echo "  target file: $target | header: $header" | tee -a "$LOG"
  run_case "1 whitespace + new line numbers" "$target" "$T/t1_whitespace" pass && ok=$((ok+1)) || bad=$((bad+1))
  run_case "2 comments only" "$target" "$T/t2_comments" pass && ok=$((ok+1)) || bad=$((bad+1))
  run_case "3 one real change (< to <=)" "$target" "$T/t3_mutation" fail-both && ok=$((ok+1)) || bad=$((bad+1))
  run_case "4 header whitespace" "$header" "$T/t4_header_whitespace" pass && ok=$((ok+1)) || bad=$((bad+1))
  fmt="$T/t5_clang_format"
  clang-format --style="file:$HERE/.clang-format" "$SRC/$target" > "$fmt" 2>>"$LOG" \
    && run_case "5 your .clang-format on the target" "$target" "$fmt" info >/dev/null
  tail -1 "$LOG" | sed 's/^/ /'
  diff -rq "$SRC" "$CSRC" >/dev/null 2>&1 || fail "candidate tree was not restored after the self-test"
  [[ "$(gate_b)" == 0 ]] || fail "candidate tree no longer matches the reference after the self-test"
  if [[ "$bad" -eq 0 ]]; then
    summary "PASS $ok/4 as expected | tree restored and matches reference"
  else
    summary "FAIL $bad of 4 not as expected | tree restored"
    exit 1
  fi
}

case "$CMD" in
  check)    [[ $# -eq 5 ]] || usage; cmd_check "$4" "$5" ;;
  final)    cmd_final ;;
  recheck)  cmd_recheck ;;
  selftest) cmd_selftest ;;
  *)        usage ;;
esac
