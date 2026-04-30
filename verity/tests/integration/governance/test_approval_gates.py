"""Promotion-gate semantics — what evidence each transition requires.

Per ``Lifecycle._check_gate_requirements``:

  staging → shadow      : staging_tests_passed=True (DB) +
                          staging_results_reviewed=True (request)
  shadow → challenger   : shadow_period_complete=True (DB) +
                          shadow_metrics_reviewed=True (request)
  challenger → champion : ground_truth_passed=True (DB) +
                          ground_truth_reviewed (request) +
                          model_card_reviewed (request) +
                          challenger_metrics_reviewed (request)
  candidate → champion  : fast-track, no extra evidence required

Every gate requires that the listed condition is true. Missing any
piece raises ValueError listing the specific issue(s) — multiple gate
failures concatenate so an approver sees them all at once.
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


def _request(target: LifecycleState, **overrides) -> PromotionRequest:
    base = dict(
        approver_name="reviewer",
        rationale="Test promotion.",
        staging_results_reviewed=False,
        ground_truth_reviewed=False,
        fairness_analysis_reviewed=False,
        shadow_metrics_reviewed=False,
        challenger_metrics_reviewed=False,
        model_card_reviewed=False,
        similarity_flags_reviewed=False,
    )
    base.update(overrides)
    return PromotionRequest(target_state=target, **base)


# ── staging → shadow ────────────────────────────────────────────────────────

async def test_shadow_gate_blocks_when_staging_tests_not_passed(db):
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    await promote(db, av, to_state="staging")
    # staging_tests_passed left at the default (NULL).
    lifecycle = Lifecycle(db)

    req = _request(LifecycleState.SHADOW, staging_results_reviewed=True)
    with pytest.raises(ValueError, match="Staging tests have not passed"):
        await lifecycle.promote(EntityType.AGENT, av.id, req)


async def test_shadow_gate_blocks_when_results_not_reviewed(db):
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    await promote(db, av, to_state="staging")
    await set_gate_flags(db, av, staging_tests_passed=True)
    lifecycle = Lifecycle(db)

    req = _request(LifecycleState.SHADOW, staging_results_reviewed=False)
    with pytest.raises(ValueError, match="Staging results not reviewed"):
        await lifecycle.promote(EntityType.AGENT, av.id, req)


async def test_shadow_gate_concatenates_multiple_failures(db):
    """When BOTH the DB flag is unset AND the approver didn't review,
    both issues should be in the error message."""
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    await promote(db, av, to_state="staging")
    lifecycle = Lifecycle(db)

    req = _request(LifecycleState.SHADOW, staging_results_reviewed=False)
    with pytest.raises(ValueError) as exc_info:
        await lifecycle.promote(EntityType.AGENT, av.id, req)
    msg = str(exc_info.value)
    assert "Staging tests have not passed" in msg
    assert "Staging results not reviewed" in msg


# ── shadow → challenger ─────────────────────────────────────────────────────

async def test_challenger_gate_blocks_when_shadow_period_incomplete(db):
    av = await make_agent_version(db)
    for state in ("candidate", "staging", "shadow"):
        await promote(db, av, to_state=state)
    await set_gate_flags(db, av, staging_tests_passed=True)
    # shadow_period_complete left at default (False).
    lifecycle = Lifecycle(db)

    req = _request(LifecycleState.CHALLENGER, shadow_metrics_reviewed=True)
    with pytest.raises(ValueError, match="Shadow period not complete"):
        await lifecycle.promote(EntityType.AGENT, av.id, req)


async def test_challenger_gate_blocks_when_shadow_metrics_not_reviewed(db):
    av = await make_agent_version(db)
    for state in ("candidate", "staging", "shadow"):
        await promote(db, av, to_state=state)
    await set_gate_flags(db, av, shadow_period_complete=True)
    lifecycle = Lifecycle(db)

    req = _request(LifecycleState.CHALLENGER, shadow_metrics_reviewed=False)
    with pytest.raises(ValueError, match="Shadow metrics not reviewed"):
        await lifecycle.promote(EntityType.AGENT, av.id, req)


# ── challenger → champion (full gate) ──────────────────────────────────────

async def test_champion_gate_blocks_when_ground_truth_not_passed(db):
    av = await make_agent_version(db)
    for state in ("candidate", "staging", "shadow", "challenger"):
        await promote(db, av, to_state=state)
    # All review flags True, but ground_truth_passed left unset.
    lifecycle = Lifecycle(db)

    req = _request(
        LifecycleState.CHAMPION,
        ground_truth_reviewed=True,
        model_card_reviewed=True,
        challenger_metrics_reviewed=True,
    )
    with pytest.raises(ValueError, match="Ground truth validation has not passed"):
        await lifecycle.promote(EntityType.AGENT, av.id, req)


async def test_champion_gate_blocks_when_model_card_not_reviewed(db):
    av = await make_agent_version(db)
    for state in ("candidate", "staging", "shadow", "challenger"):
        await promote(db, av, to_state=state)
    await set_gate_flags(db, av, ground_truth_passed=True)
    lifecycle = Lifecycle(db)

    req = _request(
        LifecycleState.CHAMPION,
        ground_truth_reviewed=True,
        challenger_metrics_reviewed=True,
        model_card_reviewed=False,
    )
    with pytest.raises(ValueError, match="Model card not reviewed"):
        await lifecycle.promote(EntityType.AGENT, av.id, req)


async def test_champion_gate_blocks_when_challenger_metrics_not_reviewed(db):
    av = await make_agent_version(db)
    for state in ("candidate", "staging", "shadow", "challenger"):
        await promote(db, av, to_state=state)
    await set_gate_flags(db, av, ground_truth_passed=True)
    lifecycle = Lifecycle(db)

    req = _request(
        LifecycleState.CHAMPION,
        ground_truth_reviewed=True,
        model_card_reviewed=True,
        challenger_metrics_reviewed=False,
    )
    with pytest.raises(ValueError, match="Challenger metrics not reviewed"):
        await lifecycle.promote(EntityType.AGENT, av.id, req)


# ── candidate → champion fast-track ────────────────────────────────────────

async def test_candidate_to_champion_fast_track_skips_full_gate(db):
    """Trivial entities (e.g. formatting prompts) can take a fast path
    that doesn't require the staging/shadow/challenger evidence."""
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    lifecycle = Lifecycle(db)

    # No reviewed flags set; no gate flags set either.
    req = _request(LifecycleState.CHAMPION)
    result = await lifecycle.promote(EntityType.AGENT, av.id, req)
    assert result["to_state"] == "champion"
