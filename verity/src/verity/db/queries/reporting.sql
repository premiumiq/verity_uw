-- ============================================================
-- REPORTING QUERIES
-- Model inventory, override analysis, compliance
-- ============================================================

-- name: model_inventory_agents
SELECT
    a.id,
    a.name,
    a.display_name,
    a.materiality_tier,
    a.domain,
    av.version_label AS champion_version,
    av.valid_from AS champion_since,
    ic.name AS inference_config_name,
    ic.model_name,
    vr.run_at AS last_validation_date,
    vr.passed AS last_validation_passed,
    vr.f1_score,
    vr.cohens_kappa,
    mc.lifecycle_state AS model_card_status,
    mc.approved_by AS model_card_approved_by,
    (SELECT COUNT(*) FROM override_log ol
     JOIN agent_decision_log adl ON adl.id = ol.decision_log_id
     WHERE ol.entity_type = 'agent'
       AND ol.entity_version_id = av.id
       AND ol.created_at > NOW() - INTERVAL '30 days') AS override_count_30d,
    (SELECT COUNT(*) FROM agent_decision_log adl
     WHERE adl.entity_type = 'agent'
       AND adl.entity_version_id = av.id
       AND adl.created_at > NOW() - INTERVAL '30 days') AS decision_count_30d,
    (SELECT COUNT(*) FROM incident i
     WHERE i.entity_type = 'agent'
       AND i.entity_id = a.id
       AND i.status = 'open') AS active_incidents
FROM agent a
JOIN agent_version av ON av.id = a.current_champion_version_id
JOIN inference_config ic ON ic.id = av.inference_config_id
LEFT JOIN LATERAL (
    SELECT * FROM validation_run
    WHERE entity_type = 'agent' AND entity_version_id = av.id
    ORDER BY run_at DESC LIMIT 1
) vr ON TRUE
LEFT JOIN LATERAL (
    SELECT * FROM model_card
    WHERE entity_type = 'agent' AND entity_version_id = av.id
    ORDER BY card_version DESC LIMIT 1
) mc ON TRUE
ORDER BY a.materiality_tier, a.name;


-- name: model_inventory_tasks
SELECT
    t.id,
    t.name,
    t.display_name,
    t.capability_type,
    t.materiality_tier,
    t.domain,
    tv.version_label AS champion_version,
    tv.valid_from AS champion_since,
    ic.name AS inference_config_name,
    ic.model_name,
    vr.run_at AS last_validation_date,
    vr.passed AS last_validation_passed,
    vr.f1_score,
    vr.field_accuracy,
    mc.lifecycle_state AS model_card_status,
    (SELECT COUNT(*) FROM agent_decision_log adl
     WHERE adl.entity_type = 'task'
       AND adl.entity_version_id = tv.id
       AND adl.created_at > NOW() - INTERVAL '30 days') AS decision_count_30d
FROM task t
JOIN task_version tv ON tv.id = t.current_champion_version_id
JOIN inference_config ic ON ic.id = tv.inference_config_id
LEFT JOIN LATERAL (
    SELECT * FROM validation_run
    WHERE entity_type = 'task' AND entity_version_id = tv.id
    ORDER BY run_at DESC LIMIT 1
) vr ON TRUE
LEFT JOIN LATERAL (
    SELECT * FROM model_card
    WHERE entity_type = 'task' AND entity_version_id = tv.id
    ORDER BY card_version DESC LIMIT 1
) mc ON TRUE
ORDER BY t.materiality_tier, t.name;


-- name: dashboard_counts
SELECT
    (SELECT COUNT(*) FROM agent) AS agent_count,
    (SELECT COUNT(*) FROM task) AS task_count,
    (SELECT COUNT(*) FROM prompt) AS prompt_count,
    (SELECT COUNT(*) FROM inference_config WHERE active = TRUE) AS config_count,
    (SELECT COUNT(*) FROM tool WHERE active = TRUE) AS tool_count,
    (SELECT COUNT(*) FROM pipeline) AS pipeline_count,
    (SELECT COUNT(*) FROM agent_decision_log) AS total_decisions,
    (SELECT COUNT(*) FROM override_log) AS total_overrides,
    (SELECT COUNT(*) FROM incident WHERE status = 'open') AS open_incidents;


-- name: dashboard_30d_deltas
-- Count of new items created in last 30 days for delta indicators on cards.
SELECT
    (SELECT COUNT(*) FROM agent WHERE created_at > NOW() - INTERVAL '30 days') AS new_agents,
    (SELECT COUNT(*) FROM task WHERE created_at > NOW() - INTERVAL '30 days') AS new_tasks,
    (SELECT COUNT(*) FROM prompt WHERE created_at > NOW() - INTERVAL '30 days') AS new_prompts,
    (SELECT COUNT(*) FROM tool WHERE created_at > NOW() - INTERVAL '30 days') AS new_tools,
    (SELECT COUNT(*) FROM pipeline WHERE created_at > NOW() - INTERVAL '30 days') AS new_pipelines,
    (SELECT COUNT(*) FROM application WHERE created_at > NOW() - INTERVAL '30 days') AS new_apps,
    (SELECT COUNT(*) FROM agent_decision_log WHERE created_at > NOW() - INTERVAL '30 days') AS new_decisions,
    (SELECT COUNT(*) FROM override_log WHERE created_at > NOW() - INTERVAL '30 days') AS new_overrides,
    (SELECT COUNT(DISTINCT pipeline_run_id) FROM agent_decision_log WHERE pipeline_run_id IS NOT NULL AND created_at > NOW() - INTERVAL '30 days') AS new_pipeline_runs;


-- name: dashboard_recent_additions
-- All assets added in last 30 days across all entity types.
-- Returns all (not limited to 5) so client-side filtering works.
-- The template shows max 5 but filters dynamically.
SELECT entity_type, entity_name, display_name, created_at
FROM (
    SELECT 'agent'::text AS entity_type, name AS entity_name, display_name, created_at FROM agent
    UNION ALL
    SELECT 'task', name, display_name, created_at FROM task
    UNION ALL
    SELECT 'tool', name, display_name, created_at FROM tool
    UNION ALL
    SELECT 'prompt', name, display_name, created_at FROM prompt
    UNION ALL
    SELECT 'pipeline', name, display_name, created_at FROM pipeline
    UNION ALL
    SELECT 'config', name, display_name, created_at FROM inference_config
) AS all_assets
WHERE created_at > NOW() - INTERVAL '30 days'
ORDER BY created_at DESC;


-- name: dashboard_pipeline_runs_by_date
-- Pipeline runs grouped by date for the pipeline runs over time chart.
SELECT
    MIN(adl.created_at)::date AS run_date,
    COUNT(DISTINCT adl.pipeline_run_id) AS run_count
FROM agent_decision_log adl
WHERE adl.pipeline_run_id IS NOT NULL
GROUP BY adl.created_at::date
ORDER BY run_date;


-- name: dashboard_decisions_by_type
-- Decisions grouped by entity type (agent vs task) for the donut/bar chart.
SELECT
    adl.entity_type,
    COUNT(*) AS count
FROM agent_decision_log adl
GROUP BY adl.entity_type
ORDER BY count DESC;


-- name: dashboard_top_pipelines
-- Top pipelines by number of runs.
SELECT
    COALESCE(p.display_name, 'Unknown') AS pipeline_name,
    COUNT(DISTINCT adl.pipeline_run_id) AS run_count
FROM agent_decision_log adl
LEFT JOIN pipeline p ON p.name = 'uw_submission_pipeline'
WHERE adl.pipeline_run_id IS NOT NULL
GROUP BY pipeline_name
ORDER BY run_count DESC
LIMIT 10;


-- name: dashboard_overrides_by_date
-- Overrides grouped by date for the overrides over time chart.
SELECT
    ol.created_at::date AS override_date,
    ol.entity_type,
    COUNT(*) AS count
FROM override_log ol
GROUP BY override_date, ol.entity_type
ORDER BY override_date;


-- name: dashboard_overrides_by_entity
-- Overrides grouped by entity display name.
SELECT
    COALESCE(a.display_name, t.display_name, 'Unknown') AS entity_name,
    ol.entity_type,
    COUNT(*) AS count
FROM override_log ol
LEFT JOIN agent_version av ON av.id = ol.entity_version_id AND ol.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = ol.entity_version_id AND ol.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
GROUP BY entity_name, ol.entity_type
ORDER BY count DESC;


-- name: dashboard_decisions_by_date
-- Decisions grouped by date and entity type for the stacked bar chart.
-- Colored by entity_type (agent=blue, task=dark blue).
SELECT
    adl.created_at::date AS decision_date,
    adl.entity_type,
    COUNT(*) AS count
FROM agent_decision_log adl
GROUP BY decision_date, adl.entity_type
ORDER BY decision_date;


-- name: dashboard_decisions_by_entity
-- Decisions grouped by entity display name for the horizontal bar chart.
SELECT
    COALESCE(a.display_name, t.display_name, 'Unknown') AS entity_name,
    adl.entity_type,
    COUNT(*) AS count
FROM agent_decision_log adl
LEFT JOIN agent_version av ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
GROUP BY entity_name, adl.entity_type
ORDER BY count DESC;


-- name: dashboard_governance_stats
SELECT
    (SELECT COUNT(*) FROM approval_record) AS total_approvals,
    (SELECT COUNT(DISTINCT pipeline_run_id) FROM agent_decision_log WHERE pipeline_run_id IS NOT NULL) AS total_pipeline_runs,
    (SELECT COUNT(*) FROM application) AS app_count,
    (SELECT COUNT(*) FROM agent_version WHERE lifecycle_state IN ('staging', 'shadow', 'challenger')) AS entities_in_review,
    (SELECT COUNT(*) FROM test_execution_log WHERE passed = TRUE) AS tests_passed,
    (SELECT COUNT(*) FROM test_execution_log) AS tests_total;


-- name: dashboard_asset_relationships
-- For each agent/task champion version, which tools and prompts it uses.
-- Used by the slicer cross-filtering on the dashboard.
SELECT
    'agent' AS parent_type,
    a.name AS parent_name,
    a.display_name AS parent_display_name,
    'tool' AS related_type,
    t.name AS related_name,
    t.display_name AS related_display_name
FROM agent a
JOIN agent_version av ON av.id = a.current_champion_version_id
JOIN agent_version_tool avt ON avt.agent_version_id = av.id AND avt.authorized = TRUE
JOIN tool t ON t.id = avt.tool_id
UNION ALL
SELECT
    'agent', a.name, a.display_name,
    'prompt', p.name, p.display_name
FROM agent a
JOIN agent_version av ON av.id = a.current_champion_version_id
JOIN entity_prompt_assignment epa ON epa.entity_type = 'agent' AND epa.entity_version_id = av.id
JOIN prompt_version pvr ON pvr.id = epa.prompt_version_id
JOIN prompt p ON p.id = pvr.prompt_id
UNION ALL
SELECT
    'task', tk.name, tk.display_name,
    'prompt', p.name, p.display_name
FROM task tk
JOIN task_version tv ON tv.id = tk.current_champion_version_id
JOIN entity_prompt_assignment epa ON epa.entity_type = 'task' AND epa.entity_version_id = tv.id
JOIN prompt_version pvr ON pvr.id = epa.prompt_version_id
JOIN prompt p ON p.id = pvr.prompt_id
ORDER BY parent_type, parent_name, related_type;


-- name: override_analysis
SELECT
    ol.override_reason_code,
    COUNT(*) AS count,
    COALESCE(a.name, t.name) AS entity_name,
    ol.entity_type
FROM override_log ol
LEFT JOIN agent_version av ON av.id = ol.entity_version_id AND ol.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = ol.entity_version_id AND ol.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
WHERE ol.created_at > NOW() - INTERVAL '%(days)s days'
GROUP BY ol.override_reason_code, ol.entity_type, a.name, t.name
ORDER BY count DESC;
