"""Task and TaskVersion models.

TaskConfig was moved to verity.contracts.config as of Phase 1 of the
Registry/Runtime split. It is re-exported here for backward compatibility.

What stays here (governance-internal DB read shapes):
- Task — the task header row (with input/output schemas)
- TaskVersion — a versioned task with lifecycle state and gate flags
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.models.lifecycle import (
    CapabilityType,
    DeploymentChannel,
    LifecycleState,
    MaterialityTier,
)

# Re-export boundary model from contracts for backward compatibility.
from verity.contracts.config import TaskConfig  # noqa: F401


class Task(BaseModel):
    """Task header — one row per named task (N versions reference it)."""
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
    """One versioned task: inference config + lifecycle state + gate flags."""
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
