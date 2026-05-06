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
    ic.display_name AS inference_config_name,
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


-- name: get_agent_champion_at_date
-- Resolve the champion version that was active at a specific date.
-- SCD Type 2: valid_from <= effective_date AND valid_to > effective_date
-- Active champions have valid_to = 9999-12-31 (sentinel). No NULL checks needed.
SELECT
    a.id AS agent_id, a.name, a.display_name, a.description,
    a.materiality_tier, a.purpose, a.domain,
    a.business_context, a.known_limitations,
    av.id AS agent_version_id, av.version_label, av.lifecycle_state,
    av.output_schema, av.authority_thresholds, av.mock_mode_enabled,
    av.shadow_traffic_pct, av.challenger_traffic_pct,
    av.valid_from, av.valid_to,
    ic.id AS inference_config_id, ic.display_name AS inference_config_name,
    ic.model_name, ic.temperature, ic.max_tokens, ic.top_p, ic.top_k,
    ic.stop_sequences, ic.extended_params
FROM agent a
JOIN agent_version av ON av.agent_id = a.id
    AND av.lifecycle_state IN ('champion', 'deprecated')
    AND av.valid_from IS NOT NULL
    AND av.valid_from <= %(effective_date)s
    AND av.valid_to > %(effective_date)s
JOIN inference_config ic ON ic.id = av.inference_config_id
WHERE a.name = %(agent_name)s
LIMIT 1;


-- name: get_agent_version_by_id
-- Direct version lookup for version-pinned execution.
SELECT
    a.id AS agent_id, a.name, a.display_name, a.description,
    a.materiality_tier, a.purpose, a.domain,
    a.business_context, a.known_limitations,
    av.id AS agent_version_id, av.version_label, av.lifecycle_state,
    av.output_schema, av.authority_thresholds, av.mock_mode_enabled,
    av.shadow_traffic_pct, av.challenger_traffic_pct,
    av.valid_from, av.valid_to,
    ic.id AS inference_config_id, ic.display_name AS inference_config_name,
    ic.model_name, ic.temperature, ic.max_tokens, ic.top_p, ic.top_k,
    ic.stop_sequences, ic.extended_params
FROM agent_version av
JOIN agent a ON a.id = av.agent_id
JOIN inference_config ic ON ic.id = av.inference_config_id
WHERE av.id = %(version_id)s::uuid;


-- name: get_task_champion_at_date
SELECT
    t.id AS task_id, t.name, t.display_name, t.description,
    t.capability_type, t.materiality_tier, t.purpose, t.domain,
    t.input_schema AS task_input_schema, t.output_schema AS task_output_schema,
    t.business_context, t.known_limitations,
    tv.id AS task_version_id, tv.version_label, tv.lifecycle_state,
    tv.output_schema AS version_output_schema, tv.mock_mode_enabled,
    tv.valid_from, tv.valid_to,
    ic.id AS inference_config_id, ic.display_name AS inference_config_name,
    ic.model_name, ic.temperature, ic.max_tokens, ic.top_p, ic.top_k,
    ic.stop_sequences, ic.extended_params
FROM task t
JOIN task_version tv ON tv.task_id = t.id
    AND tv.lifecycle_state IN ('champion', 'deprecated')
    AND tv.valid_from IS NOT NULL
    AND tv.valid_from <= %(effective_date)s
    AND tv.valid_to > %(effective_date)s
JOIN inference_config ic ON ic.id = tv.inference_config_id
WHERE t.name = %(task_name)s
LIMIT 1;


-- name: get_task_version_by_id
SELECT
    t.id AS task_id, t.name, t.display_name, t.description,
    t.capability_type, t.materiality_tier, t.purpose, t.domain,
    t.input_schema AS task_input_schema, t.output_schema AS task_output_schema,
    t.business_context, t.known_limitations,
    tv.id AS task_version_id, tv.version_label, tv.lifecycle_state,
    tv.output_schema AS version_output_schema, tv.mock_mode_enabled,
    tv.valid_from, tv.valid_to,
    ic.id AS inference_config_id, ic.display_name AS inference_config_name,
    ic.model_name, ic.temperature, ic.max_tokens, ic.top_p, ic.top_k,
    ic.stop_sequences, ic.extended_params
FROM task_version tv
JOIN task t ON t.id = tv.task_id
JOIN inference_config ic ON ic.id = tv.inference_config_id
WHERE tv.id = %(version_id)s::uuid;


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
    ic.display_name AS inference_config_name,
    av.decision_log_detail,
    a.created_at
FROM agent a
LEFT JOIN agent_version av ON av.id = a.current_champion_version_id
LEFT JOIN inference_config ic ON ic.id = av.inference_config_id
ORDER BY a.name;


-- name: list_agent_versions
SELECT
    av.*,
    ic.display_name AS inference_config_name,
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
    pv.major_version AS prompt_version_number,
    pv.version_label AS prompt_version_label,
    pv.content,
    pv.template_variables,
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
    t.transport,
    t.mcp_server_name,
    t.mcp_tool_name,
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
    t.transport,
    t.mcp_server_name,
    t.mcp_tool_name,
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


-- ── TASK VERSION DATA SOURCES / TARGETS ──────────────────────
-- Loaded by the execution engine before prompt build to resolve declared
-- inputs, and after the structured output is returned to fire declared
-- outputs. connector_name is denormalised into the read shape so the
-- engine can look up the provider by name without a second query.

-- name: list_task_version_sources
SELECT
    tvs.id,
    tvs.task_version_id,
    tvs.input_field_name,
    tvs.connector_id,
    dc.name AS connector_name,
    tvs.fetch_method,
    tvs.maps_to_template_var,
    tvs.required,
    tvs.execution_order,
    tvs.description,
    tvs.created_at
FROM task_version_source tvs
JOIN data_connector dc ON dc.id = tvs.connector_id
WHERE tvs.task_version_id = %(task_version_id)s
ORDER BY tvs.execution_order, tvs.input_field_name;


-- name: list_task_version_targets
SELECT
    tvt.id,
    tvt.task_version_id,
    tvt.output_field_name,
    tvt.connector_id,
    dc.name AS connector_name,
    tvt.write_method,
    tvt.target_container,
    tvt.required,
    tvt.execution_order,
    tvt.description,
    tvt.created_at
FROM task_version_target tvt
JOIN data_connector dc ON dc.id = tvt.connector_id
WHERE tvt.task_version_id = %(task_version_id)s
ORDER BY tvt.execution_order, tvt.output_field_name;


-- ── UNIFIED WIRING (SOURCES + TARGETS, TASK + AGENT) ──────────
-- Replacement for list_task_version_sources / list_task_version_targets.
-- These queries operate on the unified source_binding / write_target /
-- target_payload_field tables that work for both tasks and agents.

-- name: list_source_bindings
-- Source bindings for a task or agent version, in execution_order.
-- Returns the raw reference string; the runtime parses it into one of
-- input.<path> | const:<v> | fetch:<connector>/<method>(input.<f>).
SELECT
    sb.id,
    sb.owner_kind,
    sb.owner_id,
    sb.template_var,
    sb.reference,
    sb.binding_kind,
    sb.required,
    sb.execution_order,
    sb.description,
    sb.created_at
FROM source_binding sb
WHERE sb.owner_kind = %(owner_kind)s
  AND sb.owner_id   = %(owner_id)s
ORDER BY sb.execution_order, sb.template_var;


-- name: list_write_targets
-- Declared output writes for a task or agent version, in execution_order.
-- connector_name is denormalised so the engine can look up the provider
-- without a second query.
SELECT
    wt.id,
    wt.owner_kind,
    wt.owner_id,
    wt.name,
    wt.connector_id,
    dc.name AS connector_name,
    wt.write_method,
    wt.container,
    wt.required,
    wt.execution_order,
    wt.description,
    wt.created_at
FROM write_target wt
JOIN data_connector dc ON dc.id = wt.connector_id
WHERE wt.owner_kind = %(owner_kind)s
  AND wt.owner_id   = %(owner_id)s
ORDER BY wt.execution_order, wt.name;


-- name: list_target_payload_fields
-- The per-field payload assembly for one write_target. Each row is one
-- entry in the payload dict the connector receives.
SELECT
    tpf.id,
    tpf.write_target_id,
    tpf.payload_field,
    tpf.reference,
    tpf.required,
    tpf.execution_order,
    tpf.description,
    tpf.created_at
FROM target_payload_field tpf
WHERE tpf.write_target_id = %(write_target_id)s
ORDER BY tpf.execution_order, tpf.payload_field;


-- name: list_mcp_servers
-- All registered MCP servers (governance UI, runtime startup).
SELECT * FROM mcp_server WHERE active = TRUE ORDER BY name;


-- name: get_mcp_server_by_name
-- Fetch one MCP server by name (for runtime dispatch — hydrate the
-- connection config referenced by tool.mcp_server_name).
SELECT * FROM mcp_server WHERE name = %(mcp_server_name)s;


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
    ic.display_name AS inference_config_name,
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
    ic.display_name AS inference_config_name,
    tv.decision_log_detail,
    t.created_at
FROM task t
LEFT JOIN task_version tv ON tv.id = t.current_champion_version_id
LEFT JOIN inference_config ic ON ic.id = tv.inference_config_id
ORDER BY t.name;


-- name: list_task_versions
SELECT
    tv.*,
    ic.display_name AS inference_config_name,
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
    p.display_name,
    p.description,
    p.primary_entity_type,
    -- Resolve the display name of the entity this prompt is primarily used by
    CASE p.primary_entity_type
        WHEN 'agent' THEN (SELECT display_name FROM agent WHERE id = p.primary_entity_id)
        WHEN 'task' THEN (SELECT display_name FROM task WHERE id = p.primary_entity_id)
    END AS primary_entity_display_name,
    pv.version_label AS latest_version,
    pv.governance_tier,
    pv.api_role,
    pv.lifecycle_state,
    pv.valid_from,
    pv.valid_to,
    pv.author_name,
    pv.approved_by,
    p.created_at
FROM prompt p
LEFT JOIN LATERAL (
    SELECT *
    FROM prompt_version
    WHERE prompt_id = p.id
    ORDER BY major_version DESC, minor_version DESC, patch_version DESC
    LIMIT 1
) pv ON TRUE
ORDER BY p.name;


-- name: get_prompt_by_name
SELECT p.*, pv.version_label AS latest_version
FROM prompt p
LEFT JOIN LATERAL (
    SELECT version_label
    FROM prompt_version
    WHERE prompt_id = p.id
    ORDER BY major_version DESC, minor_version DESC, patch_version DESC
    LIMIT 1
) pv ON TRUE
WHERE p.name = %(prompt_name)s;


-- name: list_prompt_versions
SELECT pv.*
FROM prompt_version pv
WHERE pv.prompt_id = %(prompt_id)s
ORDER BY pv.major_version DESC, pv.minor_version DESC, pv.patch_version DESC;


-- name: list_inference_configs
SELECT * FROM inference_config WHERE active = TRUE ORDER BY name;


-- name: get_inference_config_by_name
SELECT * FROM inference_config WHERE name = %(config_name)s;


-- name: update_inference_config
-- Mutable-field update. Inference configs are not versioned, so this
-- modifies the row in place. Optimistic-concurrency guard mirrors
-- the version updates: NULL ``expected_updated_at`` skips the check
-- (legacy callers); a non-NULL value must match the row's current
-- updated_at or the UPDATE matches zero rows.
UPDATE inference_config SET
    display_name    = COALESCE(%(display_name)s,                    display_name),
    description     = COALESCE(%(description)s,                     description),
    intended_use    = COALESCE(%(intended_use)s,                    intended_use),
    model_name      = COALESCE(%(model_name)s,                      model_name),
    temperature     = COALESCE(%(temperature)s::numeric(4,3),       temperature),
    max_tokens      = COALESCE(%(max_tokens)s::integer,             max_tokens),
    top_p           = COALESCE(%(top_p)s::numeric(4,3),             top_p),
    top_k           = COALESCE(%(top_k)s::integer,                  top_k),
    stop_sequences  = COALESCE(%(stop_sequences)s::text[],          stop_sequences),
    extended_params = COALESCE(%(extended_params)s::jsonb,          extended_params),
    updated_at      = NOW()
WHERE id = %(config_id)s::uuid
  AND (%(expected_updated_at)s::timestamp IS NULL
       OR updated_at = %(expected_updated_at)s::timestamp)
RETURNING id, name, display_name, updated_at;


-- name: get_inference_config_status_for_concurrency
-- Used by the Studio save handler to distinguish "row not found" from
-- "stale stamp" when the UPDATE returns zero rows.
SELECT id, name, updated_at
FROM inference_config
WHERE id = %(config_id)s::uuid;


-- name: update_tool
-- In-place edit for a tool row. Tools are global and unversioned, so
-- this modifies the row directly; saves take effect for every
-- agent_version / task_version that authorises the tool the next
-- time they run.
UPDATE tool SET
    display_name              = COALESCE(%(display_name)s,                                  display_name),
    description               = COALESCE(%(description)s,                                   description),
    input_schema              = COALESCE(%(input_schema)s::jsonb,                           input_schema),
    output_schema             = COALESCE(%(output_schema)s::jsonb,                          output_schema),
    transport                 = COALESCE(%(transport)s,                                     transport),
    mcp_server_name           = COALESCE(%(mcp_server_name)s,                               mcp_server_name),
    mcp_tool_name             = COALESCE(%(mcp_tool_name)s,                                 mcp_tool_name),
    implementation_path       = COALESCE(%(implementation_path)s,                           implementation_path),
    mock_mode_enabled         = COALESCE(%(mock_mode_enabled)s::boolean,                    mock_mode_enabled),
    mock_response_key         = COALESCE(%(mock_response_key)s,                             mock_response_key),
    mock_responses            = COALESCE(%(mock_responses)s::jsonb,                         mock_responses),
    data_classification_max   = COALESCE(%(data_classification_max)s::data_classification,  data_classification_max),
    is_write_operation        = COALESCE(%(is_write_operation)s::boolean,                   is_write_operation),
    requires_confirmation     = COALESCE(%(requires_confirmation)s::boolean,                requires_confirmation),
    tags                      = COALESCE(%(tags)s::text[],                                  tags),
    updated_at                = NOW()
WHERE id = %(tool_id)s::uuid
  AND (%(expected_updated_at)s::timestamp IS NULL
       OR updated_at = %(expected_updated_at)s::timestamp)
RETURNING id, name, display_name, updated_at;


-- name: get_tool_status_for_concurrency
SELECT id, name, updated_at
FROM tool
WHERE id = %(tool_id)s::uuid;


-- name: studio_compose_summary
-- One row of aggregate counts powering the Compose landing cards:
-- total entities of each kind, plus draft/champion breakdown for the
-- versioned ones (prompts here; tasks/agents arrive later).
SELECT
    (SELECT COUNT(*) FROM governance.prompt)                                                        AS prompt_total,
    (SELECT COUNT(*) FROM (
        SELECT p.id
        FROM governance.prompt p
        JOIN governance.prompt_version pv ON pv.prompt_id = p.id
        WHERE pv.lifecycle_state = 'draft'
        GROUP BY p.id
    ) d)                                                                                            AS prompt_with_drafts,
    (SELECT COUNT(*) FROM (
        SELECT p.id
        FROM governance.prompt p
        JOIN governance.prompt_version pv ON pv.prompt_id = p.id
        WHERE pv.lifecycle_state = 'champion'
        GROUP BY p.id
    ) c)                                                                                            AS prompt_with_champion,
    (SELECT COUNT(*) FROM governance.inference_config WHERE active = TRUE)                          AS config_total,
    (SELECT COUNT(*) FROM governance.tool)                                                          AS tool_total,
    (SELECT COUNT(*) FROM governance.agent)                                                         AS agent_total,
    (SELECT COUNT(*) FROM governance.task)                                                          AS task_total;


-- name: list_prompts_with_state_summary
-- Per-prompt row enriched with version-state aggregates so the
-- prompts list can render "5 versions / champion v2.1.0 / 1 draft"
-- without N+1 follow-up queries.
SELECT
    p.id,
    p.name,
    p.display_name,
    p.description,
    COUNT(pv.id)                                                  AS version_count,
    COUNT(*) FILTER (WHERE pv.lifecycle_state = 'draft')          AS draft_count,
    bool_or(pv.lifecycle_state = 'champion')                      AS has_champion,
    MAX(pv.version_label) FILTER (WHERE pv.lifecycle_state = 'champion')  AS champion_label,
    MAX(pv.updated_at)                                            AS last_modified
FROM governance.prompt p
LEFT JOIN governance.prompt_version pv ON pv.prompt_id = p.id
GROUP BY p.id, p.name, p.display_name, p.description
ORDER BY p.name;


-- name: get_config_usage
-- Which agents and tasks use a specific inference config (champion versions only).
SELECT
    'agent' AS entity_type,
    a.name AS entity_name,
    a.display_name AS entity_display_name,
    av.version_label
FROM agent_version av
JOIN agent a ON a.id = av.agent_id AND av.id = a.current_champion_version_id
WHERE av.inference_config_id = %(config_id)s::uuid
UNION ALL
SELECT
    'task' AS entity_type,
    t.name AS entity_name,
    t.display_name AS entity_display_name,
    tv.version_label
FROM task_version tv
JOIN task t ON t.id = tv.task_id AND tv.id = t.current_champion_version_id
WHERE tv.inference_config_id = %(config_id)s::uuid
ORDER BY entity_type, entity_display_name;


-- name: list_tools
SELECT * FROM tool WHERE active = TRUE ORDER BY name;


-- name: get_tool_by_name
SELECT * FROM tool WHERE name = %(tool_name)s;


-- name: get_tool_usage
-- For each tool, which agents/tasks have it authorized (champion versions only).
-- Returns tool_id, entity_type, entity_name for cross-reference display.
SELECT
    avt.tool_id::text AS tool_id,
    'agent' AS entity_type,
    a.display_name AS entity_name
FROM agent_version_tool avt
JOIN agent_version av ON av.id = avt.agent_version_id
JOIN agent a ON a.id = av.agent_id AND av.id = a.current_champion_version_id
WHERE avt.authorized = TRUE
UNION ALL
SELECT
    tvt.tool_id::text AS tool_id,
    'task' AS entity_type,
    t.display_name AS entity_name
FROM task_version_tool tvt
JOIN task_version tv ON tv.id = tvt.task_version_id
JOIN task t ON t.id = tv.task_id AND tv.id = t.current_champion_version_id
WHERE tvt.authorized = TRUE
ORDER BY tool_id, entity_type;




-- name: list_applications
SELECT * FROM application ORDER BY name;


-- name: get_application_by_name
SELECT * FROM application WHERE name = %(app_name)s;


-- name: list_application_entities
-- All entities mapped to an application, with their display names.
SELECT
    ae.entity_type,
    ae.entity_id,
    CASE ae.entity_type
        WHEN 'agent' THEN (SELECT display_name FROM agent WHERE id = ae.entity_id)
        WHEN 'task' THEN (SELECT display_name FROM task WHERE id = ae.entity_id)
        WHEN 'prompt' THEN (SELECT display_name FROM prompt WHERE id = ae.entity_id)
        WHEN 'tool' THEN (SELECT display_name FROM tool WHERE id = ae.entity_id)
        WHEN 'pipeline' THEN (SELECT display_name FROM pipeline WHERE id = ae.entity_id)
    END AS entity_display_name
FROM application_entity ae
WHERE ae.application_id = %(application_id)s::uuid
ORDER BY ae.entity_type, entity_display_name;


-- name: get_entity_applications
-- For every entity, which applications use it. Returns entity_id → app display names.
SELECT
    ae.entity_type,
    ae.entity_id::text,
    STRING_AGG(app.display_name, ', ' ORDER BY app.display_name) AS application_names
FROM application_entity ae
JOIN application app ON app.id = ae.application_id
GROUP BY ae.entity_type, ae.entity_id;


-- name: get_agent_prompts_and_tools_summary
-- For each agent (champion version), comma-separated prompt names and tool names.
SELECT
    a.id::text AS agent_id,
    STRING_AGG(DISTINCT p.display_name, ', ') AS prompt_names,
    STRING_AGG(DISTINCT t.display_name, ', ') AS tool_names
FROM agent a
JOIN agent_version av ON av.id = a.current_champion_version_id
LEFT JOIN entity_prompt_assignment epa ON epa.entity_type = 'agent' AND epa.entity_version_id = av.id
LEFT JOIN prompt_version pvr ON pvr.id = epa.prompt_version_id
LEFT JOIN prompt p ON p.id = pvr.prompt_id
LEFT JOIN agent_version_tool avt ON avt.agent_version_id = av.id AND avt.authorized = TRUE
LEFT JOIN tool t ON t.id = avt.tool_id
GROUP BY a.id;


-- name: get_task_prompts_summary
-- For each task (champion version), comma-separated prompt names.
SELECT
    t.id::text AS task_id,
    STRING_AGG(DISTINCT p.display_name, ', ') AS prompt_names
FROM task t
JOIN task_version tv ON tv.id = t.current_champion_version_id
LEFT JOIN entity_prompt_assignment epa ON epa.entity_type = 'task' AND epa.entity_version_id = tv.id
LEFT JOIN prompt_version pvr ON pvr.id = epa.prompt_version_id
LEFT JOIN prompt p ON p.id = pvr.prompt_id
GROUP BY t.id;


-- name: get_execution_context
SELECT * FROM execution_context WHERE id = %(context_id)s::uuid;


-- name: get_execution_context_by_ref
SELECT * FROM execution_context
WHERE application_id = %(application_id)s::uuid
  AND context_ref = %(context_ref)s;


-- name: list_execution_contexts
SELECT ec.*, app.name AS application_name
FROM execution_context ec
JOIN application app ON app.id = ec.application_id
ORDER BY ec.created_at DESC
LIMIT 50;


-- ── AGENT VERSION DELEGATION (FC-1) ──────────────────────────
-- Queries against agent_version_delegation. The runtime uses
-- check_delegation_authorized to gate the delegate_to_agent meta-tool;
-- the admin UI uses the list_ queries to surface delegation graphs.


-- name: check_delegation_authorized
-- Given (parent_version_id, child_name), return the delegation row plus
-- the resolved child agent_version_id to run, or no rows if unauthorized.
--
-- Resolution rules:
--   - If the delegation row pins child_agent_version_id, use that directly.
--   - Otherwise the row has child_agent_name — resolve to the named
--     agent's current champion via agent.current_champion_version_id.
-- Returned columns:
--   delegation_id, child_agent_name, child_agent_version_id, scope,
--   resolved_child_version_id.
SELECT
    d.id AS delegation_id,
    d.child_agent_name,
    d.child_agent_version_id,
    d.scope,
    COALESCE(
        d.child_agent_version_id,
        (SELECT current_champion_version_id FROM agent WHERE name = d.child_agent_name)
    ) AS resolved_child_version_id
FROM agent_version_delegation d
LEFT JOIN agent_version cav ON d.child_agent_version_id = cav.id
LEFT JOIN agent ca ON ca.id = cav.agent_id
WHERE d.parent_agent_version_id = %(parent_version_id)s
  AND d.authorized = TRUE
  AND (
      d.child_agent_name = %(child_name)s
      OR ca.name = %(child_name)s
  )
LIMIT 1;


-- name: list_delegations_for_parent
-- All delegations authorized from a specific parent agent_version.
-- For the admin UI's "this agent can delegate to:" view.
SELECT
    d.id AS delegation_id,
    d.parent_agent_version_id,
    d.child_agent_name,
    d.child_agent_version_id,
    d.scope,
    d.authorized,
    d.rationale,
    d.notes,
    d.created_at,
    COALESCE(d.child_agent_name, ca.name) AS effective_child_name,
    (d.child_agent_version_id IS NOT NULL) AS is_version_pinned,
    cav.version_label AS child_version_label
FROM agent_version_delegation d
LEFT JOIN agent_version cav ON d.child_agent_version_id = cav.id
LEFT JOIN agent ca ON ca.id = cav.agent_id
WHERE d.parent_agent_version_id = %(parent_version_id)s
ORDER BY effective_child_name, d.created_at;


-- name: list_delegations_to_agent
-- All delegations pointing at a given child agent (by name or via a
-- version pin). For the admin UI's "this agent is delegated to by:" view.
SELECT
    d.id AS delegation_id,
    d.parent_agent_version_id,
    d.child_agent_name,
    d.child_agent_version_id,
    d.scope,
    d.authorized,
    d.rationale,
    d.notes,
    d.created_at,
    pa.name AS parent_agent_name,
    pav.version_label AS parent_version_label
FROM agent_version_delegation d
JOIN agent_version pav ON d.parent_agent_version_id = pav.id
JOIN agent pa ON pa.id = pav.agent_id
LEFT JOIN agent_version cav ON d.child_agent_version_id = cav.id
LEFT JOIN agent ca ON ca.id = cav.agent_id
WHERE d.child_agent_name = %(agent_name)s
   OR ca.name = %(agent_name)s
ORDER BY pa.name, pav.major_version DESC, pav.minor_version DESC;


-- ── WHERE-USED REVERSE LOOKUP ────────────────────────────────
-- Studio's safe-edit guarantee asks "which agent/task versions
-- consume this asset?" before allowing an in-place save on a
-- shared row. The governance.entity_consumers view (defined in
-- schema.sql) captures the FK-based edges; this query filters
-- by (used_type, used_id), de-duplicates across multiple paths,
-- and joins through to the consumer's display fields so the UI
-- can render "Used by triage_agent v2.3.1 [champion]" without a
-- second round-trip. See docs/plans/studio-build-plan.md §2.13.

-- name: get_entity_consumers
WITH consumers AS (
    -- DISTINCT collapses duplicates that arise when a connector
    -- is referenced via multiple paths (e.g. both source and
    -- target on the same task_version).
    SELECT DISTINCT consumer_type, consumer_id
    FROM governance.entity_consumers
    WHERE used_type = %(used_type)s
      AND used_id   = %(used_id)s::uuid
)
SELECT
    'agent_version'::text       AS consumer_type,
    c.consumer_id,
    a.name                      AS consumer_name,
    av.version_label,
    av.lifecycle_state::text    AS lifecycle_state
FROM consumers c
JOIN governance.agent_version av ON av.id = c.consumer_id
JOIN governance.agent a          ON a.id  = av.agent_id
WHERE c.consumer_type = 'agent_version'

UNION ALL

SELECT
    'task_version'::text,
    c.consumer_id,
    t.name,
    tv.version_label,
    tv.lifecycle_state::text
FROM consumers c
JOIN governance.task_version tv ON tv.id = c.consumer_id
JOIN governance.task t          ON t.id  = tv.task_id
WHERE c.consumer_type = 'task_version'

ORDER BY lifecycle_state, consumer_name, version_label;
