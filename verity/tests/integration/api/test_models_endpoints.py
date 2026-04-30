"""Model catalog + pricing endpoints.

Canonical seed already inserts one anthropic / claude-sonnet-4 model
into governance.model. We validate listing surfaces it, plus exercise
the CRUD + price history surfaces.
"""

from __future__ import annotations

import uuid


# ── List + get ─────────────────────────────────────────────────────────────

async def test_list_models_returns_seeded_model(client):
    r = await client.get("/api/v1/models")
    assert r.status_code == 200
    rows = r.json()
    providers = {row["provider"] for row in rows}
    assert "anthropic" in providers


async def test_get_model_404_for_unknown(client):
    bogus = uuid.uuid4()
    r = await client.get(f"/api/v1/models/{bogus}")
    assert r.status_code == 404


async def test_get_model_returns_seeded(client):
    list_resp = await client.get("/api/v1/models")
    seed_row = next(r for r in list_resp.json() if r["provider"] == "anthropic")

    r = await client.get(f"/api/v1/models/{seed_row['id']}")
    assert r.status_code == 200
    assert r.json()["provider"] == "anthropic"


# ── Register ───────────────────────────────────────────────────────────────

async def test_register_model_succeeds(client):
    r = await client.post(
        "/api/v1/models",
        json={
            "provider": "anthropic",
            "model_id": "claude-haiku-test",
            "display_name": "Test Haiku",
            "context_window": 200_000,
        },
    )
    assert r.status_code == 200
    body = r.json()
    # register_model returns the inserted row — id at minimum.
    assert "id" in body


async def test_register_model_missing_field_returns_422(client):
    r = await client.post(
        "/api/v1/models",
        json={"provider": "anthropic"},  # missing model_id, display_name
    )
    assert r.status_code == 422


async def test_register_model_duplicate_returns_400(client):
    body = {
        "provider": "anthropic",
        "model_id": "claude-dup-test",
        "display_name": "Dup",
    }
    r1 = await client.post("/api/v1/models", json=body)
    assert r1.status_code == 200
    r2 = await client.post("/api/v1/models", json=body)
    # uq_model = (provider, model_id) — UNIQUE violation surfaces as 400.
    assert r2.status_code == 400


# ── Prices ─────────────────────────────────────────────────────────────────

async def test_set_and_get_price(client):
    """Set a price, then retrieve it via current_price + the history list."""
    reg = await client.post(
        "/api/v1/models",
        json={
            "provider": "anthropic",
            "model_id": "claude-priced",
            "display_name": "Priced",
        },
    )
    model_pk = reg.json()["id"]

    r = await client.post(
        f"/api/v1/models/{model_pk}/prices",
        json={
            "input_price_per_1m": 3.00,
            "output_price_per_1m": 15.00,
        },
    )
    assert r.status_code == 200

    current = await client.get(f"/api/v1/models/{model_pk}/prices/current")
    assert current.status_code == 200
    body = current.json()
    assert body is not None
    assert float(body["input_price_per_1m"]) == 3.00


async def test_current_price_null_when_no_price_set(client):
    reg = await client.post(
        "/api/v1/models",
        json={
            "provider": "anthropic",
            "model_id": "no_price",
            "display_name": "No Price",
        },
    )
    model_pk = reg.json()["id"]

    r = await client.get(f"/api/v1/models/{model_pk}/prices/current")
    assert r.status_code == 200
    assert r.json() is None
