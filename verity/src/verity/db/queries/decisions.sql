-- ============================================================
-- DECISION QUERIES
-- Log decisions, query audit trails, record overrides
-- ============================================================

-- name: log_decision
INSERT INTO agent_decision_log (
    entity_type, entity_version_id, prompt_version_ids,
    inference_config_snapshot, submission_id, policy_id, renewal_id,
    business_entity, channel, mock_mode, pipeline_run_id,
    parent_decision_id, decision_depth, step_name,
    input_summary, input_json, output_json, output_summary,
    reasoning_text, risk_factors, confidence_score, low_confidence_flag,
    model_used, input_tokens, output_tokens, duration_ms,
    tool_calls_made, message_history, application, execution_context_id,
    hitl_required, status, error_message
)
VALUES (
    %(entity_type)s, %(entity_version_id)s, %(prompt_version_ids)s,
    %(inference_config_snapshot)s, %(submission_id)s, %(policy_id)s, %(renewal_id)s,
    %(business_entity)s, %(channel)s, %(mock_mode)s, %(pipeline_run_id)s,
    %(parent_decision_id)s, %(decision_depth)s, %(step_name)s,
    %(input_summary)s, %(input_json)s, %(output_json)s, %(output_summary)s,
    %(reasoning_text)s, %(risk_factors)s, %(confidence_score)s, %(low_confidence_flag)s,
    %(model_used)s, %(input_tokens)s, %(output_tokens)s, %(duration_ms)s,
    %(tool_calls_made)s, %(message_history)s, %(application)s, %(execution_context_id)s,
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
SELECT
    adl.id,
    adl.entity_type,
    adl.entity_version_id,
    adl.submission_id,
    adl.channel,
    adl.mock_mode,
    adl.pipeline_run_id,
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
    adl.hitl_required,
    adl.created_at,
    COALESCE(a.display_name, t.display_name) AS entity_name,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(av.version_label, tv.version_label) AS version_label
FROM agent_decision_log adl
LEFT JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
ORDER BY adl.created_at DESC
LIMIT %(limit)s OFFSET %(offset)s;


-- name: count_decisions
SELECT COUNT(*) AS total FROM agent_decision_log;


-- name: list_decisions_by_submission
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
WHERE adl.submission_id = %(submission_id)s
ORDER BY adl.decision_depth, adl.created_at;


-- name: record_override
INSERT INTO override_log (
    decision_log_id, entity_type, entity_version_id,
    overrider_name, overrider_role, override_reason_code,
    override_notes, ai_recommendation, human_decision, submission_id
)
VALUES (
    %(decision_log_id)s, %(entity_type)s, %(entity_version_id)s,
    %(overrider_name)s, %(overrider_role)s, %(override_reason_code)s,
    %(override_notes)s, %(ai_recommendation)s, %(human_decision)s, %(submission_id)s
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
    adl.submission_id,
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
-- Does not use submission_id (business key) — no cross-app collision.
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
-- Get distinct pipeline runs with aggregated info for the Pipeline Runs page.
SELECT
    adl.pipeline_run_id,
    COALESCE(app.display_name, adl.application) AS application,
    COUNT(*) AS step_count,
    STRING_AGG(DISTINCT COALESCE(a.display_name, t.display_name), ', ') AS entities,
    BOOL_OR(adl.status = 'failed') AS has_failures,
    SUM(COALESCE(adl.duration_ms, 0)) AS total_duration_ms,
    MIN(adl.created_at) AS first_at,
    MAX(adl.created_at) AS last_at
FROM agent_decision_log adl
LEFT JOIN application app ON app.name = adl.application
LEFT JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
WHERE adl.pipeline_run_id IS NOT NULL
GROUP BY adl.pipeline_run_id, app.display_name, adl.application
ORDER BY first_at DESC
LIMIT 50;


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
