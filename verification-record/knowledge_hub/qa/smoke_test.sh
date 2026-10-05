#!/usr/bin/env bash
set -uo pipefail

PG="${PG_CONTAINER:-<PG-CONTAINER>}"
DB="${PLANNER_DB:-role-planner}"
URL="${ADMIN_ROUTER_URL:-http://127.0.0.1:8765}"
fail=0

echo "== 1. tasks_actionable elevation + blocking (non-destructive; ROLLBACK) =="
out=$(docker exec -i "$PG" psql -U role-planner -d "$DB" -v ON_ERROR_STOP=1 <<'SQL' 2>&1
BEGIN;
WITH
 a AS (INSERT INTO tasks(title,due_date,category,cod_user_value,cod_time_criticality,cod_risk_opportunity,job_size)
       VALUES('demo-A',CURRENT_DATE,'Demo',8,8,5,3) RETURNING id),
 b AS (INSERT INTO tasks(title,due_date,category,cod_user_value,cod_time_criticality,cod_risk_opportunity,job_size)
       VALUES('demo-B',CURRENT_DATE,'Demo',1,1,1,3) RETURNING id),
 c AS (INSERT INTO tasks(title,due_date,category,cod_user_value,cod_time_criticality,cod_risk_opportunity,job_size)
       VALUES('demo-C',CURRENT_DATE,'Demo',1,1,1,3) RETURNING id),
 d AS (INSERT INTO task_dependencies(task_id,depends_on_id)
       SELECT (SELECT id FROM a),(SELECT id FROM b)
       UNION ALL SELECT (SELECT id FROM b),(SELECT id FROM c) RETURNING 1)
SELECT count(*) AS deps_added FROM d;
SELECT title, round(effective_wsjf,2) AS eff, round(wsjf_score,2) AS own,
       elevated, is_blocked, actionable
FROM tasks_actionable WHERE title LIKE 'demo-%'
ORDER BY effective_wsjf DESC NULLS LAST, incomplete_prereqs ASC;
SELECT 'VERDICT: ' || bool_and(chk) FROM (
  SELECT CASE
    WHEN title='demo-C' THEN actionable AND elevated AND NOT is_blocked
    WHEN title IN ('demo-A','demo-B') THEN is_blocked AND round(effective_wsjf,2)=7.00
    ELSE TRUE END AS chk
  FROM tasks_actionable WHERE title LIKE 'demo-%') s;
ROLLBACK;
SQL
)
echo "$out"
if echo "$out" | grep -q 'VERDICT: t'; then echo "  -> elevation/blocking PASS"; else echo "  -> FAIL"; fail=1; fi

echo
echo "== 2. daemon endpoints (skipped if unreachable) =="
if curl -sf "$URL/health" >/dev/null 2>&1; then
  echo "  /health -> $(curl -s "$URL/health")"
  echo "  /next   -> $(curl -s "$URL/next" | head -c 300)"
else
  echo "  daemon not reachable at $URL (start it or set ADMIN_ROUTER_URL) — skipped"
fi

echo
if [ "$fail" -eq 0 ]; then echo "SMOKE: PASS"; else echo "SMOKE: FAIL"; fi
exit "$fail"
