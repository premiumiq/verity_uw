"""Agent and AgentVersion models.

AgentConfig was moved to verity.contracts.config as of Phase 1 of the
Registry/Runtime split. It is re-exported here for backward compatibility.

What stays here (governance-internal DB read shapes):
- Agent — the agent header row
- AgentVersion — a versioned agent with lifecycle state, channel, thresholds
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.models.lifecycle import DeploymentChannel, LifecycleState, MaterialityTier

# Re-export boundary model from contracts for backward compatibility.
from verity.contracts.config import AgentConfig  # noqa: F401


class Agent(BaseModel):
    """Agent header — one row per named agent (N versions reference it)."""
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
    """One versioned agent: inference config + lifecycle state + gate flags."""
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
