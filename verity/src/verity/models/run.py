"""Run-tracking models — event-sourced lifecycle for async task and agent runs.

Run state is stored across four immutable, insert-only tables plus a view
that surfaces resolved current state. The SQL shape (defined in schema.sql)
is mirrored here as Pydantic read models.

  ExecutionRun           — the request (one row per submission, immutable)
  ExecutionRunStatus     — ledger of submitted/claimed/heartbeat/released
  ExecutionRunCompletion — terminal success row (final_status complete|cancelled)
  ExecutionRunError      — terminal failure row
  ExecutionRunCurrent    — combined view; what the API and UI read

The execution_run_current view is the canonical "what's the current state"
read; nothing about a run is mutated, so the view is the only place
callers should look for a single up-to-date status field.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class RunCurrentStatus(str, Enum):
    """Resolved current_status as surfaced by execution_run_current.

    A run is one of these at any moment. submitted/claimed/heartbeat/
    released come from the latest execution_run_status row. complete /
    cancelled / failed come from the terminal completion / error rows
    and override status events when present.
    """
    SUBMITTED = "submitted"
    CLAIMED   = "claimed"
    HEARTBEAT = "heartbeat"
    RELEASED  = "released"
    COMPLETE  = "complete"
    CANCELLED = "cancelled"
    FAILED    = "failed"


class ExecutionRun(BaseModel):
    """Immutable submission row.

    Inserted once at submit time; never updated. Holds everything the
    worker needs to dispatch the run plus the identity columns
    (execution_context_id, workflow_run_id) that thread the audit trail.
    """
    id: UUID
    entity_kind: str   # 'task' | 'agent'
    entity_version_id: UUID
    entity_name: str
    channel: str
    input_json: Optional[dict[str, Any]] = None
    execution_context_id: Optional[UUID] = None
    workflow_run_id: Optional[UUID] = None
    parent_decision_id: Optional[UUID] = None
    application: str = "default"
    mock_mode: bool = False
    write_mode: Optional[str] = None              # 'auto' | 'log_only' | 'write'
    enforce_output_schema: Optional[bool] = None  # agents only
    submitted_at: datetime
    submitted_by: Optional[str] = None


class ExecutionRunStatus(BaseModel):
    """One state-transition event on a run.

    `status` is one of submitted | claimed | heartbeat | released — terminal
    outcomes (complete/cancelled/failed) live in the completion / error
    tables, NOT here.
    """
    id: UUID
    execution_run_id: UUID
    status: str
    recorded_at: datetime
    worker_id: Optional[str] = None
    notes: Optional[str] = None


class ExecutionRunCompletion(BaseModel):
    """Terminal success row.

    UNIQUE on execution_run_id — at most one completion per run.
    final_status is 'complete' for a normal successful run; 'cancelled'
    for a run that was terminated on request.
    """
    id: UUID
    execution_run_id: UUID
    final_status: str   # 'complete' | 'cancelled'
    completed_at: datetime
    decision_log_id: Optional[UUID] = None
    duration_ms: Optional[int] = None
    worker_id: Optional[str] = None


class ExecutionRunError(BaseModel):
    """Terminal failure row.

    UNIQUE on execution_run_id — at most one error per run.
    decision_log_id is populated when a partial audit row was written
    before the failure surfaced.
    """
    id: UUID
    execution_run_id: UUID
    failed_at: datetime
    error_code: Optional[str] = None
    error_message: str
    error_trace: Optional[str] = None
    worker_id: Optional[str] = None
    decision_log_id: Optional[UUID] = None


class ExecutionRunCurrent(BaseModel):
    """Read shape for the execution_run_current view.

    Combines the four run-tracking tables into one row per run with a
    resolved current_status field. This is what the Runs UI and the
    REST API GET /runs / GET /runs/{id} endpoints return.
    """
    # Submission-time fields (mirrors ExecutionRun).
    id: UUID
    entity_kind: str
    entity_version_id: UUID
    entity_name: str
    channel: str
    input_json: Optional[dict[str, Any]] = None
    execution_context_id: Optional[UUID] = None
    workflow_run_id: Optional[UUID] = None
    parent_decision_id: Optional[UUID] = None
    application: str = "default"
    mock_mode: bool = False
    write_mode: Optional[str] = None
    enforce_output_schema: Optional[bool] = None
    submitted_at: datetime
    submitted_by: Optional[str] = None

    # Resolved state.
    current_status: RunCurrentStatus
    latest_status_event: Optional[str] = None
    current_status_as_of: Optional[datetime] = None
    current_worker_id: Optional[str] = None

    # Completion details (null if not complete/cancelled).
    completed_at: Optional[datetime] = None
    completion_decision_log_id: Optional[UUID] = None
    duration_ms: Optional[int] = None

    # Error details (null if not failed).
    failed_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error_decision_log_id: Optional[UUID] = None

    # Lifecycle helper — first time the run was claimed by any worker.
    first_started_at: Optional[datetime] = None

    # Display-name enrichments (joined from task / agent / application
    # in the listing queries). None when the join misses (e.g. a row
    # whose entity version was deleted, or an application name with no
    # matching application row).
    entity_display_name: Optional[str] = None
    application_display_name: Optional[str] = None


class RunLifecycleEvent(BaseModel):
    """One event in get_run_lifecycle's unified timeline.

    The query unions execution_run_status, execution_run_completion, and
    execution_run_error rows into one shape for the run-detail UI's
    drill-through. event_table discriminates the source row.
    """
    event_table: str    # 'status' | 'completion' | 'error'
    event_id: UUID
    occurred_at: datetime
    event_kind: str     # the status name for status rows; 'complete'/
                        # 'cancelled'/'failed' for terminal rows
    worker_id: Optional[str] = None
    notes: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    decision_log_id: Optional[UUID] = None
    duration_ms: Optional[int] = None
