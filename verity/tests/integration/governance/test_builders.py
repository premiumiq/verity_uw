"""Integration tests for the domain factories in ``tests/fixtures/builders``.

The builders are used by every later integration test, so a regression
here would cascade. These tests sanity-check that each factory:

  - inserts a row that's actually persisted (visible via a fresh fetch)
  - returns a Pydantic model whose fields match the inserted row
  - applies sensible defaults when arguments are omitted
  - composes correctly (e.g. ``make_agent_version`` creates an Agent
    on the fly when ``agent_id`` isn't supplied)

The test file lives in ``governance/`` because the entities being built
all live in the governance schema. It's not testing governance behavior
per se — just plumbing — but the markers from ``governance/`` are still
appropriate (the helpers are governance-data builders).
"""

from __future__ import annotations

import uuid

import pytest

from tests.fixtures.builders import (
    make_agent,
    make_agent_version,
    make_inference_config,
    make_prompt,
    make_prompt_version,
    make_task,
    make_task_version,
    make_tool,
    promote,
)
from verity.models.lifecycle import DeploymentChannel, LifecycleState


# ── make_agent ──────────────────────────────────────────────────────────────

async def test_make_agent_persists_and_returns_model(db):
    agent = await make_agent(db, name="risk_extractor")
    assert agent.name == "risk_extractor"
    assert agent.id is not None

    row = await db.fetch_one_raw(
        "SELECT name, display_name, materiality_tier, owner_name "
        "FROM agent WHERE id = %(id)s",
        {"id": str(agent.id)},
    )
    assert row is not None
    assert row["name"] == "risk_extractor"
    assert row["display_name"] == "risk_extractor"
    assert row["materiality_tier"] == "low"
    assert row["owner_name"] == "Test Owner"


async def test_make_agent_unique_default_name():
    # Two agents created with no `name` must not collide on UNIQUE(name).
    pass  # Covered indirectly by test_make_two_agents_no_collision below.


async def test_make_two_agents_no_collision(db):
    a1 = await make_agent(db)
    a2 = await make_agent(db)
    assert a1.name != a2.name


# ── make_agent_version ──────────────────────────────────────────────────────

async def test_make_agent_version_creates_parent_when_missing(db):
    # No agent_id supplied → builder creates a parent agent on the fly.
    av = await make_agent_version(db)
    assert av.agent_id is not None
    parent = await db.fetch_one_raw(
        "SELECT id FROM agent WHERE id = %(id)s",
        {"id": str(av.agent_id)},
    )
    assert parent is not None


async def test_make_agent_version_lands_in_draft_state(db):
    av = await make_agent_version(db)
    assert av.lifecycle_state == LifecycleState.DRAFT
    assert av.channel == DeploymentChannel.DEVELOPMENT


async def test_make_agent_version_uses_canonical_inference_config(db):
    av = await make_agent_version(db)
    row = await db.fetch_one_raw(
        "SELECT inference_config_id FROM agent_version WHERE id = %(id)s",
        {"id": str(av.id)},
    )
    assert row is not None
    assert row["inference_config_id"] == av.inference_config_id


async def test_make_agent_version_with_explicit_parent(db):
    parent = await make_agent(db, name="custom_parent")
    av = await make_agent_version(db, agent_id=parent.id)
    assert av.agent_id == parent.id


# ── make_task / make_task_version ──────────────────────────────────────────

async def test_make_task_persists(db):
    task = await make_task(db)
    row = await db.fetch_one_raw(
        "SELECT capability_type, materiality_tier FROM task WHERE id = %(id)s",
        {"id": str(task.id)},
    )
    assert row is not None
    assert row["capability_type"] == "extraction"


async def test_make_task_version_creates_parent_when_missing(db):
    tv = await make_task_version(db)
    assert tv.task_id is not None


# ── make_prompt / make_prompt_version ──────────────────────────────────────

async def test_make_prompt_persists(db):
    p = await make_prompt(db, name="extract_risk_factors")
    row = await db.fetch_one_raw(
        "SELECT name, description FROM prompt WHERE id = %(id)s",
        {"id": str(p.id)},
    )
    assert row is not None
    assert row["name"] == "extract_risk_factors"


async def test_make_prompt_version_lands_in_draft(db):
    pv = await make_prompt_version(db)
    assert pv.lifecycle_state == LifecycleState.DRAFT


# ── make_tool ──────────────────────────────────────────────────────────────

async def test_make_tool_defaults_to_python_inprocess(db):
    tool = await make_tool(db)
    assert tool.transport == "python_inprocess"
    row = await db.fetch_one_raw(
        "SELECT transport, mock_mode_enabled FROM tool WHERE id = %(id)s",
        {"id": str(tool.id)},
    )
    assert row is not None
    assert row["transport"] == "python_inprocess"
    assert row["mock_mode_enabled"] is True


# ── make_inference_config ──────────────────────────────────────────────────

async def test_make_inference_config_returns_id(db):
    cfg_id = await make_inference_config(db, name=f"cfg_{uuid.uuid4().hex[:6]}")
    row = await db.fetch_one_raw(
        "SELECT name, max_tokens FROM inference_config WHERE id = %(id)s",
        {"id": str(cfg_id)},
    )
    assert row is not None
    assert row["max_tokens"] == 4096


# ── promote ────────────────────────────────────────────────────────────────

async def test_promote_updates_state_and_channel(db):
    av = await make_agent_version(db)
    assert av.lifecycle_state == LifecycleState.DRAFT

    await promote(db, av, to_state="candidate")

    # The in-memory model is mutated to reflect the new state.
    assert av.lifecycle_state == LifecycleState.CANDIDATE
    # And the DB row matches.
    row = await db.fetch_one_raw(
        "SELECT lifecycle_state, channel FROM agent_version WHERE id = %(id)s",
        {"id": str(av.id)},
    )
    assert row is not None
    assert row["lifecycle_state"] == "candidate"
    # CANDIDATE maps to DEVELOPMENT channel per STATE_TO_CHANNEL.
    assert row["channel"] == "development"


async def test_promote_to_champion_uses_production_channel(db):
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    await promote(db, av, to_state="champion")
    assert av.channel == DeploymentChannel.PRODUCTION


async def test_promote_works_for_task_version(db):
    tv = await make_task_version(db)
    await promote(db, tv, to_state="candidate")
    assert tv.lifecycle_state == LifecycleState.CANDIDATE
    row = await db.fetch_one_raw(
        "SELECT lifecycle_state FROM task_version WHERE id = %(id)s",
        {"id": str(tv.id)},
    )
    assert row is not None
    assert row["lifecycle_state"] == "candidate"


async def test_promote_rejects_unknown_state(db):
    av = await make_agent_version(db)
    with pytest.raises(ValueError):
        await promote(db, av, to_state="not_a_real_state")
