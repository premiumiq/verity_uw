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
