"""Quota CRUD + on-demand checker.

Thin JSON wrappers over `verity.quotas.*`. The `POST /check` endpoint
triggers the checker across every enabled quota and returns a
summary (per-quota result + aggregate alert counts); admin-UI and
cron-style callers both use it.
"""

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from psycopg.errors import Error as PsycopgError


def _as_400(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def build_quotas_router(verity) -> APIRouter:
    router = APIRouter(prefix="/quotas", tags=["quotas"])

    # ── CRUD ────────────────────────────────────────────────

    @router.get("")
    async def list_quotas() -> list[dict]:
        return await verity.quotas.list_quotas()

    @router.post("")
    async def register_quota(body: dict[str, Any]) -> dict:
        """Register a new quota.

        Body:
          scope_type (application/agent/task/model)
          scope_id   (UUID of the scope entity; nullable for 'all applications' variants not implemented in V1)
          scope_name (display name — denormalized for list views)
          period     (daily/weekly/monthly)
          budget_usd (numeric)
          alert_threshold_pct (int 1-200, default 80)
          hard_stop  (bool, reserved for future)
          enabled    (bool, default true)
          notes      (string, optional)
        """
        try:
            return await verity.quotas.register_quota(
                scope_type=body["scope_type"],
                scope_id=body["scope_id"],
                scope_name=body["scope_name"],
                period=body["period"],
                budget_usd=float(body["budget_usd"]),
                alert_threshold_pct=int(body.get("alert_threshold_pct", 80)),
                hard_stop=bool(body.get("hard_stop", False)),
                enabled=bool(body.get("enabled", True)),
                notes=body.get("notes"),
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=422, detail=f"Missing required field: {exc.args[0]}",
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.get("/{quota_id}")
    async def get_quota(quota_id: UUID) -> dict:
        row = await verity.quotas.get_quota(quota_id)
        if not row:
            raise HTTPException(
                status_code=404, detail=f"Quota {quota_id} not found",
            )
        return row

    @router.patch("/{quota_id}")
    async def update_quota(quota_id: UUID, body: dict[str, Any]) -> dict:
        try:
            row = await verity.quotas.update_quota(quota_id, **body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)
        if not row:
            raise HTTPException(
                status_code=404, detail=f"Quota {quota_id} not found",
            )
        return row

    @router.delete("/{quota_id}")
    async def delete_quota(quota_id: UUID) -> dict:
        row = await verity.quotas.delete_quota(quota_id)
        if not row:
            raise HTTPException(
                status_code=404, detail=f"Quota {quota_id} not found",
            )
        return {"deleted_id": row["id"]}

    # ── Checker ─────────────────────────────────────────────

    @router.post("/check")
    async def run_all_checks() -> dict[str, Any]:
        """Run the checker across every enabled quota. Returns a
        summary: number of quotas checked, alerts fired/resolved,
        and per-quota detail."""
        return await verity.quotas.run_all_checks()

    @router.post("/{quota_id}/check")
    async def run_one_check(quota_id: UUID) -> dict[str, Any]:
        """Run the checker for a single quota."""
        try:
            return await verity.quotas.run_check(quota_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/{quota_id}/checks")
    async def list_checks(quota_id: UUID, limit: int = 20) -> list[dict]:
        return await verity.quotas.list_checks(quota_id, limit=limit)

    return router
