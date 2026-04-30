"""Tests for ``ExecutionEngine._gateway_tool_call``.

The tool gateway routes every tool call through one of three paths:

  1. Runtime mock — MockContext.tool_responses[tool_name] match → return
     the supplied dict verbatim, mock_source='runtime'
  2. DB mock-all — MockContext.mock_all_tools=True → return DB-registered
     mock_response, mock_source='db_all'
  3. DB flag fallback — mock=None and tool_def.mock_mode_enabled=True →
     return DB mock, mock_source='db_flag'
  4. Real dispatch — fall through to _execute_real_tool, which routes by
     tool_def.transport (python_inprocess in these tests; mcp_* and
     verity_builtin tested separately)

These tests construct ``ToolAuthorization`` objects directly rather than
going through the registry — the gateway only reads attributes.
"""

from __future__ import annotations

import uuid

from verity.contracts.mock import MockContext
from verity.contracts.tool import ToolAuthorization


def _tool_auth(
    name: str,
    *,
    transport: str = "python_inprocess",
    mock_mode_enabled: bool = False,
    implementation_path: str | None = None,
) -> ToolAuthorization:
    """Build a minimal ToolAuthorization for gateway tests."""
    return ToolAuthorization(
        tool_id=uuid.uuid4(),
        name=name,
        display_name=name,
        description=f"Test tool {name}.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        transport=transport,
        implementation_path=implementation_path or f"tests.tools.{name}",
        mock_mode_enabled=mock_mode_enabled,
    )


# ── Path 1: runtime mock via MockContext.tool_responses ────────────────────

async def test_runtime_mock_short_circuits_before_dispatch(engine):
    """When MockContext supplies a tool_response, the gateway returns it
    verbatim — it must not touch tool_implementations or transport."""
    auth = [_tool_auth("lookup_policy")]
    mock = MockContext(tool_responses={"lookup_policy": {"policy_id": "P-1"}})

    result = await engine._gateway_tool_call(
        tool_name="lookup_policy",
        tool_input={"id": "P-1"},
        authorized_tools=auth,
        mock=mock,
        call_order=1,
    )

    assert result["mock_mode"] is True
    assert result["mock_source"] == "runtime"
    assert result["output_data"] == {"policy_id": "P-1"}
    # Original input is preserved in the result dict for the audit trail.
    assert result["input_data"] == {"id": "P-1"}


async def test_runtime_mock_supports_list_for_multi_call(engine):
    """When the same tool is called twice, a list value consumes one
    response per call — required for tests that exercise loops."""
    auth = [_tool_auth("get_record")]
    mock = MockContext(tool_responses={
        "get_record": [{"page": 1}, {"page": 2}],
    })

    r1 = await engine._gateway_tool_call(
        tool_name="get_record", tool_input={}, authorized_tools=auth,
        mock=mock, call_order=1,
    )
    r2 = await engine._gateway_tool_call(
        tool_name="get_record", tool_input={}, authorized_tools=auth,
        mock=mock, call_order=2,
    )
    assert r1["output_data"] == {"page": 1}
    assert r2["output_data"] == {"page": 2}


# ── Path 2: mock_all_tools ─────────────────────────────────────────────────

async def test_mock_all_tools_uses_db_default_response(engine):
    """When mock_all_tools=True, even tools NOT in tool_responses get
    a canned response from the DB-registered mock (default fallback
    when no mock_responses is set on the tool)."""
    auth = [_tool_auth("any_tool")]
    mock = MockContext(mock_all_tools=True)

    result = await engine._gateway_tool_call(
        tool_name="any_tool", tool_input={}, authorized_tools=auth,
        mock=mock, call_order=1,
    )
    assert result["mock_mode"] is True
    assert result["mock_source"] == "db_all"


# ── Path 3: DB flag fallback (mock=None) ───────────────────────────────────

async def test_db_flag_mocks_when_no_mock_context(engine):
    """No MockContext + tool.mock_mode_enabled=True → DB mock is used."""
    auth = [_tool_auth("flagged_tool", mock_mode_enabled=True)]

    result = await engine._gateway_tool_call(
        tool_name="flagged_tool", tool_input={}, authorized_tools=auth,
        mock=None, call_order=1,
    )
    assert result["mock_mode"] is True
    assert result["mock_source"] == "db_flag"


async def test_runtime_mock_overrides_db_flag(engine):
    """When MockContext supplies tool_responses, the gateway honors that
    over the DB flag — the caller is in explicit control."""
    auth = [_tool_auth("flagged_tool", mock_mode_enabled=True)]
    mock = MockContext(tool_responses={"flagged_tool": {"override": True}})

    result = await engine._gateway_tool_call(
        tool_name="flagged_tool", tool_input={}, authorized_tools=auth,
        mock=mock, call_order=1,
    )
    assert result["mock_source"] == "runtime"
    assert result["output_data"] == {"override": True}


# ── Path 4: real dispatch (python_inprocess) ───────────────────────────────

async def test_real_dispatch_calls_registered_python_tool(engine):
    """No mock + mock_mode_enabled=False → the registered Python callable
    is invoked. Output_data reflects what the callable returned."""
    auth = [_tool_auth("add", mock_mode_enabled=False)]

    def add(a: int, b: int) -> dict:
        return {"sum": a + b}

    engine.register_tool_implementation("add", add)

    result = await engine._gateway_tool_call(
        tool_name="add", tool_input={"a": 2, "b": 3},
        authorized_tools=auth, mock=None, call_order=1,
    )
    assert result.get("mock_mode") is not True
    assert result["output_data"] == {"sum": 5}
    assert result["transport"] == "python_inprocess"


async def test_real_dispatch_supports_async_python_tool(engine):
    """Tool implementations may be ``async def`` — the dispatcher detects
    coroutine functions and awaits them."""
    auth = [_tool_auth("async_tool", mock_mode_enabled=False)]

    async def fetch():
        return {"async": True}

    engine.register_tool_implementation("async_tool", fetch)

    result = await engine._gateway_tool_call(
        tool_name="async_tool", tool_input={},
        authorized_tools=auth, mock=None, call_order=1,
    )
    assert result["output_data"] == {"async": True}


async def test_real_dispatch_returns_error_when_no_implementation(engine):
    """Tool authorized in DB but no Python callable registered → error
    dict, NOT an exception. The agent loop can feed this back to Claude."""
    auth = [_tool_auth("missing_impl", mock_mode_enabled=False)]

    result = await engine._gateway_tool_call(
        tool_name="missing_impl", tool_input={},
        authorized_tools=auth, mock=None, call_order=1,
    )
    assert result["error"] is True
    assert "No implementation registered" in result["output_data"]["error"]


async def test_real_dispatch_returns_error_when_implementation_raises(engine):
    """A Python tool that raises is caught — returns error dict so the
    agent loop can decide how to react. Crash-loops would be worse."""
    auth = [_tool_auth("buggy", mock_mode_enabled=False)]

    def buggy():
        raise RuntimeError("boom")

    engine.register_tool_implementation("buggy", buggy)

    result = await engine._gateway_tool_call(
        tool_name="buggy", tool_input={},
        authorized_tools=auth, mock=None, call_order=1,
    )
    assert result["error"] is True
    assert "Tool execution failed" in result["output_data"]["error"]
    assert "boom" in result["output_data"]["error"]


# ── Unknown transport ──────────────────────────────────────────────────────

async def test_unknown_transport_returns_error(engine):
    """A typo'd transport in the DB shouldn't crash the run — return an
    error dict with an explanatory message."""
    auth = [_tool_auth(
        "weird", transport="not_a_transport", mock_mode_enabled=False,
    )]

    result = await engine._gateway_tool_call(
        tool_name="weird", tool_input={},
        authorized_tools=auth, mock=None, call_order=1,
    )
    assert result["error"] is True
    assert "Unknown tool transport" in result["output_data"]["error"]
    assert "not_a_transport" in result["output_data"]["error"]
