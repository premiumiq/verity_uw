"""Decision log and override models.

DecisionLogCreate was moved to verity.contracts.decision as of Phase 1 of
the Registry/Runtime split. It is re-exported here for backward compatibility.

What stays here (governance-internal DB read shapes):
- DecisionLog — list-view row for the decisions page
- DecisionLogDetail — full detail row (with I/O data, message history)
- OverrideLogCreate — write input for record_override()
- OverrideLog — stored override read row
- AuditTrailEntry — one step in a pipeline run's audit trail
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.models.lifecycle import DeploymentChannel, EntityType, RunPurpose

# Re-export boundary model from contracts for backward compatibility.
from verity.contracts.decision import DecisionLogCreate  # noqa: F401


class DecisionLog(BaseModel):
    """A logged decision (read model for list views)."""
    id: UUID
    entity_type: EntityType
    entity_version_id: UUID
    channel: DeploymentChannel
    mock_mode: bool = False
    workflow_run_id: Optional[UUID] = None
    execution_run_id: Optional[UUID] = None
    execution_context_id: Optional[UUID] = None
    application: str = "default"
    run_purpose: RunPurpose = RunPurpose.PRODUCTION
    reproduced_from_decision_id: Optional[UUID] = None
    parent_decision_id: Optional[UUID] = None
    decision_depth: int = 0
    step_name: Optional[str] = None
    output_summary: Optional[str] = None
    confidence_score: Optional[float] = None
    low_confidence_flag: bool = False
    model_used: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    duration_ms: Optional[int] = None
    status: str = "complete"
    decision_log_detail: Optional[str] = "standard"
    hitl_required: bool = False
    # Joined from execution_context table
    execution_context_ref: Optional[str] = None
    created_at: Optional[datetime] = None

    # Joined fields
    entity_name: Optional[str] = None
    entity_display_name: Optional[str] = None
    version_label: Optional[str] = None


class DecisionLogDetail(DecisionLog):
    """Full decision detail with I/O data."""
    prompt_version_ids: list[UUID] = []
    inference_config_snapshot: dict[str, Any] = {}
    input_summary: Optional[str] = None
    input_json: Optional[dict[str, Any]] = None
    output_json: Optional[dict[str, Any]] = None
    reasoning_text: Optional[str] = None
    risk_factors: Optional[Any] = None
    tool_calls_made: Optional[list[dict[str, Any]]] = None
    message_history: Optional[list[dict[str, Any]]] = None
    application: str = "default"
    hitl_completed: bool = False
    error_message: Optional[str] = None
    redaction_applied: Optional[dict[str, Any]] = None
    source_resolutions: Optional[list[dict[str, Any]]] = None
    target_writes: Optional[list[dict[str, Any]]] = None

    # Joined names
    agent_name: Optional[str] = None
    agent_display_name: Optional[str] = None
    task_name: Optional[str] = None
    task_display_name: Optional[str] = None


class OverrideLogCreate(BaseModel):
    """Input for recording an override.

    No business keys here. The override links to decision_log_id,
    which links to execution_context_id for business context.
    """
    decision_log_id: UUID
    entity_type: EntityType
    entity_version_id: UUID
    overrider_name: str
    overrider_role: Optional[str] = None
    override_reason_code: str
    override_notes: Optional[str] = None
    ai_recommendation: Optional[dict[str, Any]] = None
    human_decision: Optional[dict[str, Any]] = None


class OverrideLog(BaseModel):
    """Stored override read row."""
    id: UUID
    decision_log_id: UUID
    entity_type: EntityType
    entity_version_id: UUID
    overrider_name: str
    overrider_role: Optional[str] = None
    override_reason_code: str
    override_notes: Optional[str] = None
    ai_recommendation: Optional[dict[str, Any]] = None
    human_decision: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None


class AuditTrailEntry(BaseModel):
    """One step in a pipeline run's audit trail."""
    decision_id: UUID
    entity_type: EntityType
    entity_name: str
    entity_display_name: str
    version_label: str
    capability_type: Optional[str] = None
    channel: DeploymentChannel
    parent_decision_id: Optional[UUID] = None
    decision_depth: int = 0
    step_name: Optional[str] = None
    output_summary: Optional[str] = None
    reasoning_text: Optional[str] = None
    confidence_score: Optional[float] = None
    risk_factors: Optional[Any] = None
    duration_ms: Optional[int] = None
    tool_calls_made: Optional[list[dict[str, Any]]] = None
    hitl_required: bool = False
    hitl_completed: bool = False
    status: str = "complete"
    created_at: Optional[datetime] = None
