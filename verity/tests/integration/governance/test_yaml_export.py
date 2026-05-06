"""YAML export — slice 4A.

Exercises ``verity.governance.yaml_io.Exporter`` and the
``dumps_bundle`` serializer end-to-end against a real cloned DB.

Each test seeds a small composition, exports it, and asserts on:

  * Bundle shape: apiVersion / kind, entity ordering (configs/tools
    before consumers), entity kinds present.
  * Field presence: lifecycle_state recorded for audit, references
    by name, no UUIDs in output.
  * Serializer: deterministic ordering, multi-line strings emitted as
    ``|`` literal blocks.

Slice 4B will add the round-trip property test that closes the loop
(export → import → re-export and assert byte-identical).
"""

from __future__ import annotations

import yaml

from tests.fixtures.builders import (
    assign_prompt,
    authorize_tool,
    make_agent,
    make_complete_agent,
    make_complete_task,
    make_prompt,
    make_prompt_version,
    make_tool,
)
from verity.governance.registry import Registry
from verity.governance.yaml_io import Exporter, dumps_bundle


# ── header-only entities (Tool, InferenceConfig) ───────────────────────────


async def test_export_tool_produces_minimal_bundle(db):
    """A tool has no dependencies, so its bundle is exactly one entry."""
    await make_tool(db, name="lookup_tool", display_name="Lookup Tool")

    exporter = Exporter(Registry(db))
    bundle = await exporter.export_tool("lookup_tool")

    assert bundle.apiVersion == "studio.verity.ai/v1"
    assert bundle.kind == "Bundle"
    assert len(bundle.entities) == 1
    assert bundle.entities[0].kind == "Tool"
    assert bundle.entities[0].name == "lookup_tool"
    # Round-trip through YAML must succeed.
    yaml_text = dumps_bundle(bundle)
    assert "kind: Tool" in yaml_text
    assert "name: lookup_tool" in yaml_text


async def test_export_unknown_entity_returns_empty_bundle(db):
    """Asking the exporter for a name that doesn't exist yields a
    bundle with no entities — the API layer turns that into a 404."""
    exporter = Exporter(Registry(db))
    bundle = await exporter.export_tool("does_not_exist")
    assert bundle.entities == []


# ── prompt with versions ───────────────────────────────────────────────────


async def test_export_prompt_includes_all_versions(db):
    """A prompt with 3 versions must surface as one PromptEntry with 3
    PromptVersionEntry rows nested under ``versions:``."""
    prompt = await make_prompt(db, name="extraction_prompt")
    # make_prompt_version uses major/minor/patch, not version_label —
    # the label is generated in SQL from the three components.
    await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=0, patch_version=0,
        content="System prompt v1.\nLine 2.",
        change_summary="Initial version.",
    )
    await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=1, patch_version=0,
        content="System prompt v2.",
        change_summary="Tweaks.",
    )

    exporter = Exporter(Registry(db))
    bundle = await exporter.export_prompt("extraction_prompt")

    assert len(bundle.entities) == 1
    prompt_entry = bundle.entities[0]
    assert prompt_entry.kind == "Prompt"
    assert prompt_entry.name == "extraction_prompt"
    labels = [v.version_label for v in prompt_entry.versions]
    assert "1.0.0" in labels and "1.1.0" in labels
    # lifecycle_state must round-trip for audit (informational, not
    # enforced on import).
    for v in prompt_entry.versions:
        assert v.lifecycle_state is not None


def test_serializer_uses_block_style_for_multiline_content(db_unused=None):
    """Multi-line strings (the killer case is prompt content) must
    render as ``|`` literal blocks — escaped one-liners are unreadable
    for prose."""
    from verity.governance.yaml_io.models import (
        Bundle,
        PromptEntry,
        PromptVersionEntry,
    )

    bundle = Bundle(
        entities=[
            PromptEntry(
                kind="Prompt",
                name="p",
                display_name="P",
                description="d",
                versions=[
                    PromptVersionEntry(
                        version_label="1.0.0",
                        api_role="system",
                        governance_tier="behavioural",
                        change_summary="x",
                        content="line one\nline two\nline three",
                    ),
                ],
            ),
        ],
    )

    text = dumps_bundle(bundle)
    # The content field should appear with the ``|`` block scalar
    # marker. Exact form is ``content: |`` on its own line (PyYAML
    # adds a trailing newline indicator like ``|`` or ``|-``); just
    # check the marker presence.
    assert "content: |" in text, (
        "Multi-line strings must use the | block scalar style, not a "
        "double-quoted one-liner. Output was:\n" + text
    )
    # The actual content lines must appear unescaped.
    assert "line one" in text
    assert "line two" in text
    # Sanity: no escaped newlines.
    assert "\\n" not in text


# ── full agent bundle (the headline case) ──────────────────────────────────


async def test_export_complete_agent_bundles_all_dependencies(db):
    """A fully-wired agent must export with its prompt + tool + config
    as separate top-level entries, ordered leaves-first.

    This is the headline scenario for the YAML format: a non-developer
    SME hands the resulting YAML to a reviewer and the reviewer can
    read the whole composition without round-tripping back to the DB.
    """
    tool = await make_tool(db, name="external_lookup")
    bundle_setup = await make_complete_agent(
        db,
        name="decision_agent",
        system_prompt="You are a decision agent.\nBe terse.",
        tools=[tool],
        promote_to_champion=True,
    )

    exporter = Exporter(Registry(db))
    bundle = await exporter.export_agent(bundle_setup.name)

    kinds = [e.kind for e in bundle.entities]
    assert "InferenceConfig" in kinds, "Config dependency must be in bundle"
    assert "Tool" in kinds, "Tool dependency must be in bundle"
    assert "Prompt" in kinds, "Prompt dependency must be in bundle"
    assert "Agent" in kinds, "The starting entity must be in bundle"

    # Bucket ordering: leaves (configs/tools/connectors) come first,
    # then prompts, then tasks, then agents. Verify the agent is last
    # of its kind so a YAML reader sees deps before the consumer.
    assert kinds.index("Agent") > kinds.index("Prompt")
    assert kinds.index("Agent") > kinds.index("Tool")
    assert kinds.index("Agent") > kinds.index("InferenceConfig")

    # Find the agent entry and verify its wiring uses name references.
    agent_entry = next(e for e in bundle.entities if e.kind == "Agent")
    assert len(agent_entry.versions) >= 1
    av = agent_entry.versions[0]
    # Inference config: name ref, not UUID.
    assert av.inference_config is not None
    assert "-" not in av.inference_config or len(av.inference_config) < 36, (
        "inference_config should be a name reference, not a UUID"
    )
    # Prompt assignments use name + version_label.
    assert len(av.prompts) >= 1
    pa = av.prompts[0]
    assert pa.prompt
    assert pa.version
    # Tool authorizations use name.
    assert len(av.tools) >= 1
    assert av.tools[0].tool == "external_lookup"

    # Lifecycle state recorded for audit.
    assert av.lifecycle_state == "champion"


async def test_exported_yaml_contains_no_uuids(db):
    """Studio's design rule: bundles never contain UUIDs. Authors and
    auditors should see only names and version labels in YAML diffs."""
    bundle_setup = await make_complete_agent(
        db, name="audit_agent", promote_to_champion=False,
    )
    exporter = Exporter(Registry(db))
    bundle = await exporter.export_agent(bundle_setup.name)
    yaml_text = dumps_bundle(bundle)

    # No literal UUIDs (8-4-4-4-12 hex pattern with dashes).
    import re
    uuid_pattern = re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    )
    matches = uuid_pattern.findall(yaml_text)
    assert matches == [], (
        f"Bundle must not contain UUIDs but found: {matches}\n"
        f"YAML:\n{yaml_text}"
    )


async def test_serializer_output_is_deterministic(db):
    """Same Bundle → same bytes. Required for the round-trip property
    test (slice 4B) and for clean git diffs."""
    bundle_setup = await make_complete_agent(
        db, name="deterministic_agent", promote_to_champion=False,
    )
    exporter = Exporter(Registry(db))

    bundle1 = await exporter.export_agent(bundle_setup.name)
    bundle2 = await exporter.export_agent(bundle_setup.name)

    # exported_at differs between calls — null it so we compare
    # only the content. (The real round-trip test in slice 4B will
    # do export → import → re-export and compare on content, not on
    # the export timestamp.)
    bundle1.exported_at = None
    bundle2.exported_at = None

    assert dumps_bundle(bundle1) == dumps_bundle(bundle2)


# ── shared dependency dedup ─────────────────────────────────────────────────


async def test_shared_prompt_appears_once_when_referenced_twice(db):
    """If two agent_versions consume the same prompt_version, the
    bundle should contain that prompt header exactly once — the BFS
    visited-set handles dedup."""
    shared_prompt = await make_prompt(db, name="shared_p")
    shared_pv = await make_prompt_version(
        db, prompt_id=shared_prompt.id, content="Shared prompt content.",
    )

    # First agent — also has its own per-agent system prompt from
    # make_complete_agent.
    a1 = await make_complete_agent(db, name="agent_one", promote_to_champion=False)
    await assign_prompt(db, entity_version=a1.version, prompt_version=shared_pv)

    # Second agent.
    a2 = await make_complete_agent(db, name="agent_two", promote_to_champion=False)
    await assign_prompt(db, entity_version=a2.version, prompt_version=shared_pv)

    exporter = Exporter(Registry(db))
    # Export the second agent — this will also pull in the shared
    # prompt and the per-agent system prompt; agent_one is NOT in
    # the bundle because we didn't start from it.
    bundle = await exporter.export_agent("agent_two")

    prompt_entries = [e for e in bundle.entities if e.kind == "Prompt"]
    prompt_names = [e.name for e in prompt_entries]
    # The shared prompt name appears at most once in the bundle.
    assert prompt_names.count("shared_p") == 1


# ── apiVersion sanity ──────────────────────────────────────────────────────


async def test_bundle_carries_api_version(db):
    """Future schema migrations need a discriminator; verify the
    constant is set on every export."""
    await make_tool(db, name="version_test_tool")
    exporter = Exporter(Registry(db))
    bundle = await exporter.export_tool("version_test_tool")
    yaml_text = dumps_bundle(bundle)
    parsed = yaml.safe_load(yaml_text)
    assert parsed["apiVersion"] == "studio.verity.ai/v1"
    assert parsed["kind"] == "Bundle"


# NOTE: HTTP-endpoint tests for /api/v1/yaml/export live in
# tests/integration/api/test_yaml_export_endpoints.py — that's where
# the ``client`` fixture is defined (one conftest per layer).


# ── version scoping (the slice 4A refinement) ──────────────────────────────


async def test_export_with_version_scopes_to_single_version(db):
    """When ``version`` is passed, only that version of the starting
    entity is included — even if the parent has more versions."""
    prompt = await make_prompt(db, name="version_scoped_prompt")
    await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=0, patch_version=0,
        content="v1 content.",
    )
    await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=2, minor_version=0, patch_version=0,
        content="v2 content.",
    )
    await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=3, minor_version=0, patch_version=0,
        content="v3 content.",
    )

    exporter = Exporter(Registry(db))
    bundle = await exporter.export_prompt(
        "version_scoped_prompt", version="2.0.0",
    )

    assert len(bundle.entities) == 1
    pe = bundle.entities[0]
    labels = [v.version_label for v in pe.versions]
    assert labels == ["2.0.0"], (
        f"Expected only 2.0.0 in bundle, got {labels}"
    )


async def test_export_without_version_includes_all_versions_of_starting_entity(db):
    """Default (no version): every version of the starting entity is in."""
    prompt = await make_prompt(db, name="default_lineage_prompt")
    await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=0, patch_version=0,
        content="v1.",
    )
    await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=1, patch_version=0,
        content="v2.",
    )

    exporter = Exporter(Registry(db))
    bundle = await exporter.export_prompt("default_lineage_prompt")

    pe = next(e for e in bundle.entities if e.kind == "Prompt")
    labels = sorted(v.version_label for v in pe.versions)
    assert labels == ["1.0.0", "1.1.0"], (
        f"Default export should include all versions; got {labels}"
    )


# ── transitive scoping — pulled deps include only referenced versions ──────


async def test_transitive_prompt_includes_only_referenced_versions(db):
    """When an agent references prompt v1.0.0 only, the bundle's
    PromptEntry must NOT include the prompt's other versions.

    This is the rule that prevents bundles from blowing up in size:
    transitively-discovered prompts come along at the granularity
    actually used.
    """
    # A prompt with three versions; the agent will reference only one.
    prompt = await make_prompt(db, name="multi_version_prompt")
    pv_used = await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=0, patch_version=0,
        content="The version actually referenced.",
    )
    await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=1, patch_version=0,
        content="Unreferenced — must NOT appear in bundle.",
    )
    await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=2, minor_version=0, patch_version=0,
        content="Also unreferenced.",
    )

    # An agent that uses only v1.0.0.
    bundle_setup = await make_complete_agent(
        db, name="trans_scope_agent", promote_to_champion=False,
    )
    await assign_prompt(
        db, entity_version=bundle_setup.version, prompt_version=pv_used,
    )

    exporter = Exporter(Registry(db))
    bundle = await exporter.export_agent("trans_scope_agent")

    transitive = next(
        (e for e in bundle.entities
         if e.kind == "Prompt" and e.name == "multi_version_prompt"),
        None,
    )
    assert transitive is not None, (
        "The referenced prompt header must appear in the bundle."
    )
    labels = [v.version_label for v in transitive.versions]
    assert labels == ["1.0.0"], (
        f"Transitive prompts should include only referenced versions; "
        f"got {labels}"
    )


# ── most-advanced version selection for champion-tracking delegations ──────


async def test_champion_tracking_delegation_picks_most_advanced(db):
    """When a champion-tracking delegation points at an agent that has
    no row in 'champion' state, the exporter falls back to the
    most-advanced available state — staging > candidate > draft, etc."""
    # Sub-agent with several versions, none promoted to champion.
    # By default make_agent_version creates a draft. promote() advances
    # it; we'll leave the most advanced one in 'staging'.
    from tests.fixtures.builders import make_agent, make_agent_version

    child = await make_agent(db, name="staged_child_agent")
    cv1 = await make_agent_version(db, agent_id=child.id)  # draft, 1.0.0
    cv2 = await make_agent_version(
        db, agent_id=child.id,
        major_version=1, minor_version=1, patch_version=0,
    )  # draft, 1.1.0
    # Promote cv2 up the chain — staging is more advanced than draft.
    from tests.fixtures.builders import promote
    await promote(db, cv2, to_state="candidate")
    await promote(db, cv2, to_state="staging")

    # Parent agent that delegates to the child (champion-tracking).
    parent = await make_complete_agent(
        db, name="staged_parent_agent", promote_to_champion=False,
    )
    await db.execute_returning(
        "insert_agent_version_delegation",
        {
            "parent_agent_version_id": str(parent.version.id),
            "child_agent_name": "staged_child_agent",
            "child_agent_version_id": None,
            "scope": "{}",
            "authorized": True,
            "rationale": "Test.",
            "notes": None,
        },
    )

    exporter = Exporter(Registry(db))
    bundle = await exporter.export_agent("staged_parent_agent")

    child_entry = next(
        (e for e in bundle.entities
         if e.kind == "Agent" and e.name == "staged_child_agent"),
        None,
    )
    assert child_entry is not None, "Sub-agent must be in bundle."
    labels = [v.version_label for v in child_entry.versions]
    # cv2 is in 'staging', cv1 is in 'draft' — staging beats draft.
    assert labels == ["1.1.0"], (
        f"Champion-tracking delegation should resolve to the most "
        f"advanced version (staging > draft); got {labels}"
    )


async def test_pinned_delegation_pulls_only_the_pinned_version(db):
    """Version-pinned delegation: only the pinned child version
    appears in the bundle, not all child versions."""
    from tests.fixtures.builders import make_agent, make_agent_version

    child = await make_agent(db, name="pinned_child_agent")
    cv1 = await make_agent_version(db, agent_id=child.id)
    cv_pinned = await make_agent_version(
        db, agent_id=child.id,
        major_version=2, minor_version=0, patch_version=0,
    )
    cv3 = await make_agent_version(
        db, agent_id=child.id,
        major_version=3, minor_version=0, patch_version=0,
    )

    parent = await make_complete_agent(
        db, name="pinning_parent_agent", promote_to_champion=False,
    )
    await db.execute_returning(
        "insert_agent_version_delegation",
        {
            "parent_agent_version_id": str(parent.version.id),
            "child_agent_name": None,
            "child_agent_version_id": str(cv_pinned.id),
            "scope": "{}",
            "authorized": True,
            "rationale": "Pinned to v2.0.0.",
            "notes": None,
        },
    )

    exporter = Exporter(Registry(db))
    bundle = await exporter.export_agent("pinning_parent_agent")

    child_entry = next(
        (e for e in bundle.entities
         if e.kind == "Agent" and e.name == "pinned_child_agent"),
        None,
    )
    assert child_entry is not None
    labels = [v.version_label for v in child_entry.versions]
    assert labels == ["2.0.0"], (
        f"Pinned delegation should include only the pinned version; "
        f"got {labels} (cv1={cv1.id}, cv_pinned={cv_pinned.id}, cv3={cv3.id})"
    )
