"""End-to-end happy-path tests for ``ExecutionEngine.run_task``.

run_task differs from run_agent in two material ways:
  - It expects single-turn structured output (no agentic loop)
  - The output_schema is enforced — the LLM call sets tool_choice or
    parses the JSON response

Tests:
  1. Step-mock short-circuit  — same shape as run_agent step-mock
  2. Real-LLM single-turn     — JSON text response → parsed output
  3. Decision log row written
"""

from __future__ import annotations

import json

from verity.contracts.mock import MockContext

from tests.fixtures.builders import make_complete_task
from tests.fixtures.fakes import text_response


# ── Step-mock short-circuit ────────────────────────────────────────────────

async def test_step_mock_skips_llm_for_task(engine, db):
    await make_complete_task(db, name="extract_risk")

    canned = {"risk_score": 0.7, "drivers": ["age"]}
    mock = MockContext(step_responses={"extract_risk": canned})

    result = await engine.run_task(
        task_name="extract_risk",
        input_data={"document_id": "doc-1"},
        mock=mock,
    )

    assert result.entity_type == "task"
    assert result.output == canned
    assert result.status == "complete"
    assert result.input_tokens == 0
    # Mocked path — no LLM call.
    assert engine.client.calls == []


async def test_step_mock_writes_decision_log_row_for_task(engine, db):
    await make_complete_task(db, name="extract_v2")
    mock = MockContext(step_responses={"extract_v2": {"k": "v"}})

    result = await engine.run_task(
        task_name="extract_v2",
        input_data={"x": 1},
        mock=mock,
    )

    log = await db.fetch_one_raw(
        "SELECT entity_type, mock_mode FROM agent_decision_log "
        "WHERE id = %(id)s",
        {"id": str(result.decision_log_id)},
    )
    assert log is not None
    assert log["entity_type"] == "task"
    assert log["mock_mode"] is True


# ── Real-LLM single-turn ───────────────────────────────────────────────────

async def test_run_task_parses_json_response(engine, db):
    """Tasks expect structured output — Claude returns JSON text and the
    engine surfaces the parsed dict as ExecutionResult.output."""
    await make_complete_task(db, name="parse_check")
    payload = {"risk_score": 0.42, "rationale": "Building age."}

    engine.client.script(text_response(
        json.dumps(payload),
        input_tokens=80, output_tokens=20,
    ))

    result = await engine.run_task(
        task_name="parse_check",
        input_data={"property_id": "P-1"},
    )

    assert result.status == "complete"
    assert result.output == payload
    assert result.input_tokens == 80
    assert result.output_tokens == 20
    assert len(engine.client.calls) == 1


async def test_run_task_records_inference_config_snapshot(engine, db):
    """Same audit guarantee as run_agent — the per-call inference params
    must be persisted in the decision log."""
    await make_complete_task(db, name="audit_task")
    engine.client.script(text_response('{"ok": true}'))

    result = await engine.run_task(
        task_name="audit_task",
        input_data={"q": "x"},
    )

    log = await db.fetch_one_raw(
        "SELECT inference_config_snapshot::text AS snapshot "
        "FROM agent_decision_log WHERE id = %(id)s",
        {"id": str(result.decision_log_id)},
    )
    snapshot = log["snapshot"]
    assert snapshot.startswith("{")
    assert "claude" in snapshot.lower()
