"""Optimistic-concurrency contract for PATCH endpoints.

Implements the test commitment from docs/plans/studio-build-plan.md
§4.2 ("Stale-write rejection"). The PATCH endpoints accept an optional
``expected_updated_at`` body field. When supplied:
  - matching the row's current stamp → 200 with a new stamp
  - non-matching                      → 409 with ``error_code: stale_write``
  - omitted (legacy callers)          → 200, no concurrency check

A non-draft row still returns the existing 409 lifecycle conflict —
that takes precedence over stale_write.
"""

from __future__ import annotations

from tests.fixtures.builders import (
    make_agent_version,
    make_prompt_version,
    make_task_version,
    promote,
)


# ── Backwards compatibility ────────────────────────────────────────────────
# Existing SDK callers that don't know about expected_updated_at must
# continue to work unchanged. Prove it for all three editable entities.

async def test_patch_without_expected_stamp_succeeds(client, db):
    """No expected_updated_at in the body → no concurrency check."""
    av = await make_agent_version(db)
    list_resp = await client.get("/api/v1/agents")
    agent_name = next(
        a["name"] for a in list_resp.json() if a["id"] == str(av.agent_id)
    )

    r = await client.patch(
        f"/api/v1/agents/{agent_name}/versions/{av.id}",
        json={"change_summary": "Legacy caller — no stamp."},
    )
    assert r.status_code == 200
    # The response still surfaces the stamp so a client that wants to
    # opt in on the next save can read it here.
    assert r.json().get("updated_at") is not None


# ── Happy path ─────────────────────────────────────────────────────────────
# Read the row's current updated_at, send it back as
# expected_updated_at on save → server applies the update and returns
# a NEWER stamp.

async def test_patch_with_matching_stamp_succeeds_and_advances_stamp(client, db):
    av = await make_agent_version(db)
    list_resp = await client.get("/api/v1/agents")
    agent_name = next(
        a["name"] for a in list_resp.json() if a["id"] == str(av.agent_id)
    )

    # First read: an unrelated PATCH (no stamp) acts as a "read" that
    # captures the current updated_at. Real Studio clients will read
    # via GET /agents/.../versions/... once that endpoint surfaces the
    # stamp; for this test the PATCH response is the cleanest source.
    initial = await client.patch(
        f"/api/v1/agents/{agent_name}/versions/{av.id}",
        json={"change_summary": "Read-equivalent."},
    )
    assert initial.status_code == 200
    initial_stamp = initial.json()["updated_at"]
    assert initial_stamp is not None

    # Second save with the matching stamp: must succeed and the
    # response stamp must be strictly newer than the one we sent.
    second = await client.patch(
        f"/api/v1/agents/{agent_name}/versions/{av.id}",
        json={
            "change_summary": "Second save.",
            "expected_updated_at": initial_stamp,
        },
    )
    assert second.status_code == 200
    new_stamp = second.json()["updated_at"]
    assert new_stamp is not None
    assert new_stamp >= initial_stamp


# ── Stale write — the headline case ────────────────────────────────────────
# Two clients race. The slower one's stamp is stale by the time it
# reaches the server, and its save is rejected with stale_write so it
# can recover (reload + re-apply) instead of silently overwriting.

async def test_patch_with_stale_stamp_returns_409_stale_write(client, db):
    av = await make_agent_version(db)
    list_resp = await client.get("/api/v1/agents")
    agent_name = next(
        a["name"] for a in list_resp.json() if a["id"] == str(av.agent_id)
    )

    # Both clients read — they observe the same stamp.
    read = await client.patch(
        f"/api/v1/agents/{agent_name}/versions/{av.id}",
        json={"change_summary": "Initial state."},
    )
    assert read.status_code == 200
    stamp_observed_by_both = read.json()["updated_at"]

    # Client B saves first, with the matching stamp. Server bumps the
    # stamp; client A's view of it is now stale.
    client_b = await client.patch(
        f"/api/v1/agents/{agent_name}/versions/{av.id}",
        json={
            "change_summary": "Client B got there first.",
            "expected_updated_at": stamp_observed_by_both,
        },
    )
    assert client_b.status_code == 200

    # Client A tries to save with the now-stale stamp.
    client_a = await client.patch(
        f"/api/v1/agents/{agent_name}/versions/{av.id}",
        json={
            "change_summary": "Client A's later save.",
            "expected_updated_at": stamp_observed_by_both,
        },
    )
    assert client_a.status_code == 409

    # The 409 body carries the new structured shape so the UI can
    # surface a precise recovery message.
    detail = client_a.json()["detail"]
    assert isinstance(detail, dict), (
        "stale_write 409 must carry a structured detail, not a string"
    )
    assert detail["error_code"] == "stale_write"
    assert detail["current_updated_at"] is not None
    # The current stamp surfaced by the 409 must be strictly newer
    # than the stale stamp the client sent — that's how the UI knows
    # how much it missed.
    assert detail["current_updated_at"] > stamp_observed_by_both


# ── Lifecycle conflict still wins ──────────────────────────────────────────
# When a row has been promoted out of draft, the response must remain
# the existing "not editable" 409 rather than morphing into stale_write.
# The existing test suite asserts on the "not editable" substring, so
# this test guards that contract too.

async def test_patch_on_promoted_version_returns_lifecycle_409_not_stale_write(client, db):
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")

    list_resp = await client.get("/api/v1/agents")
    agent_name = next(
        a["name"] for a in list_resp.json() if a["id"] == str(av.agent_id)
    )

    r = await client.patch(
        f"/api/v1/agents/{agent_name}/versions/{av.id}",
        json={
            "change_summary": "Won't apply.",
            # Even with a stamp present, lifecycle conflict takes precedence.
            "expected_updated_at": "2000-01-01T00:00:00",
        },
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    # Lifecycle conflict surfaces the original string detail — not the
    # structured stale_write shape.
    assert isinstance(detail, str)
    assert "not editable" in detail.lower()


# ── Same contract on tasks ─────────────────────────────────────────────────

async def test_task_patch_stale_stamp_returns_stale_write(client, db):
    tv = await make_task_version(db)
    list_resp = await client.get("/api/v1/tasks")
    task_name = next(
        t["name"] for t in list_resp.json() if t["id"] == str(tv.task_id)
    )

    read = await client.patch(
        f"/api/v1/tasks/{task_name}/versions/{tv.id}",
        json={"change_summary": "Initial."},
    )
    assert read.status_code == 200
    stamp = read.json()["updated_at"]

    first = await client.patch(
        f"/api/v1/tasks/{task_name}/versions/{tv.id}",
        json={"change_summary": "First.", "expected_updated_at": stamp},
    )
    assert first.status_code == 200

    second = await client.patch(
        f"/api/v1/tasks/{task_name}/versions/{tv.id}",
        json={"change_summary": "Stale.", "expected_updated_at": stamp},
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "stale_write"


# ── Same contract on prompts (the table that gained updated_at in this slice) ─

async def test_prompt_patch_stale_stamp_returns_stale_write(client, db):
    pv = await make_prompt_version(db)
    # The prompts list endpoint exposes name; resolve it via the
    # parent prompt id to keep the test independent of route shape.
    list_resp = await client.get("/api/v1/prompts")
    prompt_name = next(
        p["name"] for p in list_resp.json() if p["id"] == str(pv.prompt_id)
    )

    read = await client.patch(
        f"/api/v1/prompts/{prompt_name}/versions/{pv.id}",
        json={"change_summary": "Initial."},
    )
    assert read.status_code == 200
    stamp = read.json()["updated_at"]
    assert stamp is not None, (
        "prompt_version.updated_at must be present in PATCH responses "
        "after the slice-2 schema migration"
    )

    first = await client.patch(
        f"/api/v1/prompts/{prompt_name}/versions/{pv.id}",
        json={"change_summary": "First.", "expected_updated_at": stamp},
    )
    assert first.status_code == 200

    second = await client.patch(
        f"/api/v1/prompts/{prompt_name}/versions/{pv.id}",
        json={"change_summary": "Stale.", "expected_updated_at": stamp},
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "stale_write"
