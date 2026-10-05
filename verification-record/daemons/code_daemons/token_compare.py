"""usage: token_compare.py <original> <candidate> <name-used-for-language>"""
import os
import re
import subprocess
import sys

LANGS = {".mm": "objective-c++", ".m": "objective-c", ".c": "c"}
RECORD = re.compile(r"\tLoc=<[^>\n]*>\n?")
HEAD = re.compile(r"^([A-Za-z_]+) '(.*?)'\t", re.S)
CONTINUATION = re.compile(r"\\\s*\n")


def language(name):
    return LANGS.get(os.path.splitext(name)[1].lower(), "c++")


def tokens(path, lang):
    cmd = ["clang++", "-x", lang, "-fsyntax-only", "-Xclang", "-dump-raw-tokens", path]
    if lang == "c++":
        cmd.insert(3, "-std=c++20")
    run = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    out = []
    seen = 0
    for record in RECORD.split(run.stderr):
        head = HEAD.match(record)
        if not head:
            continue
        seen += 1
        kind, spelling = head.group(1), head.group(2)
        if kind == "comment":
            continue
        if kind == "unknown":
            spelling = CONTINUATION.sub("", spelling).strip()
            if not spelling:
                continue
        out.append((kind, spelling))
    return out, seen


def short(tok):
    kind, spelling = tok
    return f"{kind} {spelling[:40]!r}"


def main():
    if len(sys.argv) != 4:
        print(__doc__.strip())
        return 2
    original, candidate, name = sys.argv[1:4]
    lang = language(name)
    a, a_seen = tokens(original, lang)
    b, _ = tokens(candidate, lang)
    if not a_seen and os.path.getsize(original) > 0:
        print(f"ERROR clang read no tokens at all from {original}")
        return 2
    if not a:
        if b:
            print(f"DIFFERENT: original has no code tokens, candidate gained {len(b)}: {short(b[0])}")
            return 1
        print(f"SAME 0 code tokens (comments and blank space only, {a_seen} raw tokens)")
        return 0
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            print(f"DIFFERENT at token {i + 1} of {len(a)}: {short(x)} became {short(y)}")
            return 1
    if len(a) != len(b):
        print(f"DIFFERENT token count: {len(a)} became {len(b)}")
        return 1
    print(f"SAME {len(a)} tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
