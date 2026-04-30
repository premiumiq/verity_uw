"""Async run-submission endpoints — POST /runs, GET /runs/{id}, etc.

The actual execution happens in a separate worker process; these tests
only exercise the submission + polling surface. We submit a run,
verify it shows up in listings, and cancel it.
"""

from __future__ import annotations

import uuid

from tests.fixtures.builders import make_complete_agent, make_complete_task


# ── POST /runs (submit) ─────────────────────────────────────────────────────

async def test_submit_run_for_agent_returns_run_id(client, db):
    await make_complete_agent(db, name="submit_agent")

    r = await client.post(
        "/api/v1/runs",
        json={
            "entity_kind": "agent",
            "entity_name": "submit_agent",
            "input": {"q": "hello"},
            "channel": "production",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "run_id" in body


async def test_submit_run_for_task_returns_run_id(client, db):
    await make_complete_task(db, name="submit_task")

    r = await client.post(
        "/api/v1/runs",
        json={
            "entity_kind": "task",
            "entity_name": "submit_task",
            "input": {"q": "hi"},
        },
    )
    assert r.status_code == 200


async def test_submit_run_returns_404_for_unknown_agent(client):
    r = await client.post(
        "/api/v1/runs",
        json={
            "entity_kind": "agent",
            "entity_name": "never_existed",
            "input": {},
        },
    )
    assert r.status_code == 404


async def test_submit_run_validates_entity_kind(client):
    """RunSubmission's entity_kind is Literal["task", "agent"] —
    Pydantic rejects anything else with 422."""
    r = await client.post(
        "/api/v1/runs",
        json={
            "entity_kind": "pipeline",
            "entity_name": "x",
            "input": {},
        },
    )
    assert r.status_code == 422


# ── GET /runs (list) ────────────────────────────────────────────────────────

async def test_list_runs_empty(client):
    r = await client.get("/api/v1/runs")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_runs_returns_submitted(client, db):
    await make_complete_agent(db, name="listed_agent")
    submit = await client.post(
        "/api/v1/runs",
        json={"entity_kind": "agent", "entity_name": "listed_agent", "input": {}},
    )
    run_id = submit.json()["run_id"]

    r = await client.get("/api/v1/runs")
    assert r.status_code == 200
    rows = r.json()
    assert any(row["id"] == run_id for row in rows)


async def test_list_runs_filters_by_entity_name(client, db):
    await make_complete_agent(db, name="filter_a")
    await make_complete_agent(db, name="filter_b")
    await client.post(
        "/api/v1/runs",
        json={"entity_kind": "agent", "entity_name": "filter_a", "input": {}},
    )
    await client.post(
        "/api/v1/runs",
        json={"entity_kind": "agent", "entity_name": "filter_b", "input": {}},
    )

    r = await client.get("/api/v1/runs?entity_name=filter_a")
    rows = r.json()
    assert all(row["entity_name"] == "filter_a" for row in rows)


# ── GET /runs/{id} ──────────────────────────────────────────────────────────

async def test_get_run_returns_current_state(client, db):
    await make_complete_agent(db, name="state_agent")
    submit = await client.post(
        "/api/v1/runs",
        json={"entity_kind": "agent", "entity_name": "state_agent", "input": {}},
    )
    run_id = submit.json()["run_id"]

    r = await client.get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == run_id
    assert body["current_status"] == "submitted"  # no worker has claimed it


async def test_get_run_404_for_unknown(client):
    r = await client.get(f"/api/v1/runs/{uuid.uuid4()}")
    assert r.status_code == 404


# ── GET /runs/{id}/result (409 when not terminal) ──────────────────────────

async def test_get_run_result_409_when_not_terminal(client, db):
    await make_complete_agent(db, name="result_agent")
    submit = await client.post(
        "/api/v1/runs",
        json={"entity_kind": "agent", "entity_name": "result_agent", "input": {}},
    )
    run_id = submit.json()["run_id"]

    # Run is in 'submitted' — result endpoint must say "not yet".
    r = await client.get(f"/api/v1/runs/{run_id}/result")
    assert r.status_code == 409


# ── POST /runs/{id}/cancel ─────────────────────────────────────────────────

async def test_cancel_run_succeeds_for_pending(client, db):
    await make_complete_agent(db, name="cancel_agent")
    submit = await client.post(
        "/api/v1/runs",
        json={"entity_kind": "agent", "entity_name": "cancel_agent", "input": {}},
    )
    run_id = submit.json()["run_id"]

    r = await client.post(f"/api/v1/runs/{run_id}/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True


async def test_cancel_run_404_for_unknown(client):
    r = await client.post(f"/api/v1/runs/{uuid.uuid4()}/cancel")
    assert r.status_code == 404
