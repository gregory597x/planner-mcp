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




usage() { echo "usage: build_reference.sh <library> <tag>    (DRY_RUN=1 to preview)" >&2; exit 2; }
[[ $# -eq 2 ]] || usage
LIB=$1
TAG=$2
DRY_RUN=${DRY_RUN:-0}

HERE=${CD_HOME:-$(cd "$(dirname "$0")" && pwd)}
WORK="$HERE/work/$LIB/$TAG"
SRC="$WORK/src"
B1="$WORK/build"
B2="$WORK/build2"
REF="$WORK/reference"
LOG="$WORK/build_reference.log"
PID_FILE="$HERE/work/build_reference.pid"

say()  { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
fail() { say "FAILED: $*"; echo "SUMMARY $LIB $TAG: FAILED - $* (log: $LOG)"; exit 1; }

CONF="$HERE/libraries/$LIB.conf"
if [[ ! -f "$CONF" ]]; then
  echo "SUMMARY $LIB $TAG: FAILED - no recipe at $CONF"
  exit 1
fi
# shellcheck source=/dev/null
. "$CONF"
: "${LIB_ARGS[@]}" "${CHAINS_ROOT:?CHAINS_ROOT missing in $CONF}" "${HAS_TESTS:=no}"
UPSTREAM="$CHAINS_ROOT/$LIB/upstream"

[[ -d "$UPSTREAM/.git" ]] || { echo "SUMMARY $LIB $TAG: FAILED - no upstream repo at $UPSTREAM" >&2; exit 1; }
git -C "$UPSTREAM" rev-parse -q --verify "refs/tags/$TAG" >/dev/null \
  || { echo "SUMMARY $LIB $TAG: FAILED - tag $TAG not in $UPSTREAM" >&2; exit 1; }
for t in git cmake ninja clang++ shasum tar; do
  command -v "$t" >/dev/null || { echo "SUMMARY $LIB $TAG: FAILED - missing tool $t" >&2; exit 1; }
done
if [[ -e "$REF" ]]; then
  echo "SUMMARY $LIB $TAG: FAILED - reference already exists at $REF; move it aside first (never overwritten)" >&2
  exit 1
fi

UP_COMMIT=$(git -C "$UPSTREAM" rev-list -n 1 "$TAG")
UP_TREE=$(git -C "$UPSTREAM" rev-parse "$TAG^{tree}")

if [[ "$DRY_RUN" == 1 ]]; then
  echo "DRY RUN - nothing will be written"
  echo "  library:   $LIB $TAG (commit ${UP_COMMIT:0:12}, tree ${UP_TREE:0:12})"
  echo "  export to: $SRC"
  echo "  build 1:   $B1 (then tests)"
  echo "  build 2:   $B2 (reproducibility check)"
  echo "  reference: $REF"
  echo "  options:   ${LIB_ARGS[*]}"
  echo "SUMMARY $LIB $TAG: DRY RUN OK"
  exit 0
fi

mkdir -p "$HERE/work"
if [[ -f "$PID_FILE" ]]; then
  old=$(cat "$PID_FILE")
  if ps -p "$old" >/dev/null 2>&1; then
    echo "SUMMARY $LIB $TAG: NOT STARTED - another build_reference.sh is running (PID $old)"
    exit 0
  fi
fi
echo $$ > "$PID_FILE"
trap 'rm -f "$PID_FILE"; cd_cleanup' EXIT

mkdir -p "$SRC" "$REF"
: > "$LOG"
say "start $LIB $TAG (commit $UP_COMMIT)"

say "1/5 export $TAG from upstream"
git -C "$UPSTREAM" archive "$TAG" | tar -x -C "$SRC" || fail "export"
# Blobs only: a submodule pointer is an entry in the tree but not a file, so
# git archive cannot export it (found 2026-09-20 on FreeType).
want=$(git -C "$UPSTREAM" ls-tree -r "$TAG" | awk '$2 == "blob"' | wc -l | tr -d ' ')
# Symlinks count too: harfbuzz ships CLAUDE.md as a link to AGENTS.md, and
# -type f alone made the export look short by one (found 2026-09-20).
got=$(cd "$SRC" && find . \( -type f -o -type l \) | wc -l | tr -d ' ')
[[ "$want" == "$got" ]] || fail "export has $got files, tag has $want"

build_one() {
  local dir=$1
  local map="-g0 -ffile-prefix-map=$SRC=/lib-src -ffile-prefix-map=$dir=/lib-build"
  cmake -S "$SRC${SRC_SUBDIR:+/$SRC_SUBDIR}" -B "$dir" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_FLAGS="$map" \
    -DCMAKE_CXX_FLAGS="$map" \
    -DCMAKE_OBJC_FLAGS="$map" \
    -DCMAKE_OBJCXX_FLAGS="$map" \
    -DFETCHCONTENT_QUIET=ON \
    "${LIB_ARGS[@]}" >>"$LOG" 2>&1 || return 1
  cmake --build "$dir" >>"$LOG" 2>&1 || return 1
}

object_list() {
  (cd "$1" && find . -name '*.o' -not -path './_deps/*' | LC_ALL=C sort)
}

say "2/5 build 1 (configure + compile)"
build_one "$B1" || fail "build 1 (see log)"

say "3/5 library tests"
tests="none found"
if [[ "$HAS_TESTS" == "no" ]]; then
  tests="none (the recipe says this library has no test suite)"
  tr=0
  : > "$WORK/ctest.log"
elif [[ -n "${TEST_CMD:-}" ]]; then
  ( cd "$B1" && eval "$TEST_CMD" ) >"$WORK/ctest.log" 2>&1
  tr=$?
  tests="recipe TEST_CMD $([[ $tr -eq 0 ]] && echo passed || echo FAILED): $TEST_CMD"
else
  ctest --test-dir "$B1" --output-on-failure >"$WORK/ctest.log" 2>&1
  tr=$?
  line=$(grep -E "tests passed" "$WORK/ctest.log" | tail -1)
  if grep -q "No tests were found" "$WORK/ctest.log"; then
    tests="NONE FOUND"
  elif [[ -n "$line" ]]; then
    tests="$line"
  fi
fi
cat "$WORK/ctest.log" >> "$LOG"

say "4/5 build 2 (reproducibility check)"
build_one "$B2" || fail "build 2 (see log)"

say "5/5 save reference objects"
object_list "$B1" > "$REF/objects.list"
n=$(wc -l < "$REF/objects.list" | tr -d ' ')
[[ "$n" -gt 0 ]] || fail "no object files found in $B1"
mkdir -p "$REF/objects"
(cd "$B1" && tar -cf - -T "$REF/objects.list") | tar -xf - -C "$REF/objects" || fail "copy objects"
(cd "$B1" && xargs shasum -a 256 < "$REF/objects.list") > "$REF/objects.sha256" || fail "hash build 1"
(cd "$B2" && xargs shasum -a 256 < "$REF/objects.list") > "$WORK/build2.sha256" 2>>"$LOG" || fail "hash build 2"
diffs=$(diff "$REF/objects.sha256" "$WORK/build2.sha256" | grep -c '^<')
same=$((n - diffs))
diff "$REF/objects.sha256" "$WORK/build2.sha256" | grep '^<' | awk '{print $3}' > "$REF/not_reproducible.list"

{
  echo "library:          $LIB"
  echo "tag:              $TAG"
  echo "upstream commit:  $UP_COMMIT"
  echo "upstream tree:    $UP_TREE"
  echo "built:            $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "compiler:         $(clang++ --version | head -1)"
  echo "cmake:            $(cmake --version | head -1)"
  echo "ninja:            $(ninja --version)"
  echo "macOS SDK:        $(xcrun --show-sdk-version 2>/dev/null)"
  echo "build type:       Release (-O3 -DNDEBUG) plus -g0 and path maps"
  echo "path maps:        source -> /lib-src, build -> /lib-build"
  echo "options:          ${LIB_ARGS[*]}"
  echo "objects:          $n (dependencies under _deps excluded)"
  echo "reproducible:     $same of $n identical across two clean builds"
  echo "tests:            $tests (ctest exit $tr)"
} > "$REF/BUILD_INFO.txt"

status=OK
[[ "$diffs" -eq 0 ]] || status="OK-BUT-$diffs-NOT-REPRODUCIBLE"
[[ "$tr" -eq 0 && "$tests" != "NONE FOUND" && "$tests" != "none found" ]] || status="$status TESTS-NOT-CLEAN"
[[ "$HAS_TESTS" == "no" ]] && status="OK-NO-TESTS"
summary="SUMMARY $LIB $TAG: $status | objects $n | reproducible $same/$n | tests: $tests"
echo "$summary" > "$REF/SUMMARY.txt"
say "done"
echo "$summary"
