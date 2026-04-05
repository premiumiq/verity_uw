"""Agent and AgentVersion models."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.models.inference_config import InferenceConfig, InferenceConfigSnapshot
from verity.models.lifecycle import LifecycleState, MaterialityTier, DeploymentChannel
from verity.models.prompt import PromptAssignment
from verity.models.tool import ToolAuthorization


class Agent(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: str
    purpose: str
    domain: str = "underwriting"
    materiality_tier: MaterialityTier
    owner_name: str
    owner_email: Optional[str] = None
    business_context: Optional[str] = None
    known_limitations: Optional[str] = None
    regulatory_notes: Optional[str] = None
    current_champion_version_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AgentVersion(BaseModel):
    id: UUID
    agent_id: UUID
    major_version: int = 1
    minor_version: int = 0
    patch_version: int = 0
    version_label: Optional[str] = None
    lifecycle_state: LifecycleState = LifecycleState.DRAFT
    channel: DeploymentChannel = DeploymentChannel.DEVELOPMENT
    inference_config_id: UUID
    inference_config_name: Optional[str] = None
    output_schema: Optional[dict[str, Any]] = None
    authority_thresholds: dict[str, Any] = {}
    mock_mode_enabled: bool = False
    shadow_traffic_pct: float = 0
    challenger_traffic_pct: float = 0
    staging_tests_passed: Optional[bool] = None
    ground_truth_passed: Optional[bool] = None
    fairness_passed: Optional[bool] = None
    shadow_period_complete: bool = False
    challenger_period_complete: bool = False
    developer_name: Optional[str] = None
    change_summary: Optional[str] = None
    change_type: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AgentConfig(BaseModel):
    """Full runtime config returned by get_agent_config().

    This is what the execution engine uses to invoke an agent.
    Everything here comes from Verity — nothing hardcoded.
    """
    agent_id: UUID
    agent_name: str
    display_name: str
    description: str
    materiality_tier: MaterialityTier
    purpose: str
    domain: str

    agent_version_id: UUID
    version_label: str
    lifecycle_state: LifecycleState

    # Inference configuration
    inference_config: InferenceConfig

    # Prompts (system + user, ordered by execution_order)
    prompts: list[PromptAssignment] = []

    # Authorized tools
    tools: list[ToolAuthorization] = []

    # Authority thresholds (HITL triggers)
    authority_thresholds: dict[str, Any] = {}
    output_schema: Optional[dict[str, Any]] = None

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
