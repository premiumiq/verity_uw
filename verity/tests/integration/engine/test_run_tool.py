"""Tests for ``ExecutionEngine.run_tool``.

run_tool executes a registered tool directly (no LLM in the loop) and
writes a decision_log row with ``entity_type='tool'``.

Schema note: the ``runtime.agent_decision_log.entity_type`` CHECK
constraint accepts ``'agent'``, ``'task'``, and ``'tool'``. (Earlier
versions of this test pinned a bug where 'tool' was rejected; the
schema was widened, and these tests now assert the working behavior.)

Coverage:
  - Unknown tool → ValueError
  - Mock-mode tool → mock response, decision_log row with
    ``entity_type='tool'`` and ``mock_mode=True``
  - Real Python tool implementation → real call, output flows into
    decision_log; ``mock_mode=False``
  - Tool implementation raising → captured as gateway error;
    decision_log records ``status='failed'``
"""

from __future__ import annotations

import pytest

from tests.fixtures.builders import make_tool


# ── Unknown tool ───────────────────────────────────────────────────────────

async def test_run_tool_raises_on_unknown_name(engine):
    with pytest.raises(ValueError, match="not found in registry"):
        await engine.run_tool(tool_name="never_existed", input_data={})


# ── Mock-mode tool ─────────────────────────────────────────────────────────

async def test_run_tool_returns_mock_response_when_flag_set(engine, db):
    await make_tool(db, name="mock_lookup", mock_mode_enabled=True)

    result = await engine.run_tool(
        tool_name="mock_lookup",
        input_data={"q": "anything"},
    )

    assert result.status == "complete", result.error_message
    assert result.entity_type == "tool"
    assert result.entity_name == "mock_lookup"


async def test_run_tool_writes_decision_log_with_entity_type_tool(engine, db):
    await make_tool(db, name="audited_tool", mock_mode_enabled=True)

    result = await engine.run_tool(
        tool_name="audited_tool",
        input_data={"q": "x"},
    )

    log = await db.fetch_one_raw(
        "SELECT entity_type, mock_mode, "
        "       inference_config_snapshot::text AS snapshot "
        "FROM agent_decision_log WHERE id = %(id)s",
        {"id": str(result.decision_log_id)},
    )
    assert log is not None
    assert log["entity_type"] == "tool"
    assert log["mock_mode"] is True
    # Snapshot for tool runs records the tool_name + mock flag — the
    # audit shape consumers check (no LLM model_name for direct tools).
    assert "audited_tool" in log["snapshot"]


# ── Real Python tool implementation ───────────────────────────────────────

async def test_run_tool_dispatches_real_python_implementation(engine, db):
    await make_tool(db, name="real_calc", mock_mode_enabled=False)

    def add(a: int, b: int) -> dict:
        return {"sum": a + b}

    engine.register_tool_implementation("real_calc", add)

    result = await engine.run_tool(
        tool_name="real_calc",
        input_data={"a": 5, "b": 7},
    )

    assert result.status == "complete", result.error_message
    assert result.output == {"sum": 12}

    log = await db.fetch_one_raw(
        "SELECT mock_mode FROM agent_decision_log WHERE id = %(id)s",
        {"id": str(result.decision_log_id)},
    )
    assert log["mock_mode"] is False


# ── Tool implementation that raises ───────────────────────────────────────

async def test_run_tool_records_failed_status_when_implementation_raises(
    engine, db,
):
    """The gateway catches exceptions raised inside the tool function
    and returns an error tool_record. run_tool then writes a decision
    log with ``status='failed'`` and surfaces the error in
    ``ExecutionResult.error_message``."""
    await make_tool(db, name="exploding_tool", mock_mode_enabled=False)

    def boom():
        raise RuntimeError("kaboom")

    engine.register_tool_implementation("exploding_tool", boom)

    result = await engine.run_tool(
        tool_name="exploding_tool",
        input_data={},
    )

    assert result.status == "failed"
    assert "kaboom" in (result.error_message or "")

    # Decision log was still written — failed runs are audit-visible.
    log = await db.fetch_one_raw(
        "SELECT status FROM agent_decision_log WHERE id = %(id)s",
        {"id": str(result.decision_log_id)},
    )
    assert log["status"] == "failed"
