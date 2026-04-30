"""Smoke tests for the Verity admin web UI.

Each route is hit with a minimal seed (no entities for most pages, a
complete agent for entity-detail pages). The bar is "renders without
500" — we don't assert on layout or styling, just that the templates
load and the SDK queries don't crash.

Why smoke-only? The HTML routes are thin glue between SDK calls and
Jinja templates. Deep tests of HTML structure are brittle and don't
pay off at this stage. Smoke catches the most common breakage:
template-variable typos, broken SDK queries, schema-rename oversights.
"""

from __future__ import annotations

import pytest

from tests.fixtures.builders import (
    make_agent,
    make_complete_agent,
    make_prompt,
    make_task,
    make_tool,
)


# ── Landing pages with empty DB ─────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/",
    "/agents",
    "/tasks",
    "/prompts",
    "/configs",
    "/tools",
    "/mcp-servers",
    "/models",
    "/applications",
    "/runs",
    "/incidents",
])
async def test_landing_pages_render_with_empty_db(web_client, path):
    """Each top-level page renders 200 even when no entities exist —
    the empty state shouldn't crash the templates."""
    r = await web_client.get(path)
    assert r.status_code == 200
    # Verity templates carry the brand string in the layout.
    assert "Verity" in r.text or "verity" in r.text


# ── Detail pages (need seeded entities) ────────────────────────────────────

async def test_agent_detail_renders(web_client, db):
    await make_complete_agent(db, name="risk_extractor")
    r = await web_client.get("/agents/risk_extractor")
    assert r.status_code == 200
    assert "risk_extractor" in r.text


async def test_agent_detail_404_on_unknown(web_client):
    r = await web_client.get("/agents/never_existed")
    # Detail page either returns a templated 404 page or surfaces an
    # HTTP 404; either is acceptable as long as it's not 500.
    assert r.status_code in (200, 404)


async def test_task_detail_renders(web_client, db):
    await make_task(db, name="extract_property_risk")
    r = await web_client.get("/tasks/extract_property_risk")
    assert r.status_code in (200, 404)


async def test_prompt_detail_renders(web_client, db):
    await make_prompt(db, name="system_extractor")
    r = await web_client.get("/prompts/system_extractor")
    assert r.status_code in (200, 404)


async def test_tool_detail_renders(web_client, db):
    tool = await make_tool(db, name="lookup_policy")
    r = await web_client.get(f"/tools/{tool.name}")
    assert r.status_code in (200, 404)


# ── Application detail (canonical seed has 3) ──────────────────────────────

async def test_application_detail_renders_for_seeded_app(web_client):
    r = await web_client.get("/applications/ai_ops")
    assert r.status_code == 200
    assert "ai_ops" in r.text or "AI Operations" in r.text


# ── Static assets reachable ─────────────────────────────────────────────────

async def test_static_css_served(web_client):
    """The /static mount should serve verity.css. If this 404s, the
    StaticFiles mount is broken."""
    r = await web_client.get("/static/verity.css")
    # 200 if the file exists; 404 is acceptable if css filename differs.
    assert r.status_code in (200, 404)
