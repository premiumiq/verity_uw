"""Lifecycle POST endpoints — promote, rollback, list_approvals.

The router translates SDK errors into HTTP semantics:
  - ValueError (illegal transition / missing prereqs) → 400
  - KeyError (missing required body field)            → 422
  - Successful promote/rollback                       → 200 with result
"""

from __future__ import annotations

from tests.fixtures.builders import make_agent_version, promote


async def test_promote_draft_to_candidate_succeeds(client, db):
    av = await make_agent_version(db)

    r = await client.post(
        "/api/v1/lifecycle/promote",
        json={
            "entity_type": "agent",
            "entity_version_id": str(av.id),
            "target_state": "candidate",
            "approver_name": "alice",
            "rationale": "Initial draft review complete.",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["from_state"] == "draft"
    assert body["to_state"] == "candidate"


async def test_promote_invalid_transition_returns_400(client, db):
    av = await make_agent_version(db)
    # draft → champion isn't legal — must come back as 400, not 500.
    r = await client.post(
        "/api/v1/lifecycle/promote",
        json={
            "entity_type": "agent",
            "entity_version_id": str(av.id),
            "target_state": "champion",
            "approver_name": "alice",
            "rationale": "Try to skip the line.",
        },
    )
    assert r.status_code == 400
    assert "Invalid transition" in r.json()["detail"]


async def test_promote_missing_field_returns_422(client, db):
    av = await make_agent_version(db)
    # Missing "rationale" — required by the lifecycle SDK.
    r = await client.post(
        "/api/v1/lifecycle/promote",
        json={
            "entity_type": "agent",
            "entity_version_id": str(av.id),
            "target_state": "candidate",
            "approver_name": "alice",
        },
    )
    assert r.status_code == 422
    assert "rationale" in r.json()["detail"].lower()


async def test_rollback_champion_succeeds(client, db):
    av = await make_agent_version(db)
    # Get to champion via the SDK fast-track path.
    await promote(db, av, to_state="candidate")
    r = await client.post(
        "/api/v1/lifecycle/promote",
        json={
            "entity_type": "agent",
            "entity_version_id": str(av.id),
            "target_state": "champion",
            "approver_name": "alice",
            "rationale": "Fast-track to champion.",
        },
    )
    assert r.status_code == 200

    r = await client.post(
        "/api/v1/lifecycle/rollback",
        json={
            "entity_type": "agent",
            "entity_version_id": str(av.id),
            "approver_name": "owner",
            "rationale": "Production incident.",
        },
    )
    assert r.status_code == 200
    assert str(r.json()["rolled_back_version"]) == str(av.id)


async def test_rollback_non_champion_returns_400(client, db):
    av = await make_agent_version(db)  # stays in draft

    r = await client.post(
        "/api/v1/lifecycle/rollback",
        json={
            "entity_type": "agent",
            "entity_version_id": str(av.id),
            "approver_name": "owner",
            "rationale": "Mistake.",
        },
    )
    assert r.status_code == 400
    assert "champion" in r.json()["detail"].lower()


async def test_list_approvals_returns_promotion_record(client, db):
    av = await make_agent_version(db)
    await client.post(
        "/api/v1/lifecycle/promote",
        json={
            "entity_type": "agent",
            "entity_version_id": str(av.id),
            "target_state": "candidate",
            "approver_name": "alice",
            "rationale": "Initial.",
        },
    )

    r = await client.get(
        "/api/v1/lifecycle/approvals",
        params={"entity_type": "agent", "entity_version_id": str(av.id)},
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["gate_type"] == "draft_to_candidate_promotion"
    assert rows[0]["approver_name"] == "alice"
