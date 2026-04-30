"""Usage & spend endpoints.

These read aggregations over model_invocation_log. With no invocations
recorded, every endpoint returns zero/empty — that's the smoke we
verify here. The query plumbing is what's under test.
"""

from __future__ import annotations


async def test_usage_totals_empty(client):
    r = await client.get("/api/v1/usage/totals")
    assert r.status_code == 200
    body = r.json()
    # Expected shape: dict with totals (cost, invocations, tokens).
    assert isinstance(body, dict)


async def test_usage_by_model_empty(client):
    r = await client.get("/api/v1/usage/by-model")
    assert r.status_code == 200
    assert r.json() == []


async def test_usage_by_agent_empty(client):
    r = await client.get("/api/v1/usage/by-agent")
    assert r.status_code == 200
    assert r.json() == []


async def test_usage_by_task_empty(client):
    r = await client.get("/api/v1/usage/by-task")
    assert r.status_code == 200
    assert r.json() == []


async def test_usage_by_application_empty(client):
    r = await client.get("/api/v1/usage/by-application")
    assert r.status_code == 200
    assert r.json() == []


async def test_usage_over_time_empty(client):
    r = await client.get("/api/v1/usage/over-time")
    assert r.status_code == 200
    # Daily time-series is a list (potentially empty).
    assert isinstance(r.json(), list)


async def test_usage_totals_with_window_params(client):
    """Pass from/to query params — endpoint should accept and parse."""
    r = await client.get(
        "/api/v1/usage/totals",
        params={"from": "2026-01-01T00:00:00", "to": "2026-12-31T23:59:59"},
    )
    assert r.status_code == 200
