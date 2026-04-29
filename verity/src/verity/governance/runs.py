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

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from verity.contracts.envelope import ExecutionEnvelope
from verity.db.connection import Database
from verity.governance.envelope_builder import build_envelope
from verity.models.run import (
    ExecutionRunCurrent,
    RunLifecycleEvent,
)


class RunsReader:
    """Query the run-tracking tables for current state and history."""

    # Universe of channel values, mirroring the deployment_channel enum
    # defined in db/schema.sql. Hardcoded rather than queried because the
    # set is fixed by the schema and adding a value requires a migration
    # anyway — paying for a SELECT DISTINCT scan to recover values that
    # are already known at compile time would be wasteful.
    DEPLOYMENT_CHANNELS: tuple[str, ...] = (
        "development", "staging", "shadow", "evaluation", "production",
    )

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
        entity_name_contains: Optional[str] = None,
        channel: Optional[str] = None,
        application: Optional[str] = None,
        status: Optional[str] = None,
        submitted_after: Optional[datetime] = None,
        submitted_before: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExecutionRunCurrent]:
        """List runs with the supplied filters. Pass None to disable a filter.

        entity_name vs entity_name_contains:
          - entity_name: exact match (used by SDK / REST deep-links).
          - entity_name_contains: case-insensitive substring (used by the
            UI free-text search box).
        submitted_after / submitted_before form an inclusive-lower /
        exclusive-upper window on submitted_at.
        """
        rows = await self.db.fetch_all(
            "list_runs_current",
            {
                "execution_context_id": _str_or_none(execution_context_id),
                "workflow_run_id": _str_or_none(workflow_run_id),
                "entity_kind": entity_kind,
                "entity_name": entity_name,
                "entity_name_contains": entity_name_contains,
                "channel": channel,
                "application": application,
                "status": status,
                "submitted_after": _iso_or_none(submitted_after),
                "submitted_before": _iso_or_none(submitted_before),
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
        entity_name_contains: Optional[str] = None,
        channel: Optional[str] = None,
        application: Optional[str] = None,
        status: Optional[str] = None,
        submitted_after: Optional[datetime] = None,
        submitted_before: Optional[datetime] = None,
    ) -> int:
        """Total count for the given filter set (drives UI pagination)."""
        row = await self.db.fetch_one(
            "count_runs_current",
            {
                "execution_context_id": _str_or_none(execution_context_id),
                "workflow_run_id": _str_or_none(workflow_run_id),
                "entity_kind": entity_kind,
                "entity_name": entity_name,
                "entity_name_contains": entity_name_contains,
                "channel": channel,
                "application": application,
                "status": status,
                "submitted_after": _iso_or_none(submitted_after),
                "submitted_before": _iso_or_none(submitted_before),
            },
        )
        return row["total"] if row else 0

    async def list_filter_applications(self) -> list[dict]:
        """Distinct (name, display_name) pairs for the Application filter
        dropdown on the Runs UI. Sourced from the application table when
        a row exists; falls back to the raw `application` string from
        execution_run otherwise. Sorted by display_name.
        """
        return await self.db.fetch_all("list_runs_filter_applications", {})

    async def list_filter_entity_names(self) -> list[dict]:
        """Every registered entity (task or agent) for the Runs UI Entity
        Name autocomplete. Returns dicts of {name, display_name, entity_kind}.

        Sourced from the catalog tables (task ∪ agent) rather than from
        DISTINCT entity_name on execution_run — both source tables are
        small and UNIQUE-indexed on name, so the cost stays O(catalog)
        regardless of run-history size.
        """
        return await self.db.fetch_all("list_runs_filter_entity_names", {})

    def list_filter_channels(self) -> list[str]:
        """The deployment_channel enum universe. No DB round-trip — the
        set is fixed by the schema (see db/schema.sql `deployment_channel`).
        """
        return list(self.DEPLOYMENT_CHANNELS)

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

    async def get_run_result(self, run_id: UUID) -> Optional[ExecutionEnvelope]:
        """Build the canonical ExecutionEnvelope for a terminal run.

        Combines the execution_run_current view row with the linked
        agent_decision_log row (if any) into the envelope shape every
        external consumer sees: REST `GET /runs/{id}/result`, the
        Runs UI, SDK callers polling on `verity.get_run_result`.

        Returns None when:
          - the run doesn't exist
          - the run hasn't reached a terminal state (callers should
            check `current_status` first or call wait_for_run)

        Runs that terminated without a decision_log_id (e.g. cancelled
        before claim) still produce an envelope — the audit-row-derived
        telemetry fields are simply absent.
        """
        run = await self.get_run(run_id)
        if not run:
            return None
        # Gate envelope construction on terminal-only states. The
        # builder enforces the same invariant; this just gives a clean
        # None at the API surface for in-flight runs instead of an
        # exception.
        if run.current_status.value not in ("complete", "cancelled", "failed"):
            return None
        decision: Optional[dict[str, Any]] = None
        decision_id = (
            run.completion_decision_log_id or run.error_decision_log_id
        )
        if decision_id:
            decision = await self.db.fetch_one(
                "get_decision_by_id",
                {"decision_id": str(decision_id)},
            )
        # version_label isn't on the execution_run_current view; one
        # extra lookup keeps the envelope informative for human-facing
        # UIs. Cheap — single-row query keyed on a UUID.
        version_label = await self._lookup_version_label(
            run.entity_kind, run.entity_version_id,
        )
        return build_envelope(run, decision, version_label=version_label)

    async def _lookup_version_label(
        self, entity_kind: str, entity_version_id: UUID,
    ) -> Optional[str]:
        """Resolve the SemVer label for a task or agent version. None on miss."""
        if entity_kind == "task":
            row = await self.db.fetch_one(
                "get_task_version_by_id", {"version_id": str(entity_version_id)},
            )
        elif entity_kind == "agent":
            row = await self.db.fetch_one(
                "get_agent_version_by_id", {"version_id": str(entity_version_id)},
            )
        else:
            return None
        if not row:
            return None
        return row.get("version_label")


def _str_or_none(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _iso_or_none(value: Optional[datetime]) -> Optional[str]:
    """Render a datetime as an ISO-8601 string for psycopg's ::timestamptz
    cast in SQL. Returning a string keeps the disable-via-NULL pattern
    consistent across all filter params.
    """
    return None if value is None else value.isoformat()
