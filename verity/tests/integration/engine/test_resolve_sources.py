"""Tests for ``ExecutionEngine._resolve_sources`` — pre-prompt input
resolution from declared source_binding rows.

Reference DSL (in source_binding.reference):
  input.<path>            — copy a value out of input_data
  const:<value>           — overlay a constant
  fetch:<conn>/<method>(input.<field>) — call a registered connector

This file exercises:
  - Empty: no bindings → returns input_data unchanged
  - input.<path> binding overlays the value
  - const:<value> binding overlays the constant
  - Malformed reference raises SourceResolutionError
  - MockContext.source_responses skips connector fetch

Connector-fetch happy paths require a registered provider (covered
by test_run_agent_happy where the engine wires it end-to-end).
"""

from __future__ import annotations

import uuid

import pytest

from verity.contracts.mock import MockContext

from tests.fixtures.builders import make_complete_agent


async def _add_source_binding(
    db, *, owner_kind: str, owner_id, template_var: str,
    reference: str, binding_kind: str = "text", required: bool = True,
    execution_order: int = 1,
):
    await db.execute(
        "insert_source_binding",
        {
            "owner_kind": owner_kind,
            "owner_id": str(owner_id),
            "template_var": template_var,
            "reference": reference,
            "binding_kind": binding_kind,
            "required": required,
            "execution_order": execution_order,
            "description": None,
        },
    )


# ── Empty: no bindings short-circuit ───────────────────────────────────────

async def test_resolve_sources_empty_returns_input_unchanged(engine, db):
    bundle = await make_complete_agent(db, name="no_bindings")
    template_ctx, blocks, resolutions = await engine._resolve_sources(
        version_id=bundle.version.id,
        owner_kind="agent_version",
        entity_name=bundle.name,
        input_data={"foo": "bar"},
        mock=None,
    )
    assert template_ctx == {"foo": "bar"}
    assert blocks == []
    assert resolutions == []


# ── input.<path> binding ───────────────────────────────────────────────────

async def test_resolve_sources_input_path_binding_copies_value(engine, db):
    bundle = await make_complete_agent(db, name="input_binding")
    await _add_source_binding(
        db, owner_kind="agent_version", owner_id=bundle.version.id,
        template_var="customer_name", reference="input.customer_name",
    )

    template_ctx, blocks, resolutions = await engine._resolve_sources(
        version_id=bundle.version.id,
        owner_kind="agent_version",
        entity_name=bundle.name,
        input_data={"customer_name": "Acme Corp"},
        mock=None,
    )
    assert template_ctx["customer_name"] == "Acme Corp"
    assert blocks == []
    assert len(resolutions) == 1
    assert resolutions[0]["template_var"] == "customer_name"


# ── const:<value> binding ──────────────────────────────────────────────────

async def test_resolve_sources_const_binding_overlays_constant(engine, db):
    bundle = await make_complete_agent(db, name="const_binding")
    await _add_source_binding(
        db, owner_kind="agent_version", owner_id=bundle.version.id,
        template_var="region", reference="const:US-NY",
    )

    template_ctx, _blocks, resolutions = await engine._resolve_sources(
        version_id=bundle.version.id,
        owner_kind="agent_version",
        entity_name=bundle.name,
        input_data={},
        mock=None,
    )
    assert template_ctx["region"] == "US-NY"
    assert resolutions[0]["status"] == "resolved"


# ── Malformed reference ────────────────────────────────────────────────────

async def test_resolve_sources_malformed_reference_raises(engine, db):
    """A registration-level data error (bad DSL syntax) must abort —
    the engine can't fall through to a partial run."""
    from verity.runtime.connectors import SourceResolutionError

    bundle = await make_complete_agent(db, name="bad_ref")
    await _add_source_binding(
        db, owner_kind="agent_version", owner_id=bundle.version.id,
        template_var="x", reference="garbled@not@valid",
    )

    with pytest.raises(SourceResolutionError):
        await engine._resolve_sources(
            version_id=bundle.version.id,
            owner_kind="agent_version",
            entity_name=bundle.name,
            input_data={},
            mock=None,
        )


# ── MockContext.source_responses short-circuits fetch ──────────────────────

async def test_resolve_sources_mock_skips_fetch(engine, db):
    """When MockContext.source_responses has the input field name as a
    key, the connector fetch is skipped and the mock value is bound.
    Verifies mocking semantics without registering a real provider."""
    bundle = await make_complete_agent(db, name="mocked_fetch")
    await _add_source_binding(
        db, owner_kind="agent_version", owner_id=bundle.version.id,
        template_var="document_text",
        reference="fetch:edms/get_document_text(input.doc_id)",
    )

    mock = MockContext(source_responses={"doc_id": "Mocked document body."})

    template_ctx, _blocks, resolutions = await engine._resolve_sources(
        version_id=bundle.version.id,
        owner_kind="agent_version",
        entity_name=bundle.name,
        input_data={"doc_id": "doc-1"},
        mock=mock,
    )
    assert template_ctx["document_text"] == "Mocked document body."
    # Audit row should mark this as mocked, not a real fetch.
    assert resolutions[0]["mocked"] is True
