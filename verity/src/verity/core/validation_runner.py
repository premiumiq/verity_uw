"""Verity Validation Runner — validate entity versions against ground truth datasets.

Runs an entity version against every record in a ground truth dataset,
compares outputs to authoritative annotations, computes aggregate metrics,
checks against metric thresholds, and stores results.

Usage:
    runner = ValidationRunner(registry, execution_engine, testing, db)
    result = await runner.run_validation(
        entity_type="task",
        entity_version_id=version_id,
        dataset_id=dataset_id,
        run_by="Maria Santos, Senior UW",
    )
    print(result.passed, result.f1, result.per_record_results)
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

from verity.core.execution import ExecutionEngine
from verity.core.metrics import (
    check_thresholds,
    classification_metrics,
    field_accuracy,
)
from verity.core.mock_context import MockContext
from verity.core.registry import Registry
from verity.core.testing import Testing
from verity.db.connection import Database

logger = logging.getLogger(__name__)


@dataclass
class RecordResult:
    """Result of validating a single ground truth record."""
    record_id: UUID
    record_index: int
    expected_output: dict
    actual_output: dict
    correct: bool
    match_score: Optional[float] = None
    confidence: Optional[float] = None
    field_results: Optional[dict] = None
    decision_log_id: Optional[UUID] = None
    duration_ms: int = 0


@dataclass
class ValidationResult:
    """Result of a full validation run."""
    validation_run_id: Optional[UUID] = None
    entity_type: str = ""
    entity_version_id: Optional[UUID] = None
    dataset_id: Optional[UUID] = None
    dataset_name: str = ""
    total_records: int = 0
    correct_records: int = 0
    # Aggregate metrics
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    cohens_kappa: Optional[float] = None
    overall_accuracy: Optional[float] = None
    confusion_matrix: Optional[dict] = None
    field_accuracy_detail: Optional[dict] = None
    # Threshold check
    thresholds_met: bool = False
    threshold_details: list = field(default_factory=list)
    # Per-record detail
    per_record_results: list[RecordResult] = field(default_factory=list)
    # Overall
    passed: bool = False
    duration_ms: int = 0
    notes: str = ""


class ValidationRunner:
    """Validate entity versions against ground truth datasets."""

    def __init__(
        self,
        registry: Registry,
        execution_engine: ExecutionEngine,
        testing: Testing,
        db: Database,
    ):
        self.registry = registry
        self.engine = execution_engine
        self.testing = testing
        self.db = db

    async def run_validation(
        self,
        entity_type: str,
        entity_version_id: UUID,
        dataset_id: UUID,
        run_by: str,
        mock_llm: bool = False,
        channel: str = "staging",
    ) -> ValidationResult:
        """Run a full validation against a ground truth dataset.

        Steps:
        1. Load authoritative annotations from ground_truth_record + annotation
        2. For each record: load tool mocks from ground_truth_record_mock, run entity
        3. Compare outputs to expected (classification or extraction metrics)
        4. Compute aggregate metrics
        5. Check against metric thresholds
        6. Store validation_run and per-record results

        Args:
            entity_type: "agent" or "task"
            entity_version_id: Which version to validate
            dataset_id: Ground truth dataset to validate against
            run_by: Who triggered the validation
            mock_llm: If True, mock LLM responses (for testing the runner itself)
            channel: Deployment channel for logging

        Returns:
            ValidationResult with aggregate metrics and per-record detail.
        """
        start_ms = _now_ms()

        # Load dataset metadata
        dataset = await self.db.fetch_one("get_ground_truth_dataset", {"dataset_id": str(dataset_id)})
        if not dataset:
            raise ValueError(f"Ground truth dataset {dataset_id} not found")

        dataset_name = dataset["name"]
        entity_id = dataset["entity_id"]

        logger.info("Validation run starting: %s (entity=%s, dataset=%s, records=%d)",
                     entity_type, entity_version_id, dataset_name, dataset.get("record_count", 0))

        # Create the validation_run record IMMEDIATELY with status='running'.
        # This makes the run visible in the UI as soon as it starts.
        run_id = await self._create_run(
            entity_type=entity_type,
            entity_version_id=entity_version_id,
            dataset_id=dataset_id,
            dataset_version=dataset.get("version", "1.0"),
            run_by=run_by,
        )
        logger.info("Validation run created: %s (status=running)", run_id)

        try:
            return await self._execute_validation(
                run_id, entity_type, entity_version_id, dataset_id, dataset,
                run_by, mock_llm, channel, start_ms,
            )
        except Exception as e:
            await self._fail_run(run_id, str(e))
            logger.error("Validation run failed: %s", e, exc_info=True)
            raise

    async def _execute_validation(
        self, run_id, entity_type, entity_version_id, dataset_id, dataset,
        run_by, mock_llm, channel, start_ms,
    ) -> "ValidationResult":
        """Internal: execute the validation (called within try/except)."""
        dataset_name = dataset["name"]
        entity_id = dataset["entity_id"]

        # Load authoritative annotations
        records = await self.db.fetch_all("list_authoritative_annotations", {"dataset_id": str(dataset_id)})
        if not records:
            raise ValueError(f"No authoritative annotations found for dataset {dataset_id}")

        # Determine entity name for execution
        entity_name = dataset.get("entity_name", "")

        # Execute entity against each record and collect results
        per_record: list[RecordResult] = []
        all_actual_labels = []
        all_expected_labels = []
        all_actual_fields = []
        all_expected_fields = []

        for record in records:
            record_result = await self._validate_record(
                entity_type=entity_type,
                entity_name=entity_name,
                record=record,
                mock_llm=mock_llm,
                channel=channel,
            )
            per_record.append(record_result)

            # Collect for aggregate metrics
            actual = record_result.actual_output
            expected = record_result.expected_output

            # Classification: extract label field
            for label_key in ("document_type", "risk_score", "determination"):
                if label_key in expected:
                    all_actual_labels.append(actual.get(label_key, ""))
                    all_expected_labels.append(expected.get(label_key, ""))
                    break

            # Extraction: collect field dicts
            if "fields" in expected:
                all_actual_fields.append(actual.get("fields", {}))
                all_expected_fields.append(expected.get("fields", {}))

        # Compute aggregate metrics
        agg_metrics = {}
        if all_actual_labels:
            agg_metrics = classification_metrics(all_actual_labels, all_expected_labels)
        elif all_actual_fields:
            # Aggregate field accuracy across all records
            combined_actual = {}
            combined_expected = {}
            for i, (af, ef) in enumerate(zip(all_actual_fields, all_expected_fields)):
                for k, v in ef.items():
                    combined_expected[f"{i}:{k}"] = v
                for k, v in af.items():
                    combined_actual[f"{i}:{k}"] = v

            # Load field configs if available
            field_configs = await self.db.fetch_all("list_field_extraction_configs", {
                "entity_type": entity_type, "entity_id": str(entity_id),
            })
            agg_metrics = field_accuracy(combined_actual, combined_expected, field_configs or None)

        # Check thresholds
        thresholds = await self.db.fetch_all("list_metric_thresholds", {
            "entity_type": entity_type, "entity_id": str(entity_id),
        })
        threshold_result = check_thresholds(agg_metrics, thresholds) if thresholds else {
            "all_passed": True, "details": [],
        }

        # Determine pass/fail
        correct_count = sum(1 for r in per_record if r.correct)
        passed = threshold_result["all_passed"] if thresholds else (correct_count == len(per_record))

        duration_ms = _now_ms() - start_ms

        # Update the validation run with results (was created as 'running' at start)
        await self._complete_run(
            run_id=run_id,
            agg_metrics=agg_metrics,
            threshold_result=threshold_result,
            passed=passed,
            notes=f"Validated {len(per_record)} records in {duration_ms}ms",
        )

        # Store per-record results
        for rr in per_record:
            await self._store_record_result(run_id, rr)

        logger.info("Validation run complete: %s (dataset=%s, %d/%d correct, passed=%s, %dms)",
                     entity_type, dataset_name, correct_count, len(per_record), passed, duration_ms)

        return ValidationResult(
            validation_run_id=run_id,
            entity_type=entity_type,
            entity_version_id=entity_version_id,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            total_records=len(per_record),
            correct_records=correct_count,
            precision=agg_metrics.get("precision", 0.0),
            recall=agg_metrics.get("recall", 0.0),
            f1=agg_metrics.get("f1", 0.0),
            cohens_kappa=agg_metrics.get("cohens_kappa"),
            overall_accuracy=agg_metrics.get("overall_accuracy"),
            confusion_matrix=agg_metrics.get("confusion_matrix"),
            field_accuracy_detail=agg_metrics.get("per_field"),
            thresholds_met=threshold_result["all_passed"],
            threshold_details=threshold_result.get("details", []),
            per_record_results=per_record,
            passed=passed,
            duration_ms=duration_ms,
        )

    async def _validate_record(
        self,
        entity_type: str,
        entity_name: str,
        record: dict,
        mock_llm: bool,
        channel: str,
    ) -> RecordResult:
        """Validate a single ground truth record.

        Mock behavior:
        - Tool mocks loaded from ground_truth_record_mock table. These provide
          the controlled scenario data the SME saw when labeling the expected output.
        - mock_llm=True additionally mocks the LLM (for testing the runner only).
          Real validation = mock_llm=False + tool mocks from DB.
        """
        record_start = _now_ms()
        record_id = record["record_id"]
        record_index = record["record_index"]
        input_data = record["input_data"] if isinstance(record["input_data"], dict) else json.loads(record["input_data"])
        expected = record["expected_output"] if isinstance(record["expected_output"], dict) else json.loads(record["expected_output"])

        # Load tool mocks from ground_truth_record_mock table
        tool_mock_rows = await self.db.fetch_all(
            "list_ground_truth_record_mocks", {"record_id": str(record_id)}
        )

        tool_responses = {}
        for row in tool_mock_rows:
            name = row["tool_name"]
            response = row["mock_response"] if isinstance(row["mock_response"], dict) else json.loads(row["mock_response"])
            if name in tool_responses:
                existing = tool_responses[name]
                if isinstance(existing, list):
                    existing.append(response)
                else:
                    tool_responses[name] = [existing, response]
            else:
                tool_responses[name] = response

        # Build MockContext
        mock = None
        if mock_llm:
            # Mock BOTH LLM and tools - for testing the runner only
            mock = MockContext(llm_responses=[expected], tool_responses=tool_responses or None, mock_all_tools=True)
        elif tool_responses:
            # Mock tools only - Claude called for real. This is real validation.
            mock = MockContext(tool_responses=tool_responses)

        # Execute
        try:
            if entity_type == "agent":
                exec_result = await self.engine.run_agent(
                    agent_name=entity_name,
                    context=input_data,
                    channel=channel,
                    mock=mock,
                    step_name=f"validation:record_{record_index}",
                )
            else:
                exec_result = await self.engine.run_task(
                    task_name=entity_name,
                    input_data=input_data,
                    channel=channel,
                    mock=mock,
                    step_name=f"validation:record_{record_index}",
                )
            actual_output = exec_result.output or {}
            decision_log_id = exec_result.decision_log_id
            confidence = exec_result.confidence_score
        except Exception as e:
            logger.error("Validation record %d failed: %s", record_index, e, exc_info=True)
            return RecordResult(
                record_id=record_id,
                record_index=record_index,
                expected_output=expected,
                actual_output={},
                correct=False,
                duration_ms=_now_ms() - record_start,
            )

        # Compare output to expected
        correct, match_score, field_results = self._compare(actual_output, expected)

        return RecordResult(
            record_id=record_id,
            record_index=record_index,
            expected_output=expected,
            actual_output=actual_output,
            correct=correct,
            match_score=match_score,
            confidence=confidence,
            field_results=field_results,
            decision_log_id=decision_log_id,
            duration_ms=_now_ms() - record_start,
        )

    def _compare(self, actual: dict, expected: dict) -> tuple[bool, Optional[float], Optional[dict]]:
        """Compare actual output to expected. Returns (correct, score, field_detail)."""
        # Classification: check label match
        for label_key in ("document_type", "risk_score", "determination"):
            if label_key in expected:
                matched = actual.get(label_key) == expected.get(label_key)
                return matched, 1.0 if matched else 0.0, None

        # Extraction: check field accuracy
        if "fields" in expected:
            result = field_accuracy(
                actual.get("fields", {}),
                expected.get("fields", {}),
            )
            return (
                result["overall_accuracy"] >= 0.8,  # 80% field accuracy = correct
                result["overall_accuracy"],
                result["per_field"],
            )

        # Default: exact match on all keys
        matched = all(actual.get(k) == v for k, v in expected.items())
        return matched, 1.0 if matched else 0.0, None

    async def _create_run(self, entity_type, entity_version_id, dataset_id,
                           dataset_version, run_by) -> UUID:
        """Create a validation_run record with status='running'. Called at start."""
        result = await self.db.execute_returning("insert_validation_run", {
            "entity_type": entity_type,
            "entity_version_id": str(entity_version_id),
            "dataset_id": str(dataset_id),
            "dataset_version": dataset_version,
            "run_by": run_by,
            "precision_score": None,
            "recall_score": None,
            "f1_score": None,
            "cohens_kappa": None,
            "confusion_matrix": None,
            "field_accuracy": None,
            "overall_extraction_rate": None,
            "low_confidence_rate": None,
            "fairness_metrics": None,
            "fairness_passed": None,
            "fairness_notes": None,
            "thresholds_met": None,
            "threshold_details": None,
            "inference_config_snapshot": json.dumps({"validation_runner": True}),
            "status": "running",
            "passed": None,
            "notes": "Validation in progress...",
        })
        return result["id"]

    async def _complete_run(self, run_id, agg_metrics, threshold_result, passed, notes):
        """Update a validation_run to status='complete' with results."""
        await self.db.execute_raw(
            """UPDATE validation_run SET
                status = 'complete',
                precision_score = %(precision)s,
                recall_score = %(recall)s,
                f1_score = %(f1)s,
                cohens_kappa = %(kappa)s,
                confusion_matrix = %(cm)s,
                field_accuracy = %(fa)s,
                overall_extraction_rate = %(oer)s,
                thresholds_met = %(tm)s,
                threshold_details = %(td)s,
                passed = %(passed)s,
                notes = %(notes)s
            WHERE id = %(run_id)s""",
            {
                "run_id": str(run_id),
                "precision": agg_metrics.get("precision"),
                "recall": agg_metrics.get("recall"),
                "f1": agg_metrics.get("f1"),
                "kappa": agg_metrics.get("cohens_kappa"),
                "cm": json.dumps(agg_metrics.get("confusion_matrix")) if agg_metrics.get("confusion_matrix") else None,
                "fa": json.dumps(agg_metrics.get("per_field")) if agg_metrics.get("per_field") else None,
                "oer": agg_metrics.get("overall_accuracy"),
                "tm": threshold_result["all_passed"],
                "td": json.dumps(threshold_result.get("details")),
                "passed": passed,
                "notes": notes,
            },
        )

    async def _fail_run(self, run_id, error_message):
        """Update a validation_run to status='failed'."""
        await self.db.execute_raw(
            "UPDATE validation_run SET status = 'failed', notes = %(notes)s WHERE id = %(run_id)s",
            {"run_id": str(run_id), "notes": f"Failed: {error_message}"},
        )

    async def _store_record_result(self, validation_run_id: UUID, rr: RecordResult):
        """Store a per-record validation result."""
        try:
            await self.db.execute_returning("insert_validation_record_result", {
                "validation_run_id": str(validation_run_id),
                "ground_truth_record_id": str(rr.record_id),
                "record_index": rr.record_index,
                "expected_output": json.dumps(rr.expected_output),
                "actual_output": json.dumps(rr.actual_output),
                "confidence": rr.confidence,
                "correct": rr.correct,
                "match_type": "classification" if not rr.field_results else "field_accuracy",
                "match_score": rr.match_score,
                "field_results": json.dumps(rr.field_results) if rr.field_results else None,
                "decision_log_id": str(rr.decision_log_id) if rr.decision_log_id else None,
                "duration_ms": rr.duration_ms,
            })
        except Exception:
            logger.warning("Failed to store record result for record %d", rr.record_index, exc_info=True)


def _now_ms() -> int:
    return int(time.time() * 1000)
