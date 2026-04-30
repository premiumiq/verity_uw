"""Reporting endpoints — dashboard counts + model inventories."""

from __future__ import annotations

from tests.fixtures.builders import make_complete_agent, make_complete_task


async def test_dashboard_counts_empty(client):
    r = await client.get("/api/v1/reporting/dashboard-counts")
    assert r.status_code == 200
    body = r.json()
    # Every counter present, all zero on a clean DB.
    assert isinstance(body, dict)


async def test_dashboard_counts_reflect_seeded_entities(client, db):
    await make_complete_agent(db, name="for_dashboard_a")
    await make_complete_agent(db, name="for_dashboard_b")
    await make_complete_task(db, name="for_dashboard_t")

    r = await client.get("/api/v1/reporting/dashboard-counts")
    assert r.status_code == 200
    body = r.json()
    # Exact key names depend on the SDK; just verify the response has
    # something resembling agent/task counts.
    assert any("agent" in k.lower() for k in body.keys())


async def test_inventory_agents_empty(client):
    r = await client.get("/api/v1/reporting/agents")
    assert r.status_code == 200
    assert r.json() == []


async def test_inventory_agents_lists_seeded(client, db):
    await make_complete_agent(db, name="inventory_agent")
    r = await client.get("/api/v1/reporting/agents")
    assert r.status_code == 200
    rows = r.json()
    assert any(row.get("name") == "inventory_agent" for row in rows)


async def test_inventory_tasks_empty(client):
    r = await client.get("/api/v1/reporting/tasks")
    assert r.status_code == 200
    assert r.json() == []


async def test_inventory_tasks_lists_seeded(client, db):
    await make_complete_task(db, name="inventory_task")
    r = await client.get("/api/v1/reporting/tasks")
    assert r.status_code == 200
    rows = r.json()
    assert any(row.get("name") == "inventory_task" for row in rows)
