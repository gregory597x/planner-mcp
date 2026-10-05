#!/usr/bin/env python3
"""
check_docs.py -- guardrail against handoff documents that lie.

Two failure modes, both observed on 2026-08-30, both invisible to the
author of the document:

  1. A document cites a file path that does not exist.  Common after a
     rename, or when a doc is written from memory of the tree.
  2. A document's "Running it" section lists a command that does not
     work.  Chat A's C-coil handoff listed four commands, two of which
     exited non-zero, and one of which passed a distance taken from a
     prediction the same document had already withdrawn.

Neither is catchable by re-reading the document.  Both are caught by
trying to use it, which is what this does.

Usage:
    python3 check_docs.py [--run] [doc ...]

    default    check that every cited file path resolves
    --run      ALSO execute fenced shell commands and require exit 0

Exit 0 when clean, 1 when anything fails.  Commands containing a
<placeholder> are reported and skipped rather than run.
"""
import os, re, subprocess, sys

HOME = os.path.expanduser("~")
DOCS_DIR = os.path.join(HOME, "TCS-Planner", "docs")
TREES = [
    "TCS-Software_Projects/_cpp-v20_projects/Solver",
    "TCS-Software_Projects/_cpp-v20_projects/Media_Module",
    "TCS-Software_Projects/_cpp-v20_projects/MRI_Demonstration",
    "TCS-Software_Projects/_cpp-v20_projects/Karmarkar_module",
    "TCS-Software_Projects/_cpp-v20_projects/math_symbolic",
    # game track, added 2026-09-11 by code-role-terrain-01
    "TCS-Software_Projects/_cpp-v20_projects/PlanetEngine",
    # game track consumer, added 2026-09-13 by code-role-combat-01
    "TCS-Software_Projects/_cpp-v20_projects/PlanetGame",
    "TCS-Planner/docs", "TCS-Planner/scripts",
    "TCS-Software_Workspace/MRI-rethink",
    # sibling explanation docs, added 2026-09-11 by code-role-solver-b-01
    "TCS-Software_Workspace/MRI-Dev docs",
    "Desktop/_a_/_ from RHV 3",
]
SKIP_DIRS = {"build", ".git", "node_modules", "vendor", "__pycache__"}
EXTS = ("hpp", "cpp", "md", "sh", "py", "json", "docx")
# .vol / .cxvol are RUN OUTPUTS, not tracked files: a doc naming one is
# describing what a producer emits, not referencing something that should
# already exist.  Checking them produced only false positives.
PLACEHOLDER_RE = re.compile(r"XX|\bTBD\b|\bNN\b|<[^>]+>")
# A document may suppress specific paths with a visible, auditable marker:
#     <!-- check-docs-ignore: foo.hpp, bar.cpp -->
# Needed because a document that DISCUSSES a dangling path (a status report,
# or this checker's own findings) would otherwise flag itself.  Suppression
# is deliberately in-band so it shows up in review rather than hiding in a
# config file.
IGNORE_RE = re.compile(r"<!--\s*check-docs-ignore:\s*([^>]*?)\s*-->")

PATH_RE = re.compile(r"[\w./~+-]*\.(?:" + "|".join(EXTS) + r")\b")
FENCE_RE = re.compile(r"```(?:sh|bash|console)?\n(.*?)```", re.S)


def build_index():
    idx = {}
    for t in TREES:
        root = os.path.join(HOME, t)
        if not os.path.isdir(root):
            continue
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in SKIP_DIRS]
            for f in fn:
                idx.setdefault(f, []).append(os.path.join(dp, f))
    return idx


def check_paths(doc, idx):
    """Every filename a doc cites should name a real file somewhere."""
    text = open(doc, encoding="utf8").read()
    ignored = set()
    for m in IGNORE_RE.finditer(text):
        ignored.update(x.strip() for x in m.group(1).split(",") if x.strip())
    bad = []
    for raw in sorted(set(PATH_RE.findall(text))):
        if raw in ignored or os.path.basename(raw) in ignored:
            continue
        # brace expansion and globs are prose shorthand, not paths
        if any(c in raw for c in "{}*<>") or PLACEHOLDER_RE.search(raw):
            continue
        base = os.path.basename(raw)
        stem = base.rsplit(".", 1)[0]
        # A bare extension, or a purely numeric stem, is a regex artefact of
        # a filename containing a space -- e.g. "Build {1,2}.docx" yields
        # "1.docx".  Not a reference, so not a dangling one.
        if base.startswith(".") or base in EXTS or stem.isdigit():
            continue
        if base not in idx:
            bad.append(raw)
    return bad


def check_commands(doc, run):
    """Commands a doc tells a reader to run should actually run."""
    text = open(doc, encoding="utf8").read()
    results = []
    for block in FENCE_RE.findall(text):
        if "./" not in block:
            continue
        if PLACEHOLDER_RE.search(block):
            results.append((block.strip().splitlines()[0], "skipped: placeholder"))
            continue
        if not run:
            results.append((block.strip().splitlines()[0], "not run (pass --run)"))
            continue
        cwd = os.path.join(HOME, "TCS-Software_Projects", "_cpp-v20_projects")
        try:
            rc = subprocess.run(block, shell=True, cwd=cwd, timeout=300,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL).returncode
        except Exception as e:                          # noqa: BLE001
            results.append((block.strip().splitlines()[0], f"ERROR {e}"))
            continue
        first = block.strip().splitlines()[0]
        results.append((first, "ok" if rc == 0 else f"EXIT {rc}"))
    return results


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run = "--run" in sys.argv
    docs = args or sorted(
        os.path.join(DOCS_DIR, f) for f in os.listdir(DOCS_DIR)
        if f.endswith(".md"))

    idx = build_index()
    failures = 0
    for doc in docs:
        name = os.path.basename(doc)
        bad = check_paths(doc, idx)
        cmds = check_commands(doc, run)
        broken = [c for c in cmds if c[1].startswith(("EXIT", "ERROR"))]
        if not bad and not broken:
            continue
        print(f"\n{name}")
        for b in bad:
            print(f"  [dangling path] {b}")
        for line, why in broken:
            print(f"  [{why}] {line}")
        failures += len(bad) + len(broken)

    total = len(docs)
    if failures:
        print(f"\n{failures} problem(s) across {total} document(s)")
        return 1
    print(f"{total} document(s) checked, no dangling paths"
          + (", all commands exit 0" if run else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
