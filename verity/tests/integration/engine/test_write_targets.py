"""Tests for ``ExecutionEngine._write_targets`` and the
``_effective_write_mode`` write gate.

The write gate decides per-target what happens after the LLM call:
  - "write"     → call the connector
  - "log_only"  → record intent, skip connector

The gate combines:
  - MockContext.target_blocks (always wins; ensures validation/test
    runs are side-effect-free)
  - Explicit write_mode override ("write" or "log_only")
  - "auto" mode is channel-gated (write iff channel=production)

Tests:
  - _effective_write_mode pure unit tests cover the precedence table
  - _write_targets short-circuits to [] with no declared targets
  - _write_targets logs intent in log_only mode (no connector call)
  - _write_targets calls connector and records handle in write mode
  - _write_targets honors MockContext.target_blocks
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from verity.contracts.mock import MockContext
from verity.runtime.connectors import register_provider
from verity.runtime.engine import _effective_write_mode

from tests.fixtures.builders import make_complete_agent


# ── _effective_write_mode pure unit tests ──────────────────────────────────

def test_mock_block_always_wins():
    mode, reason = _effective_write_mode(
        write_mode="write", channel="production", mock_blocked=True,
    )
    assert mode == "log_only"
    assert reason == "mock_target_block"


def test_explicit_log_only_overrides_channel():
    mode, reason = _effective_write_mode(
        write_mode="log_only", channel="production", mock_blocked=False,
    )
    assert mode == "log_only"
    assert "log_only" in reason


def test_explicit_write_overrides_channel():
    mode, reason = _effective_write_mode(
        write_mode="write", channel="staging", mock_blocked=False,
    )
    assert mode == "write"
    assert "write" in reason


def test_auto_writes_in_production():
    mode, _reason = _effective_write_mode(
        write_mode="auto", channel="production", mock_blocked=False,
    )
    assert mode == "write"


@pytest.mark.parametrize("channel", ["development", "staging", "shadow", "evaluation"])
def test_auto_log_only_in_non_production(channel):
    mode, _reason = _effective_write_mode(
        write_mode="auto", channel=channel, mock_blocked=False,
    )
    assert mode == "log_only"


# ── _write_targets short-circuit (empty) ───────────────────────────────────

async def test_write_targets_empty_returns_empty(engine, db):
    bundle = await make_complete_agent(db, name="no_targets")
    writes = await engine._write_targets(
        version_id=bundle.version.id,
        owner_kind="agent_version",
        entity_name=bundle.name,
        input_data={},
        output={"x": 1},
        channel="production",
        write_mode="auto",
        mock=None,
    )
    assert writes == []


# ── _write_targets with one declared target ───────────────────────────────

class _FakeWriteProvider:
    """Records calls and returns a synthetic handle for tests."""

    def __init__(self):
        self.writes: list[dict[str, Any]] = []

    async def fetch(self, method: str, ref: Any) -> Any:
        raise NotImplementedError("write-only provider for tests")

    async def write(self, method: str, container, payload: dict) -> str:
        self.writes.append({"method": method, "container": container, "payload": payload})
        return f"handle-{len(self.writes)}"


async def _make_target(db, agent_version_id) -> tuple[uuid.UUID, _FakeWriteProvider]:
    """Insert a data_connector, write_target, and one payload field.
    Register a fake provider in the runtime registry. Returns
    (target_id, provider) for assertions."""
    # 1. data_connector row.
    conn_name = f"fake_writer_{uuid.uuid4().hex[:6]}"
    conn_row = await db.execute_returning(
        "insert_data_connector",
        {
            "name": conn_name,
            "connector_type": "test",
            "display_name": "Fake Writer",
            "description": "Test write target connector.",
            "config": json.dumps({}),
            "owner_name": "tests",
        },
    )
    connector_id = conn_row["id"]

    # 2. write_target row.
    target_row = await db.execute_returning(
        "insert_write_target",
        {
            "owner_kind": "agent_version",
            "owner_id": str(agent_version_id),
            "name": "result_target",
            "connector_id": str(connector_id),
            "write_method": "save",
            "container": "results",
            "required": False,
            "execution_order": 1,
            "description": None,
        },
    )
    target_id = target_row["id"]

    # 3. One payload field — copy output.x.
    await db.execute_returning(
        "insert_target_payload_field",
        {
            "write_target_id": str(target_id),
            "payload_field": "value",
            "reference": "output.x",
            "required": True,
            "execution_order": 1,
            "description": None,
        },
    )

    # 4. Register the fake provider so _write_targets can dispatch.
    provider = _FakeWriteProvider()
    register_provider(conn_name, provider)
    return target_id, provider


async def test_write_targets_log_only_skips_connector(engine, db):
    bundle = await make_complete_agent(db, name="log_only_target")
    _target_id, provider = await _make_target(db, bundle.version.id)

    writes = await engine._write_targets(
        version_id=bundle.version.id,
        owner_kind="agent_version",
        entity_name=bundle.name,
        input_data={},
        output={"x": 42},
        channel="production",
        write_mode="log_only",
        mock=None,
    )

    assert len(writes) == 1
    assert writes[0]["status"] == "logged"
    assert writes[0]["mode"] == "log_only"
    # The connector was NOT called.
    assert provider.writes == []


async def test_write_targets_writes_via_connector(engine, db):
    bundle = await make_complete_agent(db, name="real_target")
    _target_id, provider = await _make_target(db, bundle.version.id)

    writes = await engine._write_targets(
        version_id=bundle.version.id,
        owner_kind="agent_version",
        entity_name=bundle.name,
        input_data={},
        output={"x": 42},
        channel="production",
        write_mode="write",
        mock=None,
    )

    assert len(writes) == 1
    assert writes[0]["status"] == "wrote"
    assert writes[0]["handle"] == "handle-1"
    # The fake provider received the call with payload assembled from output.
    assert len(provider.writes) == 1
    assert provider.writes[0]["payload"] == {"value": 42}


async def test_write_targets_mock_target_block_overrides_write_mode(engine, db):
    """target_blocks is the strongest override — even write_mode='write'
    yields log_only when the block is set."""
    bundle = await make_complete_agent(db, name="blocked_target")
    _target_id, provider = await _make_target(db, bundle.version.id)

    mock = MockContext(target_blocks={"result_target"})

    writes = await engine._write_targets(
        version_id=bundle.version.id,
        owner_kind="agent_version",
        entity_name=bundle.name,
        input_data={},
        output={"x": 42},
        channel="production",
        write_mode="write",  # would write if not for the mock block
        mock=mock,
    )

    assert len(writes) == 1
    assert writes[0]["status"] == "logged"
    assert writes[0]["mode_reason"] == "mock_target_block"
    assert writes[0]["mocked"] is True
    assert provider.writes == []  # connector was NOT called
