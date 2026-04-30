"""Engine test harness.

The ``engine`` fixture wires up an ``ExecutionEngine`` against the
per-test cloned DB, with the LLM client replaced by ``FakeAnthropicClient``.
Real ``Registry`` and ``DecisionsWriter`` — we want to exercise the
production read/write paths against the test DB.

Construction shape:

    engine = await make_engine(db, llm_responses=[...])
    # or, the fixture form:
    async def test_x(engine):
        ...

The fixture creates an empty FakeAnthropicClient by default. Tests
script responses via ``engine.client.script(...)``.
"""

from __future__ import annotations

import pytest_asyncio

from verity.governance.registry import Registry
from verity.runtime.decisions_writer import DecisionsWriter
from verity.runtime.engine import ExecutionEngine

from tests.fixtures.fakes import FakeAnthropicClient


def _build_engine(db) -> ExecutionEngine:
    """Construct an ExecutionEngine wired to the test DB.

    Empty anthropic_api_key → ``engine.client`` is None. Tests should
    set ``engine.client = FakeAnthropicClient(...)`` before any code path
    that hits ``_gateway_llm_call``. The ``engine`` fixture below does
    this once per test.
    """
    registry = Registry(db)
    decisions = DecisionsWriter(db)
    return ExecutionEngine(
        registry=registry,
        decisions=decisions,
        anthropic_api_key="",          # → engine.client is None
        application="tests",
        mcp_client=None,                # MCP path tested separately
        models=None,                    # skip model_invocation_log writes
    )


@pytest_asyncio.fixture
async def engine(db):
    """Per-test ExecutionEngine with a stubbed Anthropic client.

    Tests typically:
      1. Use builders to register the agent_version / prompts / tools
         the test exercises.
      2. Script responses on engine.client (FakeAnthropicClient).
      3. Call engine.run_agent(...) / engine.run_tool(...) / etc.
    """
    eng = _build_engine(db)
    eng.client = FakeAnthropicClient()
    yield eng
