"""Tests for ``ExecutionEngine.run_tool``.

run_tool executes a registered tool directly (no LLM in the loop) and
attempts to write a decision_log row with entity_type='tool'.

KNOWN PRODUCTION BUG (as of this test's writing):
  ``runtime.agent_decision_log.entity_type`` carries
  ``CHECK (entity_type IN ('agent', 'task'))``. ``run_tool`` writes
  ``entity_type='tool'``, which violates the constraint. The engine's
  outer try/except catches the violation and returns an
  ``ExecutionResult(status='failed', error_message=...)``.

The tests below pin current behavior — when the schema is updated to
accept 'tool' (or run_tool is changed to use a different entity_type),
the assertions should flip from 'failed' to 'complete'. The
``test_run_tool_*_currently_fails_due_to_*_check`` test names are
intentional bug-tracker breadcrumbs.

Coverage:
  - Unknown tool → ValueError (works correctly today)
  - Tool execution does the gateway dispatch (mocked or real) and
    THEN fails the decision log write — error_message captures the
    underlying constraint violation
"""

from __future__ import annotations

import pytest

from tests.fixtures.builders import make_tool


# ── Unknown tool: ValueError before any write ──────────────────────────────

async def test_run_tool_raises_on_unknown_name(engine):
    """Tool not in registry → ValueError raised before any decision_log
    write attempt. This path is unaffected by the schema bug."""
    with pytest.raises(ValueError, match="not found in registry"):
        await engine.run_tool(tool_name="never_existed", input_data={})


# ── Known-bug tests pinned to current behavior ─────────────────────────────

async def test_run_tool_with_mock_flag_currently_fails_due_to_entity_type_check(
    engine, db,
):
    """Mock-mode tool: gateway returns mock response, but the
    decision_log INSERT violates the entity_type CHECK constraint.
    Engine returns failed ExecutionResult with the constraint message
    in error_message."""
    await make_tool(db, name="mock_lookup", mock_mode_enabled=True)

    result = await engine.run_tool(
        tool_name="mock_lookup",
        input_data={"q": "anything"},
    )

    # Pinned to current behavior — see file docstring.
    assert result.status == "failed"
    assert result.entity_type == "tool"
    assert result.entity_name == "mock_lookup"
    assert "agent_decision_log_entity_type_check" in (result.error_message or "")


async def test_run_tool_with_real_impl_currently_fails_due_to_entity_type_check(
    engine, db,
):
    """Real Python impl: gateway dispatches the function (we can verify
    side effects), but the decision_log write still fails the CHECK."""
    await make_tool(db, name="real_calc", mock_mode_enabled=False)

    calls: list[dict] = []

    def add(a: int, b: int) -> dict:
        calls.append({"a": a, "b": b})
        return {"sum": a + b}

    engine.register_tool_implementation("real_calc", add)

    result = await engine.run_tool(
        tool_name="real_calc",
        input_data={"a": 5, "b": 7},
    )

    # The implementation DID get called — the gateway dispatch itself
    # works. The bug is in the post-dispatch decision_log write.
    assert calls == [{"a": 5, "b": 7}]
    # Pinned to current behavior.
    assert result.status == "failed"
    assert "agent_decision_log_entity_type_check" in (result.error_message or "")


async def test_run_tool_no_decision_log_row_when_check_constraint_fails(
    engine, db,
):
    """Confirm that on failure the engine's exception handler returns
    decision_log_id=UUID(int=0) and no row is actually persisted."""
    from uuid import UUID

    await make_tool(db, name="exploding_audit", mock_mode_enabled=True)

    result = await engine.run_tool(
        tool_name="exploding_audit",
        input_data={"q": "x"},
    )

    assert result.status == "failed"
    assert result.decision_log_id == UUID(int=0)

    # And the table really is unchanged (no row was inserted).
    rows = await db.fetch_all_raw(
        "SELECT count(*) AS n FROM runtime.agent_decision_log",
    )
    assert rows[0]["n"] == 0
