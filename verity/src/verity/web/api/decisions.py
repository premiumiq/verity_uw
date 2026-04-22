"""Decision-log and audit-trail endpoints.

Read-mostly surface over `verity.decisions.*`. Covers four distinct
lookup paths the compliance/audit notebooks need:

  - list_decisions       — paginated, most-recent-first catalog view
  - get_decision         — full DecisionLogDetail by id (includes
                            message_history, tool_calls, risk_factors)
  - get_audit_trail      — all decisions in an execution_context
                            (can span multiple pipeline runs)
  - get_audit_trail_by_run — all decisions from one pipeline run

Plus one write: POST /overrides to record a human override.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from psycopg.errors import Error as PsycopgError

from verity.models.decision import (
    AuditTrailEntry, DecisionLog, DecisionLogDetail, OverrideLogCreate,
)


def _as_400(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def build_decisions_router(verity) -> APIRouter:
    router = APIRouter(tags=["decisions"])

    @router.get("/decisions", response_model=list[DecisionLog])
    async def list_decisions(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> list[DecisionLog]:
        """Most recent decisions first. Caps at limit=500 per page."""
        return await verity.list_decisions(limit=limit, offset=offset)

    @router.get("/decisions/{decision_id}", response_model=DecisionLogDetail)
    async def get_decision(decision_id: UUID) -> DecisionLogDetail:
        """Full detail for one decision — includes message_history,
        tool_calls_made, risk_factors, and the inference_config
        snapshot captured at run time."""
        decision = await verity.get_decision(decision_id)
        if not decision:
            raise HTTPException(
                status_code=404, detail=f"Decision {decision_id} not found",
            )
        return decision

    @router.get(
        "/audit-trail/context/{execution_context_id}",
        response_model=list[AuditTrailEntry],
    )
    async def get_audit_trail_by_context(
        execution_context_id: UUID,
    ) -> list[AuditTrailEntry]:
        """All decisions tied to a business-level execution_context.
        A context can span multiple pipeline runs (e.g. an initial
        run plus a re-run), so this is the right view for 'show me
        everything Verity did for submission X'."""
        return await verity.get_audit_trail(execution_context_id)

    @router.get(
        "/audit-trail/run/{pipeline_run_id}",
        response_model=list[AuditTrailEntry],
    )
    async def get_audit_trail_by_run(
        pipeline_run_id: UUID,
    ) -> list[AuditTrailEntry]:
        """All decisions from one pipeline_run — the preferred query
        for replaying a single execution, since pipeline_run_id is
        unique per run (no cross-application collision risk)."""
        return await verity.get_audit_trail_by_run(pipeline_run_id)

    @router.post("/overrides")
    async def record_override(override: OverrideLogCreate) -> dict:
        """Record a human override of an AI decision. The override
        links to decision_log_id (which in turn links to an
        execution_context), so no separate business keys are
        needed on the override row itself."""
        try:
            return await verity.record_override(override)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    return router
