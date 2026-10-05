#!/usr/bin/env python3
"""role-coordinator.py — the chat role-coordinator daemon's tick.

Two jobs on one tick, per md_staging/reference/chat-role-coordinator-daemon-design.md:

  TRACK   read what chats claimed from Planner, chase the quiet ones, collect
          their reports, write completions and blockers back to Planner.
  ROUTE   answer questions a chat did not know where to send.

Design rules that are enforced here rather than remembered:

  * Completion is never inferred. Only an explicit complete report with a
    summary closes a Planner task. Silence is reported as silence.
  * Blocked never auto-closes anything. A blocked report becomes a dependency
    row; the task stays open and the view derives the rest.
  * A verifier that cannot act is a REPORTED stall, never a quiet wait.
  * The asking chat is dropped from its own routing candidates.
  * "Broadcast to the group" means a topic, not every open chat.

Standard library only, on purpose: this machine has two pythons and only one of
them carries PyYAML, and a daemon must not depend on which one is first on
PATH. Postgres is reached through `docker exec`, so no password is ever stored.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# The runner executes a snapshot of this file from a temp directory, so state
# must resolve to the REAL home. Without this the chase cooldown log lands in a
# directory that is deleted at exit, and every run re-chases every quiet chat.
HERE = os.environ.get("CD_HOME") or os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
CHASE_LOG = os.path.join(WORK, "chased.tsv")

DEFAULTS = {
    "HUB": "http://127.0.0.1:8000",
    "PG_CONTAINER": "<PG-CONTAINER>",
    "PG_USER": "role-planner",
    "PG_DB": "role-planner",
    "CHAT_ID": "role-coordinator",
    "ROLE": "role-coordinator",
    "QUIET_HOURS": "24",
    "CHASE_COOLDOWN_HOURS": "24",
    "VERIFIER_STALL_HOURS": "24",
    "FALLBACK_VERIFIER": "greg",
    "ROUTE_MIN_FIT": "0.6",
    "BROADCAST_POLICY": "topic",
    "DRY_RUN": "1",
}


def load_conf():
    conf = dict(DEFAULTS)
    path = os.path.join(HERE, "role-coordinator.conf")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip().strip('"').strip("'")
    for k, v in os.environ.items():          # env wins, for one-off runs
        if k in conf:
            conf[k] = v
    return conf


CONF = load_conf()
DRY = CONF["DRY_RUN"] == "1"
NOTES = []          # anything a human needs to know that is not a count


def note(msg):
    NOTES.append(msg)


# ----------------------------------------------------------------- database

def lit(value):
    """A SQL string literal. Never build SQL by concatenating raw text."""
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _psql(sql, want_output=True, db=None):
    cmd = ["docker", "exec", "-i", CONF["PG_CONTAINER"],
           "psql", "-U", CONF["PG_USER"], "-d", db or CONF["PG_DB"],
           "-v", "ON_ERROR_STOP=1", "-At", "-c", sql]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip().splitlines()[-1][:300])
    return p.stdout if want_output else ""


def rows(sql):
    """Rows as dicts. Postgres does the JSON encoding, so no delimiter in any
    title, summary or mail body can corrupt the parse."""
    return rows_db(sql)


def rows_db(sql, db=None):
    """Same, against a named database. The RAG corpus lives in rag_system, a
    different database in the same container."""
    out = _psql("SELECT coalesce(json_agg(t), '[]'::json) FROM (%s) t;"
                % sql.rstrip().rstrip(";"), db=db)
    return json.loads(out.strip() or "[]")


def execute(sql):
    if DRY:
        return "dry-run"
    return _psql(sql, want_output=False)


# ---------------------------------------------------------------------- hub

def hub(path, payload=None, timeout=30):
    url = CONF["HUB"] + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"content-type": "application/json"} if data else {},
        method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
        return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError("hub %s: %s %s" % (path, e.code, e.read().decode()[:200]))
    except Exception as e:                        # noqa: BLE001 - reported, not raised
        raise RuntimeError("hub %s unreachable: %s" % (path, e))


def send_mail(to_kind, to_value, subject, body, priority="normal"):
    """to_kind is one of to_chat, to_role, to_topic."""
    if DRY:
        note("WOULD MAIL %s=%s: %s" % (to_kind, to_value, subject))
        return {"dry_run": True}
    payload = {"from_chat": CONF["CHAT_ID"], "subject": subject,
               "body": body, "priority": priority, to_kind: to_value}
    return hub("/mailbox/send", payload)


# ------------------------------------------------------------ step 1: state

def read_state():
    """Open Planner work, who claimed it, and whether that chat is speaking."""
    role-planner = rows("""
        SELECT t.id, t.title, t.status, t.priority,
               t.due_date::text AS due_date, t.hard_deadline, t.category,
               a.is_blocked, a.incomplete_prereqs, a.effective_wsjf, a.elevated
        FROM tasks_actionable a JOIN tasks t ON t.id = a.id
        WHERE t.status NOT IN ('Completed', 'Cancelled')
    """)
    claims = rows("""
        SELECT tt.id AS tracked_id, tt.chat_id, tt.planner_task_id, tt.status,
               tt.blocked_by, tt.summary_on_completion,
               tt.last_status_update::text AS last_status_update,
               l.liveness, extract(epoch from (now() - l.last_seen_at))/3600 AS silent_hours,
               c.role
        FROM knowledge_hub.tracked_tasks tt
        LEFT JOIN knowledge_hub.chat_liveness l ON l.chat_id = tt.chat_id
        LEFT JOIN knowledge_hub.active_chats c ON c.chat_id = tt.chat_id
        WHERE tt.planner_task_id IS NOT NULL
    """)
    return role-planner, claims


# ------------------------------------------------- step 2: chase quiet chats

def load_chase_log():
    seen = {}
    if os.path.exists(CHASE_LOG):
        for line in open(CHASE_LOG):
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                seen[parts[0]] = float(parts[1])
    return seen


def record_chase(key):
    if DRY:
        return
    os.makedirs(WORK, exist_ok=True)
    with open(CHASE_LOG, "a") as fh:
        fh.write("%s\t%f\n" % (key, time.time()))


def chase(role-planner, claims):
    quiet_h = float(CONF["QUIET_HOURS"])
    cooldown = float(CONF["CHASE_COOLDOWN_HOURS"]) * 3600
    open_ids = {p["id"] for p in role-planner}
    log = load_chase_log()
    chased = []
    for c in claims:
        if c["status"] not in ("in_progress", "blocked"):
            continue
        if c["planner_task_id"] not in open_ids:
            continue
        silent = c["silent_hours"] or 0
        if silent < quiet_h:
            continue
        key = "%s:%s" % (c["planner_task_id"], c["chat_id"])
        if time.time() - log.get(key, 0) < cooldown:
            continue
        title = next((p["title"] for p in role-planner if p["id"] == c["planner_task_id"]), "")
        subject = "status on Planner task %s?" % c["planner_task_id"]
        body = (
            "%s\n\nYou claimed this and the hub has not heard from you in %d hours.\n"
            "Answer by posting status, not prose:\n"
            "  done     -> POST /tasks/%s/complete with a summary\n"
            "  blocked  -> POST /tasks/%s/status {\"status\":\"blocked\",\n"
            "              \"blocked_by\":\"task <id>\"}  (name the task id)\n"
            "  working  -> a checkpoint is enough\n\n"
            "No reply is read as silence, not as done. Nothing is closed on your behalf."
            % (title, int(silent), c["tracked_id"], c["tracked_id"]))
        target = ("to_role", c["role"]) if c.get("role") else ("to_chat", c["chat_id"])
        send_mail(target[0], target[1], subject, body)
        record_chase(key)
        chased.append({"task": c["planner_task_id"], "chat": c["chat_id"],
                       "silent_hours": int(silent)})
    return chased


# ------------------------------------------- step 3: collect and write back

TASK_REF = re.compile(r"(?:task|role-planner|#)\s*[#:]?\s*(\d+)", re.I)


def write_back(role-planner, claims):
    """Completions close their Planner task. Blocked reports become dependency
    rows. Neither is ever inferred: both come from an explicit report."""
    by_id = {p["id"]: p for p in role-planner}
    closed, blocked, ignored = [], [], []

    for c in claims:
        pid = c["planner_task_id"]
        task = by_id.get(pid)
        if task is None:
            continue                       # already Completed in Planner

        if c["status"] == "complete":
            if not (c["summary_on_completion"] or "").strip():
                ignored.append({"task": pid, "chat": c["chat_id"],
                                "why": "complete with no summary — not closed"})
                continue
            if not DRY:
                hub("/role-planner/tasks/%d/status" % pid,
                    {"status": "Completed",
                     "note": "closed by role-coordinator: %s reported complete. %s"
                             % (c["chat_id"], c["summary_on_completion"][:400])})
            closed.append({"task": pid, "chat": c["chat_id"], "title": task["title"]})

        elif c["status"] == "blocked":
            ref = TASK_REF.search(c["blocked_by"] or "")
            if not ref:
                ignored.append({"task": pid, "chat": c["chat_id"],
                                "why": "blocked but blocked_by names no task id: %r"
                                       % (c["blocked_by"] or "")[:60]})
                continue
            dep = int(ref.group(1))
            if dep == pid:
                ignored.append({"task": pid, "chat": c["chat_id"],
                                "why": "blocked on itself — refused"})
                continue
            exists = rows("SELECT 1 AS ok FROM tasks WHERE id = %d" % dep)
            if not exists:
                ignored.append({"task": pid, "chat": c["chat_id"],
                                "why": "blocked on task %d, which does not exist" % dep})
                continue
            already = rows("SELECT 1 AS ok FROM task_dependencies "
                           "WHERE task_id = %d AND depends_on_id = %d" % (pid, dep))
            if already:
                continue
            execute("INSERT INTO task_dependencies (task_id, depends_on_id) "
                    "VALUES (%d, %d) ON CONFLICT DO NOTHING;" % (pid, dep))
            blocked.append({"task": pid, "chat": c["chat_id"], "waiting_on": dep})

    return closed, blocked, ignored


# ------------------------------------------------------- step 4: verifiers

def classify_verifier(holders_of_role, stall_hours):
    """Can this verifier role actually clear a gate right now?

    ok           a holder has spoken inside the stall window
    holder_quiet someone holds the post but has gone silent
    no_holder    nobody holds it at all

    Only 'ok' can clear a gate. The other two are reported, never waited on.
    """
    if any((h.get("silent_hours") or 0) < stall_hours for h in holders_of_role):
        return "ok"
    return "holder_quiet" if holders_of_role else "no_holder"


def pick_topic(text, sender, topics, exclude=()):
    """The topic rung: a topic whose own name appears in the question, and that
    somebody other than the asker is subscribed to. Widest audience wins.

    `exclude` carries the role-coordinator's own chat id as well as the sender.
    Found live on 2026-09-23: a message whose text contained the word "routing"
    matched the role-coordinator's OWN topic, whose only subscriber was itself. It
    would have mailed itself, read it back on the next tick, and routed it
    again — forever. A recipient set that is empty once the asker and the
    daemon are removed is not a destination.
    """
    blocked = {sender} | set(exclude)
    words = set(re.findall(r"[a-z0-9-]+", text.lower()))
    audience = {t: [c for c in topics[t] if c not in blocked] for t in topics}
    hits = [t for t in topics if t.lower() in words and audience[t]]
    if not hits:
        return None
    return max(hits, key=lambda t: len(audience[t]))


def check_verifiers():
    """A gate whose verifier cannot act is reported, never quietly waited on.

    Three outcomes per verifier role: it has a responsive holder, it has a
    holder that has gone quiet, or it has no holder at all. Only the first can
    actually clear a gate.
    """
    items = rows("""
        SELECT w.id, w.title, w.produced_by_role, w.produced_by_chat,
               extract(epoch from (now() - w.created_at))/3600 AS age_hours,
               coalesce(r.verifier_roles, '{}') AS verifier_roles,
               coalesce(array_agg(g.gate) FILTER (WHERE g.result = 'pass'), '{}') AS passed
        FROM knowledge_hub.work_items w
        LEFT JOIN knowledge_hub.agent_roles r ON r.slug = w.produced_by_role
        LEFT JOIN knowledge_hub.work_item_gates g ON g.work_item_id = w.id
        WHERE w.state = 'open'
        GROUP BY w.id, w.title, w.produced_by_role, w.produced_by_chat,
                 w.created_at, r.verifier_roles
    """)
    if not items:
        return []

    holders = {}
    for h in rows("""
            SELECT c.role, c.chat_id, l.liveness,
                   extract(epoch from (now() - l.last_seen_at))/3600 AS silent_hours
            FROM knowledge_hub.active_chats c
            JOIN knowledge_hub.chat_liveness l ON l.chat_id = c.chat_id
            WHERE c.closed_at IS NULL AND c.role IS NOT NULL"""):
        holders.setdefault(h["role"], []).append(h)

    stall_h = float(CONF["VERIFIER_STALL_HOURS"])
    findings = []
    for it in items:
        missing = [g for g in ("smoke", "validate") if g not in (it["passed"] or [])]
        for role in (it["verifier_roles"] or []):
            state = classify_verifier(holders.get(role, []), stall_h)
            if state == "ok":
                continue
            # Mail it anyway: a dead drop is delivered the moment the role is
            # claimed, so the request is waiting rather than forgotten.
            send_mail("to_role", role,
                      "verification needed: work item %s" % it["id"],
                      "%s\nProduced by %s. Missing gates: %s.\nThis has been open %d hours.\n"
                      "If you are picking up this role, this is what is waiting for you."
                      % (it["title"], it["produced_by_role"],
                         ", ".join(missing) or "none recorded", int(it["age_hours"] or 0)),
                      priority="blocking" if state == "no_holder" else "normal")
            findings.append({
                "work_item": it["id"], "title": it["title"],
                "verifier_role": role, "state": state,
                "age_hours": int(it["age_hours"] or 0),
                "missing_gates": missing,
                "fallback": CONF["FALLBACK_VERIFIER"],
            })
    return findings


# ---------------------------------------------------------- step 5: routing

def register():
    """Claim the role-coordinator address, so chats have somewhere to send a
    question. Found live on 2026-09-23: the daemon was posting checkpoints but
    had never registered, so it had no mailbox and its own inbox was empty by
    construction. Registering is idempotent and doubles as a heartbeat."""
    if DRY:
        note("WOULD REGISTER %s as role %s" % (CONF["CHAT_ID"], CONF["ROLE"]))
        return
    try:
        hub("/chats/register", {
            "chat_id": CONF["CHAT_ID"], "account": "daemon", "role": CONF["ROLE"],
            "topics": ["coordination", "role-planner", "routing"],
            "description": "Chat role-coordinator daemon: tracks Planner work across chats, "
                           "chases quiet claims, writes completions and blockers back, "
                           "and routes questions a chat cannot address itself.",
        })
    except RuntimeError as e:
        note("could not register: %s" % e)


def route_inbox():
    """Questions sent to the role-coordinator, forwarded by the ladder:
    assignment, then topic, then word evidence, then a topic broadcast, then
    the digest. Never back to the sender."""
    try:
        inbox = hub("/mailbox/inbox?chat_id=" + CONF["CHAT_ID"])
    except RuntimeError as e:
        note("inbox unreadable: %s" % e)
        return [], []
    messages = inbox if isinstance(inbox, list) else inbox.get("messages", [])
    routed, unroutable = [], []
    if not messages:
        return routed, unroutable

    topics = {}
    for t in rows("""SELECT unnest(topics) AS topic, chat_id
                     FROM knowledge_hub.active_chats WHERE closed_at IS NULL"""):
        topics.setdefault(t["topic"], []).append(t["chat_id"])

    for m in messages:
        sender = m.get("from_chat")
        text = "%s %s" % (m.get("subject", ""), m.get("body", ""))
        decision = None

        # Rung 1 — assignment. The question names a task someone claimed.
        ref = TASK_REF.search(text)
        if ref:
            owner = rows("""SELECT tt.chat_id, c.role
                            FROM knowledge_hub.tracked_tasks tt
                            LEFT JOIN knowledge_hub.active_chats c ON c.chat_id = tt.chat_id
                            WHERE tt.planner_task_id = %d AND tt.status <> 'complete'
                            ORDER BY tt.last_status_update DESC LIMIT 1""" % int(ref.group(1)))
            if owner and owner[0]["chat_id"] != sender:
                decision = ("to_chat", owner[0]["chat_id"],
                            "assigned to Planner task %s" % ref.group(1))

        # Rung 2 — topic, matched on the topic words themselves.
        if decision is None:
            best = pick_topic(text, sender, topics, exclude=[CONF["CHAT_ID"]])
            if best:
                decision = ("to_topic", best, "topic match")

        # Rung 3 — word evidence, the hub's own ranking, sender excluded.
        if decision is None:
            try:
                q = urllib.parse.quote(text[:400])
                sug = hub("/suggest?task=%s&limit=6" % q)
            except Exception:                        # noqa: BLE001
                sug = {}
            cands = [c for c in sug.get("candidates", [])
                     if c["chat_id"] not in (sender, CONF["CHAT_ID"])]
            if cands:
                best_n = max(c["matched_count"] for c in cands)
                keep = [c for c in cands
                        if c["matched_count"] >= best_n - 1
                        and c["fit"] >= float(CONF["ROUTE_MIN_FIT"])]
                if keep:
                    for c in keep:
                        send_mail("to_chat", c["chat_id"],
                                  "routed: %s" % m.get("subject", "")[:80],
                                  "From %s, routed by the role-coordinator on word evidence "
                                  "(fit %.2f, matched %s).\n\n%s"
                                  % (sender, c["fit"], ", ".join(c.get("matched_words", [])),
                                     m.get("body", "")))
                    routed.append({"message": m.get("id"), "to": [c["chat_id"] for c in keep],
                                   "why": "word evidence", "verdict": sug.get("verdict")})
                    ack(m, "routed to %s on word evidence" % ", ".join(c["chat_id"] for c in keep))
                    continue

        # Rung 4 — broadcast to a topic, never to the whole roster by default.
        if decision is None:
            best = pick_topic(text, sender, topics, exclude=[CONF["CHAT_ID"]])
            if best:
                decision = ("to_topic", best, "broadcast, no single fit")
            elif (CONF["BROADCAST_POLICY"] == "topic+blocking"
                  and m.get("priority") == "blocking"):
                decision = ("roster", None, "blocking, no topic matched")

        # Rung 5 — the digest. Unroutable is reported, not silent.
        if decision is None:
            unroutable.append({"message": m.get("id"), "from": sender,
                               "subject": m.get("subject", "")[:80]})
            continue

        kind, value, why = decision
        if kind == "roster":
            note("message %s is blocking and matched no topic; roster broadcast "
                 "needs a human decision" % m.get("id"))
            unroutable.append({"message": m.get("id"), "from": sender,
                               "subject": m.get("subject", "")[:80], "why": why})
            continue
        send_mail(kind, value, "routed: %s" % m.get("subject", "")[:80],
                  "From %s, routed by the role-coordinator (%s).\n\n%s"
                  % (sender, why, m.get("body", "")),
                  priority=m.get("priority", "normal"))
        routed.append({"message": m.get("id"), "to": value, "why": why})
        ack(m, "routed to %s (%s)" % (value, why))
    return routed, unroutable


def ack(message, note_text):
    if DRY:
        return
    try:
        hub("/mailbox/%s/ack" % message.get("id"),
            {"chat_id": CONF["CHAT_ID"], "ack": True, "note": note_text})
    except RuntimeError as e:
        note("could not ack message %s: %s" % (message.get("id"), e))


# ------------------------------------------------------------ step 6: digest

def embedding_coverage():
    """Chunks with no embedding cannot be retrieved, and nothing said so for ten
    weeks. On 2026-09-27, 8,926 of 13,840 chunks (66%) had none because
    embed_chunks.py is the only writer and nothing scheduled it; retrieval had
    been answering from a third of the corpus since 2026-07-13, confidently.
    rag_verify.sh reads the same table and never flagged it. Reported here so a
    gap is a number on every tick rather than a discovery."""
    try:
        rows = rows_db("""
            SELECT (SELECT count(*) FROM document_chunks) AS chunks,
                   (SELECT count(*) FROM chunk_embeddings) AS embeddings,
                   (SELECT count(*) FROM document_chunks c
                      LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id
                     WHERE e.id IS NULL) AS missing,
                   (SELECT max(created_at)::text FROM chunk_embeddings) AS newest
        """, db="rag_system")
    except RuntimeError as e:
        note("embedding coverage unreadable: %s" % e)
        return None
    if not rows:
        return None
    r = rows[0]
    total = r["chunks"] or 0
    pct = (100.0 * (total - (r["missing"] or 0)) / total) if total else 100.0
    if r["missing"]:
        note("RETRIEVAL GAP: %d of %d chunks have no embedding (%.1f%% covered). "
             "Fix: cd ~/TCS-Software_Projects/_admin/rag_tools && "
             "DATABASE_URL=postgres://rag@localhost:5432/rag_system "
             "~/TCS-Software_Projects/_admin/.venv/bin/python3 ./embed_chunks.py"
             % (r["missing"], total, pct))
    return {"chunks": total, "embeddings": r["embeddings"],
            "missing": r["missing"], "coverage_pct": round(pct, 1),
            "newest_embedding": r["newest"]}


def what_to_work_on(role-planner, limit=5):
    """Deadline, then priority, then blocker elevation. Blocked work is listed
    apart from actionable work: a blocked task is not something Greg can do."""
    actionable = [p for p in role-planner if not p["is_blocked"]]

    def key(p):
        return (0 if p["hard_deadline"] else 1,
                p["due_date"] or "9999-99-99",
                p["priority"] if p["priority"] is not None else 9,
                -(float(p["effective_wsjf"]) if p["effective_wsjf"] else 0.0))

    return sorted(actionable, key=key)[:limit]


def nudge_list(role-planner, claims):
    """Who to push to clear a block, ranked by what the blocker is holding up."""
    blocked = [p for p in role-planner if p["is_blocked"]]
    if not blocked:
        return []
    owner = {}
    for c in claims:
        if c["status"] != "complete":
            owner[c["planner_task_id"]] = c.get("role") or c["chat_id"]
    out = []
    for b in blocked:
        for dep in rows("""SELECT d.depends_on_id AS id, t.title, t.status
                           FROM task_dependencies d JOIN tasks t ON t.id = d.depends_on_id
                           WHERE d.task_id = %d AND t.status <> 'Completed'""" % b["id"]):
            out.append({"blocked_task": b["id"], "blocked_title": b["title"],
                        "blocker": dep["id"], "blocker_title": dep["title"],
                        "nudge": owner.get(dep["id"], "unclaimed"),
                        "blocked_priority": b["priority"]})
    out.sort(key=lambda r: (r["blocked_priority"] or 9))
    return out


def main():
    os.makedirs(WORK, exist_ok=True)
    started = datetime.now(timezone.utc)
    try:
        role-planner, claims = read_state()
    except RuntimeError as e:
        print("SUMMARY role-coordinator: FAILED - %s" % e)
        return 1

    claimed_ids = {c["planner_task_id"] for c in claims if c["status"] != "complete"}
    unclaimed = [p for p in role-planner if p["id"] not in claimed_ids]

    register()
    chased = chase(role-planner, claims)
    closed, blocked, ignored = write_back(role-planner, claims)
    verifiers = check_verifiers()
    routed, unroutable = route_inbox()
    coverage = embedding_coverage()
    nudges = nudge_list(role-planner, claims)
    next_up = what_to_work_on(role-planner)

    report = {
        "run_at": started.isoformat(),
        "dry_run": DRY,
        "open_tasks": len(role-planner),
        "claimed": len(claimed_ids),
        "unclaimed": len(unclaimed),
        "closed_in_planner": closed,
        "blockers_recorded": blocked,
        "reports_ignored": ignored,
        "chased": chased,
        "verifier_findings": verifiers,
        "routed": routed,
        "unroutable": unroutable,
        "nudge_list": nudges,
        "embedding_coverage": coverage,
        "next_up": [{"id": p["id"], "title": p["title"], "priority": p["priority"],
                     "due": p["due_date"]} for p in next_up],
        "notes": NOTES,
    }
    out = os.path.join(WORK, "last_run.json")
    with open(out, "w") as fh:
        json.dump(report, fh, indent=2, default=str)

    # A quiet holder is reported separately from no holder at all: one is a
    # chat to nudge, the other is a post nobody is standing in. Folding them
    # into one number hides which problem it is.
    no_holder = [v for v in verifiers if v["state"] == "no_holder"]
    quiet_holder = [v for v in verifiers if v["state"] == "holder_quiet"]
    summary = ("SUMMARY role-coordinator: %s | open %d | claimed %d | unclaimed %d | "
               "closed %d | blockers %d | chased %d | routed %d | unroutable %d | "
               "verifiers: %d with no holder, %d gone quiet | ignored %d | retrieval %s"
               % ("DRY RUN" if DRY else "LIVE", len(role-planner), len(claimed_ids),
                  len(unclaimed), len(closed), len(blocked), len(chased),
                  len(routed), len(unroutable), len(no_holder), len(quiet_holder),
                  len(ignored),
                  ("%.1f%% covered" % coverage["coverage_pct"]) if coverage else "unknown"))
    print(summary)
    if not DRY:
        try:
            hub("/chats/checkpoint",
                {"chat_id": CONF["CHAT_ID"], "kind": "progress",
                 "summary": summary, "detail": json.dumps(report, default=str)[:4000]})
        except RuntimeError as e:
            print("note: checkpoint not posted (%s)" % e)
    return 0


def selftest():
    """Exercise the decisions that live data cannot reach yet.

    work_items and work_item_gates are empty, and no chat has reported blocked,
    so a live run reports zeros for the verifier and blocker paths. Zeros prove
    nothing, hence this.
    """
    checks, failed = 0, []

    def ok(name, got, want):
        nonlocal checks
        checks += 1
        if got != want:
            failed.append("%s: got %r, wanted %r" % (name, got, want))

    # --- verifier classification -------------------------------------------
    live = [{"chat_id": "a", "silent_hours": 0.5}]
    quiet = [{"chat_id": "a", "silent_hours": 220.0}]
    ok("verifier: responsive holder", classify_verifier(live, 24), "ok")
    ok("verifier: silent holder", classify_verifier(quiet, 24), "holder_quiet")
    ok("verifier: no holder at all", classify_verifier([], 24), "no_holder")
    ok("verifier: one live among silent",
       classify_verifier(quiet + live, 24), "ok")
    # The real case behind this feature: role-recovery's verifier is `role-dedupe`,
    # whose chat has been silent for days. It must not read as ok.
    ok("verifier: the role-recovery case",
       classify_verifier([{"chat_id": "role-dedupe-<HOST>-2", "silent_hours": 240.0}], 24),
       "holder_quiet")

    # --- blocked_by parsing -------------------------------------------------
    for text, want in (("task 62", "62"), ("Task #62", "62"), ("role-planner:62", "62"),
                       ("#62", "62"), ("blocked on the viewer", None),
                       ("waiting for task 7 to land", "7")):
        m = TASK_REF.search(text)
        ok("blocked_by %r" % text, m.group(1) if m else None, want)

    # --- routing: the sender is never a candidate ---------------------------
    topics = {"mri": ["asker", "other"], "role-dedupe": ["asker"], "viewer": ["third"]}
    ok("topic rung picks a topic others watch",
       pick_topic("question about mri bundles", "asker", topics), "mri")
    ok("topic rung refuses a topic only the asker watches",
       pick_topic("a role-dedupe question", "asker", topics), None)
    ok("topic rung finds nothing when no topic is named",
       pick_topic("where is the welding paperwork", "asker", topics), None)
    ok("topic rung prefers the wider audience",
       pick_topic("mri viewer question", "asker", topics), "mri")
    # The loop found live on 2026-09-23: a message containing the word
    # "routing" matched the role-coordinator's own topic, whose only subscriber was
    # the role-coordinator. Routed to itself, it would come back every tick.
    self_only = {"routing": ["role-coordinator"], "mri": ["asker", "other"]}
    ok("never routes to a topic only the daemon watches",
       pick_topic("routing test about welding", "asker", self_only,
                  exclude=["role-coordinator"]), None)
    ok("still routes when others watch the topic",
       pick_topic("routing question about mri", "asker", self_only,
                  exclude=["role-coordinator"]), "mri")

    # --- ordering: deadline, then priority, then elevation ------------------
    tasks = [
        {"id": 1, "is_blocked": False, "hard_deadline": False, "due_date": "2026-12-01",
         "priority": 1, "effective_wsjf": None, "title": "", "elevated": False},
        {"id": 2, "is_blocked": False, "hard_deadline": True, "due_date": "2027-01-01",
         "priority": 5, "effective_wsjf": None, "title": "", "elevated": False},
        {"id": 3, "is_blocked": False, "hard_deadline": False, "due_date": "2026-11-01",
         "priority": 3, "effective_wsjf": None, "title": "", "elevated": False},
        {"id": 4, "is_blocked": True, "hard_deadline": True, "due_date": "2026-01-01",
         "priority": 1, "effective_wsjf": None, "title": "", "elevated": False},
        {"id": 5, "is_blocked": False, "hard_deadline": False, "due_date": "2026-11-01",
         "priority": 3, "effective_wsjf": 9.0, "title": "", "elevated": True},
    ]
    order = [t["id"] for t in what_to_work_on(tasks, limit=9)]
    ok("hard deadline first", order[0], 2)
    ok("blocked work is never offered", 4 in order, False)
    ok("earlier due date beats higher priority", order.index(3) < order.index(1), True)
    ok("elevation breaks a tie", order.index(5) < order.index(3), True)

    print("SUMMARY role-coordinator selftest: %s | checks %d | failed %d"
          % ("PASS" if not failed else "FAIL", checks, len(failed)))
    for f in failed:
        print("  FAILED " + f)
    return 0 if not failed else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
