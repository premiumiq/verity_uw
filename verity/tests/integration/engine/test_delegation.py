"""Tests for ``ExecutionEngine._delegate_to_agent`` — the
``verity_builtin/delegate_to_agent`` meta-tool that lets one agent
spawn another as a fully governed nested run.

Error paths fire before the registry check, so they're cheap to test.
The happy path requires:
  - parent agent with a delegation row authorizing a child agent name
  - child agent with a champion version
  - the engine's run_agent path working end-to-end (covered already
    by test_run_agent_happy)

We test:
  - shape validation (missing agent_name / context / wrong type)
  - depth guard (caller already at MAX_DECISION_DEPTH-1 → refuse)
  - missing parent_agent_version_id (programming-error guard)
  - unauthorized (no delegation row → error tool_result)
  - authorized happy path (sub-agent runs, decision_log row written)
"""

from __future__ import annotations

import uuid

from verity.contracts.mock import MockContext

from tests.fixtures.builders import make_complete_agent


# ── Shape validation ───────────────────────────────────────────────────────

async def test_delegate_missing_agent_name_returns_error(engine, db):
    bundle = await make_complete_agent(db, name="parent_a")
    result = await engine._delegate_to_agent(
        tool_input={"context": {}},
        call_order=1,
        parent_agent_version_id=bundle.version.id,
    )
    assert result["error"] is True
    assert "agent_name" in result["output_data"]["error"].lower()


async def test_delegate_missing_context_returns_error(engine, db):
    bundle = await make_complete_agent(db, name="parent_b")
    result = await engine._delegate_to_agent(
        tool_input={"agent_name": "child"},
        call_order=1,
        parent_agent_version_id=bundle.version.id,
    )
    assert result["error"] is True
    assert "context" in result["output_data"]["error"].lower()


async def test_delegate_non_dict_context_returns_error(engine, db):
    bundle = await make_complete_agent(db, name="parent_c")
    result = await engine._delegate_to_agent(
        tool_input={"agent_name": "child", "context": "not a dict"},
        call_order=1,
        parent_agent_version_id=bundle.version.id,
    )
    assert result["error"] is True
    assert "must be a dict" in result["output_data"]["error"].lower()


# ── Depth guard ────────────────────────────────────────────────────────────

async def test_delegate_refuses_at_depth_limit(engine, db):
    """next_depth >= MAX_DECISION_DEPTH (5). Caller passes
    decision_depth=4 → next_depth=5 → refuse."""
    bundle = await make_complete_agent(db, name="parent_d")
    result = await engine._delegate_to_agent(
        tool_input={"agent_name": "child", "context": {}},
        call_order=1,
        parent_agent_version_id=bundle.version.id,
        decision_depth=4,
    )
    assert result["error"] is True
    assert "MAX_DECISION_DEPTH" in result["output_data"]["error"]


# ── Programming-error guard ────────────────────────────────────────────────

async def test_delegate_without_parent_version_id_returns_error(engine):
    """parent_agent_version_id=None means the gateway threading is
    broken. Surface as tool error so the loop can continue."""
    result = await engine._delegate_to_agent(
        tool_input={"agent_name": "child", "context": {}},
        call_order=1,
        parent_agent_version_id=None,
    )
    assert result["error"] is True
    assert "parent_agent_version_id" in result["output_data"]["error"]


# ── Unauthorized ───────────────────────────────────────────────────────────

async def test_delegate_unauthorized_child_returns_error(engine, db):
    """Parent has no delegation row authorizing this child name —
    error tool_result with the list of authorized targets."""
    bundle = await make_complete_agent(db, name="parent_e")

    result = await engine._delegate_to_agent(
        tool_input={"agent_name": "no_such_child", "context": {}},
        call_order=1,
        parent_agent_version_id=bundle.version.id,
    )
    assert result["error"] is True
    err_msg = result["output_data"]["error"]
    assert "authorized" in err_msg.lower() or "delegation" in err_msg.lower()


# ── Authorized happy path ──────────────────────────────────────────────────

async def test_delegate_authorized_child_runs_sub_agent(engine, db):
    """Parent has a delegation row → sub-agent runs via step-mock,
    returns a tool_record with the sub-decision's id.

    Setup: pre-insert the parent's decision_log row so the sub-agent's
    parent_decision_id FK resolves. In production this row is written
    by the parent's run_agent — calling _delegate_to_agent directly
    bypasses that, hence the manual insert.
    """
    import json
    parent = await make_complete_agent(db, name="delegating_parent")
    child = await make_complete_agent(db, name="delegated_child")

    # Author the delegation row.
    await db.execute(
        "insert_agent_version_delegation",
        {
            "parent_agent_version_id": str(parent.version.id),
            "child_agent_name": "delegated_child",
            "child_agent_version_id": None,
            "scope": "{}",
            "authorized": True,
            "rationale": "Test delegation.",
            "notes": None,
        },
    )

    # Pre-insert the parent's decision_log row so the sub-agent's FK
    # to parent_decision_id resolves. We then pass that id into
    # _delegate_to_agent as parent_decision_id.
    parent_decision = await db.fetch_one_raw(
        """
        INSERT INTO runtime.agent_decision_log (
            entity_type, entity_version_id, inference_config_snapshot, channel
        ) VALUES (
            'agent', %(version_id)s, %(snapshot)s::jsonb, 'production'
        )
        RETURNING id
        """,
        {
            "version_id": str(parent.version.id),
            "snapshot": json.dumps({"model": "claude"}),
        },
    )
    parent_decision_id = parent_decision["id"]

    # Bypass LLM in the sub-agent via per-sub-agent step_responses.
    # MockContext threading would normally be done by run_agent before
    # calling the gateway — _delegate_to_agent itself doesn't read
    # MockContext, but the sub-agent's run_agent will if step_responses
    # is provided via mock= argument. The current _delegate_to_agent
    # signature doesn't accept a mock kwarg, so the sub-agent goes
    # through the full LLM path. We script a single LLM response on
    # the FakeAnthropicClient instead.
    from tests.fixtures.fakes import text_response
    engine.client.script(text_response("sub-agent finished"))

    result = await engine._delegate_to_agent(
        tool_input={
            "agent_name": "delegated_child",
            "context": {"q": "x"},
            "reason": "Test reason.",
        },
        call_order=1,
        parent_agent_version_id=parent.version.id,
        parent_decision_id=parent_decision_id,
    )

    # The delegation succeeded — tool_record has the sub-agent's output.
    assert result.get("error") is not True, result["output_data"]
    assert result["tool_name"] == "delegate_to_agent"
