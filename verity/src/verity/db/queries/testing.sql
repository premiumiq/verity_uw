-- ============================================================
-- TESTING QUERIES
-- Test suites, test cases, execution logs, validation runs
-- ============================================================

-- name: list_test_suites_for_entity
SELECT ts.*
FROM test_suite ts
WHERE ts.entity_type = %(entity_type)s
  AND ts.entity_id = %(entity_id)s
  AND ts.active = TRUE
ORDER BY ts.suite_type, ts.name;


-- name: list_test_cases_for_suite
SELECT tc.*
FROM test_case tc
WHERE tc.suite_id = %(suite_id)s
  AND tc.active = TRUE
ORDER BY tc.name;


-- name: log_test_execution
INSERT INTO test_execution_log (
    suite_id, entity_type, entity_version_id, test_case_id,
    mock_mode, channel, input_used, actual_output, expected_output,
    metric_type, metric_result, passed, failure_reason,
    duration_ms, inference_config_snapshot
)
VALUES (
    %(suite_id)s, %(entity_type)s, %(entity_version_id)s, %(test_case_id)s,
    %(mock_mode)s, %(channel)s, %(input_used)s, %(actual_output)s, %(expected_output)s,
    %(metric_type)s, %(metric_result)s, %(passed)s, %(failure_reason)s,
    %(duration_ms)s, %(inference_config_snapshot)s
)
RETURNING id, run_at;


-- name: list_test_results_for_entity
SELECT
    tel.id,
    tel.suite_id,
    ts.name AS suite_name,
    ts.suite_type,
    tel.test_case_id,
    tc.name AS test_case_name,
    tel.mock_mode,
    tel.metric_type,
    tel.metric_result,
    tel.passed,
    tel.failure_reason,
    tel.duration_ms,
    tel.run_at
FROM test_execution_log tel
JOIN test_suite ts ON ts.id = tel.suite_id
JOIN test_case tc ON tc.id = tel.test_case_id
WHERE tel.entity_type = %(entity_type)s
  AND tel.entity_version_id = %(entity_version_id)s
ORDER BY tel.run_at DESC;


-- name: get_latest_validation_run
SELECT vr.*
FROM validation_run vr
WHERE vr.entity_type = %(entity_type)s
  AND vr.entity_version_id = %(entity_version_id)s
ORDER BY vr.run_at DESC
LIMIT 1;


-- name: list_model_cards_for_entity
SELECT mc.*
FROM model_card mc
WHERE mc.entity_type = %(entity_type)s
  AND mc.entity_version_id = %(entity_version_id)s
ORDER BY mc.card_version DESC;


-- ============================================================
-- ALL TEST SUITES (for UI overview page)
-- ============================================================

-- name: list_all_test_suites
SELECT
    ts.id, ts.name, ts.description, ts.entity_type, ts.entity_id,
    ts.suite_type, ts.created_by, ts.active, ts.created_at,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(a.name, t.name) AS entity_name,
    (SELECT COUNT(*) FROM test_case tc WHERE tc.suite_id = ts.id AND tc.active = TRUE) AS case_count,
    (SELECT COUNT(*) FROM test_execution_log tel WHERE tel.suite_id = ts.id AND tel.passed = TRUE) AS pass_count,
    (SELECT COUNT(*) FROM test_execution_log tel WHERE tel.suite_id = ts.id) AS total_runs,
    (SELECT MAX(tel.run_at) FROM test_execution_log tel WHERE tel.suite_id = ts.id) AS last_run_at
FROM test_suite ts
LEFT JOIN agent a ON a.id = ts.entity_id AND ts.entity_type = 'agent'
LEFT JOIN task t ON t.id = ts.entity_id AND ts.entity_type = 'task'
WHERE ts.active = TRUE
ORDER BY ts.entity_type, ts.name;


-- name: get_test_suite
SELECT
    ts.*,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(a.name, t.name) AS entity_name
FROM test_suite ts
LEFT JOIN agent a ON a.id = ts.entity_id AND ts.entity_type = 'agent'
LEFT JOIN task t ON t.id = ts.entity_id AND ts.entity_type = 'task'
WHERE ts.id = %(suite_id)s;


-- name: list_test_results_for_suite
SELECT
    tel.id, tel.test_case_id, tel.mock_mode, tel.channel,
    tel.metric_type, tel.metric_result, tel.passed, tel.failure_reason,
    tel.duration_ms, tel.run_at,
    tc.name AS test_case_name, tc.description AS test_case_description
FROM test_execution_log tel
JOIN test_case tc ON tc.id = tel.test_case_id
WHERE tel.suite_id = %(suite_id)s
ORDER BY tel.run_at DESC;


-- ============================================================
-- GROUND TRUTH DATASETS (for UI and validation runner)
-- ============================================================

-- name: list_all_ground_truth_datasets
SELECT
    gtd.*,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(a.name, t.name) AS entity_name
FROM ground_truth_dataset gtd
LEFT JOIN agent a ON a.id = gtd.entity_id AND gtd.entity_type = 'agent'
LEFT JOIN task t ON t.id = gtd.entity_id AND gtd.entity_type = 'task'
ORDER BY gtd.entity_type, gtd.name;


-- name: get_ground_truth_dataset
SELECT
    gtd.*,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(a.name, t.name) AS entity_name
FROM ground_truth_dataset gtd
LEFT JOIN agent a ON a.id = gtd.entity_id AND gtd.entity_type = 'agent'
LEFT JOIN task t ON t.id = gtd.entity_id AND gtd.entity_type = 'task'
WHERE gtd.id = %(dataset_id)s;


-- name: list_ground_truth_records
SELECT gtr.*
FROM ground_truth_record gtr
WHERE gtr.dataset_id = %(dataset_id)s
ORDER BY gtr.record_index;


-- name: list_authoritative_annotations
SELECT
    gtr.id AS record_id, gtr.record_index, gtr.input_data,
    gtr.source_type, gtr.source_provider, gtr.source_container,
    gtr.source_key, gtr.source_description,
    gtr.tags, gtr.difficulty, gtr.record_notes,
    gta.expected_output, gta.annotator_type,
    gta.labeled_by, gta.judge_model, gta.label_confidence, gta.label_notes
FROM ground_truth_record gtr
JOIN ground_truth_annotation gta ON gta.record_id = gtr.id AND gta.is_authoritative = TRUE
WHERE gtr.dataset_id = %(dataset_id)s
ORDER BY gtr.record_index;


-- name: get_ground_truth_record
SELECT gtr.*
FROM ground_truth_record gtr
WHERE gtr.id = %(record_id)s;


-- name: list_annotations_for_record
SELECT gta.*
FROM ground_truth_annotation gta
WHERE gta.record_id = %(record_id)s
ORDER BY gta.is_authoritative DESC, gta.labeled_at;


-- ============================================================
-- VALIDATION RUNS AND RESULTS
-- ============================================================

-- name: list_validation_runs
SELECT
    vr.*,
    gtd.name AS dataset_name,
    COALESCE(a.display_name, t.display_name) AS entity_display_name
FROM validation_run vr
JOIN ground_truth_dataset gtd ON gtd.id = vr.dataset_id
LEFT JOIN agent_version av ON av.id = vr.entity_version_id AND vr.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = vr.entity_version_id AND vr.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
ORDER BY vr.run_at DESC;


-- insert_validation_run lives in registration.sql (not duplicated here)


-- name: insert_validation_record_result
INSERT INTO validation_record_result (
    validation_run_id, ground_truth_record_id, record_index,
    expected_output, actual_output, confidence,
    correct, match_type, match_score,
    field_results, decision_log_id, duration_ms
)
VALUES (
    %(validation_run_id)s, %(ground_truth_record_id)s, %(record_index)s,
    %(expected_output)s, %(actual_output)s, %(confidence)s,
    %(correct)s, %(match_type)s, %(match_score)s,
    %(field_results)s, %(decision_log_id)s, %(duration_ms)s
)
RETURNING id;


-- name: list_validation_record_results
SELECT vrr.*
FROM validation_record_result vrr
WHERE vrr.validation_run_id = %(validation_run_id)s
ORDER BY vrr.record_index;


-- name: list_validation_record_failures
SELECT vrr.*
FROM validation_record_result vrr
WHERE vrr.validation_run_id = %(validation_run_id)s
  AND vrr.correct = FALSE
ORDER BY vrr.record_index;


-- name: get_validation_run_by_id
SELECT
    vr.*,
    gtd.name AS dataset_name,
    gtd.record_count AS dataset_record_count,
    gtd.quality_tier AS dataset_quality_tier,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(a.name, t.name) AS entity_name,
    COALESCE(av.version_label, tv.version_label) AS version_label
FROM validation_run vr
JOIN ground_truth_dataset gtd ON gtd.id = vr.dataset_id
LEFT JOIN agent_version av ON av.id = vr.entity_version_id AND vr.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = vr.entity_version_id AND vr.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
WHERE vr.id = %(run_id)s;


-- ============================================================
-- METRIC THRESHOLDS AND FIELD CONFIGS
-- ============================================================

-- name: list_metric_thresholds
SELECT mt.*
FROM metric_threshold mt
WHERE mt.entity_type = %(entity_type)s
  AND mt.entity_id = %(entity_id)s
ORDER BY mt.metric_name, mt.field_name;


-- name: list_field_extraction_configs
SELECT fec.*
FROM field_extraction_config fec
WHERE fec.entity_type = %(entity_type)s
  AND fec.entity_id = %(entity_id)s
ORDER BY fec.field_name;


-- ============================================================
-- LIFECYCLE OVERVIEW (union of all version tables)
-- ============================================================

-- name: list_all_entity_versions_with_state
SELECT
    'agent' AS entity_type,
    a.name AS entity_name,
    a.display_name AS entity_display_name,
    a.materiality_tier,
    av.id AS version_id,
    av.version_label,
    av.lifecycle_state,
    av.channel,
    av.decision_log_detail,
    av.valid_from,
    av.valid_to,
    av.developer_name,
    av.change_summary,
    av.staging_tests_passed,
    av.ground_truth_passed,
    av.created_at
FROM agent_version av
JOIN agent a ON a.id = av.agent_id
UNION ALL
SELECT
    'task' AS entity_type,
    t.name AS entity_name,
    t.display_name AS entity_display_name,
    t.materiality_tier,
    tv.id AS version_id,
    tv.version_label,
    tv.lifecycle_state,
    tv.channel,
    tv.decision_log_detail,
    tv.valid_from,
    tv.valid_to,
    tv.developer_name,
    tv.change_summary,
    tv.staging_tests_passed,
    tv.ground_truth_passed,
    tv.created_at
FROM task_version tv
JOIN task t ON t.id = tv.task_id
ORDER BY entity_type, entity_name, created_at DESC;


-- ============================================================
-- TEST CASE MOCKS (per-tool mock data for test cases)
-- ============================================================

-- name: list_test_case_mocks
SELECT tcm.*
FROM test_case_mock tcm
WHERE tcm.test_case_id = %(test_case_id)s
ORDER BY tcm.tool_name, tcm.call_order;


-- name: insert_test_case_mock
INSERT INTO test_case_mock (test_case_id, tool_name, call_order, mock_response, description)
VALUES (%(test_case_id)s, %(tool_name)s, %(call_order)s, %(mock_response)s, %(description)s)
RETURNING id, created_at;


-- name: delete_test_case_mock
DELETE FROM test_case_mock WHERE id = %(mock_id)s RETURNING id;


-- name: delete_all_test_case_mocks
DELETE FROM test_case_mock WHERE test_case_id = %(test_case_id)s;


-- ============================================================
-- GROUND TRUTH RECORD MOCKS (per-tool scenario data for GT records)
-- ============================================================

-- name: list_ground_truth_record_mocks
SELECT gtrm.*
FROM ground_truth_record_mock gtrm
WHERE gtrm.record_id = %(record_id)s
ORDER BY gtrm.tool_name, gtrm.call_order;


-- name: insert_ground_truth_record_mock
INSERT INTO ground_truth_record_mock (record_id, tool_name, call_order, mock_response, description)
VALUES (%(record_id)s, %(tool_name)s, %(call_order)s, %(mock_response)s, %(description)s)
RETURNING id, created_at;


-- name: delete_ground_truth_record_mock
DELETE FROM ground_truth_record_mock WHERE id = %(mock_id)s RETURNING id;


-- name: delete_all_ground_truth_record_mocks
DELETE FROM ground_truth_record_mock WHERE record_id = %(record_id)s;
