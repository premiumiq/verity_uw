"""Integration test: insert an agent through a named query, fetch it back
through another named query.

This is the smallest end-to-end exercise of the named-query plumbing — it
runs real SQL against a real DB through ``Database.execute_returning`` and
``Database.fetch_one``. If the named-query loader, the SQL itself, or the
FK constraints break, this test catches it.
"""

from __future__ import annotations

import uuid


async def test_insert_and_fetch_agent(db):
    agent_name = f"test_agent_{uuid.uuid4().hex[:8]}"

    inserted = await db.execute_returning(
        "insert_agent",
        {
            "name":              agent_name,
            "display_name":      "Test Agent",
            "description":       "Created by tests/integration/test_registry_roundtrip.",
            "purpose":           "Exercise the registry insert/fetch round-trip.",
            "domain":            "underwriting",
            "materiality_tier":  "low",
            "owner_name":        "Test Owner",
            "owner_email":       "test@example.com",
            "business_context":  None,
            "known_limitations": None,
            "regulatory_notes":  None,
        },
    )
    assert inserted is not None
    assert "id" in inserted
    assert "created_at" in inserted

    # Fetch via the read-side named query. ``get_agent_by_name`` joins to
    # agent_version + inference_config via LEFT JOINs, so even with no
    # version yet the row should come back populated for agent fields and
    # NULL for the join-side fields.
    fetched = await db.fetch_one("get_agent_by_name", {"agent_name": agent_name})
    assert fetched is not None
    assert fetched["name"] == agent_name
    assert fetched["display_name"] == "Test Agent"
    assert fetched["champion_version_id"] is None  # No version yet.
