"""Runtime-side writes for the event-sourced run-tracking tables.

Mirrors the decisions reader/writer split: this module owns every
INSERT into execution_run / execution_run_status / execution_run_completion /
execution_run_error. The governance plane reads back via
verity.governance.runs.

Run state is event-sourced and never updated. Every state change is a
fresh INSERT. The execution_run_current view is the canonical "what's
the current state" surface; this writer never touches it.

Two callers:
  - The submit API endpoint (web/api/runs.py): POST /runs writes the
    initial execution_run + execution_run_status('submitted') rows in
    one transaction.
  - The worker (runtime/worker.py): claims runs, emits heartbeats,
    writes terminal completion / error rows.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID, uuid4

import psycopg

from verity.contracts.run import RunSubmission, RunSubmissionResponse
from verity.db.connection import Database


class RunsWriter:
    """Writes against the event-sourced run-tracking tables.

    Idempotency note: most methods INSERT on every call. The UNIQUE
    constraints on execution_run_completion and execution_run_error
    enforce one-terminal-row-per-run; duplicate completion attempts
    raise psycopg.errors.UniqueViolation, which callers should treat
    as 'already terminal' (no-op).
    """

    def __init__(self, db: Database):
        self.db = db

    # ── Submission ──────────────────────────────────────────────

    async def submit(
        self,
        *,
        request: RunSubmission,
        entity_version_id: UUID,
    ) -> RunSubmissionResponse:
        """Insert the run + initial 'submitted' status row.

        Caller has resolved entity_name → entity_version_id (typically
        by looking up the entity's champion or named version under the
        given channel). This method writes both rows in one transaction
        so a worker can never see an execution_run without a matching
        first status event.
        """
        run_id = uuid4()
        # Use a single connection for the two inserts so they share a
        # transaction. The Database wrapper auto-commits on each call,
        # which is wrong here — we open a connection directly.
        async with self.db._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    self.db._get_sql("insert_execution_run"),
                    {
                        "id": str(run_id),
                        "entity_kind": request.entity_kind,
                        "entity_version_id": str(entity_version_id),
                        "entity_name": request.entity_name,
                        "channel": request.channel,
                        "input_json": _to_json(request.input) if request.input else None,
                        "execution_context_id": _str_or_none(request.execution_context_id),
                        "workflow_run_id": _str_or_none(request.workflow_run_id),
                        "parent_decision_id": _str_or_none(request.parent_decision_id),
                        "application": request.application,
                        "mock_mode": request.mock_mode,
                        "write_mode": request.write_mode,
                        "enforce_output_schema": request.enforce_output_schema,
                        "submitted_by": request.submitted_by,
                    },
                )
                await conn.execute(
                    self.db._get_sql("insert_execution_run_status"),
                    {
                        "execution_run_id": str(run_id),
                        "status": "submitted",
                        "worker_id": None,
                        "notes": None,
                    },
                )
                # Read submitted_at back. The pool has dict_row as the
                # default row factory, so the cursor returns a dict.
                cur = await conn.execute(
                    "SELECT submitted_at FROM execution_run WHERE id = %s",
                    (str(run_id),),
                )
                row = await cur.fetchone()
                submitted_at = row["submitted_at"]
        return RunSubmissionResponse(run_id=run_id, submitted_at=submitted_at)

    # ── Worker lifecycle ────────────────────────────────────────

    async def claim_next(self, worker_id: str) -> Optional[dict[str, Any]]:
        """Atomically claim the next available run, or return None.

        Wraps the claim_next_execution_run SQL which is itself
        atomic (FOR UPDATE SKIP LOCKED + INSERT 'claimed' in one CTE
        statement). Returns the claimed execution_run row as a dict, or
        None if no work is available.
        """
        return await self.db.fetch_one(
            "claim_next_execution_run",
            {"worker_id": worker_id},
        )

    async def heartbeat(self, run_id: UUID, worker_id: str) -> None:
        """Insert a heartbeat status row. Called periodically by workers."""
        await self.db.execute_returning(
            "heartbeat_execution_run",
            {"execution_run_id": str(run_id), "worker_id": worker_id},
        )

    async def release(self, run_id: UUID, worker_id: str, notes: Optional[str] = None) -> None:
        """Insert a 'released' status row. Worker hands the run back."""
        await self.db.execute_returning(
            "release_execution_run",
            {
                "execution_run_id": str(run_id),
                "worker_id": worker_id,
                "notes": notes,
            },
        )

    async def complete(
        self,
        run_id: UUID,
        *,
        decision_log_id: Optional[UUID],
        duration_ms: Optional[int],
        worker_id: Optional[str],
        final_status: str = "complete",
    ) -> None:
        """Write the terminal-success row. UNIQUE on run_id.

        Raises psycopg.errors.UniqueViolation if a completion row
        already exists for this run — caller should treat as no-op.
        """
        await self.db.execute_returning(
            "insert_execution_run_completion",
            {
                "execution_run_id": str(run_id),
                "final_status": final_status,
                "decision_log_id": _str_or_none(decision_log_id),
                "duration_ms": duration_ms,
                "worker_id": worker_id,
            },
        )

    async def error(
        self,
        run_id: UUID,
        *,
        error_code: Optional[str],
        error_message: str,
        error_trace: Optional[str] = None,
        worker_id: Optional[str] = None,
        decision_log_id: Optional[UUID] = None,
    ) -> None:
        """Write the terminal-failure row."""
        await self.db.execute_returning(
            "insert_execution_run_error",
            {
                "execution_run_id": str(run_id),
                "error_code": error_code,
                "error_message": error_message,
                "error_trace": error_trace,
                "worker_id": worker_id,
                "decision_log_id": _str_or_none(decision_log_id),
            },
        )

    async def cancel(self, run_id: UUID, worker_id: Optional[str] = None) -> bool:
        """Insert a 'cancelled' completion row.

        Returns True if the cancel was accepted, False if the run is
        already terminal (UniqueViolation on the completion row, which
        means another row got there first).
        """
        try:
            await self.db.execute_returning(
                "cancel_execution_run",
                {"execution_run_id": str(run_id), "worker_id": worker_id},
            )
            return True
        except psycopg.errors.UniqueViolation:
            return False


def _str_or_none(value: Any) -> Optional[str]:
    """Cast UUIDs / similar to strings; preserve None."""
    return None if value is None else str(value)


def _to_json(value: Any) -> str:
    """Serialize Python value to JSON for JSONB columns."""
    import json
    return json.dumps(value, default=str)
