-- ============================================================
-- DECISION QUERIES
-- Log decisions, query audit trails, record overrides
-- ============================================================

-- name: log_decision
-- Insert a decision log entry for every AI invocation (agent, task, or tool).
-- Business context is linked via execution_context_id, NOT direct business keys.
--
-- The `id` column accepts an optional caller-supplied UUID (COALESCE with the
-- column's default uuid_generate_v4()). This lets the runtime pre-generate
-- a decision's UUID at the START of run_agent so that sub-agent calls
-- made during the agentic loop can set their parent_decision_id to this
-- value BEFORE the parent's decision row has actually been written.
-- Added in FC-1 (sub-agent delegation).
INSERT INTO agent_decision_log (
    id,
    entity_type, entity_version_id, prompt_version_ids,
    inference_config_snapshot, channel, mock_mode, pipeline_run_id,
    parent_decision_id, decision_depth, step_name,
    input_summary, input_json, output_json, output_summary,
    reasoning_text, risk_factors, confidence_score, low_confidence_flag,
    model_used, input_tokens, output_tokens, duration_ms,
    tool_calls_made, message_history, application,
    run_purpose, reproduced_from_decision_id,
    execution_context_id,
    hitl_required, status, error_message
)
VALUES (
    COALESCE(%(id)s::uuid, uuid_generate_v4()),
    %(entity_type)s, %(entity_version_id)s, %(prompt_version_ids)s,
    %(inference_config_snapshot)s, %(channel)s, %(mock_mode)s, %(pipeline_run_id)s,
    %(parent_decision_id)s, %(decision_depth)s, %(step_name)s,
    %(input_summary)s, %(input_json)s, %(output_json)s, %(output_summary)s,
    %(reasoning_text)s, %(risk_factors)s, %(confidence_score)s, %(low_confidence_flag)s,
    %(model_used)s, %(input_tokens)s, %(output_tokens)s, %(duration_ms)s,
    %(tool_calls_made)s, %(message_history)s, %(application)s,
    %(run_purpose)s, %(reproduced_from_decision_id)s,
    %(execution_context_id)s,
    %(hitl_required)s, %(status)s, %(error_message)s
)
RETURNING id, created_at;


-- name: get_decision_by_id
SELECT
    adl.*,
    a.name AS agent_name,
    a.display_name AS agent_display_name,
    t.name AS task_name,
    t.display_name AS task_display_name
FROM agent_decision_log adl
LEFT JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
WHERE adl.id = %(decision_id)s;


-- name: list_decisions
-- Paginated list of all decisions with entity names and execution context reference.
SELECT
    adl.id,
    adl.entity_type,
    adl.entity_version_id,
    adl.channel,
    adl.mock_mode,
    adl.pipeline_run_id,
    adl.execution_context_id,
    COALESCE(app.display_name, adl.application) AS application,
    adl.parent_decision_id,
    adl.decision_depth,
    adl.step_name,
    adl.output_summary,
    adl.confidence_score,
    adl.low_confidence_flag,
    adl.model_used,
    adl.input_tokens,
    adl.output_tokens,
    adl.duration_ms,
    adl.status,
    adl.decision_log_detail,
    adl.hitl_required,
    adl.created_at,
    COALESCE(a.display_name, t.display_name) AS entity_name,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(av.version_label, tv.version_label) AS version_label,
    ec.context_ref AS execution_context_ref
FROM agent_decision_log adl
LEFT JOIN application app ON app.name = adl.application
LEFT JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
LEFT JOIN execution_context ec ON ec.id = adl.execution_context_id
ORDER BY adl.created_at DESC
LIMIT %(limit)s OFFSET %(offset)s;


-- name: count_decisions
SELECT COUNT(*) AS total FROM agent_decision_log;


-- name: list_decisions_by_execution_context
-- All decisions for an execution context (e.g., all runs for a submission).
-- Replaces the old list_decisions_by_submission query.
-- The business app registers a context_ref like "submission:SUB-001" and
-- passes the execution_context_id. Verity doesn't know what "submission" means.
SELECT
    adl.id,
    adl.entity_type,
    adl.entity_version_id,
    adl.channel,
    adl.mock_mode,
    adl.pipeline_run_id,
    adl.parent_decision_id,
    adl.decision_depth,
    adl.step_name,
    adl.input_summary,
    adl.output_summary,
    adl.reasoning_text,
    adl.confidence_score,
    adl.risk_factors,
    adl.model_used,
    adl.input_tokens,
    adl.output_tokens,
    adl.duration_ms,
    adl.tool_calls_made,
    adl.hitl_required,
    adl.hitl_completed,
    adl.status,
    adl.created_at,
    COALESCE(a.display_name, t.display_name) AS entity_name,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(av.version_label, tv.version_label) AS version_label,
    t.capability_type
FROM agent_decision_log adl
LEFT JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
WHERE adl.execution_context_id = %(execution_context_id)s::uuid
ORDER BY adl.decision_depth, adl.created_at;


-- name: record_override
-- Record a human override of an AI decision.
-- No business keys here — the override links to the decision_log_id,
-- which links to execution_context_id for business context.
INSERT INTO override_log (
    decision_log_id, entity_type, entity_version_id,
    overrider_name, overrider_role, override_reason_code,
    override_notes, ai_recommendation, human_decision
)
VALUES (
    %(decision_log_id)s, %(entity_type)s, %(entity_version_id)s,
    %(overrider_name)s, %(overrider_role)s, %(override_reason_code)s,
    %(override_notes)s, %(ai_recommendation)s, %(human_decision)s
)
RETURNING id, created_at;


-- name: list_overrides_by_entity
SELECT
    ol.*,
    adl.output_summary AS original_output_summary,
    adl.confidence_score AS original_confidence
FROM override_log ol
JOIN agent_decision_log adl ON adl.id = ol.decision_log_id
WHERE ol.entity_type = %(entity_type)s
  AND ol.entity_version_id = %(entity_version_id)s
ORDER BY ol.created_at DESC;


-- name: list_recent_decisions
SELECT
    adl.id,
    adl.entity_type,
    adl.entity_version_id,
    adl.channel,
    adl.step_name,
    adl.output_summary,
    adl.status,
    adl.duration_ms,
    adl.created_at,
    COALESCE(a.display_name, t.display_name) AS entity_name,
    COALESCE(av.version_label, tv.version_label) AS version_label
FROM agent_decision_log adl
LEFT JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
ORDER BY adl.created_at DESC
LIMIT %(limit)s;


-- name: list_decisions_by_pipeline_run
-- Audit trail by pipeline_run_id (Verity-owned UUID).
-- This is the correct way to query decisions for a specific execution run.
SELECT
    adl.id,
    adl.entity_type,
    adl.entity_version_id,
    adl.channel,
    adl.mock_mode,
    adl.pipeline_run_id,
    adl.parent_decision_id,
    adl.decision_depth,
    adl.step_name,
    adl.input_summary,
    adl.output_summary,
    adl.reasoning_text,
    adl.confidence_score,
    adl.risk_factors,
    adl.model_used,
    adl.input_tokens,
    adl.output_tokens,
    adl.duration_ms,
    adl.tool_calls_made,
    adl.application,
    adl.hitl_required,
    adl.hitl_completed,
    adl.status,
    adl.created_at,
    COALESCE(a.display_name, t.display_name) AS entity_name,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(av.version_label, tv.version_label) AS version_label,
    t.capability_type
FROM agent_decision_log adl
LEFT JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
WHERE adl.pipeline_run_id = %(pipeline_run_id)s::uuid
ORDER BY adl.decision_depth, adl.created_at;


-- name: list_decisions_by_context
-- All decisions for an execution context (spans multiple pipeline runs).
SELECT
    adl.id,
    adl.entity_type,
    adl.entity_version_id,
    adl.channel,
    adl.pipeline_run_id,
    adl.step_name,
    adl.output_summary,
    adl.confidence_score,
    adl.duration_ms,
    adl.application,
    adl.status,
    adl.created_at,
    COALESCE(a.display_name, t.display_name) AS entity_name,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(av.version_label, tv.version_label) AS version_label
FROM agent_decision_log adl
LEFT JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
WHERE adl.execution_context_id = %(execution_context_id)s::uuid
ORDER BY adl.created_at;


-- name: list_pipeline_runs
-- Drives from the `pipeline_run` table which is authoritative for
-- lifecycle state — inserted at PipelineExecutor.run_pipeline entry
-- with status='running' and updated at exit with the final status.
-- Step-level facts (entity names, failure count among logged steps,
-- aggregate duration) are joined in from agent_decision_log.
--
-- decision_step_count may lag pipeline_run.step_count when the run
-- is still in-flight — the template shows `decision_step_count` so
-- users see progress like "2 / 5 steps logged so far" as the run
-- unfolds.
SELECT
    pr.id AS pipeline_run_id,
    pr.pipeline_name,
    COALESCE(app.display_name, pr.application) AS application,
    pr.status,
    pr.started_at,
    pr.completed_at,
    pr.duration_ms,
    pr.step_count AS expected_step_count,
    pr.failed_step_count,
    pr.error_message,
    -- Decision-log derived extras:
    COUNT(adl.id) AS decision_step_count,
    STRING_AGG(DISTINCT COALESCE(a.display_name, t.display_name), ', ') AS entities,
    SUM(COALESCE(adl.duration_ms, 0)) AS logged_duration_ms
FROM pipeline_run pr
LEFT JOIN application app ON app.name = pr.application
LEFT JOIN agent_decision_log adl ON adl.pipeline_run_id = pr.id
LEFT JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
GROUP BY pr.id, pr.pipeline_name, app.display_name, pr.application,
         pr.status, pr.started_at, pr.completed_at, pr.duration_ms,
         pr.step_count, pr.failed_step_count, pr.error_message
ORDER BY pr.started_at DESC
LIMIT 50;


-- name: insert_pipeline_run_start
-- Written at PipelineExecutor entry with status='running'. The id
-- is caller-supplied (matches the uuid4 already generated for
-- pipeline_run_id on the step decisions) so the agent_decision_log
-- FKs line up correctly.
INSERT INTO pipeline_run (
    id, pipeline_name, application, status, started_at,
    step_count, execution_context_id
)
VALUES (
    %(id)s::uuid, %(pipeline_name)s, %(application)s, 'running', %(started_at)s,
    %(step_count)s, %(execution_context_id)s
)
RETURNING id;


-- name: update_pipeline_run_complete
-- Written at PipelineExecutor exit (both success and exception paths).
-- `status` is one of complete/partial/failed. `step_count` here is
-- the actual executed count (may equal expected or be less if the
-- pipeline failed mid-run). Skipped is tracked separately so the UI
-- can distinguish "was never supposed to run" from "was but failed".
UPDATE pipeline_run SET
    status             = %(status)s,
    completed_at       = %(completed_at)s,
    duration_ms        = %(duration_ms)s,
    step_count         = %(step_count)s,
    failed_step_count  = %(failed_step_count)s,
    skipped_step_count = %(skipped_step_count)s,
    error_message      = %(error_message)s
WHERE id = %(id)s::uuid
RETURNING id;


-- name: list_all_overrides
-- All override records with joined decision context.
SELECT
    ol.*,
    adl.output_summary AS original_output_summary,
    adl.confidence_score AS original_confidence,
    COALESCE(a.display_name, t.display_name) AS entity_name,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(av.version_label, tv.version_label) AS version_label
FROM override_log ol
JOIN agent_decision_log adl ON adl.id = ol.decision_log_id
LEFT JOIN agent_version av ON av.id = ol.entity_version_id AND ol.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = ol.entity_version_id AND ol.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
ORDER BY ol.created_at DESC;
