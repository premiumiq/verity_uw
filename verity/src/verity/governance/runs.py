"""Governance-side reads against the event-sourced run-tracking tables.

Mirrors the decisions reader/writer split: this module owns every read
of execution_run / execution_run_current / lifecycle queries. The
runtime plane writes via verity.runtime.runs_writer.

Why a reader/writer split? The runtime never needs the read surface —
it only inserts state events. The UI, REST API, and replay tooling
never need the write surface — they only query current state and
lifecycles. Separating them keeps each plane's interface minimal.

All reads come through the execution_run_current view (combined state)
or the lifecycle query (full event sequence) so callers never have to
join the four lifecycle tables themselves.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from verity.db.connection import Database
from verity.models.run import (
    ExecutionRunCurrent,
    RunLifecycleEvent,
)


class RunsReader:
    """Query the run-tracking tables for current state and history."""

    def __init__(self, db: Database):
        self.db = db

    async def get_run(self, run_id: UUID) -> Optional[ExecutionRunCurrent]:
        """Read one run's current state from the execution_run_current view.

        Returns None if no run exists with that id.
        """
        row = await self.db.fetch_one("get_run_current", {"run_id": str(run_id)})
        if not row:
            return None
        return ExecutionRunCurrent(**row)

    async def list_runs(
        self,
        *,
        execution_context_id: Optional[UUID] = None,
        workflow_run_id: Optional[UUID] = None,
        entity_kind: Optional[str] = None,
        entity_name: Optional[str] = None,
        channel: Optional[str] = None,
        application: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExecutionRunCurrent]:
        """List runs with the supplied filters. Pass None to disable a filter."""
        rows = await self.db.fetch_all(
            "list_runs_current",
            {
                "execution_context_id": _str_or_none(execution_context_id),
                "workflow_run_id": _str_or_none(workflow_run_id),
                "entity_kind": entity_kind,
                "entity_name": entity_name,
                "channel": channel,
                "application": application,
                "status": status,
                "limit": limit,
                "offset": offset,
            },
        )
        return [ExecutionRunCurrent(**r) for r in rows]

    async def count_runs(
        self,
        *,
        execution_context_id: Optional[UUID] = None,
        workflow_run_id: Optional[UUID] = None,
        entity_kind: Optional[str] = None,
        entity_name: Optional[str] = None,
        channel: Optional[str] = None,
        application: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """Total count for the given filter set (drives UI pagination)."""
        row = await self.db.fetch_one(
            "count_runs_current",
            {
                "execution_context_id": _str_or_none(execution_context_id),
                "workflow_run_id": _str_or_none(workflow_run_id),
                "entity_kind": entity_kind,
                "entity_name": entity_name,
                "channel": channel,
                "application": application,
                "status": status,
            },
        )
        return row["total"] if row else 0

    async def get_run_lifecycle(self, run_id: UUID) -> list[RunLifecycleEvent]:
        """Full event sequence for one run, in time order.

        Drives the run-detail UI's lifecycle drill-through. Combines
        execution_run_status (every state transition), the completion
        row if present, and the error row if present, into one timeline.
        """
        rows = await self.db.fetch_all("get_run_lifecycle", {"run_id": str(run_id)})
        return [RunLifecycleEvent(**r) for r in rows]

    async def list_runs_for_workflow(self, workflow_run_id: UUID) -> list[ExecutionRunCurrent]:
        """Every run sharing this caller-supplied workflow_run_id correlation id.

        Drives the workflow-detail UI page (the "what happened during
        this multi-step app workflow" view).
        """
        rows = await self.db.fetch_all(
            "list_runs_for_workflow",
            {"workflow_run_id": str(workflow_run_id)},
        )
        return [ExecutionRunCurrent(**r) for r in rows]

    async def list_runs_for_execution_context(
        self, execution_context_id: UUID
    ) -> list[ExecutionRunCurrent]:
        """Every run for a business context (e.g. a submission).

        Drives the "View in Verity" deep-link from the consuming app.
        Returns runs across all workflow_run_ids registered against
        this execution context, in submission order.
        """
        rows = await self.db.fetch_all(
            "list_runs_for_execution_context",
            {"execution_context_id": str(execution_context_id)},
        )
        return [ExecutionRunCurrent(**r) for r in rows]

    async def get_run_result(self, run_id: UUID) -> Optional[dict[str, Any]]:
        """Return the decision_log row for a completed run, or None.

        For a run whose execution_run_completion exists with a
        decision_log_id, this fetches the full audit row and returns
        it as the run's "result envelope." Callers that want the
        canonical envelope shape (Phase G) will reshape this output;
        for now the raw decision_log dict is what's available.

        Returns None when:
          - the run doesn't exist
          - the run hasn't reached a terminal state
          - the run terminated without a decision_log_id (e.g. cancelled
            before any engine work)
        """
        run = await self.get_run(run_id)
        if not run:
            return None
        decision_id = run.completion_decision_log_id or run.error_decision_log_id
        if not decision_id:
            return None
        return await self.db.fetch_one(
            "get_decision_by_id",
            {"decision_id": str(decision_id)},
        )


def _str_or_none(value: Any) -> Optional[str]:
    return None if value is None else str(value)
