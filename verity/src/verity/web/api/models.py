"""Model catalog + pricing REST endpoints.

Thin JSON wrappers over `verity.models.*`. Covers the catalog CRUD
and the SCD-2 price history — invocation-log writes happen inside the
engine, not from HTTP callers. The usage aggregations live in the
sibling usage.py module since they read model_invocation_log across
tables rather than touching `model` / `model_price` directly.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from psycopg.errors import Error as PsycopgError


def _as_400(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def build_models_router(verity) -> APIRouter:
    router = APIRouter(prefix="/models", tags=["models"])

    # ── Model catalog ────────────────────────────────────────

    @router.get("")
    async def list_models() -> list[dict]:
        """Every registered model, with its currently-active price
        row joined in (null if no price is set)."""
        return await verity.models.list_models()

    @router.post("")
    async def register_model(body: dict[str, Any]) -> dict:
        """Register a new model.

        Body: provider, model_id, display_name, modality (default 'chat'),
        context_window (int, optional), status (default 'active'),
        description (optional).
        """
        try:
            return await verity.models.register_model(
                provider=body["provider"],
                model_id=body["model_id"],
                display_name=body["display_name"],
                modality=body.get("modality", "chat"),
                context_window=body.get("context_window"),
                status=body.get("status", "active"),
                description=body.get("description"),
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=422, detail=f"Missing required field: {exc.args[0]}",
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.get("/{model_pk}")
    async def get_model(model_pk: UUID) -> dict:
        row = await verity.models.get_model(model_pk)
        if not row:
            raise HTTPException(status_code=404, detail=f"Model {model_pk} not found")
        return row

    @router.patch("/{model_pk}")
    async def update_model(model_pk: UUID, body: dict[str, Any]) -> dict:
        """Update mutable metadata (display_name, modality,
        context_window, status, description). Price changes use the
        separate /prices endpoint — mutating the catalog row isn't
        how you reprice."""
        try:
            row = await verity.models.update_model(model_pk, **body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)
        if not row:
            raise HTTPException(status_code=404, detail=f"Model {model_pk} not found")
        return row

    # ── Price history (SCD-2) ────────────────────────────────

    @router.get("/{model_pk}/prices")
    async def list_prices(model_pk: UUID) -> list[dict]:
        """Full price history for a model, newest first. The row
        whose valid_to is NULL is the currently-active price."""
        return await verity.models.list_prices(model_pk)

    @router.get("/{model_pk}/prices/current")
    async def current_price(model_pk: UUID) -> Optional[dict]:
        """The currently-active price row, or null if no price has
        ever been set for this model."""
        return await verity.models.get_current_price(model_pk)

    @router.post("/{model_pk}/prices")
    async def set_price(model_pk: UUID, body: dict[str, Any]) -> dict:
        """Set a new currently-active price. Closes the prior active
        row (sets its valid_to to the new row's valid_from) in a
        single transaction.

        Body: input_price_per_1m, output_price_per_1m (required).
        Optional: cache_read_price_per_1m, cache_write_price_per_1m,
        currency ('USD'), valid_from (ISO 8601; defaults to now),
        notes.
        """
        try:
            valid_from_raw = body.get("valid_from")
            valid_from = (
                datetime.fromisoformat(valid_from_raw) if valid_from_raw else None
            )
            return await verity.models.set_price(
                model_pk=model_pk,
                input_price_per_1m=body["input_price_per_1m"],
                output_price_per_1m=body["output_price_per_1m"],
                cache_read_price_per_1m=body.get("cache_read_price_per_1m"),
                cache_write_price_per_1m=body.get("cache_write_price_per_1m"),
                currency=body.get("currency", "USD"),
                valid_from=valid_from,
                notes=body.get("notes"),
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=422, detail=f"Missing required field: {exc.args[0]}",
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    return router
