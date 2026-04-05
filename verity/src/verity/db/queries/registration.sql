-- ============================================================
-- REGISTRATION QUERIES
-- INSERT operations for registering new entities in Verity
-- ============================================================

-- name: insert_inference_config
INSERT INTO inference_config (
    name, display_name, description, intended_use, model_name,
    temperature, max_tokens, top_p, top_k, stop_sequences, extended_params
)
VALUES (
    %(name)s, %(display_name)s, %(description)s, %(intended_use)s, %(model_name)s,
    %(temperature)s, %(max_tokens)s, %(top_p)s, %(top_k)s, %(stop_sequences)s,
    %(extended_params)s
)
RETURNING id, created_at;


-- name: insert_agent
INSERT INTO agent (
    name, display_name, description, purpose, domain, materiality_tier,
    owner_name, owner_email, business_context, known_limitations, regulatory_notes
)
VALUES (
    %(name)s, %(display_name)s, %(description)s, %(purpose)s, %(domain)s, %(materiality_tier)s,
    %(owner_name)s, %(owner_email)s, %(business_context)s, %(known_limitations)s, %(regulatory_notes)s
)
RETURNING id, created_at;


-- name: insert_agent_version
INSERT INTO agent_version (
    agent_id, major_version, minor_version, patch_version,
    lifecycle_state, channel, inference_config_id,
    output_schema, authority_thresholds, mock_mode_enabled,
    developer_name, change_summary, change_type
)
VALUES (
    %(agent_id)s, %(major_version)s, %(minor_version)s, %(patch_version)s,
    %(lifecycle_state)s, %(channel)s, %(inference_config_id)s,
    %(output_schema)s, %(authority_thresholds)s, %(mock_mode_enabled)s,
    %(developer_name)s, %(change_summary)s, %(change_type)s
)
RETURNING id, version_label, created_at;


-- name: insert_task
INSERT INTO task (
    name, display_name, description, capability_type, purpose, domain, materiality_tier,
    input_schema, output_schema, owner_name, owner_email,
    business_context, known_limitations, regulatory_notes
)
VALUES (
    %(name)s, %(display_name)s, %(description)s, %(capability_type)s, %(purpose)s, %(domain)s, %(materiality_tier)s,
    %(input_schema)s, %(output_schema)s, %(owner_name)s, %(owner_email)s,
    %(business_context)s, %(known_limitations)s, %(regulatory_notes)s
)
RETURNING id, created_at;


-- name: insert_task_version
INSERT INTO task_version (
    task_id, major_version, minor_version, patch_version,
    lifecycle_state, channel, inference_config_id,
    output_schema, mock_mode_enabled,
    developer_name, change_summary, change_type
)
VALUES (
    %(task_id)s, %(major_version)s, %(minor_version)s, %(patch_version)s,
    %(lifecycle_state)s, %(channel)s, %(inference_config_id)s,
    %(output_schema)s, %(mock_mode_enabled)s,
    %(developer_name)s, %(change_summary)s, %(change_type)s
)
RETURNING id, version_label, created_at;


-- name: insert_prompt
INSERT INTO prompt (name, display_name, description, primary_entity_type, primary_entity_id)
VALUES (%(name)s, %(display_name)s, %(description)s, %(primary_entity_type)s, %(primary_entity_id)s)
RETURNING id, created_at;


-- name: insert_prompt_version
INSERT INTO prompt_version (
    prompt_id, version_number, content, api_role, governance_tier,
    lifecycle_state, change_summary, sensitivity_level, author_name
)
VALUES (
    %(prompt_id)s, %(version_number)s, %(content)s, %(api_role)s, %(governance_tier)s,
    %(lifecycle_state)s, %(change_summary)s, %(sensitivity_level)s, %(author_name)s
)
RETURNING id, created_at;


-- name: insert_entity_prompt_assignment
INSERT INTO entity_prompt_assignment (
    entity_type, entity_version_id, prompt_version_id,
    api_role, governance_tier, execution_order, is_required, condition_logic
)
VALUES (
    %(entity_type)s, %(entity_version_id)s, %(prompt_version_id)s,
    %(api_role)s, %(governance_tier)s, %(execution_order)s, %(is_required)s, %(condition_logic)s
)
RETURNING id;


-- name: insert_tool
INSERT INTO tool (
    name, display_name, description, input_schema, output_schema,
    implementation_path, mock_mode_enabled, mock_response_key,
    data_classification_max, is_write_operation, requires_confirmation, tags
)
VALUES (
    %(name)s, %(display_name)s, %(description)s, %(input_schema)s, %(output_schema)s,
    %(implementation_path)s, %(mock_mode_enabled)s, %(mock_response_key)s,
    %(data_classification_max)s, %(is_write_operation)s, %(requires_confirmation)s, %(tags)s
)
RETURNING id, created_at;


-- name: insert_agent_version_tool
INSERT INTO agent_version_tool (agent_version_id, tool_id, authorized, notes)
VALUES (%(agent_version_id)s, %(tool_id)s, %(authorized)s, %(notes)s)
RETURNING id;


-- name: insert_task_version_tool
INSERT INTO task_version_tool (task_version_id, tool_id, authorized, notes)
VALUES (%(task_version_id)s, %(tool_id)s, %(authorized)s, %(notes)s)
RETURNING id;


-- name: insert_pipeline
INSERT INTO pipeline (name, display_name, description)
VALUES (%(name)s, %(display_name)s, %(description)s)
RETURNING id, created_at;


-- name: insert_pipeline_version
INSERT INTO pipeline_version (
    pipeline_id, version_number, lifecycle_state, steps,
    change_summary, developer_name
)
VALUES (
    %(pipeline_id)s, %(version_number)s, %(lifecycle_state)s, %(steps)s,
    %(change_summary)s, %(developer_name)s
)
RETURNING id, created_at;


-- name: insert_test_suite
INSERT INTO test_suite (name, description, entity_type, entity_id, suite_type, created_by)
VALUES (%(name)s, %(description)s, %(entity_type)s, %(entity_id)s, %(suite_type)s, %(created_by)s)
RETURNING id, created_at;


-- name: insert_test_case
INSERT INTO test_case (
    suite_id, name, description, input_data, expected_output,
    metric_type, metric_config, is_adversarial, tags
)
VALUES (
    %(suite_id)s, %(name)s, %(description)s, %(input_data)s, %(expected_output)s,
    %(metric_type)s, %(metric_config)s, %(is_adversarial)s, %(tags)s
)
RETURNING id, created_at;


-- name: insert_ground_truth_dataset
INSERT INTO ground_truth_dataset (
    entity_type, entity_id, name, version, description, lob,
    record_count, minio_bucket, minio_key, labeled_by_sme, reviewed_by
)
VALUES (
    %(entity_type)s, %(entity_id)s, %(name)s, %(version)s, %(description)s, %(lob)s,
    %(record_count)s, %(minio_bucket)s, %(minio_key)s, %(labeled_by_sme)s, %(reviewed_by)s
)
RETURNING id, created_at;


-- name: insert_validation_run
INSERT INTO validation_run (
    entity_type, entity_version_id, dataset_id, run_by,
    precision_score, recall_score, f1_score, cohens_kappa, confusion_matrix,
    field_accuracy, overall_extraction_rate, low_confidence_rate,
    fairness_metrics, fairness_passed, fairness_notes,
    thresholds_met, threshold_details, inference_config_snapshot,
    passed, notes
)
VALUES (
    %(entity_type)s, %(entity_version_id)s, %(dataset_id)s, %(run_by)s,
    %(precision_score)s, %(recall_score)s, %(f1_score)s, %(cohens_kappa)s, %(confusion_matrix)s,
    %(field_accuracy)s, %(overall_extraction_rate)s, %(low_confidence_rate)s,
    %(fairness_metrics)s, %(fairness_passed)s, %(fairness_notes)s,
    %(thresholds_met)s, %(threshold_details)s, %(inference_config_snapshot)s,
    %(passed)s, %(notes)s
)
RETURNING id, run_at;


-- name: insert_model_card
INSERT INTO model_card (
    entity_type, entity_version_id, card_version,
    purpose, design_rationale, inputs_description, outputs_description,
    known_limitations, conditions_of_use,
    lm_specific_limitations, prompt_sensitivity_notes,
    validated_by, validation_run_id, validation_notes,
    regulatory_notes, materiality_classification,
    approved_by, approved_at, lifecycle_state
)
VALUES (
    %(entity_type)s, %(entity_version_id)s, %(card_version)s,
    %(purpose)s, %(design_rationale)s, %(inputs_description)s, %(outputs_description)s,
    %(known_limitations)s, %(conditions_of_use)s,
    %(lm_specific_limitations)s, %(prompt_sensitivity_notes)s,
    %(validated_by)s, %(validation_run_id)s, %(validation_notes)s,
    %(regulatory_notes)s, %(materiality_classification)s,
    %(approved_by)s, %(approved_at)s, %(lifecycle_state)s
)
RETURNING id, created_at;


-- name: insert_metric_threshold
INSERT INTO metric_threshold (
    entity_type, entity_id, materiality_tier, metric_name,
    minimum_acceptable, target_champion
)
VALUES (
    %(entity_type)s, %(entity_id)s, %(materiality_tier)s, %(metric_name)s,
    %(minimum_acceptable)s, %(target_champion)s
)
RETURNING id, created_at;


-- name: insert_application
INSERT INTO application (name, display_name, description)
VALUES (%(name)s, %(display_name)s, %(description)s)
RETURNING id, created_at;


-- name: insert_application_entity
INSERT INTO application_entity (application_id, entity_type, entity_id)
VALUES (%(application_id)s::uuid, %(entity_type)s::entity_type, %(entity_id)s::uuid)
ON CONFLICT (application_id, entity_type, entity_id) DO NOTHING
RETURNING id;


-- name: insert_execution_context
INSERT INTO execution_context (application_id, context_ref, context_type, metadata)
VALUES (%(application_id)s::uuid, %(context_ref)s, %(context_type)s, %(metadata)s)
ON CONFLICT (application_id, context_ref) DO UPDATE
    SET metadata = EXCLUDED.metadata
RETURNING id, created_at;
