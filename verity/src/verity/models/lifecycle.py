"""Lifecycle: governance-internal state machine + approval models.

The shared enums (LifecycleState, DeploymentChannel, etc.) were moved to
verity.contracts.enums as of Phase 1 of the Registry/Runtime split. They
are re-exported here for backward compatibility — any existing code that
did `from verity.models.lifecycle import EntityType` keeps working and
resolves to the exact same class object.

What stays here (governance-internal, not re-exported from contracts):
- PromotionRequest — the lifecycle promotion request Pydantic model
- ApprovalRecord  — the stored approval record read model
- VALID_TRANSITIONS — the 7-state machine's transition table
- STATE_TO_CHANNEL — mapping of lifecycle_state → default deployment channel
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

# Re-export enums from contracts for backward compatibility.
# These imports make `from verity.models.lifecycle import EntityType` work.
from verity.contracts.enums import (  # noqa: F401
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


# ── GOVERNANCE-INTERNAL MACHINE STATE ─────────────────────────

# Valid lifecycle transitions per the 7-state model.
# This is governance-internal — the runtime never reads this.
VALID_TRANSITIONS: dict[LifecycleState, list[LifecycleState]] = {
    LifecycleState.DRAFT: [LifecycleState.CANDIDATE],
    LifecycleState.CANDIDATE: [LifecycleState.STAGING, LifecycleState.CHAMPION, LifecycleState.DEPRECATED],
    LifecycleState.STAGING: [LifecycleState.SHADOW, LifecycleState.DEPRECATED],
    LifecycleState.SHADOW: [LifecycleState.CHALLENGER, LifecycleState.DEPRECATED],
    LifecycleState.CHALLENGER: [LifecycleState.CHAMPION, LifecycleState.DEPRECATED],
    LifecycleState.CHAMPION: [LifecycleState.DEPRECATED],
    LifecycleState.DEPRECATED: [],
}

# Channel mapping for each lifecycle state — used by the governance plane
# when promoting a version to set its deployment_channel correctly.
STATE_TO_CHANNEL: dict[LifecycleState, DeploymentChannel] = {
    LifecycleState.DRAFT: DeploymentChannel.DEVELOPMENT,
    LifecycleState.CANDIDATE: DeploymentChannel.DEVELOPMENT,
    LifecycleState.STAGING: DeploymentChannel.STAGING,
    LifecycleState.SHADOW: DeploymentChannel.SHADOW,
    LifecycleState.CHALLENGER: DeploymentChannel.EVALUATION,
    LifecycleState.CHAMPION: DeploymentChannel.PRODUCTION,
    LifecycleState.DEPRECATED: DeploymentChannel.PRODUCTION,
}


class PromotionRequest(BaseModel):
    """Input to the governance plane's promote() method.

    Carries the target state plus the evidence-review flags an approver
    asserts at promotion time. The gate check combines these with the
    version's stored test/validation flags to decide whether to proceed.
    """
    target_state: LifecycleState
    approver_name: str
    approver_role: Optional[str] = None
    rationale: str
    staging_results_reviewed: bool = False
    ground_truth_reviewed: bool = False
    fairness_analysis_reviewed: bool = False
    shadow_metrics_reviewed: bool = False
    challenger_metrics_reviewed: bool = False
    model_card_reviewed: bool = False
    similarity_flags_reviewed: bool = False


class ApprovalRecord(BaseModel):
    """Stored approval record for a lifecycle promotion."""
    id: UUID
    entity_type: EntityType
    entity_version_id: UUID
    gate_type: str
    from_state: Optional[LifecycleState] = None
    to_state: Optional[LifecycleState] = None
    approver_name: str
    approver_role: Optional[str] = None
    approved_at: datetime
    rationale: str
