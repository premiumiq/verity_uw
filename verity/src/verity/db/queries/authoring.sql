-- ============================================================
-- AUTHORING QUERIES — draft-state edits, deletes, replace-assoc, clone
-- ============================================================
-- Every UPDATE / DELETE / cascade here is guarded by
--     WHERE lifecycle_state = 'draft'
-- (either directly or via an EXISTS subquery). That's how we preserve
-- the immutability contract for audit-load-bearing states (candidate /
-- staging / shadow / challenger / champion / deprecated) while still
-- giving authors a tight in-place edit loop on drafts.


-- ── DRAFT-STATE IN-PLACE UPDATES ─────────────────────────────
-- COALESCE pattern lets the SDK pass None for fields the caller
-- didn't supply — the existing value is preserved. Non-draft rows
-- never match the WHERE, so UPDATE returns zero rows and the SDK
-- surfaces a 409.

-- name: update_agent_version_draft
UPDATE agent_version SET
    inference_config_id  = COALESCE(%(inference_config_id)s::uuid,  inference_config_id),
    output_schema        = COALESCE(%(output_schema)s::jsonb,       output_schema),
    authority_thresholds = COALESCE(%(authority_thresholds)s::jsonb, authority_thresholds),
    mock_mode_enabled    = COALESCE(%(mock_mode_enabled)s::boolean, mock_mode_enabled),
    decision_log_detail  = COALESCE(%(decision_log_detail)s,        decision_log_detail),
    developer_name       = COALESCE(%(developer_name)s,             developer_name),
    change_summary       = COALESCE(%(change_summary)s,             change_summary),
    change_type          = COALESCE(%(change_type)s,                change_type),
    limitations_this_version = COALESCE(%(limitations_this_version)s, limitations_this_version),
    updated_at           = NOW()
WHERE id = %(version_id)s::uuid AND lifecycle_state = 'draft'
RETURNING id, version_label, lifecycle_state, updated_at;


-- name: update_task_version_draft
UPDATE task_version SET
    inference_config_id  = COALESCE(%(inference_config_id)s::uuid,  inference_config_id),
    output_schema        = COALESCE(%(output_schema)s::jsonb,       output_schema),
    mock_mode_enabled    = COALESCE(%(mock_mode_enabled)s::boolean, mock_mode_enabled),
    decision_log_detail  = COALESCE(%(decision_log_detail)s,        decision_log_detail),
    developer_name       = COALESCE(%(developer_name)s,             developer_name),
    change_summary       = COALESCE(%(change_summary)s,             change_summary),
    change_type          = COALESCE(%(change_type)s,                change_type),
    updated_at           = NOW()
WHERE id = %(version_id)s::uuid AND lifecycle_state = 'draft'
RETURNING id, version_label, lifecycle_state, updated_at;


-- name: update_prompt_version_draft
UPDATE prompt_version SET
    content           = COALESCE(%(content)s,           content),
    api_role          = COALESCE(%(api_role)s::api_role, api_role),
    governance_tier   = COALESCE(%(governance_tier)s::governance_tier, governance_tier),
    change_summary    = COALESCE(%(change_summary)s,    change_summary),
    sensitivity_level = COALESCE(%(sensitivity_level)s, sensitivity_level),
    author_name       = COALESCE(%(author_name)s,       author_name)
WHERE id = %(version_id)s::uuid AND lifecycle_state = 'draft'
RETURNING id, version_label, lifecycle_state;


-- name: update_pipeline_version_draft
UPDATE pipeline_version SET
    steps            = COALESCE(%(steps)s::jsonb, steps),
    change_summary   = COALESCE(%(change_summary)s, change_summary),
    developer_name   = COALESCE(%(developer_name)s, developer_name)
WHERE id = %(version_id)s::uuid AND lifecycle_state = 'draft'
RETURNING id, version_number, lifecycle_state;


-- ── DRAFT-STATE DELETES WITH CASCADE ─────────────────────────
-- Single CTE: the guard subquery yields the target id only if the
-- row is in draft; each "delete dependents" CTE removes associated
-- rows whose FKs point at this version; the final DELETE removes
-- the version itself. All in one atomic statement.

-- name: delete_draft_agent_version_cascade
WITH guard AS (
    SELECT id FROM agent_version
    WHERE id = %(version_id)s::uuid AND lifecycle_state = 'draft'
),
d_prompts AS (
    DELETE FROM entity_prompt_assignment
    WHERE entity_type = 'agent' AND entity_version_id IN (SELECT id FROM guard)
),
d_tools AS (
    DELETE FROM agent_version_tool
    WHERE agent_version_id IN (SELECT id FROM guard)
),
d_delegations AS (
    DELETE FROM agent_version_delegation
    WHERE parent_agent_version_id IN (SELECT id FROM guard)
)
DELETE FROM agent_version WHERE id IN (SELECT id FROM guard)
RETURNING id;


-- name: delete_draft_task_version_cascade
WITH guard AS (
    SELECT id FROM task_version
    WHERE id = %(version_id)s::uuid AND lifecycle_state = 'draft'
),
d_prompts AS (
    DELETE FROM entity_prompt_assignment
    WHERE entity_type = 'task' AND entity_version_id IN (SELECT id FROM guard)
),
d_tools AS (
    DELETE FROM task_version_tool
    WHERE task_version_id IN (SELECT id FROM guard)
)
DELETE FROM task_version WHERE id IN (SELECT id FROM guard)
RETURNING id;


-- name: delete_draft_prompt_version
-- No cascade: if this prompt_version is referenced from any
-- entity_prompt_assignment, the FK will reject the DELETE and the
-- caller sees a 400. That is the right behavior — we don't want to
-- silently orphan assignments on promoted agent/task versions.
DELETE FROM prompt_version
WHERE id = %(version_id)s::uuid AND lifecycle_state = 'draft'
RETURNING id;


-- name: delete_draft_pipeline_version
-- Pipeline versions have no association tables (steps are embedded
-- JSONB), so no cascade is needed.
DELETE FROM pipeline_version
WHERE id = %(version_id)s::uuid AND lifecycle_state = 'draft'
RETURNING id;


-- ── DRAFT-STATE GUARDS (used before replace-association writes) ──
-- Returns the version row if it's in draft, NULL otherwise. The SDK
-- uses this inside a transaction before running DELETE + INSERTs.

-- name: check_agent_version_is_draft
SELECT id, lifecycle_state
FROM agent_version
WHERE id = %(version_id)s::uuid AND lifecycle_state = 'draft';

-- name: check_task_version_is_draft
SELECT id, lifecycle_state
FROM task_version
WHERE id = %(version_id)s::uuid AND lifecycle_state = 'draft';


-- ── CLEAR ASSOCIATIONS (inside replace-* SDK flows) ──────────
-- Run only after the caller has already confirmed the version is
-- in draft via check_*_version_is_draft above (inside the same
-- transaction handle).

-- name: delete_agent_prompt_assignments_for_version
DELETE FROM entity_prompt_assignment
WHERE entity_type = 'agent' AND entity_version_id = %(version_id)s::uuid;

-- name: delete_task_prompt_assignments_for_version
DELETE FROM entity_prompt_assignment
WHERE entity_type = 'task' AND entity_version_id = %(version_id)s::uuid;

-- name: delete_agent_tool_authorizations_for_version
DELETE FROM agent_version_tool
WHERE agent_version_id = %(version_id)s::uuid;

-- name: delete_task_tool_authorizations_for_version
DELETE FROM task_version_tool
WHERE task_version_id = %(version_id)s::uuid;

-- name: delete_agent_delegations_for_parent
DELETE FROM agent_version_delegation
WHERE parent_agent_version_id = %(version_id)s::uuid;


-- ── CLONE HELPERS — read the source row with all its columns ──
-- The clone workflow is: read-source-row, INSERT new version with
-- copied column values + new label + cloned_from_version_id, then
-- duplicate the association rows. Reuses insert_* queries for the
-- association INSERTs.

-- name: get_agent_version_row
SELECT * FROM agent_version WHERE id = %(version_id)s::uuid;

-- name: get_task_version_row
SELECT * FROM task_version WHERE id = %(version_id)s::uuid;

-- name: get_prompt_version_row
SELECT * FROM prompt_version WHERE id = %(version_id)s::uuid;

-- name: get_pipeline_version_row
SELECT * FROM pipeline_version WHERE id = %(version_id)s::uuid;

-- name: get_agent_prompt_assignments_raw
SELECT * FROM entity_prompt_assignment
WHERE entity_type = 'agent' AND entity_version_id = %(version_id)s::uuid
ORDER BY execution_order;

-- name: get_task_prompt_assignments_raw
SELECT * FROM entity_prompt_assignment
WHERE entity_type = 'task' AND entity_version_id = %(version_id)s::uuid
ORDER BY execution_order;

-- name: get_agent_tool_authorizations_raw
SELECT * FROM agent_version_tool
WHERE agent_version_id = %(version_id)s::uuid;

-- name: get_task_tool_authorizations_raw
SELECT * FROM task_version_tool
WHERE task_version_id = %(version_id)s::uuid;

-- name: get_agent_delegations_raw
SELECT * FROM agent_version_delegation
WHERE parent_agent_version_id = %(version_id)s::uuid;
