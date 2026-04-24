"""Async run-submission request/response shapes.

The runtime accepts task and agent runs over an asynchronous API:
callers submit a run and get back a run_id immediately; a worker pool
claims the run, executes it, and writes terminal state back to
execution_run_completion / execution_run_error. Reads come from the
execution_run_current view (see verity.models.run).

This module defines the WRITE-side contracts: what callers POST to
/api/v1/runs and what the runtime returns at submission time. The
read-side models (ExecutionRunCurrent, ExecutionRunStatus, etc.) live
in verity.models.run.
"""

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RunSubmission(BaseModel):
    """What a caller POSTs to /api/v1/runs to start a task or agent run.

    Mirrors the columns of execution_run plus a place for the input dict
    that becomes execution_run.input_json. Validation (entity exists,
    schema check, etc.) happens server-side at submit time.
    """

    # Which kind of unit and which one. Resolved server-side to a
    # task_version.id or agent_version.id.
    entity_kind: Literal["task", "agent"]
    entity_name: str

    # Input dict bound to the unit's input_schema. Stored verbatim as
    # execution_run.input_json. Becomes input_data inside the engine.
    input: dict[str, Any] = Field(default_factory=dict)

    # Lifecycle channel — controls source resolution, target writes,
    # and which prompt-version-channel pin to use.
    channel: str = "production"

    # Identity threading. All three are caller-supplied and stored as-is.
    execution_context_id: Optional[UUID] = None
    workflow_run_id: Optional[UUID] = None
    parent_decision_id: Optional[UUID] = None

    # Caller identity for audit (the application or user submitting).
    application: str = "default"
    submitted_by: Optional[str] = None

    # Runtime gates. None falls back to the engine's defaults.
    mock_mode: bool = False
    write_mode: Optional[Literal["auto", "log_only", "write"]] = None
    enforce_output_schema: Optional[bool] = None  # agents only


class RunSubmissionResponse(BaseModel):
    """Response from POST /api/v1/runs at submission time.

    Returned synchronously after the run row is written; the actual
    execution happens asynchronously when a worker claims it.
    """

    run_id: UUID
    status: Literal["submitted"] = "submitted"
    submitted_at: datetime
