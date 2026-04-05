-- ============================================================
-- REGISTRY QUERIES
-- Retrieve and register agents, tasks, prompts, configs, tools
-- ============================================================

-- name: get_agent_champion
-- Returns the champion version config for a named agent.
-- Called by execution engine at runtime.
SELECT
    a.id AS agent_id,
    a.name,
    a.display_name,
    a.description,
    a.materiality_tier,
    a.purpose,
    a.domain,
    a.business_context,
    a.known_limitations,
    av.id AS agent_version_id,
    av.version_label,
    av.lifecycle_state,
    av.output_schema,
    av.authority_thresholds,
    av.mock_mode_enabled,
    av.shadow_traffic_pct,
    av.challenger_traffic_pct,
    ic.id AS inference_config_id,
    ic.name AS inference_config_name,
    ic.model_name,
    ic.temperature,
    ic.max_tokens,
    ic.top_p,
    ic.top_k,
    ic.stop_sequences,
    ic.extended_params
FROM agent a
JOIN agent_version av ON av.id = a.current_champion_version_id
JOIN inference_config ic ON ic.id = av.inference_config_id
WHERE a.name = %(agent_name)s;


-- name: get_agent_by_name
SELECT
    a.*,
    av.id AS champion_version_id,
    av.version_label AS champion_version_label,
    av.lifecycle_state AS champion_lifecycle_state,
    ic.name AS champion_inference_config_name
FROM agent a
LEFT JOIN agent_version av ON av.id = a.current_champion_version_id
LEFT JOIN inference_config ic ON ic.id = av.inference_config_id
WHERE a.name = %(agent_name)s;


-- name: list_agents
SELECT
    a.id,
    a.name,
    a.display_name,
    a.description,
    a.materiality_tier,
    a.domain,
    av.version_label AS champion_version,
    av.lifecycle_state AS champion_state,
    ic.name AS inference_config_name,
    a.created_at
FROM agent a
LEFT JOIN agent_version av ON av.id = a.current_champion_version_id
LEFT JOIN inference_config ic ON ic.id = av.inference_config_id
ORDER BY a.name;


-- name: list_agent_versions
SELECT
    av.*,
    ic.name AS inference_config_name,
    ic.model_name,
    ic.temperature
FROM agent_version av
JOIN inference_config ic ON ic.id = av.inference_config_id
WHERE av.agent_id = %(agent_id)s
ORDER BY av.major_version DESC, av.minor_version DESC, av.patch_version DESC;


-- name: get_entity_prompts
-- Get all prompt assignments for an agent_version or task_version.
SELECT
    epa.id AS assignment_id,
    epa.api_role,
    epa.governance_tier,
    epa.execution_order,
    epa.is_required,
    epa.condition_logic,
    pv.id AS prompt_version_id,
    pv.version_number AS prompt_version_number,
    pv.content,
    pv.lifecycle_state AS prompt_lifecycle_state,
    p.name AS prompt_name,
    p.description AS prompt_description
FROM entity_prompt_assignment epa
JOIN prompt_version pv ON pv.id = epa.prompt_version_id
JOIN prompt p ON p.id = pv.prompt_id
WHERE epa.entity_type = %(entity_type)s
  AND epa.entity_version_id = %(entity_version_id)s
ORDER BY epa.execution_order;


-- name: get_entity_tools
-- Get all authorized tools for an agent_version.
SELECT
    avt.id AS authorization_id,
    avt.authorized,
    avt.notes,
    t.id AS tool_id,
    t.name,
    t.display_name,
    t.description,
    t.input_schema,
    t.output_schema,
    t.implementation_path,
    t.mock_mode_enabled,
    t.mock_response_key,
    t.data_classification_max,
    t.is_write_operation,
    t.requires_confirmation
FROM agent_version_tool avt
JOIN tool t ON t.id = avt.tool_id
WHERE avt.agent_version_id = %(entity_version_id)s
  AND avt.authorized = TRUE
ORDER BY t.name;


-- name: get_task_tools
-- Get all authorized tools for a task_version.
SELECT
    tvt.id AS authorization_id,
    tvt.authorized,
    tvt.notes,
    t.id AS tool_id,
    t.name,
    t.display_name,
    t.description,
    t.input_schema,
    t.output_schema,
    t.implementation_path,
    t.mock_mode_enabled,
    t.mock_response_key,
    t.data_classification_max,
    t.is_write_operation,
    t.requires_confirmation
FROM task_version_tool tvt
JOIN tool t ON t.id = tvt.tool_id
WHERE tvt.task_version_id = %(entity_version_id)s
  AND tvt.authorized = TRUE
ORDER BY t.name;


-- name: get_task_champion
-- Returns the champion version config for a named task.
SELECT
    t.id AS task_id,
    t.name,
    t.display_name,
    t.description,
    t.capability_type,
    t.materiality_tier,
    t.purpose,
    t.domain,
    t.input_schema AS task_input_schema,
    t.output_schema AS task_output_schema,
    t.business_context,
    t.known_limitations,
    tv.id AS task_version_id,
    tv.version_label,
    tv.lifecycle_state,
    tv.output_schema AS version_output_schema,
    tv.mock_mode_enabled,
    ic.id AS inference_config_id,
    ic.name AS inference_config_name,
    ic.model_name,
    ic.temperature,
    ic.max_tokens,
    ic.top_p,
    ic.top_k,
    ic.stop_sequences,
    ic.extended_params
FROM task t
JOIN task_version tv ON tv.id = t.current_champion_version_id
JOIN inference_config ic ON ic.id = tv.inference_config_id
WHERE t.name = %(task_name)s;


-- name: get_task_by_name
SELECT
    t.*,
    tv.id AS champion_version_id,
    tv.version_label AS champion_version_label,
    tv.lifecycle_state AS champion_lifecycle_state,
    ic.name AS champion_inference_config_name
FROM task t
LEFT JOIN task_version tv ON tv.id = t.current_champion_version_id
LEFT JOIN inference_config ic ON ic.id = tv.inference_config_id
WHERE t.name = %(task_name)s;


-- name: list_tasks
SELECT
    t.id,
    t.name,
    t.display_name,
    t.description,
    t.capability_type,
    t.materiality_tier,
    t.domain,
    tv.version_label AS champion_version,
    tv.lifecycle_state AS champion_state,
    ic.name AS inference_config_name,
    t.created_at
FROM task t
LEFT JOIN task_version tv ON tv.id = t.current_champion_version_id
LEFT JOIN inference_config ic ON ic.id = tv.inference_config_id
ORDER BY t.name;


-- name: list_task_versions
SELECT
    tv.*,
    ic.name AS inference_config_name,
    ic.model_name,
    ic.temperature
FROM task_version tv
JOIN inference_config ic ON ic.id = tv.inference_config_id
WHERE tv.task_id = %(task_id)s
ORDER BY tv.major_version DESC, tv.minor_version DESC, tv.patch_version DESC;


-- name: list_prompts
SELECT
    p.id,
    p.name,
    p.description,
    p.primary_entity_type,
    pv.version_number AS latest_version,
    pv.governance_tier,
    pv.api_role,
    pv.lifecycle_state,
    pv.author_name,
    pv.approved_by,
    p.created_at
FROM prompt p
LEFT JOIN LATERAL (
    SELECT *
    FROM prompt_version
    WHERE prompt_id = p.id
    ORDER BY version_number DESC
    LIMIT 1
) pv ON TRUE
ORDER BY p.name;


-- name: get_prompt_by_name
SELECT p.*, pv.version_number AS latest_version
FROM prompt p
LEFT JOIN LATERAL (
    SELECT version_number
    FROM prompt_version
    WHERE prompt_id = p.id
    ORDER BY version_number DESC
    LIMIT 1
) pv ON TRUE
WHERE p.name = %(prompt_name)s;


-- name: list_prompt_versions
SELECT pv.*
FROM prompt_version pv
WHERE pv.prompt_id = %(prompt_id)s
ORDER BY pv.version_number DESC;


-- name: list_inference_configs
SELECT * FROM inference_config WHERE active = TRUE ORDER BY name;


-- name: get_inference_config_by_name
SELECT * FROM inference_config WHERE name = %(config_name)s;


-- name: list_tools
SELECT * FROM tool WHERE active = TRUE ORDER BY name;


-- name: get_tool_by_name
SELECT * FROM tool WHERE name = %(tool_name)s;


-- name: list_pipelines
SELECT
    p.id,
    p.name,
    p.display_name,
    p.description,
    pv.version_number AS champion_version,
    pv.lifecycle_state AS champion_state,
    pv.steps,
    p.created_at
FROM pipeline p
LEFT JOIN pipeline_version pv ON pv.id = p.current_champion_version_id
ORDER BY p.name;


-- name: get_pipeline_by_name
SELECT
    p.*,
    pv.id AS champion_version_id,
    pv.version_number AS champion_version_number,
    pv.lifecycle_state AS champion_lifecycle_state,
    pv.steps
FROM pipeline p
LEFT JOIN pipeline_version pv ON pv.id = p.current_champion_version_id
WHERE p.name = %(pipeline_name)s;
