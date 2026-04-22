"""Verity contracts — Pydantic (and dataclass) models on the governance↔runtime boundary.

Anything in this subpackage is shared vocabulary between the governance plane
(registry, lifecycle, decision log writer/reader, audit, compliance) and the
runtime plane (execution, pipelines, runners). Governance-internal models
(DB read shapes, approval records, registration inputs) stay under
verity.models.*.

Import from this subpackage directly:

    from verity.contracts import (
        # Enums
        LifecycleState, DeploymentChannel, MaterialityTier, CapabilityType,
        EntityType, GovernanceTier, ApiRole, MetricType, RunPurpose,
        GtDatasetStatus, GtQualityTier, GtSourceType, GtAnnotatorType,

        # Config / resolve() result
        AgentConfig, TaskConfig, InferenceConfig, InferenceConfigSnapshot,
        PromptAssignment, ToolAuthorization, PipelineStep,

        # Decision log / runtime result
        DecisionLogCreate, ExecutionResult, ExecutionEvent, ExecutionEventType,

        # Runtime mock control
        MockContext,

        # Testing / validation boundary
        TestSuite, TestCase, TestExecutionResult, ValidationRun,
    )
"""

from verity.contracts.config import AgentConfig, TaskConfig
from verity.contracts.decision import (
    DecisionLogCreate,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionResult,
)
from verity.contracts.enums import (
    ApiRole,
    CapabilityType,
    DeploymentChannel,
    EntityType,
    GovernanceTier,
    GtAnnotatorType,
    GtDatasetStatus,
    GtQualityTier,
    GtSourceType,
    LifecycleState,
    MaterialityTier,
    MetricType,
    RunPurpose,
)
from verity.contracts.inference import InferenceConfig, InferenceConfigSnapshot
from verity.contracts.mock import MockContext
from verity.contracts.pipeline import PipelineStep
from verity.contracts.prompt import PromptAssignment
from verity.contracts.testing import TestCase, TestExecutionResult, TestSuite, ValidationRun
from verity.contracts.tool import ToolAuthorization

__all__ = [
    # Enums
    "ApiRole",
    "CapabilityType",
    "DeploymentChannel",
    "EntityType",
    "GovernanceTier",
    "GtAnnotatorType",
    "GtDatasetStatus",
    "GtQualityTier",
    "GtSourceType",
    "LifecycleState",
    "MaterialityTier",
    "MetricType",
    "RunPurpose",
    # Config / resolve()
    "AgentConfig",
    "TaskConfig",
    "InferenceConfig",
    "InferenceConfigSnapshot",
    "PromptAssignment",
    "ToolAuthorization",
    "PipelineStep",
    # Decision log / runtime result
    "DecisionLogCreate",
    "ExecutionResult",
    "ExecutionEvent",
    "ExecutionEventType",
    # Runtime mock control
    "MockContext",
    # Testing / validation
    "TestSuite",
    "TestCase",
    "TestExecutionResult",
    "ValidationRun",
]
