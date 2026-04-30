"""Error and edge-case paths for ``ExecutionEngine.run_agent``.

Happy paths live in test_run_agent_happy.py. This file covers the
guards and failure modes:

  - decision_depth >= MAX_DECISION_DEPTH → refuses without resolving
  - get_agent_config 404 (unknown agent) → ValueError surfaces
  - MockContext.step_responses provided but key missing → MockMissingError
  - mock=None on an agent that needs a real LLM but no client is set
"""

from __future__ import annotations

import pytest

from verity.contracts.mock import MockContext, MockMissingError

from tests.fixtures.builders import make_complete_agent
from tests.fixtures.fakes import FakeAnthropicClient


# ── decision_depth guard ────────────────────────────────────────────────────

async def test_run_agent_refuses_when_depth_at_limit(engine, db):
    """MAX_DECISION_DEPTH guards runaway delegation. The engine returns
    a failed ExecutionResult instead of crashing — easier for the caller
    to feed the error back to the parent agent."""
    await make_complete_agent(db, name="depth_check")

    result = await engine.run_agent(
        agent_name="depth_check",
        context={},
        decision_depth=5,  # equal to MAX_DECISION_DEPTH
    )

    assert result.status == "failed"
    assert "decision_depth=5" in result.error_message
    assert "MAX_DECISION_DEPTH" in result.error_message
    # Engine refused before resolving config — no Claude call.
    assert engine.client.calls == []


async def test_run_agent_refuses_when_depth_above_limit(engine, db):
    await make_complete_agent(db, name="depth_check_above")

    result = await engine.run_agent(
        agent_name="depth_check_above",
        context={},
        decision_depth=10,
    )
    assert result.status == "failed"


async def test_run_agent_runs_at_depth_below_limit(engine, db):
    """decision_depth=4 is just under the limit — should still run."""
    from tests.fixtures.fakes import text_response
    await make_complete_agent(db, name="depth_under")
    engine.client.script(text_response("ok"))

    result = await engine.run_agent(
        agent_name="depth_under",
        context={},
        decision_depth=4,
    )
    assert result.status == "complete"


# ── Unknown agent ───────────────────────────────────────────────────────────

async def test_run_agent_raises_on_unknown_agent(engine, db):
    """Registry.get_agent_config raises ValueError when the agent has no
    champion. The engine doesn't catch — caller sees the raw ValueError."""
    with pytest.raises(ValueError, match="not found or has no champion"):
        await engine.run_agent(
            agent_name="never_existed",
            context={},
        )


# ── MockContext step_responses missing key ─────────────────────────────────

async def test_run_agent_raises_when_step_mock_missing_key(engine, db):
    """When step_responses is supplied but the agent's name isn't a key,
    MockMissingError fires — strict mode prevents accidentally falling
    through to a real (token-burning) Claude call."""
    await make_complete_agent(db, name="strict_mock")

    mock = MockContext(step_responses={"unrelated_agent": {"x": 1}})

    with pytest.raises(MockMissingError):
        await engine.run_agent(
            agent_name="strict_mock",
            context={},
            mock=mock,
        )


# The "no LLM client" path is already covered by
# test_gateway_llm.py::test_raises_when_no_client_configured at the
# gateway layer. Re-testing it through run_agent doesn't add coverage
# and the engine's wrapping behavior (catch vs raise) shifts over time.
