-- ============================================================
-- LIFECYCLE QUERIES
-- Promote, rollback, deprecate, approval records
-- ============================================================

-- name: get_agent_version
SELECT av.*, ic.name AS inference_config_name
FROM agent_version av
JOIN inference_config ic ON ic.id = av.inference_config_id
WHERE av.id = %(version_id)s;


-- name: get_task_version
SELECT tv.*, ic.name AS inference_config_name
FROM task_version tv
JOIN inference_config ic ON ic.id = tv.inference_config_id
WHERE tv.id = %(version_id)s;


-- name: get_prompt_version
SELECT pv.*, p.name AS prompt_name
FROM prompt_version pv
JOIN prompt p ON p.id = pv.prompt_id
WHERE pv.id = %(version_id)s;


-- name: update_agent_version_state
-- On champion promotion: valid_from=NOW(), valid_to=9999-12-31 (sentinel for "currently active").
-- Pre-champion states: valid_from and valid_to stay NULL (not date-resolvable).
UPDATE agent_version
SET lifecycle_state = %(new_state)s::lifecycle_state,
    channel = %(channel)s::deployment_channel,
    valid_from = CASE WHEN %(new_state)s = 'champion' THEN NOW() ELSE valid_from END,
    valid_to = CASE WHEN %(new_state)s = 'champion' THEN '2999-12-31 23:59:59'::timestamp ELSE valid_to END,
    updated_at = NOW()
WHERE id = %(version_id)s::uuid
RETURNING id, lifecycle_state, valid_from, valid_to;


-- name: update_task_version_state
UPDATE task_version
SET lifecycle_state = %(new_state)s::lifecycle_state,
    channel = %(channel)s::deployment_channel,
    valid_from = CASE WHEN %(new_state)s = 'champion' THEN NOW() ELSE valid_from END,
    valid_to = CASE WHEN %(new_state)s = 'champion' THEN '2999-12-31 23:59:59'::timestamp ELSE valid_to END,
    updated_at = NOW()
WHERE id = %(version_id)s::uuid
RETURNING id, lifecycle_state, valid_from, valid_to;


-- name: update_prompt_version_state
UPDATE prompt_version
SET lifecycle_state = %(new_state)s::lifecycle_state,
    valid_from = CASE WHEN %(new_state)s = 'champion' THEN NOW() ELSE valid_from END,
    valid_to = CASE WHEN %(new_state)s = 'champion' THEN '2999-12-31 23:59:59'::timestamp ELSE valid_to END
WHERE id = %(version_id)s::uuid
RETURNING id, lifecycle_state, valid_from, valid_to;


-- name: deprecate_agent_version
-- Deprecation: overwrites the sentinel valid_to with NOW().
UPDATE agent_version
SET lifecycle_state = 'deprecated',
    valid_to = NOW(),
    updated_at = NOW()
WHERE id = %(version_id)s::uuid
RETURNING id;


-- name: deprecate_task_version
UPDATE task_version
SET lifecycle_state = 'deprecated',
    valid_to = NOW(),
    updated_at = NOW()
WHERE id = %(version_id)s::uuid
RETURNING id;


-- name: set_agent_champion
UPDATE agent
SET current_champion_version_id = %(version_id)s::uuid,
    updated_at = NOW()
WHERE id = %(agent_id)s::uuid
RETURNING id;


-- name: set_task_champion
UPDATE task
SET current_champion_version_id = %(version_id)s::uuid,
    updated_at = NOW()
WHERE id = %(task_id)s::uuid
RETURNING id;


-- name: deprecate_prompt_version
UPDATE prompt_version
SET lifecycle_state = 'deprecated',
    valid_to = NOW()
WHERE id = %(version_id)s::uuid
RETURNING id;


-- name: create_approval_record
INSERT INTO approval_record (
    entity_type, entity_version_id, gate_type,
    from_state, to_state,
    approver_name, approver_role, rationale,
    staging_results_reviewed, ground_truth_reviewed,
    fairness_analysis_reviewed, shadow_metrics_reviewed,
    challenger_metrics_reviewed, model_card_reviewed,
    similarity_flags_reviewed
)
VALUES (
    %(entity_type)s::entity_type, %(entity_version_id)s::uuid, %(gate_type)s,
    %(from_state)s::lifecycle_state, %(to_state)s::lifecycle_state,
    %(approver_name)s, %(approver_role)s, %(rationale)s,
    %(staging_results_reviewed)s, %(ground_truth_reviewed)s,
    %(fairness_analysis_reviewed)s, %(shadow_metrics_reviewed)s,
    %(challenger_metrics_reviewed)s, %(model_card_reviewed)s,
    %(similarity_flags_reviewed)s
)
RETURNING id, approved_at;


-- name: list_approvals_for_entity
SELECT * FROM approval_record
WHERE entity_type = %(entity_type)s::entity_type
  AND entity_version_id = %(entity_version_id)s::uuid
ORDER BY approved_at DESC;


-- name: get_current_champion_agent_version
SELECT av.id
FROM agent a
JOIN agent_version av ON av.id = a.current_champion_version_id
WHERE a.id = %(agent_id)s::uuid;


-- name: get_current_champion_task_version
SELECT tv.id
FROM task t
JOIN task_version tv ON tv.id = t.current_champion_version_id
WHERE t.id = %(task_id)s::uuid;
