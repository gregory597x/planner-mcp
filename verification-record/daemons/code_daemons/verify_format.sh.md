# verify_format.sh and token_compare.py — why they work the way they do

Sidecar for `verify_format.sh` and `token_compare.py` (comment-sidecar
convention). Design: `md_staging/reference/code-daemons-design.md`, section
4.4 and build step 3.

## Role

The independent checker. The formatter never judges its own output; this
script does, and it is the only thing that may accept a formatted file into
the candidate tree.

## Commands

```
verify_format.sh sfml 3.0.2 selftest
verify_format.sh sfml 3.0.2 check <path inside the library> <candidate file>
verify_format.sh sfml 3.0.2 final
```

The last line of output is always one `SUMMARY verify ...` line. Details go to
`work/<lib>/<tag>/verify.log`; every `check` verdict is appended to
`work/<lib>/<tag>/verify_results.tsv`.

## The gates

- **Gate A, token equality** (`token_compare.py`). Clang's raw lexer
  (`-Xclang -dump-raw-tokens`) lists every piece of the file, including
  spacing and comments as separate pieces. Spacing and comments are dropped
  and the remaining sequence must be identical to the upstream file's. Raw
  lexing needs no include paths, so headers are checked directly. The
  language comes from the file name (`.mm` is Objective-C++). If a non-empty
  file yields no tokens at all, that is an error, never a pass.
  Token records are split on their `Loc=<...>` ending, because a whitespace
  token holding an escaped newline is printed across two lines; parsing line
  by line mis-aligned every later token and reported a false difference
  (found 2026-09-20 on `examples/include/gl.h`). Whitespace tokens are
  dropped after line continuations are removed, so re-aligning the
  backslashes in a macro passes. A backslash that is genuinely added or
  removed is therefore invisible to gate A and is caught by gate B instead.
- **Gate B, compiled output.** The candidate tree is rebuilt incrementally and
  every reference object (215 for SFML 3.0.2) must be byte-identical to the
  reference build. All objects are compared on every check, so a header change
  is judged through every file that includes it.
  A difference is allowed only when it is **explained** (design section 4.4):
  the object's source must be token-identical to upstream *and* contain
  line-number macros (`__LINE__`, `assert(`, or Catch2's `TEST_CASE`,
  `SECTION`, `REQUIRE`, `CHECK`, `STATIC_CHECK`). Catch2 bakes the line number
  of every assertion into the object, so reformatting a test file changes its
  bytes while its behaviour is identical (found 2026-09-20 on
  `test/Audio/InputSoundFile.test.cpp`, 213 such macros). Explained
  differences are listed in `gate_b_explained.list`; anything else fails.
  Checked the same day: changing `==` to `!=` in that test file is still
  rejected, so the allowance is not a loophole. Gate C is the compensating
  control — the tests must pass at the end.
- **Gate C, tests** (`final` only). The library's own test suite must pass on
  the candidate tree.

## The candidate tree

`work/<lib>/<tag>/cand/` is a separate copy of the upstream export with its own
build. Accepted files stay in it; rejected files are put back the way they
were and the tree is rebuilt. Standing rule: **the candidate tree always
compiles to exactly the reference.** It is checked at the start of every
command, and nothing is judged if it fails. That also proves the candidate
build uses the same settings as `build_reference.sh`, whose build settings
this script repeats.

## Why the self-test exists

A check that cannot fail proves nothing. The self-test runs the real
`place` / build / gate / `revert` path on variants of one SFML source file and
one header:

1. whitespace only, plus a new first line so every line number moves — must
   pass (proves `-g0` and `NDEBUG` remove line-number effects)
2. comments only — must pass
3. one real change, the first ` < ` in an `if` becomes ` <= ` — **both** gate
   A and gate B must fail, so each gate is shown able to catch a real change
   on its own
4. whitespace only in a header — must pass through every file that includes it
5. Greg's `.clang-format` on the target file — reported for information; it
   shows whether the formatter's real output passes before step 4 relies on it

Afterwards the candidate tree must be byte-identical to the upstream export and
still compile to the reference.

## Safety (00-codegen-safety-protocol)

- Never writes to the upstream repository or the reference.
- Every replaced candidate file is saved first under `cand/.prev/`.
- One instance per library and tag (`verify.pid`).
- Stops on the first failure; a failed revert is reported loudly as needing
  attention, never ignored.
