-- ============================================================
-- VERITY_DB: analytics views (logical mart over L1)
--
-- Architecture: docs/architecture/compliance-stack.md
--
-- Phase 2 logical mart — read-only views over public.* L1 tables that
-- project them into the L2 shape (`event_ts`, `ingest_ts`, `source_pk`,
-- conformed dim joins). Reports query these views; they NEVER touch L1
-- directly. Phase 5+ replaces views with materialized fact_/dim_ tables;
-- the (table_name, column_name) identifiers in mart_field stay stable
-- across that migration.
--
-- Applied AFTER schema.sql + schema_compliance.sql by migrate.py.
-- ============================================================


-- ── v_entity_version ─────────────────────────────────────────
-- One row per (entity_type, entity_version) covering the three primary
-- versioned governance entities. Used for Model Inventory, Decision
-- Audit Trail (entity-side), Fairness Validation (entity-side).
CREATE OR REPLACE VIEW analytics.v_entity_version AS
WITH agent_v AS (
    SELECT
        av.id::text                         AS source_pk,
        'agent'::text                       AS entity_type,
        a.id                                AS entity_id,
        a.name                              AS entity_name,
        a.display_name                      AS entity_display_name,
        a.description                       AS entity_description,
        av.version_label                    AS version_label,
        av.lifecycle_state::text            AS lifecycle_state,
        av.channel::text                    AS channel,
        a.materiality_tier::text            AS materiality_tier,
        a.owner_name                        AS owner_name,
        a.owner_email                       AS owner_email,
        a.domain                            AS domain,
        av.created_at                       AS event_ts,
        av.created_at                       AS created_at,
        av.created_at                       AS ingest_ts
    FROM agent_version av
    JOIN agent a ON a.id = av.agent_id
),
task_v AS (
    SELECT
        tv.id::text                         AS source_pk,
        'task'::text                        AS entity_type,
        t.id                                AS entity_id,
        t.name                              AS entity_name,
        t.display_name                      AS entity_display_name,
        t.description                       AS entity_description,
        tv.version_label                    AS version_label,
        tv.lifecycle_state::text            AS lifecycle_state,
        tv.channel::text                    AS channel,
        t.materiality_tier::text            AS materiality_tier,
        t.owner_name                        AS owner_name,
        t.owner_email                       AS owner_email,
        t.domain                            AS domain,
        tv.created_at                       AS event_ts,
        tv.created_at                       AS created_at,
        tv.created_at                       AS ingest_ts
    FROM task_version tv
    JOIN task t ON t.id = tv.task_id
),
prompt_v AS (
    SELECT
        pv.id::text                         AS source_pk,
        'prompt'::text                      AS entity_type,
        p.id                                AS entity_id,
        p.name                              AS entity_name,
        p.display_name                      AS entity_display_name,
        p.description                       AS entity_description,
        pv.version_label                    AS version_label,
        pv.lifecycle_state::text            AS lifecycle_state,
        NULL::text                          AS channel,
        NULL::text                          AS materiality_tier,
        NULL::text                          AS owner_name,
        NULL::text                          AS owner_email,
        NULL::text                          AS domain,
        pv.created_at                       AS event_ts,
        pv.created_at                       AS created_at,
        pv.created_at                       AS ingest_ts
    FROM prompt_version pv
    JOIN prompt p ON p.id = pv.prompt_id
)
SELECT * FROM agent_v
UNION ALL
SELECT * FROM task_v
UNION ALL
SELECT * FROM prompt_v;


-- ── v_application_entity ─────────────────────────────────────
-- Resolves which application owns which entity. Joins back to
-- v_entity_version on (entity_type, entity_id).
CREATE OR REPLACE VIEW analytics.v_application_entity AS
SELECT
    ae.id::text                 AS source_pk,
    ae.application_id           AS application_id,
    app.name                    AS application_name,
    app.display_name            AS application_display_name,
    ae.entity_type::text        AS entity_type,
    ae.entity_id                AS entity_id,
    ae.created_at               AS event_ts,
    ae.created_at               AS created_at,
    ae.created_at               AS ingest_ts
FROM application_entity ae
JOIN application app ON app.id = ae.application_id;


-- ── v_lifecycle_event ───────────────────────────────────────
-- State transitions from approval_record. One row per HITL approval gate.
CREATE OR REPLACE VIEW analytics.v_lifecycle_event AS
SELECT
    ar.id::text                 AS source_pk,
    ar.entity_type::text        AS entity_type,
    ar.entity_version_id        AS entity_version_id,
    ar.gate_type                AS gate_type,
    ar.from_state::text         AS from_state,
    ar.to_state::text           AS to_state,
    ar.approver_name            AS approver_name,
    ar.approver_role            AS approver_role,
    ar.rationale                AS rationale,
    ar.approved_at              AS event_ts,
    ar.approved_at              AS approved_at,
    ar.approved_at              AS ingest_ts
FROM approval_record ar;


-- ── v_decision ───────────────────────────────────────────────
-- One row per agent_decision_log entry. The execution-side data for
-- Decision Audit Trail report.
CREATE OR REPLACE VIEW analytics.v_decision AS
SELECT
    adl.id::text                AS source_pk,
    adl.id                      AS decision_id,
    adl.execution_context_id    AS execution_context_id,
    adl.workflow_run_id         AS workflow_run_id,
    adl.entity_type::text       AS entity_type,
    adl.entity_version_id       AS entity_version_id,
    adl.application             AS application_code,
    adl.channel::text           AS channel,
    adl.run_purpose::text       AS run_purpose,
    adl.created_at              AS event_ts,
    adl.created_at              AS created_at,
    adl.created_at              AS ingest_ts,
    adl.input_summary           AS input_summary,
    adl.output_summary          AS output_summary,
    adl.reasoning_text          AS reasoning_text,
    adl.confidence_score        AS confidence_score,
    adl.duration_ms             AS duration_ms,
    adl.input_tokens            AS input_tokens,
    adl.output_tokens           AS output_tokens,
    adl.model_used              AS model_used,
    adl.step_name               AS step_name,
    adl.hitl_required           AS hitl_required,
    adl.hitl_completed          AS hitl_completed,
    adl.low_confidence_flag     AS low_confidence_flag
FROM agent_decision_log adl;


-- ── v_validation_result ──────────────────────────────────────
-- One row per test_execution_log entry. Powers Fairness Validation
-- Summary and the testing component of NAIC Exhibit C.
CREATE OR REPLACE VIEW analytics.v_validation_result AS
SELECT
    tel.id::text                AS source_pk,
    tel.id                      AS test_log_id,
    tel.entity_type::text       AS entity_type,
    tel.entity_version_id       AS entity_version_id,
    tel.suite_id                AS suite_id,
    tel.test_case_id            AS test_case_id,
    tel.run_at                  AS event_ts,
    tel.run_at                  AS run_at,
    tel.run_at                  AS ingest_ts,
    tel.passed                  AS passed,
    tel.duration_ms             AS duration_ms,
    tel.metric_type::text       AS metric_type,
    tel.metric_result           AS metric_result,
    tel.failure_reason          AS failure_reason,
    tel.channel::text           AS channel,
    tel.mock_mode               AS mock_mode
FROM test_execution_log tel;


-- ── v_override ───────────────────────────────────────────────
-- One row per HITL override. Powers fairness production monitoring
-- and override-rate sections of compliance reports.
CREATE OR REPLACE VIEW analytics.v_override AS
SELECT
    ho.id::text                 AS source_pk,
    ho.id                       AS override_id,
    ho.decision_log_id          AS decision_id,
    ho.application              AS application_code,
    ho.entity_type              AS business_entity_type,
    ho.entity_reference         AS business_entity_reference,
    ho.fact_type                AS fact_type,
    ho.output_path              AS output_path,
    ho.ai_value                 AS ai_value,
    ho.hitl_value               AS hitl_value,
    ho.ai_found                 AS ai_found,
    ho.reason                   AS override_reason,
    ho.created_by               AS overridden_by,
    ho.created_at               AS event_ts,
    ho.created_at               AS created_at,
    ho.created_at               AS ingest_ts
FROM hitl_override ho;
