"""YAML import — slice 4B.

Exercises the Importer + serialization round-trip behaviours that
don't need a second DB clone. Round-trip across two databases lives
in ``test_yaml_roundtrip.py``.
"""

from __future__ import annotations

import pytest

from tests.fixtures.builders import make_complete_agent
from verity.governance.registry import Registry
from verity.governance.yaml_io import (
    Bundle,
    Exporter,
    Importer,
    ImportValidationError,
    InferenceConfigEntry,
    PromptAssignment,
    PromptEntry,
    PromptVersionEntry,
    ToolAuthorization,
    ToolEntry,
    AgentEntry,
    AgentVersionEntry,
    dumps_bundle,
    loads_bundle,
)


# ── Validation phase: dangling references ─────────────────────────────────


async def test_import_dangling_prompt_reference_raises_validation_error(db):
    """An agent_version that references a prompt+version that exists
    in neither the bundle nor the DB must fail validation BEFORE any
    writes."""
    bundle = Bundle(
        entities=[
            AgentEntry(
                name="lonely_agent",
                display_name="Lonely Agent",
                description="No deps shipped.",
                versions=[
                    AgentVersionEntry(
                        version_label="1.0.0",
                        change_summary="Initial.",
                        # References a prompt that doesn't exist.
                        prompts=[
                            PromptAssignment(
                                prompt="missing_prompt",
                                version="1.0.0",
                                api_role="system",
                                governance_tier="behavioural",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )

    importer = Importer(Registry(db))
    with pytest.raises(ImportValidationError) as exc_info:
        await importer.import_bundle(bundle)

    errors = exc_info.value.errors
    assert len(errors) >= 1
    dangling = [e for e in errors if e.code == "dangling_reference"]
    assert dangling, "Expected at least one dangling_reference error"
    assert "missing_prompt" in dangling[0].message
    # Path must point at the prompt assignment so the user can find it.
    assert "prompts[0]" in dangling[0].path


async def test_import_dangling_tool_reference_aggregates_with_others(db):
    """All validation errors are reported at once — one error fixed
    at a time is friction the user shouldn't have to absorb."""
    bundle = Bundle(
        entities=[
            AgentEntry(
                name="multi_error_agent",
                display_name="Has Two Problems",
                description="d",
                versions=[
                    AgentVersionEntry(
                        version_label="1.0.0",
                        change_summary="Initial.",
                        inference_config="missing_config",
                        tools=[
                            ToolAuthorization(tool="missing_tool"),
                        ],
                    ),
                ],
            ),
        ],
    )

    importer = Importer(Registry(db))
    with pytest.raises(ImportValidationError) as exc_info:
        await importer.import_bundle(bundle)

    codes = {e.code for e in exc_info.value.errors}
    assert "dangling_reference" in codes
    # Two distinct dangling refs — config and tool — both reported.
    paths = [e.path for e in exc_info.value.errors]
    assert any("inference_config" in p for p in paths)
    assert any("tools[0]" in p for p in paths)


# ── Lifecycle state ignored on import ─────────────────────────────────────


async def test_import_creates_versions_as_draft_regardless_of_yaml_state(db):
    """The YAML can claim ``lifecycle_state: champion`` but the
    importer must create the row as ``draft`` — promotion is a
    deliberate human action, not a YAML side-effect."""
    # Build a tiny standalone bundle with a prompt claiming champion state.
    bundle = Bundle(
        entities=[
            PromptEntry(
                name="champion_in_yaml",
                display_name="Champion In Yaml",
                description="d",
                versions=[
                    PromptVersionEntry(
                        version_label="1.0.0",
                        lifecycle_state="champion",   # ← informational only
                        api_role="system",
                        governance_tier="behavioural",
                        change_summary="Initial.",
                        content="Hello.",
                    ),
                ],
            ),
        ],
    )

    importer = Importer(Registry(db))
    result = await importer.import_bundle(bundle)
    assert ("Prompt", "champion_in_yaml", "1.0.0") in result.versions_inserted

    # Verify the actual DB row is in draft, not champion.
    row = await db.fetch_one_raw(
        """
        SELECT pv.lifecycle_state
        FROM governance.prompt_version pv
        JOIN governance.prompt p ON p.id = pv.prompt_id
        WHERE p.name = %(name)s AND pv.version_label = %(label)s
        """,
        {"name": "champion_in_yaml", "label": "1.0.0"},
    )
    assert row is not None
    assert str(row["lifecycle_state"]) == "draft", (
        "Imported version must be in draft regardless of YAML's "
        "lifecycle_state field."
    )


# ── Idempotency: re-importing the same bundle is a no-op ─────────────────


async def test_reimport_skips_existing_rows(db):
    """Re-importing the same bundle into the same DB leaves all
    existing rows in place and reports them as skipped."""
    bundle = Bundle(
        entities=[
            ToolEntry(
                name="idempotent_tool",
                display_name="Idempotent Tool",
                description="d",
                transport="python_inprocess",
                implementation_path="x.y.z",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            ),
        ],
    )

    importer = Importer(Registry(db))
    first = await importer.import_bundle(bundle)
    assert ("Tool", "idempotent_tool") in first.headers_inserted
    assert first.headers_skipped == []

    second_importer = Importer(Registry(db))
    second = await second_importer.import_bundle(bundle)
    assert second.headers_inserted == []
    assert ("Tool", "idempotent_tool") in second.headers_skipped


# ── Wiring inserted correctly on a new agent_version ─────────────────────


async def test_import_wires_prompt_and_tool_to_new_agent_version(db):
    """A complete bundle must result in entity_prompt_assignment and
    agent_version_tool rows linked to the freshly-created agent_version."""
    bundle = Bundle(
        entities=[
            InferenceConfigEntry(
                name="test_default_config_clone",
                display_name="Cloned Default Config",
                model_name="claude-sonnet-4-20250514",
                temperature=0.0,
                max_tokens=4096,
            ),
            ToolEntry(
                name="wired_tool",
                display_name="Wired Tool",
                description="d",
                transport="python_inprocess",
                implementation_path="x.y.wired",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            ),
            PromptEntry(
                name="wired_prompt",
                display_name="Wired Prompt",
                description="d",
                versions=[
                    PromptVersionEntry(
                        version_label="1.0.0",
                        api_role="system",
                        governance_tier="behavioural",
                        change_summary="Initial.",
                        content="System prompt content.",
                    ),
                ],
            ),
            AgentEntry(
                name="wired_agent",
                display_name="Wired Agent",
                description="d",
                purpose="test",
                domain="underwriting",
                materiality_tier="low",
                owner_name="Test Owner",
                versions=[
                    AgentVersionEntry(
                        version_label="1.0.0",
                        change_summary="Initial.",
                        inference_config="test_default_config_clone",
                        prompts=[
                            PromptAssignment(
                                prompt="wired_prompt",
                                version="1.0.0",
                                api_role="system",
                                governance_tier="behavioural",
                                execution_order=1,
                                is_required=True,
                            ),
                        ],
                        tools=[
                            ToolAuthorization(tool="wired_tool", authorized=True),
                        ],
                    ),
                ],
            ),
        ],
    )

    importer = Importer(Registry(db))
    result = await importer.import_bundle(bundle)

    # Every entity made it in.
    inserted_kinds = {k for (k, _) in result.headers_inserted}
    assert {"InferenceConfig", "Tool", "Prompt", "Agent"} <= inserted_kinds

    # The agent_version exists and has the right wiring.
    av_row = await db.fetch_one_raw(
        """
        SELECT av.id
        FROM governance.agent_version av
        JOIN governance.agent a ON a.id = av.agent_id
        WHERE a.name = 'wired_agent' AND av.version_label = '1.0.0'
        """,
        {},
    )
    assert av_row is not None
    av_id = str(av_row["id"])

    prompt_assignments = await db.fetch_all_raw(
        """
        SELECT pv.version_label, p.name AS prompt_name
        FROM governance.entity_prompt_assignment epa
        JOIN governance.prompt_version pv ON pv.id = epa.prompt_version_id
        JOIN governance.prompt p ON p.id = pv.prompt_id
        WHERE epa.entity_type = 'agent' AND epa.entity_version_id = %(id)s
        """,
        {"id": av_id},
    )
    assert len(prompt_assignments) == 1
    assert prompt_assignments[0]["prompt_name"] == "wired_prompt"

    tool_auths = await db.fetch_all_raw(
        """
        SELECT t.name
        FROM governance.agent_version_tool avt
        JOIN governance.tool t ON t.id = avt.tool_id
        WHERE avt.agent_version_id = %(id)s AND avt.authorized = TRUE
        """,
        {"id": av_id},
    )
    assert len(tool_auths) == 1
    assert tool_auths[0]["name"] == "wired_tool"


# ── Resolves to existing DB rows ─────────────────────────────────────────


async def test_import_resolves_references_against_existing_db_rows(db):
    """Validation must accept a reference if the target exists in the
    DB (not in the bundle). This is what makes "ship just the new
    agent" YAML files work — the supporting prompts/tools/configs
    can already be in the target DB."""
    # Pre-populate the target DB with a tool. The bundle won't include it.
    from tests.fixtures.builders import make_tool
    pre_existing_tool = await make_tool(db, name="already_in_db_tool")

    bundle = Bundle(
        entities=[
            AgentEntry(
                name="references_existing",
                display_name="References Existing Tool",
                description="d",
                purpose="test",
                domain="underwriting",
                materiality_tier="low",
                owner_name="Test Owner",
                versions=[
                    AgentVersionEntry(
                        version_label="1.0.0",
                        change_summary="Initial.",
                        # The seed inference_config exists in every cloned
                        # test DB — referencing it by name proves the
                        # validator falls back to the DB when an entry
                        # isn't in the bundle.
                        inference_config="test_default_config",
                        tools=[
                            ToolAuthorization(tool="already_in_db_tool"),
                        ],
                    ),
                ],
            ),
        ],
    )

    importer = Importer(Registry(db))
    # Validation must NOT error — the tool and config exist in the DB.
    result = await importer.import_bundle(bundle)
    assert ("Agent", "references_existing") in result.headers_inserted
    # The tool was not inserted (it already existed and isn't in the bundle).
    inserted_names = {name for (_, name) in result.headers_inserted}
    assert "already_in_db_tool" not in inserted_names
    assert "test_default_config" not in inserted_names


# ── Export → loads_bundle round-trip (Pydantic level) ────────────────────


async def test_yaml_text_round_trip_through_loads_bundle(db):
    """Export to YAML text → loads_bundle → Bundle equality.

    This catches serializer/parser mismatches before they manifest
    as obscure import errors. Tests dumps_bundle / loads_bundle as
    a pair without touching the importer.
    """
    bundle_setup = await make_complete_agent(
        db, name="serializer_test_agent", promote_to_champion=False,
    )
    exporter = Exporter(Registry(db))
    bundle = await exporter.export_agent(bundle_setup.name)

    yaml_text = dumps_bundle(bundle)
    reparsed = loads_bundle(yaml_text)

    # Compare on content (exclude the export timestamp which serializes
    # to a string and doesn't survive the round-trip as a datetime).
    a = bundle.model_dump(exclude={"exported_at"})
    b = reparsed.model_dump(exclude={"exported_at"})
    assert a == b, "dumps_bundle ↔ loads_bundle must round-trip Bundle content"
