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
