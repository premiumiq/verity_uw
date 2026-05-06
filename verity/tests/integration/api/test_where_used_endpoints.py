"""Where-used reverse-lookup endpoint.

Exercises the GET /api/v1/where-used/{entity_type}/{entity_id} contract

Each test creates a small composition of registry rows and then asks
the endpoint "which agent/task versions consume this asset?" — the
key behaviour Studio's safe-edit guarantee depends on.
"""

from __future__ import annotations

import uuid

from tests.fixtures.builders import (
    _get_test_inference_config_id,
    assign_prompt,
    authorize_tool,
    make_agent_version,
    make_complete_agent,
    make_complete_task,
    make_prompt,
    make_prompt_version,
    make_task_version,
    make_tool,
)


# ── prompt → agent + task consumers ─────────────────────────────────────────

async def test_where_used_prompt_returns_agent_and_task_consumers(client, db):
    """A prompt assigned to one agent_version AND one task_version
    surfaces both rows, each with its current lifecycle_state."""
    # Two complete pipelines so the prompt has two consumer paths.
    agent_bundle = await make_complete_agent(db, promote_to_champion=False)
    task_bundle = await make_complete_task(db, promote_to_champion=False)

    # A shared prompt (separate from the per-bundle system prompts).
    shared_prompt = await make_prompt(db, name="shared_extraction_prompt")
    shared_pv = await make_prompt_version(
        db, prompt_id=shared_prompt.id,
        content="Shared content used by both an agent and a task.",
    )
    await assign_prompt(db, entity_version=agent_bundle.version, prompt_version=shared_pv)
    await assign_prompt(db, entity_version=task_bundle.version, prompt_version=shared_pv)

    r = await client.get(f"/api/v1/where-used/prompt/{shared_prompt.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["used_type"] == "prompt"
    assert body["used_id"] == str(shared_prompt.id)

    consumers = body["consumers"]
    types = {c["consumer_type"] for c in consumers}
    assert types == {"agent_version", "task_version"}, (
        f"Expected both agent_version and task_version consumers, got {types}"
    )

    # Every consumer must carry the safe-edit signal: lifecycle_state.
    for c in consumers:
        assert c["lifecycle_state"] in {
            "draft", "candidate", "staging", "shadow",
            "challenger", "champion", "deprecated",
        }, f"Unexpected lifecycle_state: {c['lifecycle_state']}"
        assert c["consumer_name"]
        assert c["version_label"]


# ── tool → agent + task consumers ───────────────────────────────────────────

async def test_where_used_tool_returns_consumers_across_agent_and_task(client, db):
    """A tool authorized on one agent_version and one task_version is
    found by where-used under both consumer types."""
    tool = await make_tool(db, name="shared_tool")

    agent_bundle = await make_complete_agent(db, promote_to_champion=False)
    task_bundle = await make_complete_task(db, promote_to_champion=False)

    # The agent path has a builder helper; the task path doesn't yet,
    # so we use the same insert query the SDK uses internally.
    await authorize_tool(db, agent_version=agent_bundle.version, tool=tool)
    await db.execute_returning(
        "insert_task_version_tool",
        {
            "task_version_id": str(task_bundle.version.id),
            "tool_id": str(tool.id),
            "authorized": True,
            "notes": None,
        },
    )

    r = await client.get(f"/api/v1/where-used/tool/{tool.id}")
    assert r.status_code == 200
    consumers = r.json()["consumers"]

    types = {c["consumer_type"] for c in consumers}
    assert types == {"agent_version", "task_version"}


# ── inference_config → consumers ────────────────────────────────────────────

async def test_where_used_inference_config_returns_consumers(client, db):
    """Every agent_version / task_version row carries an
    inference_config_id FK; where-used must surface them. We use the
    test seed config that all of make_complete_* references."""
    cfg_id = await _get_test_inference_config_id(db)

    # Create two consumers so the result is non-trivial.
    av = await make_agent_version(db)  # default config → test seed
    tv = await make_task_version(db)

    r = await client.get(f"/api/v1/where-used/inference_config/{cfg_id}")
    assert r.status_code == 200
    consumers = r.json()["consumers"]

    consumer_ids = {c["consumer_id"] for c in consumers}
    assert str(av.id) in consumer_ids, (
        "agent_version using the seed config should appear in consumers"
    )
    assert str(tv.id) in consumer_ids, (
        "task_version using the seed config should appear in consumers"
    )


# ── empty consumers list ────────────────────────────────────────────────────

async def test_where_used_unused_asset_returns_empty_list(client, db):
    """An asset with no consumers — and even an unknown id — returns a
    well-formed envelope with an empty list. The contract is "this is
    safe to edit" not "404"."""
    orphan_prompt = await make_prompt(db, name="never_assigned_prompt")
    # No prompt_version, no assignments → the prompt header has zero
    # consumers via the entity_consumers view.

    r = await client.get(f"/api/v1/where-used/prompt/{orphan_prompt.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["consumers"] == []

    # Unknown id (well-formed UUID) also returns an empty list rather
    # than 404. The "does it exist?" question belongs on the registry
    # endpoints; this endpoint answers "who uses it?" — which is "no
    # one" for both unused and non-existent.
    fake_id = str(uuid.uuid4())
    r2 = await client.get(f"/api/v1/where-used/prompt/{fake_id}")
    assert r2.status_code == 200
    assert r2.json()["consumers"] == []


# ── 400 for unknown entity_type ─────────────────────────────────────────────

async def test_where_used_unknown_entity_type_returns_400(client, db):
    """Asking for consumers of a not-supported asset type is a client
    error — the editor should never ship a typo to production."""
    fake_id = str(uuid.uuid4())
    r = await client.get(f"/api/v1/where-used/agent/{fake_id}")
    assert r.status_code == 400
    detail = r.json()["detail"]
    # The error names the supported types so the caller can fix it.
    assert "entity_type must be one of" in detail
    for valid in ("prompt", "tool", "inference_config", "data_connector"):
        assert valid in detail


# ── lifecycle state flows through correctly ────────────────────────────────

async def test_where_used_surfaces_consumer_lifecycle_state(client, db):
    """Studio's safe-edit gate keys off lifecycle_state — when a
    consumer is in champion, the editor must block in-place save.
    Verify the field round-trips correctly through view → query →
    response."""
    # make_complete_agent with promote_to_champion=True puts the
    # agent_version in 'champion' and points the agent header at it.
    bundle = await make_complete_agent(db, promote_to_champion=True)

    # The bundle's per-agent system prompt is the easiest asset to
    # ask about — exactly one consumer (the champion version itself).
    # We look it up via the agent's version row to get the prompt id.
    rows = await db.fetch_one_raw(
        """
        SELECT pv.prompt_id
        FROM entity_prompt_assignment epa
        JOIN prompt_version pv ON pv.id = epa.prompt_version_id
        WHERE epa.entity_type = 'agent'
          AND epa.entity_version_id = %(version_id)s
        LIMIT 1
        """,
        {"version_id": str(bundle.version.id)},
    )
    assert rows is not None, "make_complete_agent should assign a prompt"
    prompt_id = rows["prompt_id"]

    r = await client.get(f"/api/v1/where-used/prompt/{prompt_id}")
    assert r.status_code == 200
    consumers = r.json()["consumers"]
    assert len(consumers) >= 1
    champion_match = next(
        (c for c in consumers if c["lifecycle_state"] == "champion"),
        None,
    )
    assert champion_match is not None, (
        "Champion consumer must surface as lifecycle_state='champion' "
        "so the safe-edit gate can block in-place save."
    )
    assert champion_match["consumer_name"] == bundle.name
