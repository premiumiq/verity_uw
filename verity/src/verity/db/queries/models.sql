-- ============================================================
-- MODEL MANAGEMENT QUERIES
-- ============================================================
-- CRUD on the `model` catalog, SCD-2 writes on `model_price`,
-- invocation-log writes, and cost-aware aggregation queries used
-- by the /admin/usage dashboard and the /api/v1/models/* endpoints.


-- ── MODEL CATALOG ────────────────────────────────────────────

-- name: insert_model
INSERT INTO model (
    provider, model_id, display_name, modality,
    context_window, status, description
)
VALUES (
    %(provider)s, %(model_id)s, %(display_name)s, %(modality)s,
    %(context_window)s, %(status)s, %(description)s
)
RETURNING id, created_at;


-- name: list_models
-- All models ordered provider→name. Used by the admin UI.
SELECT
    m.*,
    mp.input_price_per_1m,
    mp.output_price_per_1m,
    mp.cache_read_price_per_1m,
    mp.cache_write_price_per_1m,
    mp.currency,
    mp.valid_from   AS price_valid_from,
    mp.created_at   AS price_set_at
FROM model m
LEFT JOIN model_price mp
  ON mp.model_id = m.id AND mp.valid_to IS NULL
ORDER BY m.provider, m.model_id;


-- name: get_model_by_id
SELECT * FROM model WHERE id = %(model_id)s::uuid;


-- name: get_model_by_provider_and_model_id
-- Canonical lookup used to resolve an Anthropic response's model
-- string back to a model row at invocation-log write time.
SELECT * FROM model
WHERE provider = %(provider)s AND model_id = %(model_id)s;


-- name: update_model
-- Freeform update of metadata columns (not price). Status changes
-- to 'deprecated' live here too — the invocation log uses model_id
-- so deprecated models continue to resolve for historical records.
UPDATE model SET
    display_name   = COALESCE(%(display_name)s,   display_name),
    modality       = COALESCE(%(modality)s,       modality),
    context_window = COALESCE(%(context_window)s, context_window),
    status         = COALESCE(%(status)s,         status),
    description    = COALESCE(%(description)s,    description)
WHERE id = %(model_id)s::uuid
RETURNING id;


-- ── MODEL PRICE (SCD-2) ──────────────────────────────────────

-- name: get_current_price_for_model
-- One currently-active price row, if any. The unique index
-- uq_mp_active enforces at-most-one at the DB level.
SELECT * FROM model_price
WHERE model_id = %(model_id)s::uuid AND valid_to IS NULL
LIMIT 1;


-- name: get_price_at
-- Price row whose validity window contains the given timestamp.
-- Used for ad-hoc historical lookups; the cost view uses the
-- same join logic inline.
SELECT * FROM model_price
WHERE model_id = %(model_id)s::uuid
  AND valid_from <= %(at)s
  AND (valid_to IS NULL OR valid_to > %(at)s)
LIMIT 1;


-- name: list_prices_for_model
-- Full price history for a model (newest first).
SELECT * FROM model_price
WHERE model_id = %(model_id)s::uuid
ORDER BY valid_from DESC;


-- name: close_current_price
-- Set valid_to on the currently-active row so a new one can slot in.
UPDATE model_price
SET valid_to = %(valid_to)s
WHERE model_id = %(model_id)s::uuid AND valid_to IS NULL
RETURNING id;


-- name: insert_price
INSERT INTO model_price (
    model_id,
    input_price_per_1m, output_price_per_1m,
    cache_read_price_per_1m, cache_write_price_per_1m,
    currency, valid_from, valid_to, notes
)
VALUES (
    %(model_id)s::uuid,
    %(input_price_per_1m)s, %(output_price_per_1m)s,
    %(cache_read_price_per_1m)s, %(cache_write_price_per_1m)s,
    %(currency)s, %(valid_from)s, %(valid_to)s, %(notes)s
)
RETURNING id, valid_from;


-- ── MODEL INVOCATION LOG ─────────────────────────────────────

-- name: insert_model_invocation
-- Written by the engine after each agent/task decision. Tokens are
-- summed across turns within the decision; per_turn_metadata keeps
-- the per-turn details in JSONB for drill-through.
INSERT INTO model_invocation_log (
    decision_log_id, model_id, provider, model_name,
    started_at, completed_at,
    input_tokens, output_tokens,
    cache_creation_input_tokens, cache_read_input_tokens,
    api_call_count, stop_reason,
    status, error_message, per_turn_metadata
)
VALUES (
    %(decision_log_id)s::uuid, %(model_id)s::uuid,
    %(provider)s, %(model_name)s,
    %(started_at)s, %(completed_at)s,
    %(input_tokens)s, %(output_tokens)s,
    %(cache_creation_input_tokens)s, %(cache_read_input_tokens)s,
    %(api_call_count)s, %(stop_reason)s,
    %(status)s, %(error_message)s, %(per_turn_metadata)s
)
RETURNING id, created_at;


-- name: get_invocation_by_decision
-- The invocation row for a single decision (drill-through from the
-- decision detail page).
SELECT * FROM v_model_invocation_cost
WHERE decision_log_id = %(decision_log_id)s::uuid;


-- ── AGGREGATION QUERIES FOR /admin/usage ─────────────────────
-- All roll up the cost view. Each is filterable by a date window
-- and by an optional application-name array (the same filter the
-- home dashboard carries on ?apps=). When %(app_names)s is an empty
-- array, the OR branch never fires and the global scope applies.


-- name: usage_totals
-- Top-of-page summary tiles: totals across the window. Every column
-- is qualified with `v.` because agent_decision_log (joined-in for
-- the application-name filter) also exposes input_tokens/output_tokens
-- — referring to either plain would be ambiguous.
SELECT
    COUNT(*)                                         AS invocation_count,
    COALESCE(SUM(v.input_tokens),                0) AS input_tokens,
    COALESCE(SUM(v.output_tokens),               0) AS output_tokens,
    COALESCE(SUM(v.cache_creation_input_tokens), 0) AS cache_write_tokens,
    COALESCE(SUM(v.cache_read_input_tokens),     0) AS cache_read_tokens,
    COALESCE(SUM(v.total_cost_usd),              0) AS total_cost_usd,
    COALESCE(SUM(v.input_cost_usd),              0) AS input_cost_usd,
    COALESCE(SUM(v.output_cost_usd),             0) AS output_cost_usd,
    COALESCE(SUM(v.cache_write_cost_usd),        0) AS cache_write_cost_usd,
    COALESCE(SUM(v.cache_read_cost_usd),         0) AS cache_read_cost_usd
FROM v_model_invocation_cost v
JOIN agent_decision_log adl ON adl.id = v.decision_log_id
WHERE v.started_at >= %(from_ts)s
  AND v.started_at <  %(to_ts)s
  AND (
        cardinality(%(app_names)s::text[]) = 0
     OR adl.application = ANY(%(app_names)s::text[])
  );


-- name: usage_by_model
SELECT
    v.provider,
    v.model_name,
    COUNT(*)                                AS invocation_count,
    COALESCE(SUM(v.input_tokens),  0)       AS input_tokens,
    COALESCE(SUM(v.output_tokens), 0)       AS output_tokens,
    COALESCE(SUM(v.total_cost_usd), 0)      AS total_cost_usd
FROM v_model_invocation_cost v
JOIN agent_decision_log adl ON adl.id = v.decision_log_id
WHERE v.started_at >= %(from_ts)s
  AND v.started_at <  %(to_ts)s
  AND (cardinality(%(app_names)s::text[]) = 0 OR adl.application = ANY(%(app_names)s::text[]))
GROUP BY v.provider, v.model_name
ORDER BY total_cost_usd DESC;


-- name: usage_by_agent
-- Breakdown by agent. entity_name is pulled from the agent row
-- by joining through agent_version.
SELECT
    a.name                              AS entity_name,
    a.display_name                      AS entity_display_name,
    COUNT(*)                            AS invocation_count,
    COALESCE(SUM(v.input_tokens),  0)   AS input_tokens,
    COALESCE(SUM(v.output_tokens), 0)   AS output_tokens,
    COALESCE(SUM(v.total_cost_usd), 0)  AS total_cost_usd,
    COALESCE(SUM(CASE WHEN v.status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_count
FROM v_model_invocation_cost v
JOIN agent_decision_log adl ON adl.id = v.decision_log_id
JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
JOIN agent a ON a.id = av.agent_id
WHERE v.started_at >= %(from_ts)s
  AND v.started_at <  %(to_ts)s
  AND (cardinality(%(app_names)s::text[]) = 0 OR adl.application = ANY(%(app_names)s::text[]))
GROUP BY a.name, a.display_name
ORDER BY total_cost_usd DESC;


-- name: usage_by_task
SELECT
    t.name                              AS entity_name,
    t.display_name                      AS entity_display_name,
    COUNT(*)                            AS invocation_count,
    COALESCE(SUM(v.input_tokens),  0)   AS input_tokens,
    COALESCE(SUM(v.output_tokens), 0)   AS output_tokens,
    COALESCE(SUM(v.total_cost_usd), 0)  AS total_cost_usd,
    COALESCE(SUM(CASE WHEN v.status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_count
FROM v_model_invocation_cost v
JOIN agent_decision_log adl ON adl.id = v.decision_log_id
JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
JOIN task t ON t.id = tv.task_id
WHERE v.started_at >= %(from_ts)s
  AND v.started_at <  %(to_ts)s
  AND (cardinality(%(app_names)s::text[]) = 0 OR adl.application = ANY(%(app_names)s::text[]))
GROUP BY t.name, t.display_name
ORDER BY total_cost_usd DESC;


-- name: usage_by_application
-- Uses the decision's `application` VARCHAR column — matches the
-- attribution model used everywhere else (decisions, purge, etc).
SELECT
    COALESCE(adl.application, '(none)')    AS application,
    COUNT(*)                                AS invocation_count,
    COALESCE(SUM(v.input_tokens),  0)       AS input_tokens,
    COALESCE(SUM(v.output_tokens), 0)       AS output_tokens,
    COALESCE(SUM(v.total_cost_usd), 0)      AS total_cost_usd
FROM v_model_invocation_cost v
JOIN agent_decision_log adl ON adl.id = v.decision_log_id
WHERE v.started_at >= %(from_ts)s
  AND v.started_at <  %(to_ts)s
  AND (cardinality(%(app_names)s::text[]) = 0 OR adl.application = ANY(%(app_names)s::text[]))
GROUP BY adl.application
ORDER BY total_cost_usd DESC;


-- name: usage_over_time_daily
-- Daily time-series of cost + tokens, useful for the "Usage over time"
-- chart on the dashboard.
SELECT
    date_trunc('day', v.started_at) AS bucket,
    COUNT(*)                         AS invocation_count,
    COALESCE(SUM(v.input_tokens),  0) AS input_tokens,
    COALESCE(SUM(v.output_tokens), 0) AS output_tokens,
    COALESCE(SUM(v.total_cost_usd), 0) AS total_cost_usd
FROM v_model_invocation_cost v
JOIN agent_decision_log adl ON adl.id = v.decision_log_id
WHERE v.started_at >= %(from_ts)s
  AND v.started_at <  %(to_ts)s
  AND (cardinality(%(app_names)s::text[]) = 0 OR adl.application = ANY(%(app_names)s::text[]))
GROUP BY bucket
ORDER BY bucket;


-- ── inference_config → model backfill ────────────────────────

-- name: backfill_inference_config_model_id
-- Called once after seeding the model catalog; sets model_id on
-- every inference_config row whose model_id is NULL but whose
-- text model_name matches a registered model.model_id.
UPDATE inference_config ic
SET model_id = m.id
FROM model m
WHERE ic.model_id IS NULL
  AND ic.model_name = m.model_id
RETURNING ic.id, ic.model_name, m.id AS resolved_model_id;
