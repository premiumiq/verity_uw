-- ============================================================
-- HITL OVERRIDE QUERIES
-- Per-field human override of an AI-produced value. Distinct
-- from the decision-level override_log; structured around
-- (decision_log_id, output_path) plus a parallel business
-- identification (application / entity_type / entity_reference /
-- fact_type) so reports can group by either axis.
-- ============================================================


-- name: insert_hitl_override
-- Persist one human override. Returns id + created_at.
INSERT INTO hitl_override (
    decision_log_id, output_path,
    ai_value, ai_found, hitl_value,
    application, entity_type, entity_reference, fact_type,
    created_by, reason
)
VALUES (
    %(decision_log_id)s, %(output_path)s,
    %(ai_value)s, %(ai_found)s, %(hitl_value)s,
    %(application)s, %(entity_type)s, %(entity_reference)s, %(fact_type)s,
    %(created_by)s, %(reason)s
)
RETURNING id, created_at;


-- name: get_decision_output
-- Look up a decision's output_json so the caller can run an
-- integrity check (does the request's ai_value match what's at
-- output_path in the run's stored output?).
SELECT output_json
FROM agent_decision_log
WHERE id = %(decision_log_id)s;


-- name: list_all_hitl_overrides
-- All per-field overrides, joined to the decision row + the
-- application registry so the admin page can show the human
-- display name without re-querying.
SELECT
    ho.id,
    ho.created_at,
    ho.created_by,
    ho.application,
    app.display_name    AS application_display_name,
    ho.entity_type      AS business_entity_type,
    ho.entity_reference,
    ho.fact_type,
    ho.output_path,
    ho.ai_value::text   AS ai_value,
    ho.ai_found,
    ho.hitl_value::text AS hitl_value,
    ho.reason,
    ho.decision_log_id,
    adl.entity_type     AS decision_entity_type,
    COALESCE(a.display_name, t.display_name) AS entity_name,
    COALESCE(av.version_label, tv.version_label) AS version_label,
    adl.workflow_run_id,
    adl.execution_context_id
FROM hitl_override ho
LEFT JOIN agent_decision_log adl ON adl.id = ho.decision_log_id
LEFT JOIN application app   ON app.name = ho.application
LEFT JOIN agent_version av  ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a           ON a.id  = av.agent_id
LEFT JOIN task_version tv   ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t            ON t.id  = tv.task_id
ORDER BY ho.created_at DESC;


-- name: get_hitl_override_by_id
-- Single-row read for the per-override detail page. Same shape
-- as list_all_hitl_overrides plus a few extras the list view
-- doesn't need (decision summary, model used).
SELECT
    ho.id,
    ho.created_at,
    ho.created_by,
    ho.application,
    app.display_name    AS application_display_name,
    ho.entity_type      AS business_entity_type,
    ho.entity_reference,
    ho.fact_type,
    ho.output_path,
    ho.ai_value::text   AS ai_value,
    ho.ai_found,
    ho.hitl_value::text AS hitl_value,
    ho.reason,
    ho.decision_log_id,
    adl.entity_type     AS decision_entity_type,
    adl.step_name       AS decision_step_name,
    adl.output_summary  AS decision_output_summary,
    adl.model_used      AS decision_model_used,
    adl.duration_ms     AS decision_duration_ms,
    adl.confidence_score AS decision_confidence,
    COALESCE(a.display_name, t.display_name) AS entity_name,
    COALESCE(av.version_label, tv.version_label) AS version_label,
    adl.workflow_run_id,
    adl.execution_context_id
FROM hitl_override ho
LEFT JOIN agent_decision_log adl ON adl.id = ho.decision_log_id
LEFT JOIN application app   ON app.name = ho.application
LEFT JOIN agent_version av  ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a           ON a.id  = av.agent_id
LEFT JOIN task_version tv   ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t            ON t.id  = tv.task_id
WHERE ho.id = %(override_id)s;
