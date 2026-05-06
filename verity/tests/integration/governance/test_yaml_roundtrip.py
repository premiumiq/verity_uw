"""YAML round-trip property test (slice 4B).

The headline correctness commitment from
docs/plans/studio-build-plan.md §4.2:

  "A property test: generate a random valid agent_version (with
   prompts, tools, bindings, targets), export to YAML, import to a
   clean DB, export again. The two exports must be byte-identical."

This file implements the deterministic version of that — same shape
as the spec calls for, but with hand-crafted fixtures rather than
hypothesis-style randomisation. (Randomisation can come later; the
deterministic version is enough to catch the regressions we care
about today.)

The test:

  1. Set up a fully-wired agent in the source DB (``db`` fixture).
     All versions in DRAFT state — see "lifecycle masking" note below.
  2. Export the agent to YAML.
  3. Import the same YAML into a SECOND clean DB (``db_target``
     fixture). Both DBs come from the same template, so the seed
     ``inference_config`` is present in both.
  4. Re-export from the second DB.
  5. Assert the two YAMLs are byte-identical (after masking the
     ``exported_at`` timestamp, which is wall-clock-dependent).

Why DRAFT-only fixtures? Imports always create as draft, regardless
of the YAML's ``lifecycle_state`` field (see studio-build-plan.md
§2.6). So if the source agent has ``lifecycle_state: champion``, the
re-exported YAML will say ``lifecycle_state: draft`` — not byte-
identical. To prove the format itself round-trips, we keep the source
in draft so the YAML is invariant under import.

A separate import test (``test_yaml_import.py::
test_import_creates_versions_as_draft_regardless_of_yaml_state``)
covers the lifecycle-masking behaviour explicitly.
"""

from __future__ import annotations

import re

from tests.fixtures.builders import (
    assign_prompt,
    authorize_tool,
    make_complete_agent,
    make_prompt,
    make_prompt_version,
    make_tool,
)
from verity.governance.registry import Registry
from verity.governance.yaml_io import (
    Exporter,
    Importer,
    dumps_bundle,
    loads_bundle,
)


# Match the ``exported_at`` line so we can strip it before comparing.
# It's the only wall-clock-dependent field in the bundle.
_EXPORTED_AT_LINE = re.compile(r"^exported_at: .*$", re.MULTILINE)


def _strip_volatile(yaml_text: str) -> str:
    """Remove fields that legitimately differ between exports."""
    return _EXPORTED_AT_LINE.sub("exported_at: <masked>", yaml_text)


async def test_round_trip_preserves_agent_through_clean_import(db, db_target):
    """Set up agent in db, export, import to db_target, re-export.
    The two exports must be byte-identical (modulo timestamps)."""
    # ── Setup in source DB ─────────────────────────────────────
    # Use draft state throughout so the import (which always creates
    # as draft) doesn't introduce a difference.
    tool = await make_tool(db, name="rt_lookup_tool")
    bundle_setup = await make_complete_agent(
        db,
        name="rt_decision_agent",
        system_prompt=(
            "You are a decision agent.\n"
            "Round-trip test fixture.\n"
            "Multiple lines so the | block scalar is exercised."
        ),
        tools=[tool],
        promote_to_champion=False,
    )

    # ── Export from source DB ──────────────────────────────────
    source_exporter = Exporter(Registry(db))
    source_bundle = await source_exporter.export_agent("rt_decision_agent")
    source_yaml = dumps_bundle(source_bundle)

    # ── Import into target DB ──────────────────────────────────
    importer = Importer(Registry(db_target))
    parsed = loads_bundle(source_yaml)
    result = await importer.import_bundle(parsed)

    # The import must have written every kind of entity in the bundle —
    # otherwise the re-export will be missing things.
    inserted_kinds = {k for (k, _) in result.headers_inserted}
    assert "Tool" in inserted_kinds
    assert "Prompt" in inserted_kinds
    assert "Agent" in inserted_kinds

    # ── Re-export from target DB ───────────────────────────────
    target_exporter = Exporter(Registry(db_target))
    target_bundle = await target_exporter.export_agent("rt_decision_agent")
    target_yaml = dumps_bundle(target_bundle)

    # ── Compare ────────────────────────────────────────────────
    source_masked = _strip_volatile(source_yaml)
    target_masked = _strip_volatile(target_yaml)

    if source_masked != target_masked:
        # Build a useful diff message for the failure path.
        import difflib
        diff = "\n".join(
            difflib.unified_diff(
                source_masked.splitlines(),
                target_masked.splitlines(),
                fromfile="source",
                tofile="re-export",
                lineterm="",
            )
        )
        raise AssertionError(
            "Round-trip YAML differs:\n" + diff
        )


async def test_round_trip_preserves_multiple_versions_per_entity(db, db_target):
    """A prompt with multiple versions, attached at different points,
    must round-trip with all versions intact."""
    # Build a prompt with three drafts.
    prompt = await make_prompt(db, name="rt_multi_prompt")
    pv1 = await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=0, patch_version=0,
        content="v1 content.",
    )
    pv2 = await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=1, patch_version=0,
        content="v2 content.",
    )
    pv3 = await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=2, minor_version=0, patch_version=0,
        content="v3 content.",
    )
    # An agent that uses one of them — exercises the transitive
    # scoping path. Exporting the *prompt* should still include all
    # three versions because the prompt is the starting entity.
    bundle_setup = await make_complete_agent(
        db, name="rt_multi_consumer", promote_to_champion=False,
    )
    await assign_prompt(db, entity_version=bundle_setup.version, prompt_version=pv2)

    # Export the prompt as the starting entity → all 3 versions.
    source_exporter = Exporter(Registry(db))
    source_bundle = await source_exporter.export_prompt("rt_multi_prompt")
    source_yaml = dumps_bundle(source_bundle)

    # Round-trip
    importer = Importer(Registry(db_target))
    await importer.import_bundle(loads_bundle(source_yaml))

    target_exporter = Exporter(Registry(db_target))
    target_bundle = await target_exporter.export_prompt("rt_multi_prompt")
    target_yaml = dumps_bundle(target_bundle)

    assert _strip_volatile(source_yaml) == _strip_volatile(target_yaml)

    # Sanity: the target DB has all three versions.
    target_prompt_entry = next(
        e for e in target_bundle.entities if e.kind == "Prompt"
    )
    labels = sorted(v.version_label for v in target_prompt_entry.versions)
    assert labels == ["1.0.0", "1.1.0", "2.0.0"]
