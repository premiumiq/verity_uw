"""Canonical execution envelope — the single return shape for any
task or agent run that's reached a terminal state.

Read-side construct: built from the persisted execution_run_current
view row + its linked agent_decision_log row. The runtime continues
to return ExecutionResult internally; this envelope is what external
consumers (REST API, SDK polling, Runs UI) see.

Shape borrows from established specs:
  - CloudEvents 1.0           — identity + typed event + time + data
  - JSON-RPC 2.0              — mutually-exclusive output / error,
                                  discriminated by status
  - RFC 7807 Problem Details  — structured error with code + message
  - Anthropic Messages API    — stop_reason / usage as telemetry

Intentional design notes:

  - status is a two-value enum (success | failure). No 'partial' state —
    a single task or agent either produces its output or it doesn't.
    Multi-step partial-success semantics belong in app orchestration.

  - output and error are mutually exclusive. Discriminated by status.

  - No nested steps[]: pipelines are descoped from Verity. Apps that
    want a workflow-level envelope build their own from multiple per-
    run envelopes that share a workflow_run_id.

  - parent_run_id is set automatically when an agent delegates to a
    sub-agent. Apps may also set it across their own chained runs for
    end-to-end traceability; Verity never sets it cross-run on behalf
    of app-level orchestration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EnvelopeEntity(BaseModel):
    """Which task or agent version produced this envelope.

    `type` discriminates task vs agent; `name` is the registered
    entity name; `version_label` is the SemVer string from the
    `*_version` row; `version_id` is the UUID FK; `channel` is the
    deployment channel under which this run was dispatched.
    """
    type: Literal["task", "agent"]
    name: str
    version_label: Optional[str] = None
    version_id: Optional[UUID] = None
    channel: Optional[str] = None


class EnvelopeError(BaseModel):
    """Structured error block, present iff envelope.status == 'failure'."""
    code: Optional[str] = None
    message: str
    retriable: bool = False
    # Free-form extra context — full traceback for debug, the failing
    # source binding, the connector's error response, etc.
    details: dict[str, Any] = Field(default_factory=dict)


class EnvelopeTelemetry(BaseModel):
    """Engine-generated counters for cost / utilization analytics.

    Most fields come straight from agent_decision_log; sources_resolved
    and targets_fired are derived from the per-row JSONB audit lists.
    cost_usd, turns, and mocks_used are forward-compatible fields the
    runtime doesn't populate yet — they require model_price joins,
    per_turn_metadata aggregation, or MockContext introspection that
    aren't wired up.
    """
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    turns: Optional[int] = None
    tool_calls: Optional[int] = None
    sources_resolved: list[str] = Field(default_factory=list)
    targets_fired: list[str] = Field(default_factory=list)
    mocks_used: list[str] = Field(default_factory=list)


class EnvelopeProvenance(BaseModel):
    """Pointers to the persisted state behind this envelope.

    decision_log_id is the immutable audit row produced by the engine.
    execution_run_id is the live-state row the worker drove. The two
    business-context identity columns (workflow_run_id, execution_context_id)
    let consumers walk back to all related runs for the same submission
    or workflow invocation.
    """
    decision_log_id: Optional[UUID] = None
    execution_run_id: Optional[UUID] = None
    workflow_run_id: Optional[UUID] = None
    execution_context_id: Optional[UUID] = None
    parent_decision_id: Optional[UUID] = None
    mock_mode: bool = False
    application: str = "default"


class ExecutionEnvelope(BaseModel):
    """Canonical return shape for a task or agent run.

    Returned synchronously after a sync run completes, OR retrieved
    via GET /api/v1/runs/{id}/result once an async run reaches a
    terminal state. Same shape either way.
    """
    envelope_version: Literal["1.0"] = "1.0"
    run_id: UUID
    parent_run_id: Optional[UUID] = None

    entity: EnvelopeEntity
    status: Literal["success", "failure"]

    # Mutually exclusive — discriminated by `status`. Validators on the
    # consuming side trust the discriminator; we don't enforce
    # exclusivity in the model so callers can construct either branch
    # cleanly.
    output: Optional[dict[str, Any]] = None
    error: Optional[EnvelopeError] = None

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    telemetry: EnvelopeTelemetry = Field(default_factory=EnvelopeTelemetry)
    provenance: EnvelopeProvenance
