"""Async run-submission endpoints — POST /runs and the polling surface.

Read-mostly except for the submit and cancel endpoints. Reads come
through the execution_run_current view via verity.runs.RunsReader;
writes go through verity.runs.RunsWriter. The actual execution happens
in a separate worker process — this API only inserts state-event rows.

Endpoints:
  POST   /runs                  — submit a task or agent run
  GET    /runs                  — filtered list (drives the Runs UI)
  GET    /runs/{id}             — current state for one run
  GET    /runs/{id}/lifecycle   — full event sequence (status + terminal)
  GET    /runs/{id}/result      — decision-log row for a completed run
  POST   /runs/{id}/cancel      — request cancellation

Submission resolves entity_name + entity_kind + channel to a concrete
entity_version_id by querying the champion at submit time. The worker
later loads the full config when it dispatches.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from verity.contracts.run import RunSubmission, RunSubmissionResponse
from verity.models.run import (
    ExecutionRunCurrent,
    RunLifecycleEvent,
)


def build_runs_router(verity) -> APIRouter:
    """Build the /runs router. `verity` is the in-process SDK client."""

    router = APIRouter(tags=["runs"])

    async def _resolve_entity_version(kind: str, name: str) -> UUID:
        """Look up the champion version_id for the named entity.

        Submission always uses the champion at the time of submit. If
        callers want to pin to a specific version, that's a future
        capability (RunSubmission would carry an optional version_id).
        """
        if kind == "task":
            row = await verity.db.fetch_one("get_task_champion", {"task_name": name})
            id_key = "task_version_id"
        elif kind == "agent":
            row = await verity.db.fetch_one("get_agent_champion", {"agent_name": name})
            id_key = "agent_version_id"
        else:
            raise HTTPException(400, f"Unknown entity_kind '{kind}'")
        if not row:
            raise HTTPException(
                404,
                f"{kind.capitalize()} '{name}' has no champion version registered.",
            )
        return UUID(str(row[id_key]))

    @router.post("/runs", response_model=RunSubmissionResponse)
    async def submit_run(request: RunSubmission) -> RunSubmissionResponse:
        """Submit a run. Returns immediately with run_id; execution
        happens asynchronously when a worker claims the row."""
        version_id = await _resolve_entity_version(
            request.entity_kind, request.entity_name,
        )
        return await verity.runs_writer.submit(
            request=request, entity_version_id=version_id,
        )

    @router.get("/runs", response_model=list[ExecutionRunCurrent])
    async def list_runs(
        execution_context_id: UUID | None = Query(default=None),
        workflow_run_id: UUID | None = Query(default=None),
        entity_kind: str | None = Query(default=None),
        entity_name: str | None = Query(default=None),
        channel: str | None = Query(default=None),
        application: str | None = Query(default=None),
        status: str | None = Query(
            default=None,
            description="One of submitted/claimed/heartbeat/released/complete/cancelled/failed.",
        ),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> list[ExecutionRunCurrent]:
        """Most-recent-first list with multi-dimensional filters.
        Each filter is independent; pass None (omit the param) to
        disable. Drives the unified Runs UI page."""
        return await verity.runs_reader.list_runs(
            execution_context_id=execution_context_id,
            workflow_run_id=workflow_run_id,
            entity_kind=entity_kind,
            entity_name=entity_name,
            channel=channel,
            application=application,
            status=status,
            limit=limit,
            offset=offset,
        )

    @router.get("/runs/{run_id}", response_model=ExecutionRunCurrent)
    async def get_run(run_id: UUID) -> ExecutionRunCurrent:
        """Current state of one run — current_status + identity columns +
        completion or error details if terminal."""
        run = await verity.runs_reader.get_run(run_id)
        if not run:
            raise HTTPException(404, f"Run {run_id} not found")
        return run

    @router.get("/runs/{run_id}/lifecycle", response_model=list[RunLifecycleEvent])
    async def get_run_lifecycle(run_id: UUID) -> list[RunLifecycleEvent]:
        """Full event sequence for one run: every status transition plus
        the completion or error row, in time order. Used by the run-detail
        UI to show 'how this run unfolded'."""
        events = await verity.runs_reader.get_run_lifecycle(run_id)
        if not events:
            # Could be a missing run or a run that somehow has no events
            # at all. Differentiate via a separate get_run lookup so the
            # 404 actually means missing.
            run = await verity.runs_reader.get_run(run_id)
            if not run:
                raise HTTPException(404, f"Run {run_id} not found")
        return events

    @router.get("/runs/{run_id}/result")
    async def get_run_result(run_id: UUID) -> dict:
        """Decision-log row for a completed run.

        Returns the full audit row (input, output, source_resolutions,
        target_writes, telemetry) for runs that have a decision_log_id
        on their completion or error row. 409 if the run hasn't reached
        a terminal state, or terminated without producing a decision
        (e.g. cancelled before claim)."""
        run = await verity.runs_reader.get_run(run_id)
        if not run:
            raise HTTPException(404, f"Run {run_id} not found")
        # Two cases for "not yet terminal": current_status is in the
        # in-flight set. Map them to 409 so callers can tell "not
        # ready" from "not present."
        if run.current_status.value in (
            "submitted", "claimed", "heartbeat", "released",
        ):
            raise HTTPException(
                409,
                f"Run {run_id} is not terminal (status={run.current_status.value}).",
            )
        result = await verity.runs_reader.get_run_result(run_id)
        if not result:
            raise HTTPException(
                409,
                f"Run {run_id} terminated without a decision_log_id.",
            )
        return result

    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: UUID) -> dict:
        """Request cancellation. Inserts a 'cancelled' completion row
        if no terminal row exists yet. Idempotent: returns
        {accepted: false} if the run is already terminal."""
        run = await verity.runs_reader.get_run(run_id)
        if not run:
            raise HTTPException(404, f"Run {run_id} not found")
        accepted = await verity.runs_writer.cancel(run_id, worker_id="api-cancel")
        return {"run_id": str(run_id), "accepted": accepted}

    return router
