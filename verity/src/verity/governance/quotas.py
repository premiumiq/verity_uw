"""Soft budget quotas + on-demand checker.

A quota pairs a scope (application / agent / task / model) with a
period (daily / weekly / monthly) and a USD budget. The checker
computes period-scoped spend via `v_model_invocation_cost` (the
same cost view the Usage dashboard uses), compares against the
budget, and writes a `quota_check` row recording the outcome.

V1 is SOFT — the engine never refuses calls based on quota state.
The `hard_stop` column on `quota` is reserved for a later commit.

Breaches don't write to the shared `incident` table because the
entity_type enum (agent/task/prompt/pipeline/tool) doesn't fit
application/model scopes. quota_check is self-contained: the
admin UI counts "active breaches" as the most-recent check per
quota with alert_fired=true and resolved_at IS NULL.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from verity.db.connection import Database


# Canonical period → start-of-window computation. All times UTC.
def _period_window(period: str, now: datetime) -> tuple[datetime, datetime]:
    """Return (period_start, period_end=now) for the active period."""
    if period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        # ISO week starts Monday. weekday(): Mon=0.
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = midnight - timedelta(days=midnight.weekday())
    elif period == "monthly":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Unknown period {period!r} (expected daily/weekly/monthly)")
    return start, now


# Scope-type → spend-query name mapping. The checker picks one per quota.
_SPEND_QUERY_BY_SCOPE = {
    "application": "quota_spend_by_application",
    "agent":       "quota_spend_by_agent",
    "task":        "quota_spend_by_task",
    "model":       "quota_spend_by_model",
}


class Quotas:
    """Quota CRUD + on-demand checker."""

    def __init__(self, db: Database):
        self.db = db

    # ── CRUD ─────────────────────────────────────────────────

    async def register_quota(
        self,
        scope_type: str,
        scope_id: UUID,
        scope_name: str,
        period: str,
        budget_usd: float,
        *,
        alert_threshold_pct: int = 80,
        hard_stop: bool = False,
        enabled: bool = True,
        notes: Optional[str] = None,
    ) -> dict:
        return await self.db.execute_returning("insert_quota", {
            "scope_type": scope_type,
            "scope_id":   str(scope_id) if scope_id else None,
            "scope_name": scope_name,
            "period":     period,
            "budget_usd": budget_usd,
            "alert_threshold_pct": int(alert_threshold_pct),
            "hard_stop":  bool(hard_stop),
            "enabled":    bool(enabled),
            "notes":      notes,
        })

    async def list_quotas(self) -> list[dict]:
        return await self.db.fetch_all("list_quotas")

    async def get_quota(self, quota_id: UUID) -> Optional[dict]:
        return await self.db.fetch_one("get_quota_by_id", {"id": str(quota_id)})

    async def update_quota(self, quota_id: UUID, **fields) -> Optional[dict]:
        params = {
            "id": str(quota_id),
            "period":              fields.get("period"),
            "budget_usd":          fields.get("budget_usd"),
            "alert_threshold_pct": fields.get("alert_threshold_pct"),
            "hard_stop":           fields.get("hard_stop"),
            "enabled":             fields.get("enabled"),
            "notes":               fields.get("notes"),
        }
        return await self.db.execute_returning("update_quota", params)

    async def delete_quota(self, quota_id: UUID) -> Optional[dict]:
        return await self.db.execute_returning("delete_quota", {"id": str(quota_id)})

    # ── Check history ────────────────────────────────────────

    async def list_checks(self, quota_id: UUID, limit: int = 20) -> list[dict]:
        return await self.db.fetch_all(
            "list_checks_for_quota",
            {"quota_id": str(quota_id), "limit": int(limit)},
        )

    async def latest_checks(self) -> list[dict]:
        """One row per quota: its most recent check, or no row if never checked."""
        return await self.db.fetch_all("latest_check_per_quota")

    async def count_active_breaches(self) -> int:
        row = await self.db.fetch_one("count_active_breaches")
        return int((row or {}).get("active_breaches") or 0)

    # ── The checker ──────────────────────────────────────────

    async def run_check(self, quota_id: UUID) -> dict:
        """Compute current-period spend for one quota and record a
        quota_check row. Returns the inserted check dict.
        """
        quota = await self.get_quota(quota_id)
        if not quota:
            raise ValueError(f"Quota {quota_id} not found")
        return await self._check_one(quota)

    async def run_all_checks(self) -> dict[str, Any]:
        """Run the checker across every enabled quota. Returns a
        summary: per-quota check + aggregate counts."""
        quotas = await self.list_quotas()
        results: list[dict] = []
        alert_count = 0
        resolved_count = 0
        for q in quotas:
            if not q.get("enabled"):
                continue
            try:
                check = await self._check_one(q)
            except Exception as exc:
                results.append({
                    "quota_id": q["id"],
                    "scope_name": q["scope_name"],
                    "error": str(exc),
                })
                continue
            results.append({
                "quota_id": q["id"],
                "scope_type": q["scope_type"],
                "scope_name": q["scope_name"],
                "period": q["period"],
                "spend_usd": float(check["spend_usd"]),
                "budget_usd": float(check["budget_usd"]),
                "spend_pct": check["spend_pct"],
                "alert_fired": check["alert_fired"],
                "alert_level": check.get("alert_level"),
                "resolved": check.get("resolved_previous", False),
            })
            if check["alert_fired"]:
                alert_count += 1
            if check.get("resolved_previous"):
                resolved_count += 1

        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "quotas_checked": len(results),
            "alerts_fired": alert_count,
            "alerts_resolved": resolved_count,
            "results": results,
        }

    async def _check_one(self, quota: dict) -> dict:
        """Internal: compute + persist one check for one quota."""
        scope_type = quota["scope_type"]
        query_name = _SPEND_QUERY_BY_SCOPE.get(scope_type)
        if query_name is None:
            raise ValueError(f"Unsupported quota scope_type {scope_type!r}")

        now = datetime.now(timezone.utc)
        period_start, period_end = _period_window(quota["period"], now)

        spend_params = {
            "from_ts": period_start,
            "to_ts": period_end,
            "scope_id": str(quota["scope_id"]) if quota.get("scope_id") else None,
            "scope_name": quota.get("scope_name"),
        }
        spend_row = await self.db.fetch_one(query_name, spend_params) or {}
        spend_usd = float(spend_row.get("total_cost_usd") or 0)
        budget_usd = float(quota["budget_usd"] or 0)

        # Integer spend_pct makes UI comparisons and templates easy;
        # avoids Decimal floats in the table cells.
        spend_pct = int(round((spend_usd / budget_usd) * 100)) if budget_usd > 0 else 0

        alert_threshold = int(quota["alert_threshold_pct"] or 80)
        if spend_pct >= 100:
            alert_level = "breach"
            alert_fired = True
        elif spend_pct >= alert_threshold:
            alert_level = "warning"
            alert_fired = True
        else:
            alert_level = None
            alert_fired = False

        note = None
        if alert_fired:
            note = f"Spend {spend_pct}% of ${budget_usd:.4f} {quota['period']} budget (${spend_usd:.4f})"

        # If this check is CLEAR and the previous active check was a
        # breach, mark that prior breach resolved so the home-dashboard
        # counter decrements naturally.
        resolved_previous = False
        if not alert_fired:
            resolved = await self.db.execute_returning(
                "resolve_active_check_for_quota",
                {"quota_id": quota["id"]},
            )
            resolved_previous = resolved is not None

        row = await self.db.execute_returning("insert_quota_check", {
            "quota_id": quota["id"],
            "period_start": period_start,
            "period_end": period_end,
            "spend_usd": spend_usd,
            "budget_usd": budget_usd,
            "spend_pct": spend_pct,
            "alert_fired": alert_fired,
            "alert_level": alert_level,
            "note": note,
        }) or {}

        return {
            **row,
            "quota_id": quota["id"],
            "spend_usd": spend_usd,
            "budget_usd": budget_usd,
            "spend_pct": spend_pct,
            "alert_fired": alert_fired,
            "alert_level": alert_level,
            "resolved_previous": resolved_previous,
        }


__all__ = ["Quotas"]
