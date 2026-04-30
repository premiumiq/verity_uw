"""Registry GET endpoints — catalog lists, resolved configs, version listings.

These are read-only and the highest-traffic endpoints in the API surface.
Tests confirm:
  - Empty list when nothing's registered
  - Populated list after builders create entities
  - Resolved config returns a champion's config (404 when no champion)
  - Version listings work; 404 on unknown name
"""

from __future__ import annotations

from tests.fixtures.builders import (
    make_agent,
    make_complete_agent,
    make_inference_config,
    make_prompt,
    make_task,
)


# ── List endpoints ─────────────────────────────────────────────────────────

async def test_list_agents_empty(client):
    r = await client.get("/api/v1/agents")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_agents_returns_seeded_rows(client, db):
    await make_agent(db, name="risk_extractor")
    await make_agent(db, name="claim_triage")

    r = await client.get("/api/v1/agents")
    assert r.status_code == 200
    body = r.json()
    names = {row["name"] for row in body}
    assert {"risk_extractor", "claim_triage"}.issubset(names)


async def test_list_tasks_empty(client):
    r = await client.get("/api/v1/tasks")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_tasks_returns_seeded_rows(client, db):
    await make_task(db, name="extract_property_risk")
    r = await client.get("/api/v1/tasks")
    assert r.status_code == 200
    assert any(row["name"] == "extract_property_risk" for row in r.json())


async def test_list_prompts_returns_seeded_rows(client, db):
    await make_prompt(db, name="system_extractor")
    r = await client.get("/api/v1/prompts")
    assert r.status_code == 200
    assert any(row["name"] == "system_extractor" for row in r.json())


async def test_list_inference_configs_includes_canonical_seed(client):
    """The canonical seed inserts ``test_default_config`` — the listing
    endpoint must surface it."""
    r = await client.get("/api/v1/inference-configs")
    assert r.status_code == 200
    names = {row["name"] for row in r.json()}
    assert "test_default_config" in names


# ── Resolved config (champion lookup) ──────────────────────────────────────

async def test_get_agent_config_returns_champion(client, db):
    await make_complete_agent(db, name="champion_check")

    r = await client.get("/api/v1/agents/champion_check/config")
    assert r.status_code == 200
    config = r.json()
    assert config["agent_name"] == "champion_check"
    assert config["lifecycle_state"] == "champion"
    # Resolved config is required to surface inference + prompts + tools.
    assert "inference_config" in config
    assert isinstance(config["prompts"], list)
    assert isinstance(config["tools"], list)


async def test_get_agent_config_404_when_no_champion(client, db):
    """Agent exists but has no champion — config endpoint should 404."""
    await make_agent(db, name="no_champion_yet")

    r = await client.get("/api/v1/agents/no_champion_yet/config")
    assert r.status_code == 404


async def test_get_agent_config_404_when_unknown_agent(client):
    r = await client.get("/api/v1/agents/never_existed/config")
    assert r.status_code == 404


# ── Version listings ───────────────────────────────────────────────────────

async def test_list_agent_versions_returns_one_for_complete_agent(client, db):
    await make_complete_agent(db, name="versioned_agent")

    r = await client.get("/api/v1/agents/versioned_agent/versions")
    assert r.status_code == 200
    versions = r.json()
    assert len(versions) >= 1


async def test_list_agent_versions_404_on_unknown_agent(client):
    r = await client.get("/api/v1/agents/never_existed/versions")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()
