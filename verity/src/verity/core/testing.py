"""Verity Testing — run test suites, log results, validate against ground truth."""

import json
from typing import Optional
from uuid import UUID

from verity.db.connection import Database
from verity.models.lifecycle import EntityType
from verity.models.testing import TestExecutionResult, TestSuite, ValidationRun


class Testing:
    """Run test suites, log results, query validation status."""

    def __init__(self, db: Database):
        self.db = db

    async def list_test_suites(self, entity_type, entity_id: UUID) -> list[TestSuite]:
        """List all test suites for an entity."""
        et = entity_type.value if hasattr(entity_type, 'value') else str(entity_type)
        rows = await self.db.fetch_all("list_test_suites_for_entity", {
            "entity_type": et,
            "entity_id": str(entity_id),
        })
        return [TestSuite(**r) for r in rows]

    async def list_test_cases(self, suite_id: UUID) -> list[dict]:
        """List test cases in a suite."""
        return await self.db.fetch_all("list_test_cases_for_suite", {
            "suite_id": str(suite_id),
        })

    async def log_test_result(self, **kwargs) -> dict:
        """Log a test execution result."""
        params = dict(kwargs)
        for field in ["input_used", "actual_output", "expected_output", "metric_result", "inference_config_snapshot"]:
            val = params.get(field)
            if val is not None and not isinstance(val, str):
                params[field] = json.dumps(val)
        return await self.db.execute_returning("log_test_execution", params)

    async def list_test_results(
        self, entity_type, entity_version_id: UUID
    ) -> list[TestExecutionResult]:
        """List test results for an entity version."""
        et = entity_type.value if hasattr(entity_type, 'value') else str(entity_type)
        rows = await self.db.fetch_all("list_test_results_for_entity", {
            "entity_type": et,
            "entity_version_id": str(entity_version_id),
        })
        return [TestExecutionResult(**r) for r in rows]

    async def get_latest_validation(
        self, entity_type, entity_version_id: UUID
    ) -> Optional[ValidationRun]:
        """Get the latest validation run for an entity version."""
        et = entity_type.value if hasattr(entity_type, 'value') else str(entity_type)
        row = await self.db.fetch_one("get_latest_validation_run", {
            "entity_type": et,
            "entity_version_id": str(entity_version_id),
        })
        if not row:
            return None
        return ValidationRun(**_normalize(row))

    async def list_model_cards(self, entity_type, entity_version_id: UUID) -> list[dict]:
        """List model cards for an entity version."""
        et = entity_type.value if hasattr(entity_type, 'value') else str(entity_type)
        return await self.db.fetch_all("list_model_cards_for_entity", {
            "entity_type": et,
            "entity_version_id": str(entity_version_id),
        })


def _normalize(row: dict) -> dict:
    result = {}
    for k, v in row.items():
        if hasattr(v, "as_integer_ratio"):
            result[k] = float(v)
        else:
            result[k] = v
    return result
