-- ============================================================
-- INTAKE QUERIES
--
-- Named queries for the governance intake layer:
--   intake, intake_impact_assessment, intake_requirement,
--   intake_entity_link, intake_artifact_plan,
--   approval_request, approval_signoff
--
-- See verity/src/verity/db/schema_intake.sql for the schema and
-- docs/architecture/governance-intake.md for the design contract.
-- ============================================================


-- ── INTAKE: CREATE / READ / UPDATE ───────────────────────────

-- name: insert_intake
INSERT INTO governance.intake (
    application_id,
    code, title, problem_statement, expected_benefit,
    in_scope_decisions, out_of_scope_decisions, affected_populations,
    business_owner_name, business_owner_email, requesting_team,
    ai_risk_tier, risk_classification_rationale, naic_materiality,
    status, created_by, acting_as_role, notes,
    hitl_strategy, hitl_review_threshold
) VALUES (
    %(application_id)s,
    %(code)s, %(title)s, %(problem_statement)s, %(expected_benefit)s,
    %(in_scope_decisions)s, %(out_of_scope_decisions)s, %(affected_populations)s,
    %(business_owner_name)s, %(business_owner_email)s, %(requesting_team)s,
    %(ai_risk_tier)s, %(risk_classification_rationale)s, %(naic_materiality)s,
    %(status)s, %(created_by)s, %(acting_as_role)s, %(notes)s,
    %(hitl_strategy)s, %(hitl_review_threshold)s
)
RETURNING *;


-- name: get_intake_by_code
-- Joined to governance.application so the service / API layer can show
-- the owning application's code + display name without an extra hop.
-- Path-scoped: requires both application_code AND intake_code because
-- two applications can each have their own intake with the same code.
SELECT i.*,
       a.name         AS application_code,
       a.display_name AS application_name
FROM governance.intake i
JOIN governance.application a ON a.id = i.application_id
WHERE a.name = %(application_code)s
  AND i.code = %(code)s;


-- name: probe_intake_code_in_app
-- Existence probe used by IntakeService._next_unique_code to find a
-- non-colliding slug within an application before insert. Returns the
-- intake row if a row already exists with this (application_id, code),
-- NULL otherwise. Cheap — index hits the intake_app_code_key.
SELECT id
FROM governance.intake
WHERE application_id = %(application_id)s
  AND code = %(code)s;


-- name: get_intake_by_id
SELECT i.*,
       a.name         AS application_code,
       a.display_name AS application_name
FROM governance.intake i
JOIN governance.application a ON a.id = i.application_id
WHERE i.id = %(id)s;


-- name: list_intakes
SELECT
    i.id, i.code, i.title, i.status, i.ai_risk_tier, i.naic_materiality,
    i.business_owner_name, i.business_owner_email, i.requesting_team,
    i.intake_at, i.approved_at, i.retired_at, i.created_by, i.updated_at,
    a.name         AS application_code,
    a.display_name AS application_name
FROM governance.intake i
JOIN governance.application a ON a.id = i.application_id
ORDER BY
    CASE status
        WHEN 'proposed' THEN 0
        WHEN 'in_review' THEN 1
        WHEN 'impact_assessment' THEN 2
        WHEN 'approved' THEN 3
        WHEN 'in_build' THEN 4
        WHEN 'live' THEN 5
        WHEN 'rejected' THEN 6
        WHEN 'retired' THEN 7
    END,
    intake_at DESC;


-- name: list_intakes_filtered
-- Optional filters; each param can be NULL to skip its filter.
-- Explicit ::text casts on the IS NULL probes so Postgres can deduce
-- the parameter type even when only the IS-NULL branch is provided.
SELECT
    i.id, i.code, i.title, i.status, i.ai_risk_tier, i.naic_materiality,
    i.business_owner_name, i.business_owner_email, i.requesting_team,
    i.intake_at, i.approved_at, i.retired_at, i.created_by, i.updated_at,
    a.name         AS application_code,
    a.display_name AS application_name
FROM governance.intake i
JOIN governance.application a ON a.id = i.application_id
WHERE
    (%(status)s::text IS NULL
        OR i.status = %(status)s::governance.intake_status)
    AND (%(ai_risk_tier)s::text IS NULL
        OR i.ai_risk_tier = %(ai_risk_tier)s::governance.ai_risk_tier)
    AND (%(business_owner_email)s::text IS NULL
        OR i.business_owner_email = %(business_owner_email)s)
    AND (%(application_code)s::text IS NULL
        OR a.name = %(application_code)s)
ORDER BY i.intake_at DESC;


-- name: update_intake_mutable
-- Updates only mutable fields. Uses COALESCE so callers can pass NULL
-- to leave a field unchanged. Keeps risk-tier / status / lifecycle
-- timestamps OUT of this query — those move via dedicated transitions.
UPDATE governance.intake SET
    title = COALESCE(%(title)s, title),
    problem_statement = COALESCE(%(problem_statement)s, problem_statement),
    expected_benefit = COALESCE(%(expected_benefit)s, expected_benefit),
    in_scope_decisions = COALESCE(%(in_scope_decisions)s, in_scope_decisions),
    out_of_scope_decisions = COALESCE(%(out_of_scope_decisions)s, out_of_scope_decisions),
    affected_populations = COALESCE(%(affected_populations)s, affected_populations),
    business_owner_name = COALESCE(%(business_owner_name)s, business_owner_name),
    business_owner_email = COALESCE(%(business_owner_email)s, business_owner_email),
    requesting_team = COALESCE(%(requesting_team)s, requesting_team),
    notes = COALESCE(%(notes)s, notes),
    hitl_strategy = COALESCE(%(hitl_strategy)s, hitl_strategy),
    hitl_review_threshold = COALESCE(%(hitl_review_threshold)s, hitl_review_threshold),
    updated_at = now()
WHERE id = %(id)s
RETURNING *;


-- name: triage_intake
-- Sets risk tier + materiality + rationale and advances status to
-- 'in_review' (if not already past it). Used by the AI-Governance
-- triage action. Status only moves forward — never backwards from this.
UPDATE governance.intake SET
    ai_risk_tier = %(ai_risk_tier)s::governance.ai_risk_tier,
    naic_materiality = %(naic_materiality)s::governance.naic_materiality,
    risk_classification_rationale = %(risk_classification_rationale)s,
    status = CASE
        WHEN status = 'proposed' THEN 'in_review'::governance.intake_status
        WHEN status = 'in_review' AND %(ai_risk_tier)s IN ('limited','high')
            THEN 'impact_assessment'::governance.intake_status
        ELSE status
    END,
    updated_at = now()
WHERE id = %(id)s
RETURNING *;


-- name: reject_intake
-- Auto-rejects an intake. Used for the 'unacceptable' tier path
-- and for explicit governance-team rejections.
UPDATE governance.intake SET
    status = 'rejected'::governance.intake_status,
    updated_at = now(),
    notes = COALESCE(%(notes)s, notes)
WHERE id = %(id)s
RETURNING *;


-- name: approve_intake
-- Marks an intake approved once all required signoffs are in. Status
-- moves to 'approved'; the artifact plan generator runs separately.
UPDATE governance.intake SET
    status = 'approved'::governance.intake_status,
    approved_at = now(),
    updated_at = now()
WHERE id = %(id)s AND status IN ('in_review','impact_assessment')
RETURNING *;


-- name: mark_intake_in_build
UPDATE governance.intake SET
    status = 'in_build'::governance.intake_status,
    updated_at = now()
WHERE id = %(id)s AND status = 'approved'
RETURNING *;


-- name: mark_intake_live
UPDATE governance.intake SET
    status = 'live'::governance.intake_status,
    updated_at = now()
WHERE id = %(id)s AND status IN ('approved','in_build')
RETURNING *;


-- name: retire_intake
UPDATE governance.intake SET
    status = 'retired'::governance.intake_status,
    retired_at = now(),
    updated_at = now()
WHERE id = %(id)s
RETURNING *;


-- ── INTAKE REQUIREMENTS ──────────────────────────────────────

-- name: insert_intake_requirement
INSERT INTO governance.intake_requirement (
    intake_id, code, kind, statement, acceptance_criteria,
    source, status, parent_requirement_id, created_by, acting_as_role
) VALUES (
    %(intake_id)s, %(code)s, %(kind)s, %(statement)s, %(acceptance_criteria)s,
    %(source)s, %(status)s, %(parent_requirement_id)s,
    %(created_by)s, %(acting_as_role)s
)
RETURNING *;


-- name: list_requirements_for_intake
SELECT
    id, intake_id, code, kind, statement, acceptance_criteria,
    source, status, parent_requirement_id,
    (embedding IS NOT NULL) AS has_embedding,
    created_by, acting_as_role, updated_at
FROM governance.intake_requirement
WHERE intake_id = %(intake_id)s
ORDER BY
    CASE kind
        WHEN 'business' THEN 0
        WHEN 'functional' THEN 1
        WHEN 'non_functional' THEN 2
        WHEN 'compliance' THEN 3
    END,
    code;


-- name: get_requirement_by_id
SELECT
    id, intake_id, code, kind, statement, acceptance_criteria,
    source, status, parent_requirement_id,
    (embedding IS NOT NULL) AS has_embedding,
    created_by, acting_as_role, updated_at
FROM governance.intake_requirement
WHERE id = %(id)s;


-- name: update_requirement
UPDATE governance.intake_requirement SET
    statement = COALESCE(%(statement)s, statement),
    acceptance_criteria = COALESCE(%(acceptance_criteria)s, acceptance_criteria),
    source = COALESCE(%(source)s, source),
    status = COALESCE(%(status)s::governance.requirement_status, status),
    parent_requirement_id = COALESCE(%(parent_requirement_id)s, parent_requirement_id),
    updated_at = now()
WHERE id = %(id)s
RETURNING *;


-- name: update_requirement_embedding
-- Writes the pgvector embedding plus the model FK and the SHA-256
-- hash of the input text. The hash is the staleness sentinel — the
-- reembed CLI selects rows where the hash no longer matches the
-- current text or where embedding_model_id ≠ current model.
UPDATE governance.intake_requirement SET
    embedding = %(embedding)s,
    embedding_model_id = %(embedding_model_id)s,
    embedding_input_hash = %(embedding_input_hash)s,
    updated_at = now()
WHERE id = %(id)s
RETURNING id;


-- name: search_similar_requirements
-- Cosine-similarity search across all intake_requirement rows whose
-- embedding is set. Returns the top-N rows above the threshold.
-- Used by Studio's redundancy-check HTMX endpoint.
SELECT
    r.id, r.intake_id, r.code, r.kind, r.statement, r.acceptance_criteria,
    r.status,
    i.code AS intake_code, i.title AS intake_title,
    1 - (r.embedding <=> %(query_embedding)s) AS similarity
FROM governance.intake_requirement r
JOIN governance.intake i ON i.id = r.intake_id
WHERE r.embedding IS NOT NULL
    AND (%(exclude_id)s::uuid IS NULL OR r.id != %(exclude_id)s::uuid)
    AND 1 - (r.embedding <=> %(query_embedding)s) >= %(min_similarity)s
ORDER BY r.embedding <=> %(query_embedding)s
LIMIT %(top_n)s;


-- name: list_stale_requirement_embeddings
-- Reembed CLI selector. Returns rows whose embedding is missing OR
-- whose model FK differs from the current model OR whose hash no
-- longer matches the SHA-256 of (statement || COALESCE(acceptance_criteria,'')).
-- The hash check is computed in Python because pgcrypto is not
-- guaranteed; the SQL only flags missing-or-wrong-model rows.
SELECT id, intake_id, code, statement, acceptance_criteria,
       embedding_model_id, embedding_input_hash
FROM governance.intake_requirement
WHERE embedding IS NULL
   OR embedding_model_id IS NULL
   OR embedding_model_id != %(current_model_id)s;


-- ── INTAKE ENTITY LINKS ──────────────────────────────────────

-- name: insert_intake_entity_link
INSERT INTO governance.intake_entity_link (
    intake_id, requirement_id, entity_type, entity_id,
    relationship, created_by, acting_as_role
) VALUES (
    %(intake_id)s, %(requirement_id)s, %(entity_type)s::governance.entity_type,
    %(entity_id)s, %(relationship)s::governance.requirement_relationship,
    %(created_by)s, %(acting_as_role)s
)
ON CONFLICT (intake_id, requirement_id, entity_type, entity_id, relationship)
    DO NOTHING
RETURNING *;


-- name: list_entity_links_for_intake
SELECT *
FROM governance.intake_entity_link
WHERE intake_id = %(intake_id)s
ORDER BY entity_type, created_at;


-- name: list_intakes_for_entity
-- Reverse lookup: which intakes link to this registry entity? Used
-- by the lifecycle promotion gate (§ 4.5 of governance-intake.md).
SELECT
    l.id AS link_id, l.requirement_id, l.relationship,
    i.id, i.code, i.title, i.status, i.ai_risk_tier
FROM governance.intake_entity_link l
JOIN governance.intake i ON i.id = l.intake_id
WHERE l.entity_type = %(entity_type)s::governance.entity_type
  AND l.entity_id = %(entity_id)s;


-- name: delete_intake_entity_link
DELETE FROM governance.intake_entity_link
WHERE id = %(id)s
RETURNING id;


-- name: get_entity_link_by_id
SELECT * FROM governance.intake_entity_link
WHERE id = %(id)s;


-- ── ARTIFACT PLAN ────────────────────────────────────────────

-- name: insert_artifact_plan_row
-- The (intake_id, proposed_kind, proposed_name) tuple is unique. The
-- "remove from plan" path now hard-deletes (see delete_artifact_plan_row)
-- so re-running the plan generator naturally re-creates rows whose
-- requirements still warrant them — no soft-delete conflict to worry
-- about. ON CONFLICT DO NOTHING keeps the helper idempotent for the
-- generator's repeat runs while a row genuinely already exists.
INSERT INTO governance.intake_artifact_plan (
    intake_id, requirement_id, proposed_kind,
    proposed_name, proposed_display_name, proposed_description,
    proposed_purpose, proposed_inputs, proposed_outputs,
    proposed_capability_type, proposed_materiality_tier,
    auto_generated, created_by, acting_as_role
) VALUES (
    %(intake_id)s, %(requirement_id)s, %(proposed_kind)s::governance.entity_type,
    %(proposed_name)s, %(proposed_display_name)s, %(proposed_description)s,
    %(proposed_purpose)s, %(proposed_inputs)s, %(proposed_outputs)s,
    %(proposed_capability_type)s::governance.capability_type,
    %(proposed_materiality_tier)s::governance.materiality_tier,
    %(auto_generated)s, %(created_by)s, %(acting_as_role)s
)
ON CONFLICT (intake_id, proposed_kind, proposed_name) DO NOTHING
RETURNING *;


-- name: list_artifact_plan_rows
SELECT *
FROM governance.intake_artifact_plan
WHERE intake_id = %(intake_id)s
ORDER BY proposed_kind, proposed_name;


-- name: get_artifact_plan_row
SELECT *
FROM governance.intake_artifact_plan
WHERE id = %(id)s;


-- name: update_artifact_plan_row
UPDATE governance.intake_artifact_plan SET
    proposed_name = COALESCE(%(proposed_name)s, proposed_name),
    proposed_display_name = COALESCE(%(proposed_display_name)s, proposed_display_name),
    proposed_description = COALESCE(%(proposed_description)s, proposed_description),
    proposed_purpose = COALESCE(%(proposed_purpose)s, proposed_purpose),
    proposed_inputs = COALESCE(%(proposed_inputs)s, proposed_inputs),
    proposed_outputs = COALESCE(%(proposed_outputs)s, proposed_outputs),
    status = COALESCE(%(status)s::governance.artifact_plan_status, status),
    updated_at = now()
WHERE id = %(id)s
RETURNING *;


-- name: realize_artifact_plan_row
-- Called after an engineer creates a registry entity from this plan.
-- Sets realized_entity_id and flips status -> realized.
UPDATE governance.intake_artifact_plan SET
    realized_entity_id = %(realized_entity_id)s,
    status = 'realized'::governance.artifact_plan_status,
    updated_at = now()
WHERE id = %(id)s
RETURNING *;


-- name: delete_artifact_plan_row
DELETE FROM governance.intake_artifact_plan
WHERE id = %(id)s
RETURNING id;


-- ── IMPACT ASSESSMENT ────────────────────────────────────────

-- name: upsert_impact_assessment
-- Inserts or updates the version=1 impact assessment for an intake.
-- Phase A only writes version=1; Phase B may grow this to a true
-- revision flow.
INSERT INTO governance.intake_impact_assessment (
    intake_id, version,
    data_sources, potential_harms, mitigations,
    fairness_considerations, privacy_considerations,
    human_oversight_plan, completed_at, completed_by, notes
) VALUES (
    %(intake_id)s, 1,
    %(data_sources)s, %(potential_harms)s, %(mitigations)s,
    %(fairness_considerations)s, %(privacy_considerations)s,
    %(human_oversight_plan)s, %(completed_at)s, %(completed_by)s, %(notes)s
)
ON CONFLICT (intake_id, version) DO UPDATE SET
    data_sources = EXCLUDED.data_sources,
    potential_harms = EXCLUDED.potential_harms,
    mitigations = EXCLUDED.mitigations,
    fairness_considerations = EXCLUDED.fairness_considerations,
    privacy_considerations = EXCLUDED.privacy_considerations,
    human_oversight_plan = EXCLUDED.human_oversight_plan,
    completed_at = EXCLUDED.completed_at,
    completed_by = EXCLUDED.completed_by,
    notes = EXCLUDED.notes
RETURNING *;


-- name: get_impact_assessment
SELECT *
FROM governance.intake_impact_assessment
WHERE intake_id = %(intake_id)s
ORDER BY version DESC
LIMIT 1;


-- ── APPROVAL REQUEST + SIGNOFF ───────────────────────────────

-- name: insert_approval_request
INSERT INTO governance.approval_request (
    intake_id, kind, target_entity_type, target_entity_id,
    required_roles, status, opened_by, opened_by_role, summary, notes
) VALUES (
    %(intake_id)s,
    %(kind)s::governance.approval_request_kind,
    %(target_entity_type)s::governance.entity_type,
    %(target_entity_id)s,
    %(required_roles)s,
    'pending',
    %(opened_by)s, %(opened_by_role)s, %(summary)s, %(notes)s
)
RETURNING *;


-- name: get_approval_request
SELECT *
FROM governance.approval_request
WHERE id = %(id)s;


-- name: list_approval_requests_for_intake
SELECT *
FROM governance.approval_request
WHERE intake_id = %(intake_id)s
ORDER BY opened_at DESC;


-- name: list_open_intake_approvals
-- An intake-level approval is open when status='pending' AND kind='intake'.
-- Used by the promotion gate (§ 4.5) to detect "approval not yet decided".
SELECT *
FROM governance.approval_request
WHERE intake_id = %(intake_id)s
  AND status = 'pending'
  AND kind IN ('intake','risk_reclassification');


-- name: list_open_promote_champion_approvals
SELECT *
FROM governance.approval_request
WHERE intake_id = %(intake_id)s
  AND status = 'pending'
  AND kind = 'promote_champion'
  AND target_entity_type = %(entity_type)s::governance.entity_type
  AND target_entity_id = %(entity_id)s;


-- name: list_decided_promote_champion_approvals
-- Returns the most-recent decided promote_champion approval for a
-- specific (entity_type, entity_id) under an intake.
SELECT *
FROM governance.approval_request
WHERE intake_id = %(intake_id)s
  AND kind = 'promote_champion'
  AND target_entity_type = %(entity_type)s::governance.entity_type
  AND target_entity_id = %(entity_id)s
ORDER BY decided_at DESC NULLS LAST, opened_at DESC;


-- name: update_approval_request_required_roles
-- Updates only required_roles. Used by triage_intake when the risk tier
-- changes which approver roles are needed.
UPDATE governance.approval_request SET
    required_roles = %(required_roles)s::jsonb
WHERE id = %(id)s
RETURNING id;


-- name: update_approval_request_status
-- Explicit ::varchar casts so Postgres doesn't try to deduce two
-- different types for the same %(status)s placeholder (one in
-- assignment, one in a CASE WHEN comparison against text literals).
UPDATE governance.approval_request SET
    status = %(status)s::varchar,
    decided_at = CASE WHEN %(status)s::varchar IN ('approved','rejected','withdrawn')
                      THEN now() ELSE decided_at END
WHERE id = %(id)s
RETURNING *;


-- name: insert_approval_signoff
INSERT INTO governance.approval_signoff (
    approval_request_id, role, approver_name, approver_email,
    decision, comment, evidence_url
) VALUES (
    %(approval_request_id)s,
    %(role)s::governance.approval_role,
    %(approver_name)s, %(approver_email)s,
    %(decision)s::governance.approval_decision,
    %(comment)s, %(evidence_url)s
)
ON CONFLICT (approval_request_id, role, approver_email) DO UPDATE SET
    decision = EXCLUDED.decision,
    comment = EXCLUDED.comment,
    evidence_url = EXCLUDED.evidence_url,
    signed_at = now()
RETURNING *;


-- name: list_signoffs_for_request
SELECT *
FROM governance.approval_signoff
WHERE approval_request_id = %(approval_request_id)s
ORDER BY signed_at;


-- ── DASHBOARD ROLLUPS ────────────────────────────────────────

-- name: dashboard_intake_counts_by_status
SELECT status::text AS status, COUNT(*) AS n
FROM governance.intake
GROUP BY status;


-- name: dashboard_intake_counts_by_tier
SELECT ai_risk_tier::text AS ai_risk_tier, COUNT(*) AS n
FROM governance.intake
GROUP BY ai_risk_tier;


-- name: dashboard_pending_approvals
-- Approval requests still pending, with their parent intake info.
SELECT
    a.id, a.kind, a.opened_at, a.required_roles, a.summary,
    i.code AS intake_code, i.title AS intake_title, i.ai_risk_tier
FROM governance.approval_request a
JOIN governance.intake i ON i.id = a.intake_id
WHERE a.status = 'pending'
ORDER BY a.opened_at DESC;


-- name: dashboard_unlinked_entity_counts
-- Counts agent / task / prompt / tool entities that have NO
-- intake_entity_link row pointing at them. Surfaces "AI not yet
-- traced to a business intake" in the governance dashboard.
WITH linked AS (
    SELECT entity_type, entity_id
    FROM governance.intake_entity_link
)
SELECT 'agent'::text AS entity_type, COUNT(*) AS n
FROM governance.agent a
WHERE NOT EXISTS (SELECT 1 FROM linked WHERE entity_type='agent' AND entity_id=a.id)
UNION ALL
SELECT 'task'::text, COUNT(*)
FROM governance.task t
WHERE NOT EXISTS (SELECT 1 FROM linked WHERE entity_type='task' AND entity_id=t.id)
UNION ALL
SELECT 'prompt'::text, COUNT(*)
FROM governance.prompt p
WHERE NOT EXISTS (SELECT 1 FROM linked WHERE entity_type='prompt' AND entity_id=p.id)
UNION ALL
SELECT 'tool'::text, COUNT(*)
FROM governance.tool tl
WHERE NOT EXISTS (SELECT 1 FROM linked WHERE entity_type='tool' AND entity_id=tl.id);
