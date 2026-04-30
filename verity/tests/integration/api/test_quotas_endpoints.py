"""Quota CRUD + on-demand checker endpoints."""

from __future__ import annotations

import uuid


def _quota_body(scope_name: str, **overrides) -> dict:
    base = {
        "scope_type": "application",
        "scope_id": str(uuid.uuid4()),
        "scope_name": scope_name,
        "period": "daily",
        "budget_usd": 10.0,
    }
    base.update(overrides)
    return base


# ── List + register ────────────────────────────────────────────────────────

async def test_list_quotas_empty(client):
    r = await client.get("/api/v1/quotas")
    assert r.status_code == 200
    assert r.json() == []


async def test_register_quota_succeeds(client):
    r = await client.post("/api/v1/quotas", json=_quota_body("ai_ops"))
    assert r.status_code == 200, r.text
    assert "id" in r.json()


async def test_register_quota_missing_field_returns_422(client):
    r = await client.post("/api/v1/quotas", json={"scope_type": "application"})
    assert r.status_code == 422


# ── Get + 404 ──────────────────────────────────────────────────────────────

async def test_get_quota_404_for_unknown(client):
    r = await client.get(f"/api/v1/quotas/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_get_quota_returns_registered(client):
    reg = await client.post("/api/v1/quotas", json=_quota_body("for_get"))
    qid = reg.json()["id"]
    r = await client.get(f"/api/v1/quotas/{qid}")
    assert r.status_code == 200
    assert r.json()["scope_name"] == "for_get"


# ── Patch + delete ─────────────────────────────────────────────────────────

async def test_delete_quota_succeeds(client):
    reg = await client.post("/api/v1/quotas", json=_quota_body("to_delete"))
    qid = reg.json()["id"]

    r = await client.delete(f"/api/v1/quotas/{qid}")
    assert r.status_code == 200
    assert r.json()["deleted_id"] == qid

    # Now 404 on subsequent get.
    g = await client.get(f"/api/v1/quotas/{qid}")
    assert g.status_code == 404


async def test_delete_unknown_quota_404(client):
    r = await client.delete(f"/api/v1/quotas/{uuid.uuid4()}")
    assert r.status_code == 404


# ── Checker ────────────────────────────────────────────────────────────────

async def test_run_all_checks_returns_summary(client):
    """Checker over all enabled quotas — works with zero quotas
    (returns a summary with zero counts)."""
    r = await client.post("/api/v1/quotas/check")
    assert r.status_code == 200
    body = r.json()
    # Summary shape: at minimum, a count or a list of results.
    assert isinstance(body, dict)
