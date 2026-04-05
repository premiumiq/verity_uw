"""Task and TaskVersion models."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.models.inference_config import InferenceConfig, InferenceConfigSnapshot
from verity.models.lifecycle import (
    CapabilityType,
    DeploymentChannel,
    LifecycleState,
    MaterialityTier,
)
from verity.models.prompt import PromptAssignment
from verity.models.tool import ToolAuthorization


class Task(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: str
    capability_type: CapabilityType
    purpose: str
    domain: str = "underwriting"
    materiality_tier: MaterialityTier
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    owner_name: str
    owner_email: Optional[str] = None
    business_context: Optional[str] = None
    known_limitations: Optional[str] = None
    regulatory_notes: Optional[str] = None
    current_champion_version_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskVersion(BaseModel):
    id: UUID
    task_id: UUID
    major_version: int = 1
    minor_version: int = 0
    patch_version: int = 0
    version_label: Optional[str] = None
    lifecycle_state: LifecycleState = LifecycleState.DRAFT
    channel: DeploymentChannel = DeploymentChannel.DEVELOPMENT
    inference_config_id: UUID
    inference_config_name: Optional[str] = None
    output_schema: Optional[dict[str, Any]] = None
    mock_mode_enabled: bool = False
    shadow_traffic_pct: float = 0
    challenger_traffic_pct: float = 0
    staging_tests_passed: Optional[bool] = None
    ground_truth_passed: Optional[bool] = None
    fairness_passed: Optional[bool] = None
    developer_name: Optional[str] = None
    change_summary: Optional[str] = None
    change_type: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskConfig(BaseModel):
    """Full runtime config returned by get_task_config().

    This is what the execution engine uses to invoke a task.
    """
    task_id: UUID
    task_name: str
    display_name: str
    description: str
    capability_type: CapabilityType
    materiality_tier: MaterialityTier
    purpose: str
    domain: str

    task_version_id: UUID
    version_label: str
    lifecycle_state: LifecycleState

    # Inference configuration
    inference_config: InferenceConfig

    # Input/output schemas
    task_input_schema: dict[str, Any]
    task_output_schema: dict[str, Any]

    # Prompts
    prompts: list[PromptAssignment] = []

    # Tools (tasks may have authorized tools)
    tools: list[ToolAuthorization] = []

    def get_inference_snapshot(self) -> InferenceConfigSnapshot:
        """Create a snapshot for decision logging."""
        ic = self.inference_config
        return InferenceConfigSnapshot(
            config_name=ic.name,
            model_name=ic.model_name,
            temperature=ic.temperature,
            max_tokens=ic.max_tokens,
            top_p=ic.top_p,
            top_k=ic.top_k,
            stop_sequences=ic.stop_sequences,
            extended_params=ic.extended_params,
        )
