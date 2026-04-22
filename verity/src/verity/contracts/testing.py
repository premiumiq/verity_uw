"""Testing and validation boundary models.

These four models cross the governance↔runtime seam:

- TestSuite + TestCase: governance-owned definitions that the runtime's
  test_runner reads to know what to execute.
- TestExecutionResult: runtime produces; governance stores.
- ValidationRun: runtime produces aggregate metrics; governance stores
  and displays in the compliance UI.

These are the pure boundary shapes — the governance-side list views
(with joined fields for the UI) stay in verity.models.testing.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.contracts.enums import EntityType, MetricType


class TestSuite(BaseModel):
    """A named container for test cases targeting one entity."""
    id: UUID
    name: str
    description: Optional[str] = None
    entity_type: EntityType
    entity_id: UUID
    suite_type: str
    created_by: Optional[str] = None
    active: bool = True
    created_at: Optional[datetime] = None


class TestCase(BaseModel):
    """One input/expected-output pair within a test suite."""
    id: UUID
    suite_id: UUID
    name: str
    description: Optional[str] = None
    input_data: dict[str, Any]
    expected_output: dict[str, Any]
    metric_type: MetricType
    metric_config: Optional[dict[str, Any]] = None
    is_adversarial: bool = False
    tags: list[str] = []
    active: bool = True
    created_at: Optional[datetime] = None


class TestExecutionResult(BaseModel):
    """Result of running one test case against one entity version.

    Produced by the runtime's test_runner, stored by governance.
    """
    id: UUID
    suite_id: UUID
    suite_name: Optional[str] = None
    suite_type: Optional[str] = None
    test_case_id: UUID
    test_case_name: Optional[str] = None
    mock_mode: bool
    metric_type: MetricType
    metric_result: Optional[dict[str, Any]] = None
    passed: bool
    failure_reason: Optional[str] = None
    duration_ms: Optional[int] = None
    run_at: Optional[datetime] = None


class ValidationRun(BaseModel):
    """Aggregate metrics from running an entity version against a GT dataset.

    Produced by the runtime's validation_runner, stored by governance.
    """
    id: UUID
    entity_type: EntityType
    entity_version_id: UUID
    dataset_id: UUID
    run_at: Optional[datetime] = None
    run_by: str
    precision_score: Optional[float] = None
    recall_score: Optional[float] = None
    f1_score: Optional[float] = None
    cohens_kappa: Optional[float] = None
    confusion_matrix: Optional[dict[str, Any]] = None
    field_accuracy: Optional[dict[str, Any]] = None
    overall_extraction_rate: Optional[float] = None
    fairness_metrics: Optional[dict[str, Any]] = None
    fairness_passed: Optional[bool] = None
    thresholds_met: Optional[bool] = None
    threshold_details: Optional[dict[str, Any]] = None
    passed: Optional[bool] = None
    notes: Optional[str] = None
