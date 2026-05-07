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
    (SELECT COUNT(*) FROM hitl_override ho
     JOIN agent_decision_log adl ON adl.id = ho.decision_log_id
     WHERE adl.entity_type = 'agent'
       AND adl.entity_version_id = av.id
       AND ho.created_at > NOW() - INTERVAL '30 days') AS override_count_30d,
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
-- Global counts across the whole registry + activity log. The decluttered
-- home dashboard uses this when no application filter is active.
--
-- `open_incidents` is the UNION of two sources:
--   (a) governance-driven incidents (the `incident` table), and
--   (b) currently-active quota breaches (most recent quota_check per
--       quota with alert_fired=true and resolved_at IS NULL).
-- The Incidents admin page renders the same union as a single list
-- so the count on the home tile matches what you see when you click it.
SELECT
    (SELECT COUNT(*) FROM agent) AS agent_count,
    (SELECT COUNT(*) FROM task) AS task_count,
    (SELECT COUNT(*) FROM prompt) AS prompt_count,
    (SELECT COUNT(*) FROM inference_config WHERE active = TRUE) AS config_count,
    (SELECT COUNT(*) FROM tool WHERE active = TRUE) AS tool_count,
    (SELECT COUNT(*) FROM mcp_server WHERE active = TRUE) AS mcp_server_count,
    (SELECT COUNT(*) FROM agent_decision_log) AS total_decisions,
    (SELECT COUNT(*) FROM hitl_override) AS total_overrides,
    (
        (SELECT COUNT(*) FROM incident WHERE status = 'open')
      + (SELECT COUNT(*) FROM (
            SELECT DISTINCT ON (quota_id) alert_fired, resolved_at
            FROM quota_check
            ORDER BY quota_id, checked_at DESC
        ) latest WHERE alert_fired = TRUE AND resolved_at IS NULL)
    ) AS open_incidents;


-- name: dashboard_counts_scoped
-- Counts scoped to an application filter set (home dashboard — one or
-- more app cards selected). Two arrays in parallel: %(app_ids)s of the
-- apps' UUIDs and %(app_names)s of their VARCHAR names. Catalog counts
-- use application_entity; activity counts use the same "application OR
-- execution_context.application_id" predicate as the purge / preview
-- endpoints, so workbench-tagged and legacy-default decisions both count.
--
-- mcp_server and inference_config are platform-wide (not entity-mapped
-- to applications in the data model), so they stay global — matches the
-- admin UX where those catalogs are infrastructure, not app-specific.
SELECT
    (SELECT COUNT(DISTINCT entity_id) FROM application_entity
       WHERE entity_type = 'agent'    AND application_id = ANY(%(app_ids)s::uuid[])) AS agent_count,
    (SELECT COUNT(DISTINCT entity_id) FROM application_entity
       WHERE entity_type = 'task'     AND application_id = ANY(%(app_ids)s::uuid[])) AS task_count,
    (SELECT COUNT(DISTINCT entity_id) FROM application_entity
       WHERE entity_type = 'prompt'   AND application_id = ANY(%(app_ids)s::uuid[])) AS prompt_count,
    (SELECT COUNT(*) FROM inference_config WHERE active = TRUE) AS config_count,
    (SELECT COUNT(DISTINCT entity_id) FROM application_entity
       WHERE entity_type = 'tool'     AND application_id = ANY(%(app_ids)s::uuid[])) AS tool_count,
    (SELECT COUNT(*) FROM mcp_server WHERE active = TRUE) AS mcp_server_count,
    (SELECT COUNT(*) FROM agent_decision_log
       WHERE application = ANY(%(app_names)s::text[])
          OR execution_context_id IN (
                 SELECT id FROM execution_context
                 WHERE application_id = ANY(%(app_ids)s::uuid[])
             )
    ) AS total_decisions,
    (SELECT COUNT(*) FROM hitl_override
       WHERE application = ANY(%(app_names)s::text[])
    ) AS total_overrides,
    -- open_incidents stays global when scoped too — legacy incidents
    -- and quota breaches aren't (yet) attributable per application in
    -- the UI filter. Keeps the scoped + unscoped tile values
    -- consistent with what /admin/incidents shows.
    (
        (SELECT COUNT(*) FROM incident WHERE status = 'open')
      + (SELECT COUNT(*) FROM (
            SELECT DISTINCT ON (quota_id) alert_fired, resolved_at
            FROM quota_check
            ORDER BY quota_id, checked_at DESC
        ) latest WHERE alert_fired = TRUE AND resolved_at IS NULL)
    ) AS open_incidents;


-- name: dashboard_governance_stats
-- Platform-wide governance counters — always unscoped. Approvals,
-- workflow-run totals, in-review counts, and the aggregate test pass
-- rate don't decompose cleanly by application so we show them whole.
SELECT
    (SELECT COUNT(*) FROM approval_record) AS total_approvals,
    (SELECT COUNT(DISTINCT workflow_run_id) FROM agent_decision_log WHERE workflow_run_id IS NOT NULL) AS total_workflow_runs,
    (SELECT COUNT(*) FROM application) AS app_count,
    (SELECT COUNT(*) FROM agent_version WHERE lifecycle_state IN ('staging', 'shadow', 'challenger')) AS entities_in_review,
    (SELECT COUNT(*) FROM test_execution_log WHERE passed = TRUE) AS tests_passed,
    (SELECT COUNT(*) FROM test_execution_log) AS tests_total;


-- name: dashboard_workflow_runs_scoped
-- Number of distinct workflow_run_ids tied to the selected apps (same OR
-- predicate as dashboard_counts_scoped). Used by the Activity section's
-- "Workflow Runs" card. Renamed from dashboard_pipeline_runs_scoped now
-- that workflow_run_id is caller-supplied (not Verity-owned).
SELECT COUNT(DISTINCT workflow_run_id) AS total_workflow_runs
FROM agent_decision_log
WHERE workflow_run_id IS NOT NULL
  AND (application = ANY(%(app_names)s::text[])
       OR execution_context_id IN (
              SELECT id FROM execution_context
              WHERE application_id = ANY(%(app_ids)s::uuid[])
          ));


-- name: override_analysis
-- Recent HITL overrides grouped by entity (agent or task) and
-- fact_type. Replaces a prior version that grouped by
-- override_reason_code from the legacy override_log; we don't
-- carry a structured reason code on hitl_override (just freetext
-- reason), so the grouping moved to fact_type — which is more
-- useful anyway for "which fields drift between AI and human?"
SELECT
    ho.fact_type,
    COUNT(*) AS count,
    COALESCE(a.name, t.name) AS entity_name,
    adl.entity_type
FROM hitl_override ho
JOIN agent_decision_log adl ON adl.id = ho.decision_log_id
LEFT JOIN agent_version av  ON av.id = adl.entity_version_id AND adl.entity_type = 'agent'
LEFT JOIN agent a           ON a.id  = av.agent_id
LEFT JOIN task_version tv   ON tv.id = adl.entity_version_id AND adl.entity_type = 'task'
LEFT JOIN task t            ON t.id  = tv.task_id
WHERE ho.created_at > NOW() - INTERVAL '%(days)s days'
GROUP BY ho.fact_type, adl.entity_type, a.name, t.name
ORDER BY count DESC;


-- name: list_open_incidents
-- Unified list of active incidents. Two sources in one view:
--   1) governance incidents (`incident` table, status='open') — legacy
--      signal populated by earlier flows (failed validation runs,
--      similarity drift, etc.).
--   2) active quota breaches — the most recent quota_check per quota
--      whose alert_fired is true and resolved_at is null.
-- Rendered as a single list on /admin/incidents, newest first.
WITH latest_breach AS (
    SELECT DISTINCT ON (quota_id)
        id, quota_id, checked_at, spend_usd, budget_usd, spend_pct,
        alert_level
    FROM quota_check
    WHERE alert_fired = TRUE
    ORDER BY quota_id, checked_at DESC
)
SELECT
    i.id::text                                    AS id,
    'governance'::text                            AS source,
    i.title                                       AS title,
    i.description                                 AS description,
    i.severity                                    AS severity,
    i.detected_at                                 AS detected_at,
    i.status                                      AS status,
    i.entity_type::text                           AS scope_type,
    NULL::text                                    AS scope_name,
    NULL::numeric                                 AS spend_usd,
    NULL::numeric                                 AS budget_usd,
    NULL::integer                                 AS spend_pct
FROM incident i
WHERE i.status = 'open'

UNION ALL

SELECT
    lb.id::text                                   AS id,
    'quota'::text                                 AS source,
    -- Prefer the scope's human-friendly display name in the title,
    -- matching the convention used on the Quotas and Usage pages.
    ('Quota breach — ' || COALESCE(
        app.display_name, a.display_name, t.display_name,
        m.display_name, q.scope_name
    ))                                            AS title,
    -- psycopg parses the raw SQL text for placeholders and does not
    -- skip comments, so any literal percent sign inside THIS comment
    -- would also need doubling. The `percent` character in the
    -- concat below is doubled in the string literal.
    ('Spend ' || lb.spend_pct || '%% of $'
        || q.budget_usd || ' ' || q.period
        || ' budget (scope_type ' || q.scope_type || ')') AS description,
    COALESCE(lb.alert_level, 'warning')           AS severity,
    lb.checked_at                                 AS detected_at,
    'open'::text                                  AS status,
    q.scope_type                                  AS scope_type,
    COALESCE(
        app.display_name, a.display_name, t.display_name,
        m.display_name, q.scope_name
    )                                             AS scope_name,
    lb.spend_usd                                  AS spend_usd,
    lb.budget_usd                                 AS budget_usd,
    lb.spend_pct                                  AS spend_pct
FROM latest_breach lb
JOIN quota q ON q.id = lb.quota_id
LEFT JOIN application app ON q.scope_type = 'application' AND app.id = q.scope_id
LEFT JOIN agent       a   ON q.scope_type = 'agent'       AND a.id   = q.scope_id
LEFT JOIN task        t   ON q.scope_type = 'task'        AND t.id   = q.scope_id
LEFT JOIN model       m   ON q.scope_type = 'model'       AND m.id   = q.scope_id
-- Only include quota breaches that haven't been resolved since the
-- latest check (the DISTINCT-ON in latest_breach only filters by
-- alert_fired; resolved_at is evaluated here for the final filter).
JOIN quota_check qc ON qc.id = lb.id
WHERE qc.resolved_at IS NULL

ORDER BY detected_at DESC
LIMIT 200;


-- ============================================================
-- INVENTORY GRAPH QUERIES
-- Powers /admin/model-inventory/graph — three-lane network view
-- of champion executables (agents + tasks) with their wired-up
-- prompts, configs, tools, and inter-agent delegations.
--
-- "Champion" everywhere here means: only the version pointed at
-- by current_champion_version_id on the parent agent/task. The
-- graph shows what is *currently in production*, not the full
-- lifecycle history.
-- ============================================================

-- name: inventory_graph_agents
-- One row per agent with a champion. Carries everything the
-- node card needs (display name, materiality, decision count,
-- last validation status) plus the agent_version id used by
-- the edge queries below to wire up prompts/configs/tools.
SELECT
    a.id                              AS agent_id,
    a.name                            AS name,
    a.display_name                    AS display_name,
    a.materiality_tier                AS materiality_tier,
    a.domain                          AS domain,
    a.owner_name                      AS owner_name,
    av.id                             AS agent_version_id,
    av.version_label                  AS champion_version,
    av.inference_config_id            AS inference_config_id,
    ic.name                           AS inference_config_name,
    ic.model_name                     AS model_name,
    -- Last validation outcome — drives the small status dot on
    -- the node. NULL when no validation has run yet.
    (
        SELECT vr.passed FROM validation_run vr
        WHERE vr.entity_type = 'agent'
          AND vr.entity_version_id = av.id
        ORDER BY vr.run_at DESC LIMIT 1
    )                                 AS last_validation_passed,
    -- Last 30 days of decisions — drives the bubble inside the
    -- node. Same window as the existing inventory report so the
    -- two views stay consistent.
    (
        SELECT COUNT(*) FROM agent_decision_log adl
        WHERE adl.entity_type = 'agent'
          AND adl.entity_version_id = av.id
          AND adl.created_at > NOW() - INTERVAL '30 days'
    )                                 AS decision_count_30d
FROM agent a
JOIN agent_version av
  ON av.id = a.current_champion_version_id
JOIN inference_config ic
  ON ic.id = av.inference_config_id
ORDER BY a.materiality_tier, a.name;


-- name: inventory_graph_tasks
-- Same shape as inventory_graph_agents but for tasks. Tasks
-- don't have delegation, so the graph never draws edges
-- between two tasks.
SELECT
    t.id                              AS task_id,
    t.name                            AS name,
    t.display_name                    AS display_name,
    t.capability_type                 AS capability_type,
    t.materiality_tier                AS materiality_tier,
    t.domain                          AS domain,
    t.owner_name                      AS owner_name,
    tv.id                             AS task_version_id,
    tv.version_label                  AS champion_version,
    tv.inference_config_id            AS inference_config_id,
    ic.name                           AS inference_config_name,
    ic.model_name                     AS model_name,
    (
        SELECT vr.passed FROM validation_run vr
        WHERE vr.entity_type = 'task'
          AND vr.entity_version_id = tv.id
        ORDER BY vr.run_at DESC LIMIT 1
    )                                 AS last_validation_passed,
    (
        SELECT COUNT(*) FROM agent_decision_log adl
        WHERE adl.entity_type = 'task'
          AND adl.entity_version_id = tv.id
          AND adl.created_at > NOW() - INTERVAL '30 days'
    )                                 AS decision_count_30d
FROM task t
JOIN task_version tv
  ON tv.id = t.current_champion_version_id
JOIN inference_config ic
  ON ic.id = tv.inference_config_id
ORDER BY t.materiality_tier, t.name;


-- name: inventory_graph_prompts
-- One row per prompt_version that is referenced by at least
-- one champion agent_version OR task_version. Returns the
-- *prompt*-level identity (prompt_id + display_name) plus the
-- specific version label so the node can show "Triage System
-- v1.0.0" without ambiguity.
--
-- DISTINCT ON collapses the case where a prompt_version is
-- assigned to multiple champion entities — the join would
-- otherwise emit duplicate rows.
SELECT DISTINCT ON (pv.id)
    pv.id                             AS prompt_version_id,
    p.id                              AS prompt_id,
    p.name                            AS name,
    p.display_name                    AS display_name,
    pv.version_label                  AS version_label,
    pv.governance_tier                AS governance_tier,
    pv.api_role                       AS api_role,
    pv.sensitivity_level              AS sensitivity_level
FROM prompt p
JOIN prompt_version pv
  ON pv.prompt_id = p.id
JOIN entity_prompt_assignment epa
  ON epa.prompt_version_id = pv.id
WHERE
    -- Prompt is in production iff it's assigned to a champion
    -- agent_version or task_version. Two-side existence check
    -- avoids pulling assignments that belong to draft / shadow
    -- versions.
    EXISTS (
        SELECT 1 FROM agent a
        JOIN agent_version av
          ON av.id = a.current_champion_version_id
        WHERE epa.entity_type = 'agent'
          AND epa.entity_version_id = av.id
    )
    OR EXISTS (
        SELECT 1 FROM task t
        JOIN task_version tv
          ON tv.id = t.current_champion_version_id
        WHERE epa.entity_type = 'task'
          AND epa.entity_version_id = tv.id
    )
ORDER BY pv.id, p.name;


-- name: inventory_graph_configs
-- One row per inference_config referenced by a champion
-- agent_version or task_version. The graph treats configs as
-- shared resources — two agents using the same config render
-- as two edges to the same node.
SELECT
    ic.id                             AS config_id,
    ic.name                           AS name,
    ic.display_name                   AS display_name,
    ic.model_name                     AS model_name,
    ic.temperature                    AS temperature,
    ic.max_tokens                     AS max_tokens
FROM inference_config ic
WHERE EXISTS (
    SELECT 1 FROM agent a
    JOIN agent_version av
      ON av.id = a.current_champion_version_id
    WHERE av.inference_config_id = ic.id
)
   OR EXISTS (
    SELECT 1 FROM task t
    JOIN task_version tv
      ON tv.id = t.current_champion_version_id
    WHERE tv.inference_config_id = ic.id
)
ORDER BY ic.name;


-- name: inventory_graph_tools
-- One row per tool authorised on at least one champion
-- agent_version or task_version. Includes mcp_server_name so
-- the tooltip can flag MCP-backed tools (transport != local).
SELECT
    t.id                              AS tool_id,
    t.name                            AS name,
    t.display_name                    AS display_name,
    t.description                     AS description,
    t.transport                       AS transport,
    t.mcp_server_name                 AS mcp_server_name,
    t.is_write_operation              AS is_write_operation
FROM tool t
WHERE EXISTS (
    SELECT 1 FROM agent_version_tool avt
    JOIN agent a
      ON a.current_champion_version_id = avt.agent_version_id
    WHERE avt.tool_id = t.id
      AND avt.authorized = TRUE
)
   OR EXISTS (
    SELECT 1 FROM task_version_tool tvt
    JOIN task t2
      ON t2.current_champion_version_id = tvt.task_version_id
    WHERE tvt.tool_id = t.id
      AND tvt.authorized = TRUE
)
ORDER BY t.name;


-- name: inventory_graph_edges_executable_prompt
-- agent/task → prompt edges. entity_type column lets the
-- client pick the right "from" lane without a second lookup.
-- entity_id is the parent (agent.id or task.id) — what the
-- node id is in the front-end graph data.
SELECT
    epa.entity_type                   AS source_entity_type,
    CASE WHEN epa.entity_type = 'agent'
         THEN a.id ELSE t.id END      AS source_entity_id,
    epa.prompt_version_id             AS prompt_version_id,
    epa.api_role                      AS api_role,
    epa.governance_tier               AS governance_tier,
    epa.execution_order               AS execution_order
FROM entity_prompt_assignment epa
LEFT JOIN agent_version av
       ON epa.entity_type = 'agent'
      AND av.id = epa.entity_version_id
LEFT JOIN agent a
       ON a.current_champion_version_id = av.id
LEFT JOIN task_version tv
       ON epa.entity_type = 'task'
      AND tv.id = epa.entity_version_id
LEFT JOIN task t
       ON t.current_champion_version_id = tv.id
WHERE
    -- Filter to assignments whose entity_version IS the current
    -- champion. The two LEFT JOINs above produce a NULL on the
    -- non-matching side; the WHERE keeps only rows where the
    -- matching side resolves to a champion.
    (epa.entity_type = 'agent' AND a.id IS NOT NULL)
 OR (epa.entity_type = 'task'  AND t.id IS NOT NULL);


-- name: inventory_graph_edges_executable_config
-- agent/task → config edges. One row per champion entity
-- (every agent/task has exactly one inference_config_id, so
-- this is a 1:1 emission per executable).
SELECT
    'agent'::text                     AS source_entity_type,
    a.id                              AS source_entity_id,
    av.inference_config_id            AS config_id
FROM agent a
JOIN agent_version av
  ON av.id = a.current_champion_version_id
UNION ALL
SELECT
    'task'::text                      AS source_entity_type,
    t.id                              AS source_entity_id,
    tv.inference_config_id            AS config_id
FROM task t
JOIN task_version tv
  ON tv.id = t.current_champion_version_id;


-- name: inventory_graph_edges_executable_tool
-- agent/task → tool edges. Pulls the authorised flag through
-- so the front-end can distinguish a wired-but-disabled
-- relationship if we ever surface that.
SELECT
    'agent'::text                     AS source_entity_type,
    a.id                              AS source_entity_id,
    avt.tool_id                       AS tool_id,
    avt.authorized                    AS authorized
FROM agent_version_tool avt
JOIN agent a
  ON a.current_champion_version_id = avt.agent_version_id
UNION ALL
SELECT
    'task'::text                      AS source_entity_type,
    t.id                              AS source_entity_id,
    tvt.tool_id                       AS tool_id,
    tvt.authorized                    AS authorized
FROM task_version_tool tvt
JOIN task t
  ON t.current_champion_version_id = tvt.task_version_id;


-- name: inventory_graph_edges_delegation
-- agent → child agent edges, drawn within the Executables
-- lane. The schema allows two ways to point at the child:
--   * child_agent_name      — name-based pin (any version)
--   * child_agent_version_id — pinned to a specific version
-- For the production graph we only care about which AGENTS
-- delegate to which AGENTS, not the version the parent pinned
-- to. Both forms collapse to the parent agent.id of the child.
SELECT
    parent_agent.id                   AS parent_agent_id,
    child_agent.id                    AS child_agent_id,
    avd.scope                         AS scope,
    avd.authorized                    AS authorized
FROM agent_version_delegation avd
-- Parent must be a champion version of its agent.
JOIN agent_version parent_av
  ON parent_av.id = avd.parent_agent_version_id
JOIN agent parent_agent
  ON parent_agent.current_champion_version_id = parent_av.id
-- Child resolves either via the named pin or the version pin.
JOIN agent child_agent
  ON child_agent.id = COALESCE(
        (SELECT agent_id FROM agent_version
          WHERE id = avd.child_agent_version_id),
        (SELECT id FROM agent
          WHERE name = avd.child_agent_name)
     )
WHERE avd.authorized = TRUE;


-- name: inventory_graph_applications
-- One row per application — small helper that powers the
-- "Filter by application" dropdown on the graph page. Listed
-- by display_name for predictable ordering in the UI.
SELECT
    id                                AS id,
    name                              AS name,
    display_name                      AS display_name
FROM application
ORDER BY display_name;


-- name: inventory_graph_application_membership
-- Many-to-many: which application(s) each registered entity
-- belongs to. The graph applies this in two passes — direct
-- for entities of types in application_entity (agent / task /
-- prompt / tool), and inherited for configs (a config belongs
-- to every application that owns an executable wired to it).
--
-- Each row is keyed by (entity_type, entity_id, application_id).
-- entity_id matches: agent.id, task.id, prompt.id, tool.id —
-- never an _version row, since application membership lives
-- at the registered-entity level.
SELECT
    ae.entity_type                    AS entity_type,
    ae.entity_id                      AS entity_id,
    ae.application_id                 AS application_id
FROM application_entity ae;
