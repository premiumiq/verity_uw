-- ============================================================
-- QUOTA QUERIES
-- ============================================================
-- CRUD on `quota` plus one "compute spend in period" query shared
-- by every scope type (application / agent / task / model). The
-- checker reads that single query once per quota, computes spend
-- pct, and writes a quota_check row.


-- ── CRUD ────────────────────────────────────────────────────

-- name: insert_quota
INSERT INTO quota (
    scope_type, scope_id, scope_name,
    period, budget_usd, alert_threshold_pct,
    hard_stop, enabled, notes
)
VALUES (
    %(scope_type)s, %(scope_id)s::uuid, %(scope_name)s,
    %(period)s, %(budget_usd)s, %(alert_threshold_pct)s,
    %(hard_stop)s, %(enabled)s, %(notes)s
)
RETURNING id, created_at;


-- name: list_quotas
-- Most-recently created first. The admin UI also joins the latest
-- quota_check (if any) for the inline "last check" summary — that
-- join is done in a separate query to keep this one simple.
--
-- scope_display_name is resolved at query time by LEFT JOINing the
-- canonical table for each scope_type. The stored scope_name stays
-- the machine name (uw_demo / appetite_agent / claude-sonnet-4-…)
-- because the spend queries match against exactly that column in
-- decision_log / agent / task / model; changing it would break the
-- checker. Display-only names surface here.
SELECT
    q.*,
    COALESCE(
        app.display_name,
        a.display_name,
        t.display_name,
        m.display_name,
        q.scope_name
    ) AS scope_display_name
FROM quota q
LEFT JOIN application app ON q.scope_type = 'application' AND app.id = q.scope_id
LEFT JOIN agent       a   ON q.scope_type = 'agent'       AND a.id   = q.scope_id
LEFT JOIN task        t   ON q.scope_type = 'task'        AND t.id   = q.scope_id
LEFT JOIN model       m   ON q.scope_type = 'model'       AND m.id   = q.scope_id
ORDER BY q.created_at DESC;


-- name: get_quota_by_id
SELECT * FROM quota WHERE id = %(id)s::uuid;


-- name: update_quota
-- Partial update — caller supplies NULL for any field it doesn't
-- want to change. scope_type / scope_id / scope_name are NOT
-- updatable here; re-create the quota if you need to change scope.
UPDATE quota SET
    period              = COALESCE(%(period)s, period),
    budget_usd          = COALESCE(%(budget_usd)s, budget_usd),
    alert_threshold_pct = COALESCE(%(alert_threshold_pct)s::integer, alert_threshold_pct),
    hard_stop           = COALESCE(%(hard_stop)s::boolean, hard_stop),
    enabled             = COALESCE(%(enabled)s::boolean, enabled),
    notes               = COALESCE(%(notes)s, notes),
    updated_at          = NOW()
WHERE id = %(id)s::uuid
RETURNING id;


-- name: delete_quota
DELETE FROM quota WHERE id = %(id)s::uuid RETURNING id;


-- ── SPEND COMPUTATION (the core of the checker) ───────────
-- Each of these returns one row: total_cost_usd across the given
-- [from_ts, to_ts) window, filtered by the quota's scope. The
-- checker picks the right query based on scope_type. The same
-- v_model_invocation_cost view the Usage dashboard uses is the
-- source of truth — cost is always computed from the price row
-- whose validity window contains the invocation's started_at.

-- name: quota_spend_by_application
-- Application scope — match by application VARCHAR name (same
-- predicate as the purge/activity queries for consistency) OR via
-- execution_context.application_id for REST-initiated runs tagged
-- with the server's 'default' identity.
SELECT
    COALESCE(SUM(v.total_cost_usd), 0)::numeric(14,4) AS total_cost_usd,
    COUNT(*)::int                                     AS invocation_count
FROM v_model_invocation_cost v
JOIN agent_decision_log adl ON adl.id = v.decision_log_id
WHERE v.started_at >= %(from_ts)s
  AND v.started_at <  %(to_ts)s
  AND (
        adl.application = %(scope_name)s
     OR adl.execution_context_id IN (
            SELECT id FROM execution_context WHERE application_id = %(scope_id)s::uuid
        )
  );


-- name: quota_spend_by_agent
-- Agent scope — match by the decision's agent (joined through
-- agent_version). Scopes by agent ID rather than name so renames
-- don't stale-ify the quota.
SELECT
    COALESCE(SUM(v.total_cost_usd), 0)::numeric(14,4) AS total_cost_usd,
    COUNT(*)::int                                     AS invocation_count
FROM v_model_invocation_cost v
JOIN agent_decision_log adl ON adl.id = v.decision_log_id
JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
WHERE v.started_at >= %(from_ts)s
  AND v.started_at <  %(to_ts)s
  AND av.agent_id = %(scope_id)s::uuid;


-- name: quota_spend_by_task
SELECT
    COALESCE(SUM(v.total_cost_usd), 0)::numeric(14,4) AS total_cost_usd,
    COUNT(*)::int                                     AS invocation_count
FROM v_model_invocation_cost v
JOIN agent_decision_log adl ON adl.id = v.decision_log_id
JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
WHERE v.started_at >= %(from_ts)s
  AND v.started_at <  %(to_ts)s
  AND tv.task_id = %(scope_id)s::uuid;


-- name: quota_spend_by_model
-- Model scope — every invocation records model_id directly.
SELECT
    COALESCE(SUM(v.total_cost_usd), 0)::numeric(14,4) AS total_cost_usd,
    COUNT(*)::int                                     AS invocation_count
FROM v_model_invocation_cost v
WHERE v.started_at >= %(from_ts)s
  AND v.started_at <  %(to_ts)s
  AND v.model_id = %(scope_id)s::uuid;


-- ── QUOTA CHECK HISTORY ──────────────────────────────────

-- name: insert_quota_check
INSERT INTO quota_check (
    quota_id, checked_at, period_start, period_end,
    spend_usd, budget_usd, spend_pct,
    alert_fired, alert_level, note
)
VALUES (
    %(quota_id)s::uuid, NOW(), %(period_start)s, %(period_end)s,
    %(spend_usd)s, %(budget_usd)s, %(spend_pct)s,
    %(alert_fired)s, %(alert_level)s, %(note)s
)
RETURNING id, checked_at;


-- name: latest_check_per_quota
-- Most recent quota_check row per quota — used by the admin UI's
-- list page to show "last check" inline. DISTINCT ON picks one
-- row per quota_id, the newest by checked_at.
SELECT DISTINCT ON (quota_id)
    quota_id, checked_at, spend_usd, budget_usd, spend_pct,
    alert_fired, alert_level, resolved_at
FROM quota_check
ORDER BY quota_id, checked_at DESC;


-- name: count_active_breaches
-- Used by the Home dashboard's "Active quota breaches" card.
-- An "active" breach is the most recent check for a quota having
-- alert_fired=true and no resolved_at. DISTINCT ON ensures we
-- don't count an old breach that a newer check has since cleared.
WITH latest AS (
    SELECT DISTINCT ON (quota_id)
        quota_id, alert_fired, resolved_at
    FROM quota_check
    ORDER BY quota_id, checked_at DESC
)
SELECT COUNT(*)::int AS active_breaches
FROM latest
WHERE alert_fired = TRUE AND resolved_at IS NULL;


-- name: list_checks_for_quota
-- Recent check history for the quota detail / list page.
SELECT * FROM quota_check
WHERE quota_id = %(quota_id)s::uuid
ORDER BY checked_at DESC
LIMIT %(limit)s;


-- name: resolve_active_check_for_quota
-- Mark the current active breach (if any) resolved when a newer
-- check comes in below threshold. Only touches the single most-
-- recent alert_fired row whose resolved_at is still NULL.
-- RETURNING yields the resolved row's id when a match was found,
-- and nothing (empty result set) when there was no active breach
-- to resolve — callers detect the no-op via a None return.
UPDATE quota_check SET resolved_at = NOW()
WHERE id = (
    SELECT id FROM quota_check
    WHERE quota_id = %(quota_id)s::uuid
      AND alert_fired = TRUE
      AND resolved_at IS NULL
    ORDER BY checked_at DESC
    LIMIT 1
)
RETURNING id;
