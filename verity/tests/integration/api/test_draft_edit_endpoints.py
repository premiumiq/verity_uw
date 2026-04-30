"""Draft-edit endpoints — PATCH, DELETE, and clone.

Immutability contract: only ``draft`` versions are editable. Any
non-draft target returns 409 Conflict with the current lifecycle_state
in the detail. These tests exercise:
  - PATCH succeeds on a draft
  - PATCH 409s after promotion (no longer draft)
  - DELETE removes a draft cleanly
  - POST .../clone yields a new draft from any prior version
"""

from __future__ import annotations

from tests.fixtures.builders import (
    make_agent_version,
    make_complete_agent,
    promote,
)


# ── PATCH on a draft ───────────────────────────────────────────────────────

async def test_patch_agent_version_draft_succeeds(client, db):
    av = await make_agent_version(db)  # state=draft

    # Look up the parent agent name via the catalog endpoint.
    list_resp = await client.get("/api/v1/agents")
    agent_name = next(
        a["name"] for a in list_resp.json() if a["id"] == str(av.agent_id)
    )

    r = await client.patch(
        f"/api/v1/agents/{agent_name}/versions/{av.id}",
        json={"change_summary": "Updated by test."},
    )
    assert r.status_code == 200


async def test_patch_agent_version_409_after_promotion(client, db):
    """Once the version leaves draft, PATCH must return 409 with a
    'not editable' message — preserves the promotion audit chain."""
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")  # no longer draft

    list_resp = await client.get("/api/v1/agents")
    agent_name = next(
        a["name"] for a in list_resp.json() if a["id"] == str(av.agent_id)
    )

    r = await client.patch(
        f"/api/v1/agents/{agent_name}/versions/{av.id}",
        json={"change_summary": "Won't apply."},
    )
    assert r.status_code == 409
    assert "not editable" in r.json()["detail"].lower()


# ── DELETE on a draft ──────────────────────────────────────────────────────

async def test_delete_agent_version_draft_succeeds(client, db):
    av = await make_agent_version(db)

    list_resp = await client.get("/api/v1/agents")
    agent_name = next(
        a["name"] for a in list_resp.json() if a["id"] == str(av.agent_id)
    )

    r = await client.delete(f"/api/v1/agents/{agent_name}/versions/{av.id}")
    assert r.status_code in (200, 204)

    # Confirm the row is gone.
    row = await db.fetch_one_raw(
        "SELECT id FROM governance.agent_version WHERE id = %(id)s",
        {"id": str(av.id)},
    )
    assert row is None


async def test_delete_agent_version_409_after_promotion(client, db):
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")

    list_resp = await client.get("/api/v1/agents")
    agent_name = next(
        a["name"] for a in list_resp.json() if a["id"] == str(av.agent_id)
    )

    r = await client.delete(f"/api/v1/agents/{agent_name}/versions/{av.id}")
    assert r.status_code == 409


# ── POST .../clone ─────────────────────────────────────────────────────────

async def test_clone_agent_version_creates_new_draft(client, db):
    """Cloning a champion produces a new draft you can edit further.
    The clone source can be any prior state — clone copies the rows,
    sets the new version's state to draft."""
    bundle = await make_complete_agent(db, name="cloneable")

    r = await client.post(
        f"/api/v1/agents/cloneable/versions/{bundle.version.id}/clone",
        json={
            "new_version_label": "2.0.0",
            "developer_name": "tester",
            "change_summary": "Forking champion to evolve.",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "id" in body
    # The new version is a draft regardless of source state.
    new_id = body["id"]
    row = await db.fetch_one_raw(
        "SELECT lifecycle_state FROM governance.agent_version WHERE id = %(id)s",
        {"id": new_id},
    )
    assert row["lifecycle_state"] == "draft"
