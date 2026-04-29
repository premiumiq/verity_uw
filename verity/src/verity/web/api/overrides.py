"""HITL override REST endpoints.

Per-field human override of an AI-produced value, anchored to
the Verity decision that produced the value being corrected.

Endpoints:
  POST /api/v1/runs/{decision_log_id}/overrides
        Persist a per-field override anchored to a Verity
        decision row, with parallel business identification
        (application / entity_type / entity_reference / fact_type)
        so governance rollups can group by either axis.

The same operation is callable via the in-process SDK as
`Verity.record_hitl_override(...)`. This REST surface is for
external (cross-process) callers; co-located applications
should prefer the SDK to skip the HTTP hop.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class HitlOverrideRequest(BaseModel):
    """Request body for POST /runs/{decision_log_id}/overrides.

    Fields mirror the columns on hitl_override one-for-one. JSONB
    columns (ai_value, hitl_value) accept any JSON-serialisable
    payload — the SDK handles the JSON encoding.
    """
    output_path:      str          = Field(..., description="JSONPath into the run's output_json")
    ai_value:         Optional[Any] = Field(None,  description="Value the AI produced (or null)")
    ai_found:         bool         = Field(...,    description="True iff the AI looked AND produced a value")
    hitl_value:       Any          = Field(...,    description="Human-corrected value")
    application:      str          = Field(...,    description="Caller app id, e.g. 'uw_demo'")
    entity_type:      str          = Field(...,    description="Business entity kind, e.g. 'submission'")
    entity_reference: str          = Field(...,    description="Entity primary-key value as string")
    fact_type:        str          = Field(...,    description="Field name in the business model")
    created_by:       str          = Field(...,    description="Actor name")
    reason:           Optional[str] = Field(None,  description="Optional rationale")


class HitlOverrideResponse(BaseModel):
    id:         UUID
    created_at: str


def build_overrides_router(verity) -> APIRouter:
    """Build the /runs/{id}/overrides router. `verity` is the
    shared in-process SDK client from main.py."""
    router = APIRouter(tags=["overrides"])

    @router.post(
        "/runs/{decision_log_id}/overrides",
        response_model=HitlOverrideResponse,
        status_code=201,
    )
    async def post_override(
        decision_log_id: UUID,
        body: HitlOverrideRequest,
    ):
        """Record a per-field human override for a Verity run.

        404 if the decision_log row doesn't exist; otherwise the
        override row is persisted and its id + created_at returned.
        """
        # Confirm the run exists before insert. Avoids surfacing
        # an FK violation as a 500.
        existing = await verity.db.fetch_one(
            "get_decision_output",
            {"decision_log_id": str(decision_log_id)},
        )
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail=f"decision_log_id {decision_log_id} not found",
            )

        row = await verity.record_hitl_override(
            decision_log_id  = decision_log_id,
            output_path      = body.output_path,
            ai_value         = body.ai_value,
            ai_found         = body.ai_found,
            hitl_value       = body.hitl_value,
            application      = body.application,
            entity_type      = body.entity_type,
            entity_reference = body.entity_reference,
            fact_type        = body.fact_type,
            created_by       = body.created_by,
            reason           = body.reason,
        )

        return HitlOverrideResponse(
            id         = row["id"],
            created_at = row["created_at"].isoformat(),
        )

    return router
