"""Usage + spend aggregation endpoints.

All six roll up `v_model_invocation_cost` — the view that joins
invocation rows to the price window containing their started_at —
so cost is always computed from point-in-time prices, never from
frozen columns.

Shared query shape
------------------
Every endpoint accepts:
    ?from=<iso date or datetime>   default: 7 days ago
    ?to=<iso date or datetime>     default: now
    ?apps=a,b,c                    default: no filter (all apps)

The date params coerce to UTC datetimes at the boundary so callers
can pass a plain date ('2026-04-23') and get the whole day covered.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query


def _parse_window(
    from_raw: Optional[str],
    to_raw: Optional[str],
) -> tuple[datetime, datetime]:
    """Parse the from/to query pair into a (from_ts, to_ts) datetime
    tuple. Defaults: last 7 days, ending now. Raises 400 on malformed
    input. Date-only inputs ('2026-04-23') are promoted to UTC midnight.
    """
    def _parse_one(raw: str, kind: str) -> datetime:
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"invalid {kind}: {raw!r} (expected ISO 8601)",
            ) from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    now = datetime.now(timezone.utc)
    from_ts = _parse_one(from_raw, "from") if from_raw else (now - timedelta(days=7))
    to_ts   = _parse_one(to_raw,   "to")   if to_raw   else now
    if from_ts >= to_ts:
        raise HTTPException(
            status_code=400, detail="`from` must be earlier than `to`",
        )
    return from_ts, to_ts


def _parse_apps(apps_raw: Optional[str]) -> list[str]:
    """?apps=a,b,c → ['a', 'b', 'c']; blank → []. Same shape the
    home dashboard uses for consistency."""
    if not apps_raw:
        return []
    return [s.strip() for s in apps_raw.split(",") if s.strip()]


def build_usage_router(verity) -> APIRouter:
    router = APIRouter(prefix="/usage", tags=["usage"])

    # Shared query-param declaration — kept terse at call sites by
    # hoisting the descriptions out into aliases.
    _FROM_Q = Query(None, alias="from", description="Start of window (ISO 8601). Default: 7 days ago.")
    _TO_Q   = Query(None,                description="End of window (ISO 8601). Default: now.")
    _APPS_Q = Query(None,                description="Comma-separated application names to filter by. Default: all.")

    @router.get("/totals")
    async def totals(
        from_: Optional[str] = _FROM_Q,
        to:    Optional[str] = _TO_Q,
        apps:  Optional[str] = _APPS_Q,
    ) -> dict[str, Any]:
        """Top-of-page summary — total cost, invocation count, and
        token totals (input, output, cache read/write) across the
        window."""
        from_ts, to_ts = _parse_window(from_, to)
        return await verity.models.usage_totals(
            from_ts=from_ts, to_ts=to_ts, app_names=_parse_apps(apps),
        )

    @router.get("/by-model")
    async def by_model(
        from_: Optional[str] = _FROM_Q,
        to:    Optional[str] = _TO_Q,
        apps:  Optional[str] = _APPS_Q,
    ) -> list[dict]:
        from_ts, to_ts = _parse_window(from_, to)
        return await verity.models.usage_by_model(
            from_ts=from_ts, to_ts=to_ts, app_names=_parse_apps(apps),
        )

    @router.get("/by-agent")
    async def by_agent(
        from_: Optional[str] = _FROM_Q,
        to:    Optional[str] = _TO_Q,
        apps:  Optional[str] = _APPS_Q,
    ) -> list[dict]:
        from_ts, to_ts = _parse_window(from_, to)
        return await verity.models.usage_by_agent(
            from_ts=from_ts, to_ts=to_ts, app_names=_parse_apps(apps),
        )

    @router.get("/by-task")
    async def by_task(
        from_: Optional[str] = _FROM_Q,
        to:    Optional[str] = _TO_Q,
        apps:  Optional[str] = _APPS_Q,
    ) -> list[dict]:
        from_ts, to_ts = _parse_window(from_, to)
        return await verity.models.usage_by_task(
            from_ts=from_ts, to_ts=to_ts, app_names=_parse_apps(apps),
        )

    @router.get("/by-application")
    async def by_application(
        from_: Optional[str] = _FROM_Q,
        to:    Optional[str] = _TO_Q,
        apps:  Optional[str] = _APPS_Q,
    ) -> list[dict]:
        from_ts, to_ts = _parse_window(from_, to)
        return await verity.models.usage_by_application(
            from_ts=from_ts, to_ts=to_ts, app_names=_parse_apps(apps),
        )

    @router.get("/over-time")
    async def over_time(
        from_: Optional[str] = _FROM_Q,
        to:    Optional[str] = _TO_Q,
        apps:  Optional[str] = _APPS_Q,
    ) -> list[dict]:
        """Daily time-series. One row per UTC day in the window."""
        from_ts, to_ts = _parse_window(from_, to)
        return await verity.models.usage_over_time_daily(
            from_ts=from_ts, to_ts=to_ts, app_names=_parse_apps(apps),
        )

    return router
