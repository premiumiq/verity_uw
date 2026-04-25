-- ============================================================
-- RUN QUERIES
-- Async task / agent run submission, claim, heartbeat, terminate.
-- All writes are INSERTs only — run state is event-sourced across
-- four append-only tables (execution_run, execution_run_status,
-- execution_run_completion, execution_run_error). Reads go through
-- the execution_run_current view that surfaces the resolved status.
-- ============================================================

-- name: insert_execution_run
-- The submission row. Inserted once at submit time; never updated.
-- Caller pre-generates the UUID so the same id can be threaded
-- through the matching execution_run_status('submitted') row in the
-- same transaction.
INSERT INTO execution_run (
    id,
    entity_kind, entity_version_id, entity_name,
    channel, input_json,
    execution_context_id, workflow_run_id, parent_decision_id,
    application, mock_mode, write_mode, enforce_output_schema,
    submitted_by
)
VALUES (
    %(id)s,
    %(entity_kind)s, %(entity_version_id)s, %(entity_name)s,
    %(channel)s, %(input_json)s,
    %(execution_context_id)s, %(workflow_run_id)s, %(parent_decision_id)s,
    %(application)s, %(mock_mode)s, %(write_mode)s, %(enforce_output_schema)s,
    %(submitted_by)s
)
RETURNING id, submitted_at;


-- name: insert_execution_run_status
-- One row per state transition. Event types:
--   'submitted' — written transactionally with the execution_run row.
--   'claimed'   — written by the worker that takes ownership.
--   'heartbeat' — written periodically by the claiming worker.
--   'released'  — written when a worker hands the run back (graceful
--                 shutdown) or a janitor re-queues a stuck claim.
INSERT INTO execution_run_status (
    execution_run_id, status, worker_id, notes
)
VALUES (
    %(execution_run_id)s, %(status)s, %(worker_id)s, %(notes)s
)
RETURNING id, recorded_at;


-- name: claim_next_execution_run
-- Atomic claim cycle. Picks the oldest available run (current_status
-- IN ('submitted','released'), no terminal completion/error row) under
-- FOR UPDATE SKIP LOCKED, then inserts a 'claimed' status row in the
-- same transaction. Returns the full execution_run row so the worker
-- can dispatch it without a second round-trip.
--
-- The "available" predicate is computed inline rather than reading
-- execution_run_current — the view's LATERAL joins don't compose well
-- with FOR UPDATE, and the row-level lock has to be held on
-- execution_run, not on a derived view row.
WITH candidate AS (
    SELECT r.id
    FROM execution_run r
    WHERE NOT EXISTS (
        SELECT 1 FROM execution_run_completion c WHERE c.execution_run_id = r.id
    )
      AND NOT EXISTS (
        SELECT 1 FROM execution_run_error e WHERE e.execution_run_id = r.id
    )
      AND COALESCE(
          (SELECT status FROM execution_run_status s
           WHERE s.execution_run_id = r.id
           ORDER BY s.recorded_at DESC LIMIT 1),
          'submitted'
      ) IN ('submitted', 'released')
    ORDER BY r.submitted_at
    LIMIT 1
    FOR UPDATE OF r SKIP LOCKED
),
claim AS (
    INSERT INTO execution_run_status (execution_run_id, status, worker_id)
    SELECT candidate.id, 'claimed', %(worker_id)s FROM candidate
    RETURNING execution_run_id
)
SELECT r.*
FROM execution_run r
JOIN claim ON claim.execution_run_id = r.id;


-- name: heartbeat_execution_run
-- Worker's periodic proof-of-life for a claimed run. Inserts a
-- 'heartbeat' status row. The janitor uses the most recent recorded_at
-- to detect stuck runs.
INSERT INTO execution_run_status (execution_run_id, status, worker_id)
VALUES (%(execution_run_id)s, 'heartbeat', %(worker_id)s)
RETURNING id, recorded_at;


-- name: release_execution_run
-- Worker hands the run back without a terminal outcome. Used on
-- graceful shutdown (SIGTERM) and by the janitor to re-queue stuck
-- claims. Next claim cycle will re-pick the run.
INSERT INTO execution_run_status (execution_run_id, status, worker_id, notes)
VALUES (%(execution_run_id)s, 'released', %(worker_id)s, %(notes)s)
RETURNING id, recorded_at;


-- name: insert_execution_run_completion
-- Terminal-success row. UNIQUE on execution_run_id ensures only one
-- terminal row per run. final_status is 'complete' for a normal
-- successful run; 'cancelled' for a run that was terminated on
-- request (pre-claim or mid-run).
INSERT INTO execution_run_completion (
    execution_run_id, final_status, decision_log_id, duration_ms, worker_id
)
VALUES (
    %(execution_run_id)s, %(final_status)s, %(decision_log_id)s,
    %(duration_ms)s, %(worker_id)s
)
RETURNING id, completed_at;


-- name: insert_execution_run_error
-- Terminal-failure row. UNIQUE on execution_run_id. decision_log_id
-- is populated when a partial audit row was written before the
-- failure surfaced (e.g. an LLM call that timed out post-prompt-build).
INSERT INTO execution_run_error (
    execution_run_id, error_code, error_message, error_trace,
    worker_id, decision_log_id
)
VALUES (
    %(execution_run_id)s, %(error_code)s, %(error_message)s, %(error_trace)s,
    %(worker_id)s, %(decision_log_id)s
)
RETURNING id, failed_at;


-- name: get_run_current
-- Single-run state read. The view resolves status precedence
-- (completion > error > latest status_event) so callers see one
-- current_status field. Enriched with the entity's owner display_name
-- (task.display_name or agent.display_name) and the application's
-- display_name so the UI never has to render the raw internal name.
SELECT
    erc.*,
    COALESCE(t.display_name, ag.display_name)  AS entity_display_name,
    app.display_name                            AS application_display_name
FROM execution_run_current erc
LEFT JOIN task_version tv  ON tv.id = erc.entity_version_id  AND erc.entity_kind = 'task'
LEFT JOIN task t           ON t.id  = tv.task_id
LEFT JOIN agent_version av ON av.id = erc.entity_version_id  AND erc.entity_kind = 'agent'
LEFT JOIN agent ag         ON ag.id = av.agent_id
LEFT JOIN application app  ON app.name = erc.application
WHERE erc.id = %(run_id)s;


-- name: list_runs_current
-- Filtered list backing the Runs UI. All filters are optional; passing
-- NULL for a filter disables it. Sorted by submitted_at desc by default
-- (most recent first). Pagination via limit/offset.
--
-- Enriched with entity_display_name (the task or agent's owner-facing
-- display_name from task/agent tables) and application_display_name
-- (from application.display_name). LEFT JOINs because demo data and
-- ad-hoc test runs may reference rows that no longer exist; we surface
-- raw fallbacks rather than hiding the run.
SELECT
    erc.*,
    COALESCE(t.display_name, ag.display_name)  AS entity_display_name,
    app.display_name                            AS application_display_name
FROM execution_run_current erc
LEFT JOIN task_version tv  ON tv.id = erc.entity_version_id  AND erc.entity_kind = 'task'
LEFT JOIN task t           ON t.id  = tv.task_id
LEFT JOIN agent_version av ON av.id = erc.entity_version_id  AND erc.entity_kind = 'agent'
LEFT JOIN agent ag         ON ag.id = av.agent_id
LEFT JOIN application app  ON app.name = erc.application
WHERE (%(execution_context_id)s::uuid IS NULL OR erc.execution_context_id = %(execution_context_id)s::uuid)
  AND (%(workflow_run_id)s::uuid IS NULL OR erc.workflow_run_id = %(workflow_run_id)s::uuid)
  AND (%(entity_kind)s::text IS NULL OR erc.entity_kind = %(entity_kind)s::text)
  AND (%(entity_name)s::text IS NULL OR erc.entity_name = %(entity_name)s::text)
  AND (%(channel)s::text IS NULL OR erc.channel::text = %(channel)s::text)
  AND (%(application)s::text IS NULL OR erc.application = %(application)s::text)
  AND (%(status)s::text IS NULL OR erc.current_status = %(status)s::text)
ORDER BY erc.submitted_at DESC
LIMIT %(limit)s OFFSET %(offset)s;


-- name: count_runs_current
-- Total count for pagination. Same filter set as list_runs_current.
SELECT COUNT(*) AS total
FROM execution_run_current
WHERE (%(execution_context_id)s::uuid IS NULL OR execution_context_id = %(execution_context_id)s::uuid)
  AND (%(workflow_run_id)s::uuid IS NULL OR workflow_run_id = %(workflow_run_id)s::uuid)
  AND (%(entity_kind)s::text IS NULL OR entity_kind = %(entity_kind)s::text)
  AND (%(entity_name)s::text IS NULL OR entity_name = %(entity_name)s::text)
  AND (%(channel)s::text IS NULL OR channel::text = %(channel)s::text)
  AND (%(application)s::text IS NULL OR application = %(application)s::text)
  AND (%(status)s::text IS NULL OR current_status = %(status)s::text);


-- name: list_runs_filter_applications
-- Distinct (name, display_name) pairs for every application that has
-- at least one execution_run row. Drives the Application dropdown on
-- the Runs UI — cheaper than listing every registered application,
-- and avoids dropdown items that would yield zero results.
SELECT DISTINCT
    erc.application                AS name,
    COALESCE(app.display_name,
             erc.application)      AS display_name
FROM execution_run_current erc
LEFT JOIN application app ON app.name = erc.application
ORDER BY display_name;


-- name: get_run_lifecycle
-- Full event sequence for one run — all status rows in time order,
-- followed by the completion or error row if present. Used by the
-- run-detail UI's lifecycle drill-through. Returns a unioned shape
-- with a discriminator column (event_table) so callers can render
-- them in one timeline view.
SELECT
    'status'::text     AS event_table,
    s.id               AS event_id,
    s.recorded_at      AS occurred_at,
    s.status           AS event_kind,
    s.worker_id        AS worker_id,
    s.notes            AS notes,
    NULL::text         AS error_code,
    NULL::text         AS error_message,
    NULL::uuid         AS decision_log_id,
    NULL::integer      AS duration_ms
FROM execution_run_status s
WHERE s.execution_run_id = %(run_id)s
UNION ALL
SELECT
    'completion'::text,
    c.id,
    c.completed_at,
    c.final_status,
    c.worker_id,
    NULL,
    NULL,
    NULL,
    c.decision_log_id,
    c.duration_ms
FROM execution_run_completion c
WHERE c.execution_run_id = %(run_id)s
UNION ALL
SELECT
    'error'::text,
    e.id,
    e.failed_at,
    'failed'::text,
    e.worker_id,
    NULL,
    e.error_code,
    e.error_message,
    e.decision_log_id,
    NULL
FROM execution_run_error e
WHERE e.execution_run_id = %(run_id)s
ORDER BY occurred_at;


-- name: list_runs_for_workflow
-- Convenience: every run for one workflow_run_id, surfaced with its
-- current state. Drives the Workflow detail page. Enriched with
-- display names so the page can render task/agent and application
-- by their human-readable labels.
SELECT
    erc.*,
    COALESCE(t.display_name, ag.display_name)  AS entity_display_name,
    app.display_name                            AS application_display_name
FROM execution_run_current erc
LEFT JOIN task_version tv  ON tv.id = erc.entity_version_id  AND erc.entity_kind = 'task'
LEFT JOIN task t           ON t.id  = tv.task_id
LEFT JOIN agent_version av ON av.id = erc.entity_version_id  AND erc.entity_kind = 'agent'
LEFT JOIN agent ag         ON ag.id = av.agent_id
LEFT JOIN application app  ON app.name = erc.application
WHERE erc.workflow_run_id = %(workflow_run_id)s
ORDER BY erc.submitted_at;


-- name: list_runs_for_execution_context
-- Convenience: every run for one execution_context_id (i.e. one
-- business entity, like a submission). Drives the submission's
-- "View in Verity" deep-link.
SELECT
    erc.*,
    COALESCE(t.display_name, ag.display_name)  AS entity_display_name,
    app.display_name                            AS application_display_name
FROM execution_run_current erc
LEFT JOIN task_version tv  ON tv.id = erc.entity_version_id  AND erc.entity_kind = 'task'
LEFT JOIN task t           ON t.id  = tv.task_id
LEFT JOIN agent_version av ON av.id = erc.entity_version_id  AND erc.entity_kind = 'agent'
LEFT JOIN agent ag         ON ag.id = av.agent_id
LEFT JOIN application app  ON app.name = erc.application
WHERE erc.execution_context_id = %(execution_context_id)s
ORDER BY erc.submitted_at;


-- name: janitor_reclaim_stuck_runs
-- Releases runs whose latest claimed/heartbeat status is older than the
-- caller-supplied threshold. Inserts a 'released' status row for each,
-- making them re-claimable by the next claim cycle. Idempotent: a
-- second run inserts more 'released' rows but the predicate excludes
-- runs that already have a recent 'released' or any terminal row.
INSERT INTO execution_run_status (execution_run_id, status, worker_id, notes)
SELECT r.id, 'released', %(janitor_id)s, 'reclaimed by janitor'
FROM execution_run r
WHERE NOT EXISTS (
    SELECT 1 FROM execution_run_completion c WHERE c.execution_run_id = r.id
)
  AND NOT EXISTS (
    SELECT 1 FROM execution_run_error e WHERE e.execution_run_id = r.id
)
  AND EXISTS (
    SELECT 1 FROM execution_run_status s
    WHERE s.execution_run_id = r.id
      AND s.status IN ('claimed', 'heartbeat')
      AND s.recorded_at < NOW() - %(stuck_threshold)s::interval
      AND s.recorded_at = (
          SELECT MAX(recorded_at) FROM execution_run_status
          WHERE execution_run_id = r.id
      )
)
RETURNING execution_run_id, recorded_at;


-- name: cancel_execution_run
-- Insert a terminal 'cancelled' completion row. Used by the
-- POST /runs/{id}/cancel endpoint. If the run was already terminal
-- (completion or error row exists), this INSERT violates the UNIQUE
-- constraint and the caller treats that as "already done" — same
-- semantics as a no-op cancel.
INSERT INTO execution_run_completion (
    execution_run_id, final_status, worker_id
)
VALUES (
    %(execution_run_id)s, 'cancelled', %(worker_id)s
)
RETURNING id, completed_at;
