"""Lifecycle endpoints — promote, rollback, approvals.

Thin wrappers over `verity.lifecycle.*` and `verity.promote/rollback`.
The 7-state lifecycle model itself (draft → candidate → staging →
shadow → challenger → champion → deprecated) lives in the SDK; this
module just exposes the transitions to HTTP callers.
"""

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from psycopg.errors import Error as PsycopgError

from verity.models.lifecycle import EntityType


def _as_400(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def build_lifecycle_router(verity) -> APIRouter:
    router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])

    @router.post("/promote")
    async def promote(body: dict[str, Any]) -> dict:
        """Promote an entity version to the next lifecycle state.

        Body:
          entity_type (agent/task/prompt), entity_version_id,
          target_state (candidate/staging/shadow/challenger/champion/
          deprecated), approver_name, rationale, approver_role (optional),
          and any evidence_flags required by the gate
          (e.g. staging_tests_passed, ground_truth_passed, ...).

        Returns the approval_record row. Errors:
          - 400 for invalid transitions or missing gate evidence
          - 404 if the version_id does not exist
        """
        try:
            return await verity.promote(
                entity_type=body["entity_type"],
                entity_version_id=body["entity_version_id"],
                target_state=body["target_state"],
                approver_name=body["approver_name"],
                rationale=body["rationale"],
                approver_role=body.get("approver_role"),
                **{k: v for k, v in body.items() if k not in {
                    "entity_type", "entity_version_id", "target_state",
                    "approver_name", "rationale", "approver_role",
                }},
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required field: {exc.args[0]}",
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/rollback")
    async def rollback(body: dict[str, Any]) -> dict:
        """Rollback a champion version. The prior champion (if any)
        is re-promoted to champion; the current champion is marked
        deprecated.

        Body: entity_type, entity_version_id, approver_name, rationale.
        """
        try:
            return await verity.rollback(
                entity_type=body["entity_type"],
                entity_version_id=body["entity_version_id"],
                approver_name=body["approver_name"],
                rationale=body["rationale"],
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required field: {exc.args[0]}",
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.get("/approvals")
    async def list_approvals(
        entity_type: str = Query(..., description="agent / task / prompt"),
        entity_version_id: UUID = Query(..., description="The version's UUID"),
    ) -> list[dict]:
        """List every approval_record row for an entity version —
        the audit trail of its lifecycle transitions."""
        try:
            return await verity.lifecycle.list_approvals(
                entity_type=EntityType(entity_type),
                entity_version_id=entity_version_id,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    return router
