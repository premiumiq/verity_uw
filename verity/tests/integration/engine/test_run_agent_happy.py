"""End-to-end happy-path tests for ``ExecutionEngine.run_agent``.

These tests wire up a complete agent (agent + version + prompt +
assignment, optionally authorized tools), promote it to champion so
``Registry.get_agent_config`` resolves it, then exercise three flavors:

  1. Step-mock short-circuit  — caller supplies MockContext.step_responses
                                with this agent's name; engine skips
                                Claude entirely. Cheapest end-to-end test.
  2. Real-LLM single-turn      — FakeAnthropicClient scripted with one
                                text response; engine returns it, writes
                                a decision_log row.
  3. Real-LLM with tool call   — two scripted responses (tool_use →
                                final text). Engine dispatches the tool
                                via the python_inprocess path and feeds
                                the result back to Claude.

Decision log writes are real — they hit the per-test DB. Tests assert
on the persisted row to confirm the audit trail landed correctly.
"""

from __future__ import annotations

from verity.contracts.mock import MockContext

from tests.fixtures.builders import (
    authorize_tool,
    make_complete_agent,
    make_tool,
)
from tests.fixtures.fakes import (
    FakeTextBlock,
    FakeToolUseBlock,
    text_response,
    tool_use_response,
)


# ── 1. Step-mock short-circuit ─────────────────────────────────────────────

async def test_step_mock_skips_llm_and_writes_decision_log(engine, db):
    """When MockContext.step_responses names the agent, the engine
    bypasses Claude AND tools but still writes a complete decision_log
    entry — same audit shape as a real run."""
    await make_complete_agent(db, name="risk_extractor")

    canned_output = {"risk_factors": ["fire", "flood"], "score": 0.42}
    mock = MockContext(step_responses={"risk_extractor": canned_output})

    result = await engine.run_agent(
        agent_name="risk_extractor",
        context={"document_id": "doc-1"},
        mock=mock,
    )

    assert result.entity_type == "agent"
    assert result.entity_name == "risk_extractor"
    assert result.output == canned_output
    assert result.status == "complete"
    # Mocked path consumes no tokens.
    assert result.input_tokens == 0
    assert result.output_tokens == 0

    # Verify a decision_log row landed with mock_mode=True.
    log = await db.fetch_one_raw(
        "SELECT entity_type, mock_mode, output_json::text AS output_json "
        "FROM agent_decision_log WHERE id = %(id)s",
        {"id": str(result.decision_log_id)},
    )
    assert log is not None
    assert log["entity_type"] == "agent"
    assert log["mock_mode"] is True

    # FakeAnthropicClient was never called — step-mock path is total bypass.
    assert engine.client.calls == []


# ── 2. Real-LLM single-turn ────────────────────────────────────────────────

async def test_single_turn_text_response(engine, db):
    """Simplest non-mocked path: Claude returns one text block, engine
    returns the text as the agent's output, decision_log captures it."""
    await make_complete_agent(db, name="explainer")

    engine.client.script(text_response(
        "Risk score: 0.7. Drivers: aging infrastructure.",
        input_tokens=120, output_tokens=18,
    ))

    result = await engine.run_agent(
        agent_name="explainer",
        context={"asset_id": "asset-42"},
    )

    assert result.status == "complete"
    assert result.entity_name == "explainer"
    assert result.input_tokens == 120
    assert result.output_tokens == 18
    # The text is preserved in output_summary for the audit UI.
    assert "Risk score" in result.output_summary
    assert len(engine.client.calls) == 1


# ── 3. Real-LLM with one tool call ─────────────────────────────────────────

async def test_multi_turn_with_tool_call(engine, db):
    """Two-turn flow: Claude requests a tool, engine dispatches it,
    Claude sees the tool result and emits a final text answer."""
    tool = await make_tool(db, name="lookup_property", mock_mode_enabled=False)
    await make_complete_agent(db, name="property_qa", tools=[tool])

    # Register the in-process implementation the engine will dispatch.
    def lookup_property(property_id: str) -> dict:
        return {"property_id": property_id, "year_built": 1972}

    engine.register_tool_implementation("lookup_property", lookup_property)

    # Turn 1: Claude asks to call the tool.
    # Turn 2: Claude consumes the tool_result and returns a final answer.
    engine.client.script(
        tool_use_response(
            tool_name="lookup_property",
            tool_input={"property_id": "P-99"},
            tool_use_id="toolu_01",
            leading_text="Looking up the property.",
        ),
        text_response("The property at P-99 was built in 1972."),
    )

    result = await engine.run_agent(
        agent_name="property_qa",
        context={"property_id": "P-99"},
    )

    assert result.status == "complete"
    # Two turns → two messages.create calls.
    assert len(engine.client.calls) == 2
    # The final-turn text appears somewhere in the result.
    assert "1972" in result.output_summary
    # tool_calls reflects the dispatch the engine made.
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool_name"] == "lookup_property"
    assert result.tool_calls[0]["output_data"] == {
        "property_id": "P-99", "year_built": 1972,
    }


# ── 4. Decision log carries inference_config_snapshot ──────────────────────

async def test_decision_log_records_inference_config_snapshot(engine, db):
    """The decision_log's inference_config_snapshot is the JSON proof of
    what params Claude was actually called with — required for audit
    reproducibility. This test confirms it lands non-empty."""
    await make_complete_agent(db, name="snapshot_check")
    engine.client.script(text_response("ok"))

    result = await engine.run_agent(
        agent_name="snapshot_check",
        context={"q": "x"},
    )

    log = await db.fetch_one_raw(
        "SELECT inference_config_snapshot::text AS snapshot "
        "FROM agent_decision_log WHERE id = %(id)s",
        {"id": str(result.decision_log_id)},
    )
    assert log is not None
    snapshot = log["snapshot"]
    # The snapshot is JSON; confirm it's a non-empty object string.
    assert snapshot.startswith("{")
    assert snapshot != "{}"
    assert "claude" in snapshot.lower()
