"""Decision-log and audit-trail GET endpoints.

The decisions surface is read-only and the most-touched API by the
audit/compliance UIs. We need a decision row in the DB to test the
detail/list paths — the engine's run_agent step-mock path is the
cheapest way to write one.
"""

from __future__ import annotations

import uuid

from verity.contracts.mock import MockContext

from tests.fixtures.builders import make_complete_agent


async def _seed_one_decision(client, db) -> str:
    """Use the in-process Verity (via the API router's SDK reference)
    to write one decision_log row through a step-mocked run_agent.
    Returns the decision_log_id as a string."""
    # The fixture's `client` is wired to a Verity SDK instance via the
    # FastAPI app. Reach the SDK by calling run_agent through the
    # registry path — easiest is to just insert directly.
    # Don't pin the name — multiple seeds in one test would collide.
    av = await make_complete_agent(db)
    row = await db.fetch_one_raw(
        """
        INSERT INTO runtime.agent_decision_log (
            entity_type, entity_version_id, inference_config_snapshot, channel
        ) VALUES (
            'agent', %(version_id)s, %(snapshot)s::jsonb, 'production'
        )
        RETURNING id
        """,
        {"version_id": str(av.version.id), "snapshot": '{"model": "claude"}'},
    )
    return str(row["id"])


# ── list_decisions ─────────────────────────────────────────────────────────

async def test_list_decisions_empty(client):
    r = await client.get("/api/v1/decisions")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_decisions_returns_seeded_row(client, db):
    decision_id = await _seed_one_decision(client, db)

    r = await client.get("/api/v1/decisions")
    assert r.status_code == 200
    rows = r.json()
    assert any(row["id"] == decision_id for row in rows)


async def test_list_decisions_respects_limit(client, db):
    for _ in range(3):
        await _seed_one_decision(client, db)

    r = await client.get("/api/v1/decisions?limit=2")
    assert r.status_code == 200
    assert len(r.json()) <= 2


async def test_list_decisions_rejects_invalid_limit(client):
    """The endpoint enforces 1 ≤ limit ≤ 500 via FastAPI Query
    validation. Out-of-range → 422."""
    r = await client.get("/api/v1/decisions?limit=0")
    assert r.status_code == 422

    r = await client.get("/api/v1/decisions?limit=1000")
    assert r.status_code == 422


# ── get_decision ───────────────────────────────────────────────────────────

async def test_get_decision_returns_full_detail(client, db):
    decision_id = await _seed_one_decision(client, db)

    r = await client.get(f"/api/v1/decisions/{decision_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == decision_id
    # The detail endpoint returns the inference_config_snapshot dict.
    assert "inference_config_snapshot" in body


async def test_get_decision_404_for_unknown(client):
    bogus = uuid.uuid4()
    r = await client.get(f"/api/v1/decisions/{bogus}")
    assert r.status_code == 404
