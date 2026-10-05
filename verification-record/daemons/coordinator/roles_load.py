#!/usr/bin/env python3
"""roles_load.py — charters as files, loaded into knowledge_hub.agent_roles.

Reads md_staging/roles/*.md, parses the `role:` block in each file's front
matter, and upserts it. RULE 9 holds: this reads md_staging and never writes to
it. Removal is `status = 'retired'`, never a delete — a retired charter still
explains work that was done under it.

The parser is deliberately a strict subset of YAML written against the standard
library, because this machine has two pythons and only one carries PyYAML; a
loader must not depend on which one is first on PATH. When PyYAML IS importable
the file is parsed both ways and the results must match, so the mini-parser is
checked against a real one wherever one exists.

  usage: roles_load.py [--apply]     (default is a dry run)
"""

import json
import os
import subprocess
import sys

ROLES_DIR = os.environ.get(
    "ROLES_DIR", os.path.expanduser("~/TCS-Software_Workspace/md_staging/roles"))
HERE = os.path.dirname(os.path.abspath(__file__))

FIELDS = ("slug", "display_name", "charter", "inputs", "outputs",
          "guardrails", "definition_of_done", "verifier_roles",
          "project", "status")
REQUIRED = ("slug", "display_name", "charter")
LIST_FIELDS = ("inputs", "outputs", "guardrails", "verifier_roles")
VALID_STATUS = ("active", "draft", "retired")


# --------------------------------------------------------------- parsing

def front_matter(text, path):
    """The block between the first two lines that are exactly '---'."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("%s: no front matter" % path)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    raise ValueError("%s: front matter is never closed" % path)


def parse_role_block(fm, path):
    """Parse `role:` out of the front matter. Accepts exactly what a charter
    needs: `key: value`, `key: >-` folded text, and `- item` lists. Anything
    else is an error rather than a guess."""
    lines = fm.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == "role:":
            start = i + 1
            break
    if start is None:
        raise ValueError("%s: front matter has no 'role:' block" % path)

    role, key, folded, listing = {}, None, None, None
    for raw in lines[start:]:
        if raw.strip() == "" :
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:                       # back out to the document level
            break
        line = raw.strip()
        if line.startswith("#"):
            continue

        if folded is not None and indent > folded[1]:
            folded[2].append(line)
            continue
        if folded is not None:
            role[folded[0]] = " ".join(folded[2]).strip()
            folded = None

        if line.startswith("- "):
            if listing is None:
                raise ValueError("%s: list item outside any key: %r" % (path, line))
            item = line[2:].strip()
            if item[:1] in "\"'" and item[-1:] == item[:1]:
                item = item[1:-1]
            role[listing].append(item)
            continue

        if ":" not in line:
            raise ValueError("%s: cannot read line %r" % (path, line))
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key not in FIELDS:
            raise ValueError("%s: unknown role field %r" % (path, key))
        listing = None
        if value in (">-", ">", "|", "|-"):
            folded = [key, indent, []]
        elif value == "":
            role[key] = []
            listing = key
        else:
            if value[:1] in "\"'" and value[-1:] == value[:1]:
                value = value[1:-1]
            role[key] = value
    if folded is not None:
        role[folded[0]] = " ".join(folded[2]).strip()
    return role


def cross_check(fm, mine, path):
    """If a real YAML parser is here, the mini-parser must agree with it."""
    try:
        import yaml                                  # noqa: PLC0415
    except ImportError:
        return "no PyYAML on this interpreter; mini-parser not cross-checked"
    theirs = (yaml.safe_load(fm) or {}).get("role")
    if theirs is None:
        raise ValueError("%s: PyYAML found no role block" % path)
    # `mine` has already been through validate(), which fills in defaults for
    # omitted fields; apply the same defaults here or an omitted list (e.g. no
    # verifier_roles) reads as a disagreement. (2026-09-24)
    theirs = dict(theirs)
    theirs.setdefault("status", "active")
    for f in LIST_FIELDS:
        theirs.setdefault(f, [])
    norm = lambda d: {k: (list(v) if isinstance(v, list) else str(v).strip())
                      for k, v in d.items()}
    if norm(theirs) != norm(mine):
        raise ValueError(
            "%s: the mini-parser and PyYAML disagree.\n  mine:   %s\n  PyYAML: %s"
            % (path, json.dumps(norm(mine), sort_keys=True),
               json.dumps(norm(theirs), sort_keys=True)))
    return "cross-checked against PyYAML"


def validate(role, path):
    for f in REQUIRED:
        if not role.get(f):
            raise ValueError("%s: %s is required" % (path, f))
    role.setdefault("status", "active")
    if role["status"] not in VALID_STATUS:
        raise ValueError("%s: status %r must be one of %s"
                         % (path, role["status"], ", ".join(VALID_STATUS)))
    for f in LIST_FIELDS:
        role.setdefault(f, [])
        if not isinstance(role[f], list):
            raise ValueError("%s: %s must be a list" % (path, f))
    return role


# -------------------------------------------------------------- database

def lit(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def arr(values):
    return "ARRAY[%s]::text[]" % ", ".join(lit(v) for v in values) if values else "'{}'::text[]"


def psql(sql):
    p = subprocess.run(["docker", "exec", "-i", "<PG-CONTAINER>",
                        "psql", "-U", "role-planner", "-d", "role-planner",
                        "-v", "ON_ERROR_STOP=1", "-At", "-c", sql],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip().splitlines()[-1][:300])
    return p.stdout.strip()


def main():
    apply = "--apply" in sys.argv
    if not os.path.isdir(ROLES_DIR):
        print("SUMMARY roles_load: FAILED - no %s" % ROLES_DIR)
        return 1

    files = sorted(f for f in os.listdir(ROLES_DIR) if f.endswith(".md"))
    parsed, checks = {}, set()
    for name in files:
        path = os.path.join(ROLES_DIR, name)
        text = open(path).read()
        fm = front_matter(text, path)
        role = validate(parse_role_block(fm, path), path)
        checks.add(cross_check(fm, role, path))
        if role["slug"] in parsed:
            raise ValueError("%s: slug %s is declared twice" % (path, role["slug"]))
        role["source_path"] = os.path.join("md_staging/roles", name)
        parsed[role["slug"]] = role

    existing = json.loads(psql(
        "SELECT coalesce(json_agg(t),'[]') FROM (SELECT slug, status, source_path "
        "FROM knowledge_hub.agent_roles) t;") or "[]")
    have = {r["slug"]: r for r in existing}

    added   = [s for s in parsed if s not in have]
    updated = [s for s in parsed if s in have]
    # Only charters this loader owns may be retired. A row inserted by a
    # migration and never given a file is left alone, not silently retired.
    retire  = [r["slug"] for r in existing
               if r["source_path"] and r["slug"] not in parsed
               and r["status"] != "retired"]

    statements = []
    for slug, r in parsed.items():
        statements.append(
            "INSERT INTO knowledge_hub.agent_roles (slug, display_name, charter, inputs, "
            "outputs, guardrails, definition_of_done, verifier_roles, source_path, project, "
            "status, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (slug) DO UPDATE SET display_name=EXCLUDED.display_name, "
            "charter=EXCLUDED.charter, inputs=EXCLUDED.inputs, outputs=EXCLUDED.outputs, "
            "guardrails=EXCLUDED.guardrails, definition_of_done=EXCLUDED.definition_of_done, "
            "verifier_roles=EXCLUDED.verifier_roles, source_path=EXCLUDED.source_path, "
            "project=EXCLUDED.project, status=EXCLUDED.status, updated_at=now();"
            % (lit(slug), lit(r["display_name"]), lit(r["charter"]), arr(r["inputs"]),
               arr(r["outputs"]), arr(r["guardrails"]), lit(r.get("definition_of_done")),
               arr(r["verifier_roles"]), lit(r["source_path"]), lit(r.get("project")),
               lit(r["status"])))
    for slug in retire:
        statements.append("UPDATE knowledge_hub.agent_roles SET status='retired', "
                          "updated_at=now() WHERE slug=%s;" % lit(slug))

    # A dry run may go uncross-checked; a write may not. Proved 2026-09-23: a
    # defect that validation cannot see (a plausible but wrong display_name)
    # is caught only where PyYAML is importable. Refusing here is what makes
    # "one python, and it carries PyYAML" a rule instead of a preference.
    if apply and any(c.startswith("no PyYAML") for c in checks):
        raise RuntimeError(
            "refusing to write: this interpreter has no PyYAML, so the parser was "
            "not cross-checked. Re-run with an interpreter that has it.")

    if apply:
        psql("BEGIN; " + " ".join(statements) + " COMMIT;")

    print("SUMMARY roles_load: %s | files %d | added %d | updated %d | retired %d | %s"
          % ("APPLIED" if apply else "DRY RUN", len(files), len(added), len(updated),
             len(retire), "; ".join(sorted(checks))))
    for slug in added:
        print("  + %s (%s)" % (slug, parsed[slug]["status"]))
    for slug in retire:
        print("  - %s retired (its file is gone)" % slug)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError) as e:
        print("SUMMARY roles_load: FAILED - %s" % e)
        sys.exit(1)
