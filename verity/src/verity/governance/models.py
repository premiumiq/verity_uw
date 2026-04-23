"""Model catalog + pricing + invocation log.

One model row per (provider, model_id). Each model has a
SCD-2-style price history in `model_price` — to change a price you
close the current row (set valid_to) and insert a new one. Cost is
never frozen into the invocation log; the `v_model_invocation_cost`
view joins each invocation to the price row whose window contains
its `started_at`, so historical reports stay stable when prices
change but a point-in-time change to a past price is still
possible by editing the price table.

`log_invocation` is called by the engine after each agent/task
decision — one invocation row per decision, with tokens summed
across all LLM turns inside that decision and the per-turn detail
kept in `per_turn_metadata` (JSONB) for drill-through.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from verity.db.connection import Database


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Models:
    """Model catalog, price history, and invocation logging."""

    def __init__(self, db: Database):
        self.db = db

    # ── MODEL CATALOG ─────────────────────────────────────────

    async def register_model(
        self,
        provider: str,
        model_id: str,
        display_name: str,
        *,
        modality: str = "chat",
        context_window: Optional[int] = None,
        status: str = "active",
        description: Optional[str] = None,
    ) -> dict:
        """Register a new model. (provider, model_id) is unique."""
        return await self.db.execute_returning("insert_model", {
            "provider": provider,
            "model_id": model_id,
            "display_name": display_name,
            "modality": modality,
            "context_window": context_window,
            "status": status,
            "description": description,
        })

    async def list_models(self) -> list[dict]:
        """All models with their currently-active prices joined in."""
        return await self.db.fetch_all("list_models")

    async def get_model(self, model_pk: UUID) -> Optional[dict]:
        return await self.db.fetch_one(
            "get_model_by_id", {"model_id": str(model_pk)},
        )

    async def get_model_by_name(
        self, provider: str, model_id: str,
    ) -> Optional[dict]:
        """Canonical lookup used to resolve a provider's model string
        (e.g. 'claude-sonnet-4-5') back to a model catalog row. This
        is the hot path for the engine's invocation-log write."""
        return await self.db.fetch_one(
            "get_model_by_provider_and_model_id",
            {"provider": provider, "model_id": model_id},
        )

    async def update_model(
        self, model_pk: UUID, **fields,
    ) -> Optional[dict]:
        params = dict(fields)
        params["model_id"] = str(model_pk)
        for key in ("display_name", "modality", "context_window",
                    "status", "description"):
            params.setdefault(key, None)
        return await self.db.execute_returning("update_model", params)

    # ── PRICING ───────────────────────────────────────────────

    async def get_current_price(
        self, model_pk: UUID,
    ) -> Optional[dict]:
        """Currently-active price row for a model (valid_to IS NULL)."""
        return await self.db.fetch_one(
            "get_current_price_for_model", {"model_id": str(model_pk)},
        )

    async def list_prices(self, model_pk: UUID) -> list[dict]:
        """Full price history for a model, newest first."""
        return await self.db.fetch_all(
            "list_prices_for_model", {"model_id": str(model_pk)},
        )

    async def set_price(
        self,
        model_pk: UUID,
        input_price_per_1m: float,
        output_price_per_1m: float,
        *,
        cache_read_price_per_1m: Optional[float] = None,
        cache_write_price_per_1m: Optional[float] = None,
        currency: str = "USD",
        valid_from: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Set a new currently-active price.

        If a prior active row exists, its valid_to is set to the new
        row's valid_from so the timeline stays contiguous with no
        overlapping windows (enforced at the DB level by the
        uq_mp_active unique index).
        """
        start = valid_from or _utcnow()
        async with self.db.transaction() as tx:
            # Close any currently-active row first.
            await tx.execute(
                "close_current_price",
                {"model_id": str(model_pk), "valid_to": start},
            )
            return await tx.execute_returning("insert_price", {
                "model_id": str(model_pk),
                "input_price_per_1m":  input_price_per_1m,
                "output_price_per_1m": output_price_per_1m,
                "cache_read_price_per_1m":  cache_read_price_per_1m,
                "cache_write_price_per_1m": cache_write_price_per_1m,
                "currency": currency,
                "valid_from": start,
                "valid_to": None,
                "notes": notes,
            })

    # ── INVOCATION LOG ────────────────────────────────────────

    async def log_invocation(
        self,
        *,
        decision_log_id: UUID,
        model_id: UUID,
        provider: str,
        model_name: str,
        started_at: datetime,
        completed_at: datetime,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        api_call_count: int = 1,
        stop_reason: Optional[str] = None,
        status: str = "complete",
        error_message: Optional[str] = None,
        per_turn_metadata: Optional[list[dict]] = None,
    ) -> dict:
        """Write one invocation row tied to a decision.

        Tokens are the SUM across every API turn inside the decision's
        agentic loop. `per_turn_metadata` (optional) carries the per-
        turn breakdown for drill-through.

        `stop_reason` is the terminal reason from the provider
        (end_turn / max_tokens / stop_sequence / tool_use).
        """
        return await self.db.execute_returning("insert_model_invocation", {
            "decision_log_id": str(decision_log_id),
            "model_id": str(model_id),
            "provider": provider,
            "model_name": model_name,
            "started_at": started_at,
            "completed_at": completed_at,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "cache_creation_input_tokens": int(cache_creation_input_tokens or 0),
            "cache_read_input_tokens": int(cache_read_input_tokens or 0),
            "api_call_count": int(api_call_count or 1),
            "stop_reason": stop_reason,
            "status": status,
            "error_message": error_message,
            "per_turn_metadata": (
                json.dumps(per_turn_metadata) if per_turn_metadata else None
            ),
        })

    async def get_invocation_by_decision(
        self, decision_log_id: UUID,
    ) -> Optional[dict]:
        """Cost-aware invocation view for a decision (joined to the
        price row whose window contains its started_at)."""
        return await self.db.fetch_one(
            "get_invocation_by_decision",
            {"decision_log_id": str(decision_log_id)},
        )

    # ── USAGE AGGREGATIONS (for /admin/usage + REST) ──────────
    # Each takes (from_ts, to_ts) and an optional app_names list.
    # Empty app_names means "global scope" (no filter).

    async def usage_totals(
        self, from_ts: datetime, to_ts: datetime,
        app_names: Optional[list[str]] = None,
    ) -> dict:
        return (await self.db.fetch_one("usage_totals", {
            "from_ts": from_ts, "to_ts": to_ts,
            "app_names": list(app_names or []),
        })) or {}

    async def usage_by_model(
        self, from_ts: datetime, to_ts: datetime,
        app_names: Optional[list[str]] = None,
    ) -> list[dict]:
        return await self.db.fetch_all("usage_by_model", {
            "from_ts": from_ts, "to_ts": to_ts,
            "app_names": list(app_names or []),
        })

    async def usage_by_agent(
        self, from_ts: datetime, to_ts: datetime,
        app_names: Optional[list[str]] = None,
    ) -> list[dict]:
        return await self.db.fetch_all("usage_by_agent", {
            "from_ts": from_ts, "to_ts": to_ts,
            "app_names": list(app_names or []),
        })

    async def usage_by_task(
        self, from_ts: datetime, to_ts: datetime,
        app_names: Optional[list[str]] = None,
    ) -> list[dict]:
        return await self.db.fetch_all("usage_by_task", {
            "from_ts": from_ts, "to_ts": to_ts,
            "app_names": list(app_names or []),
        })

    async def usage_by_application(
        self, from_ts: datetime, to_ts: datetime,
        app_names: Optional[list[str]] = None,
    ) -> list[dict]:
        return await self.db.fetch_all("usage_by_application", {
            "from_ts": from_ts, "to_ts": to_ts,
            "app_names": list(app_names or []),
        })

    async def usage_over_time_daily(
        self, from_ts: datetime, to_ts: datetime,
        app_names: Optional[list[str]] = None,
    ) -> list[dict]:
        return await self.db.fetch_all("usage_over_time_daily", {
            "from_ts": from_ts, "to_ts": to_ts,
            "app_names": list(app_names or []),
        })

    # ── Backfill helper (one-shot after seeding the catalog) ──

    async def backfill_inference_config_model_id(self) -> list[dict]:
        """Resolve inference_config.model_id for any row that has a
        text model_name matching a registered model.model_id but no
        FK set. Returns the rows it updated."""
        return await self.db.fetch_all("backfill_inference_config_model_id")


__all__ = ["Models"]
