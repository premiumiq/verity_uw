"""Decision log write model + runtime execution result types.

DecisionLogCreate is the runtime's input when it logs a decision to the
governance plane. ExecutionResult is what the runtime returns to its
caller (UW, test runner, validation runner). ExecutionEvent is used for
streaming execution (events emitted during a run).

Governance-internal DB read models (DecisionLog, DecisionLogDetail,
OverrideLog, AuditTrailEntry) stay in verity.models.decision — the
runtime doesn't produce or consume those.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.contracts.enums import DeploymentChannel, EntityType, RunPurpose


class DecisionLogCreate(BaseModel):
    """Input for logging a decision.

    Business context is linked via execution_context_id, not direct
    business keys. The consuming app registers a context with
    context_ref="submission:SUB-001" and passes the execution_context_id.
    Verity never knows what a "submission" is.
    """
    # Optional caller-supplied UUID. When None, the SQL defaults to
    # uuid_generate_v4() at INSERT time (original behaviour). The
    # runtime sets this explicitly from FC-1 onward so it can reference
    # the parent's in-flight decision id from within sub-agent calls
    # BEFORE the parent's decision row has been written.
    id: Optional[UUID] = None
    entity_type: EntityType
    entity_version_id: UUID
    prompt_version_ids: list[UUID] = []
    inference_config_snapshot: dict[str, Any]
    channel: DeploymentChannel = DeploymentChannel.PRODUCTION
    mock_mode: bool = False
    pipeline_run_id: Optional[UUID] = None
    parent_decision_id: Optional[UUID] = None
    decision_depth: int = 0
    step_name: Optional[str] = None
    input_summary: Optional[str] = None
    input_json: Optional[dict[str, Any]] = None
    output_json: Optional[dict[str, Any]] = None
    output_summary: Optional[str] = None
    reasoning_text: Optional[str] = None
    # risk_factors is typed as Any because Claude returns a list of dicts
    # like [{"factor": "...", "severity": "..."}], not a single dict.
    # The value gets JSON-serialized into a JSONB column either way.
    risk_factors: Optional[Any] = None
    confidence_score: Optional[float] = None
    low_confidence_flag: bool = False
    model_used: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    duration_ms: Optional[int] = None
    tool_calls_made: Optional[list[dict[str, Any]]] = None
    message_history: Optional[list[dict[str, Any]]] = None
    application: str = "default"
    run_purpose: RunPurpose = RunPurpose.PRODUCTION
    reproduced_from_decision_id: Optional[UUID] = None
    execution_context_id: Optional[UUID] = None
    hitl_required: bool = False
    status: str = "complete"
    error_message: Optional[str] = None


# ── RUNTIME EXECUTION RESULT ──────────────────────────────────
# Kept as @dataclass (not BaseModel) for Phase 1 — matches the current
# shape exactly. Will be promoted to BaseModel in Phase 4 when we need
# HTTP serialization over the wire.

@dataclass
class ExecutionResult:
    """Result of an agent, task, or tool execution.

    Returned by runtime.execute_agent / execute_task / run_tool. Carries
    both the structured output and enough metadata (decision_log_id,
    tokens, duration, status) for callers to audit and display the run.
    """
    decision_log_id: UUID
    entity_type: str          # "agent", "task", or "tool"
    entity_name: str
    version_label: str
    output: dict[str, Any]
    output_summary: str = ""
    reasoning_text: str = ""
    confidence_score: Optional[float] = None
    risk_factors: Optional[dict[str, Any]] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    status: str = "complete"
    error_message: Optional[str] = None


class ExecutionEventType(str, Enum):
    """Event types for streaming execution."""
    STARTED = "started"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_RESULT = "tool_call_result"
    TEXT_DELTA = "text_delta"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class ExecutionEvent:
    """An event emitted during streaming execution."""
    event_type: ExecutionEventType
    entity_name: str
    data: dict[str, Any] = field(default_factory=dict)
