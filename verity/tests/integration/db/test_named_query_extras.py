"""Round-trip coverage for named queries that the builders don't already
exercise. Builders cover agent / agent_version / task / task_version /
prompt / prompt_version / tool / inference_config; this fills in the
remaining headline tables that downstream waves will rely on.

Each test inserts a row through the named-query path and reads it back
through another named query — same machinery as production code, no
raw SQL.
"""

from __future__ import annotations

import json
import uuid


# ── data_connector ──────────────────────────────────────────────────────────

async def test_data_connector_round_trip(db):
    name = f"edms_{uuid.uuid4().hex[:8]}"
    inserted = await db.execute_returning(
        "insert_data_connector",
        {
            "name": name,
            "connector_type": "edms",
            "display_name": "Test EDMS",
            "description": "Document storage for tests.",
            "config": json.dumps({"base_url": "http://edms:8002"}),
            "owner_name": "tests",
        },
    )
    assert inserted is not None
    assert inserted["id"] is not None

    fetched = await db.fetch_one("get_data_connector_by_name", {"name": name})
    assert fetched is not None
    assert fetched["connector_type"] == "edms"


# ── mcp_server ──────────────────────────────────────────────────────────────

async def test_mcp_server_round_trip(db):
    name = f"duckduckgo_{uuid.uuid4().hex[:8]}"
    inserted = await db.execute_returning(
        "insert_mcp_server",
        {
            "name": name,
            "display_name": "DuckDuckGo Search",
            "description": "Web search MCP server.",
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "mcp_servers.duckduckgo.server"],
            "url": None,
            "env": json.dumps({}),
            "auth_config": json.dumps({}),
            "active": True,
        },
    )
    assert inserted is not None

    rows = await db.fetch_all("list_mcp_servers")
    assert any(r["name"] == name for r in rows)


# ── application ─────────────────────────────────────────────────────────────

async def test_application_seeded_governance_apps_listable(db):
    """apply_schema seeds three platform apps. The listing query should
    surface them through the named-query path."""
    rows = await db.fetch_all("list_applications")
    names = {r["name"] for r in rows}
    assert {"ai_ops", "model_validation", "compliance_audit"}.issubset(names)
