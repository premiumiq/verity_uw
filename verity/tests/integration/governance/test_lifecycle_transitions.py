"""Lifecycle state-machine tests via ``governance.lifecycle.Lifecycle.promote``.

The promote() method threads three checks before mutating state:
  1. Transition is in VALID_TRANSITIONS for the current state
  2. Per-state gate requirements are met
  3. PromotionRequest fields are valid (Pydantic — covered in unit tests)

These tests exercise (1) directly: every legal pair, every illegal pair.
Gate semantics are in test_approval_gates.py.
"""

from __future__ import annotations

import pytest

from verity.governance.lifecycle import Lifecycle
from verity.models.lifecycle import EntityType, LifecycleState, PromotionRequest

from tests.fixtures.builders import (
    make_agent_version,
    promote,
    set_gate_flags,
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _request(target_state: LifecycleState, **flags) -> PromotionRequest:
    """Minimal PromotionRequest with reviewed flags filled from kwargs.

    Defaults to all reviewed=True so transition tests don't fail on
    gate semantics — those have their own test file.
    """
    defaults = dict(
        approver_name="tester",
        approver_role="QA",
        rationale="Promotion under test.",
        staging_results_reviewed=True,
        ground_truth_reviewed=True,
        fairness_analysis_reviewed=True,
        shadow_metrics_reviewed=True,
        challenger_metrics_reviewed=True,
        model_card_reviewed=True,
        similarity_flags_reviewed=True,
    )
    defaults.update(flags)
    return PromotionRequest(target_state=target_state, **defaults)


# ── Legal transitions ──────────────────────────────────────────────────────

async def test_promote_draft_to_candidate(db):
    av = await make_agent_version(db)
    lifecycle = Lifecycle(db)

    result = await lifecycle.promote(
        EntityType.AGENT, av.id, _request(LifecycleState.CANDIDATE),
    )
    assert result["from_state"] == "draft"
    assert result["to_state"] == "candidate"


async def test_promote_candidate_to_staging(db):
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    lifecycle = Lifecycle(db)

    result = await lifecycle.promote(
        EntityType.AGENT, av.id, _request(LifecycleState.STAGING),
    )
    assert result["to_state"] == "staging"


async def test_promote_candidate_directly_to_champion_is_legal(db):
    """Fast-track: trivial entities can skip staging/shadow/challenger."""
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    lifecycle = Lifecycle(db)

    result = await lifecycle.promote(
        EntityType.AGENT, av.id, _request(LifecycleState.CHAMPION),
    )
    assert result["to_state"] == "champion"


async def test_promote_staging_to_shadow_passes_when_gate_open(db):
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    await promote(db, av, to_state="staging")
    await set_gate_flags(db, av, staging_tests_passed=True)
    lifecycle = Lifecycle(db)

    result = await lifecycle.promote(
        EntityType.AGENT, av.id, _request(LifecycleState.SHADOW),
    )
    assert result["to_state"] == "shadow"


async def test_promote_shadow_to_challenger_passes_when_gate_open(db):
    av = await make_agent_version(db)
    for state in ("candidate", "staging", "shadow"):
        await promote(db, av, to_state=state)
        if state == "staging":
            await set_gate_flags(db, av, staging_tests_passed=True)
    await set_gate_flags(db, av, shadow_period_complete=True)
    lifecycle = Lifecycle(db)

    result = await lifecycle.promote(
        EntityType.AGENT, av.id, _request(LifecycleState.CHALLENGER),
    )
    assert result["to_state"] == "challenger"


async def test_promote_challenger_to_champion_passes_full_gate(db):
    av = await make_agent_version(db)
    for state in ("candidate", "staging", "shadow", "challenger"):
        await promote(db, av, to_state=state)
    await set_gate_flags(
        db, av, staging_tests_passed=True, shadow_period_complete=True,
        ground_truth_passed=True,
    )
    lifecycle = Lifecycle(db)

    result = await lifecycle.promote(
        EntityType.AGENT, av.id, _request(LifecycleState.CHAMPION),
    )
    assert result["to_state"] == "champion"


async def test_promote_champion_to_deprecated(db):
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    await promote(db, av, to_state="champion")
    lifecycle = Lifecycle(db)

    result = await lifecycle.promote(
        EntityType.AGENT, av.id, _request(LifecycleState.DEPRECATED),
    )
    assert result["to_state"] == "deprecated"


# ── Illegal transitions rejected ───────────────────────────────────────────

async def test_promote_draft_directly_to_champion_rejected(db):
    """draft → champion isn't in VALID_TRANSITIONS — the gate catches it
    before any state change happens."""
    av = await make_agent_version(db)
    lifecycle = Lifecycle(db)

    with pytest.raises(ValueError, match="Invalid transition"):
        await lifecycle.promote(
            EntityType.AGENT, av.id, _request(LifecycleState.CHAMPION),
        )


async def test_promote_deprecated_to_anything_rejected(db):
    """DEPRECATED is terminal — VALID_TRANSITIONS[DEPRECATED] is []."""
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    await promote(db, av, to_state="champion")
    await promote(db, av, to_state="deprecated")
    lifecycle = Lifecycle(db)

    with pytest.raises(ValueError, match="Invalid transition"):
        await lifecycle.promote(
            EntityType.AGENT, av.id, _request(LifecycleState.CHAMPION),
        )


async def test_promote_staging_directly_to_champion_rejected(db):
    """STAGING must go through SHADOW → CHALLENGER first."""
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    await promote(db, av, to_state="staging")
    lifecycle = Lifecycle(db)

    with pytest.raises(ValueError, match="Invalid transition"):
        await lifecycle.promote(
            EntityType.AGENT, av.id, _request(LifecycleState.CHAMPION),
        )


async def test_promote_unknown_version_id_rejected(db):
    import uuid
    bogus_id = uuid.uuid4()
    lifecycle = Lifecycle(db)

    with pytest.raises(ValueError, match="not found"):
        await lifecycle.promote(
            EntityType.AGENT, bogus_id, _request(LifecycleState.CANDIDATE),
        )


# ── Approval record is created on every successful promotion ───────────────

async def test_successful_promotion_writes_approval_record(db):
    av = await make_agent_version(db)
    lifecycle = Lifecycle(db)

    result = await lifecycle.promote(
        EntityType.AGENT, av.id, _request(LifecycleState.CANDIDATE),
    )

    row = await db.fetch_one_raw(
        "SELECT id, gate_type, from_state, to_state, approver_name, rationale "
        "FROM approval_record WHERE id = %(id)s",
        {"id": str(result["approval_id"])},
    )
    assert row is not None
    assert row["gate_type"] == "draft_to_candidate_promotion"
    assert row["from_state"] == "draft"
    assert row["to_state"] == "candidate"
    assert row["approver_name"] == "tester"
    assert row["rationale"] == "Promotion under test."


async def test_rejected_promotion_writes_no_approval_record(db):
    """Failed gate checks (illegal transition or missing prereqs) must
    NOT leave a partial approval row behind."""
    av = await make_agent_version(db)
    lifecycle = Lifecycle(db)

    with pytest.raises(ValueError):
        await lifecycle.promote(
            EntityType.AGENT, av.id, _request(LifecycleState.CHAMPION),
        )

    rows = await db.fetch_all_raw(
        "SELECT id FROM approval_record "
        "WHERE entity_version_id = %(id)s",
        {"id": str(av.id)},
    )
    assert rows == []
