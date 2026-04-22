"""Verity Test Runner — execute test suites against entity versions.

Uses the SAME execution path as production. MockContext controls what's
mocked. Every test execution is logged in test_execution_log with the
entity version, inputs, outputs, and metric results.

Usage:
    runner = TestRunner(registry, execution_engine, testing, metrics_engine)
    result = await runner.run_suite(
        entity_type="task",
        entity_version_id=version_id,
        suite_id=suite_id,
    )
    print(result.passed, result.pass_rate, result.case_results)
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

from verity.core.execution import ExecutionEngine
from verity.core.metrics import classification_metrics, field_accuracy, exact_match, schema_valid
from verity.core.mock_context import MockContext
from verity.core.registry import Registry
from verity.core.testing import Testing

logger = logging.getLogger(__name__)


@dataclass
class CaseResult:
    """Result of a single test case execution."""
    test_case_id: UUID
    test_case_name: str
    passed: bool
    actual_output: dict
    expected_output: dict
    metric_type: str
    metric_result: dict
    duration_ms: int
    failure_reason: Optional[str] = None
    decision_log_id: Optional[UUID] = None


@dataclass
class SuiteResult:
    """Result of running an entire test suite."""
    suite_id: UUID
    suite_name: str
    entity_type: str
    entity_version_id: UUID
    case_results: list[CaseResult] = field(default_factory=list)
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    pass_rate: float = 0.0
    duration_ms: int = 0
    passed: bool = False


class TestRunner:
    """Execute test suites against entity versions with full governance."""

    def __init__(
        self,
        registry: Registry,
        execution_engine: ExecutionEngine,
        testing: Testing,
    ):
        self.registry = registry
        self.engine = execution_engine
        self.testing = testing

    async def run_suite(
        self,
        entity_type: str,
        entity_version_id: UUID,
        suite_id: UUID,
        mock_llm: bool = True,
        channel: str = "staging",
    ) -> SuiteResult:
        """Run all test cases in a suite against an entity version.

        Args:
            entity_type: "agent" or "task"
            entity_version_id: Which version to test
            suite_id: Which test suite to run
            mock_llm: If True, use MockContext for LLM calls (free, instant).
                      If False, call Claude for real (costs money, slow).
            channel: Deployment channel for logging purposes.

        Returns:
            SuiteResult with per-case results and aggregate pass rate.
        """
        start_ms = _now_ms()

        # Load suite metadata and test cases
        cases = await self.testing.list_test_cases(suite_id)
        suite_rows = await self.testing.db.fetch_all("get_test_suite", {"suite_id": str(suite_id)})
        suite_name = suite_rows[0]["name"] if suite_rows else "unknown"

        logger.info("Test suite starting: %s (%d cases, entity=%s, mock_llm=%s)",
                     suite_name, len(cases), entity_type, mock_llm)

        case_results = []
        for case in cases:
            result = await self._run_case(
                entity_type=entity_type,
                entity_version_id=entity_version_id,
                suite_id=suite_id,
                case=case,
                mock_llm=mock_llm,
                channel=channel,
            )
            case_results.append(result)

        # Aggregate
        passed_count = sum(1 for r in case_results if r.passed)
        total = len(case_results)
        pass_rate = passed_count / total if total > 0 else 0.0
        duration_ms = _now_ms() - start_ms

        logger.info("Test suite complete: %s (%d/%d passed, %.0f%%, %dms)",
                     suite_name, passed_count, total, pass_rate * 100, duration_ms)

        return SuiteResult(
            suite_id=suite_id,
            suite_name=suite_name,
            entity_type=entity_type,
            entity_version_id=entity_version_id,
            case_results=case_results,
            total_cases=total,
            passed_cases=passed_count,
            failed_cases=total - passed_count,
            pass_rate=round(pass_rate, 4),
            duration_ms=duration_ms,
            passed=passed_count == total,
        )

    async def _run_case(
        self,
        entity_type: str,
        entity_version_id: UUID,
        suite_id: UUID,
        case: dict,
        mock_llm: bool,
        channel: str,
    ) -> CaseResult:
        """Run a single test case.

        Mock behavior:
        - Tool mocks are ALWAYS loaded from test_case_mock table (if they exist).
          This provides controlled tool data so Claude reasons against known inputs.
        - mock_llm=True additionally mocks the LLM response using expected_output.
          This is ONLY for testing the runner itself, NOT for real testing.
          Real testing = mock_llm=False + tool mocks from DB.
        """
        case_start = _now_ms()
        case_id = case["id"]
        case_name = case.get("name", "unnamed")
        input_data = case["input_data"] if isinstance(case["input_data"], dict) else json.loads(case["input_data"])
        expected = case["expected_output"] if isinstance(case["expected_output"], dict) else json.loads(case["expected_output"])
        metric_type = case.get("metric_type", "exact_match")

        # Load tool mocks from test_case_mock table
        tool_mock_rows = await self.testing.db.fetch_all(
            "list_test_case_mocks", {"test_case_id": str(case_id)}
        )

        # Build MockContext from tool mocks
        mock = None
        tool_responses = {}
        for row in tool_mock_rows:
            name = row["tool_name"]
            response = row["mock_response"] if isinstance(row["mock_response"], dict) else json.loads(row["mock_response"])
            if name in tool_responses:
                # Multiple calls to same tool - convert to list
                existing = tool_responses[name]
                if isinstance(existing, list):
                    existing.append(response)
                else:
                    tool_responses[name] = [existing, response]
            else:
                tool_responses[name] = response

        if mock_llm:
            # Mock BOTH LLM and tools - for testing the runner only
            mock = MockContext(llm_responses=[expected], tool_responses=tool_responses or None, mock_all_tools=True)
        elif tool_responses:
            # Mock tools only - Claude called for real. This is the normal test mode.
            mock = MockContext(tool_responses=tool_responses)
        # else: no mocks at all - fully live execution

        # Execute the entity
        try:
            if entity_type == "agent":
                exec_result = await self.engine.run_agent(
                    agent_name=case.get("entity_name", ""),
                    context=input_data,
                    channel=channel,
                    mock=mock,
                    step_name=f"test:{case_name}",
                )
            else:
                exec_result = await self.engine.run_task(
                    task_name=case.get("entity_name", ""),
                    input_data=input_data,
                    channel=channel,
                    mock=mock,
                    step_name=f"test:{case_name}",
                )
            actual_output = exec_result.output or {}
            decision_log_id = exec_result.decision_log_id
        except Exception as e:
            logger.error("Test case failed with exception: %s", case_name, exc_info=True)
            duration_ms = _now_ms() - case_start
            result = CaseResult(
                test_case_id=case_id,
                test_case_name=case_name,
                passed=False,
                actual_output={},
                expected_output=expected,
                metric_type=metric_type,
                metric_result={"error": str(e)},
                duration_ms=duration_ms,
                failure_reason=str(e),
            )
            await self._log_result(suite_id, entity_type, entity_version_id, result, input_data, channel)
            return result

        # Compute metrics
        metric_result = self._compute_metrics(metric_type, actual_output, expected)
        passed = metric_result.get("passed", metric_result.get("matched", False))
        failure_reason = None if passed else self._summarize_failure(metric_result)

        duration_ms = _now_ms() - case_start
        result = CaseResult(
            test_case_id=case_id,
            test_case_name=case_name,
            passed=passed,
            actual_output=actual_output,
            expected_output=expected,
            metric_type=metric_type,
            metric_result=metric_result,
            duration_ms=duration_ms,
            failure_reason=failure_reason,
            decision_log_id=decision_log_id,
        )

        # Log to test_execution_log
        await self._log_result(suite_id, entity_type, entity_version_id, result, input_data, channel)
        return result

    def _compute_metrics(self, metric_type: str, actual: dict, expected: dict) -> dict:
        """Compute metrics based on the metric type."""
        if metric_type == "classification_f1":
            # Extract the classification label from both
            actual_label = actual.get("document_type") or actual.get("risk_score") or actual.get("determination", "")
            expected_label = expected.get("document_type") or expected.get("risk_score") or expected.get("determination", "")
            result = classification_metrics([actual_label], [expected_label])
            result["passed"] = result["f1"] >= 0.5  # single sample: either matches or not
            return result

        elif metric_type == "field_accuracy":
            actual_fields = actual.get("fields", actual)
            expected_fields = expected.get("fields", expected)
            result = field_accuracy(actual_fields, expected_fields)
            result["passed"] = result["overall_accuracy"] >= 0.5
            return result

        elif metric_type == "schema_valid":
            result = schema_valid(actual, expected)
            result["passed"] = result["valid"]
            return result

        else:
            # Default: exact match
            result = exact_match(actual, expected)
            result["passed"] = result["matched"]
            return result

    def _summarize_failure(self, metric_result: dict) -> str:
        """Create a brief failure reason from metric results."""
        if "differences" in metric_result:
            diffs = metric_result["differences"]
            if diffs:
                return "; ".join(diffs[:3])
        if "errors" in metric_result:
            return "; ".join(metric_result["errors"][:3])
        return "Metric check failed"

    async def _log_result(
        self, suite_id, entity_type, entity_version_id, result: CaseResult,
        input_data: dict, channel: str,
    ):
        """Write test execution to test_execution_log."""
        try:
            await self.testing.log_test_result(
                suite_id=str(suite_id),
                entity_type=entity_type,
                entity_version_id=str(entity_version_id),
                test_case_id=str(result.test_case_id),
                mock_mode=True,
                channel=channel,
                input_used=input_data,
                actual_output=result.actual_output,
                expected_output=result.expected_output,
                metric_type=result.metric_type,
                metric_result=result.metric_result,
                passed=result.passed,
                failure_reason=result.failure_reason,
                duration_ms=result.duration_ms,
                inference_config_snapshot={"test_runner": True},
            )
        except Exception:
            logger.warning("Failed to log test result for %s", result.test_case_name, exc_info=True)


def _now_ms() -> int:
    return int(time.time() * 1000)
