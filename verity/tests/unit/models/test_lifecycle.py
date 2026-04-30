"""Unit tests for ``verity.models.lifecycle``.

The state machine table (``VALID_TRANSITIONS``) and channel mapping
(``STATE_TO_CHANNEL``) are the canonical source of truth for the
governance plane. A typo here would silently let illegal transitions
through, so the tests assert the table contents explicitly.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from verity.models.lifecycle import (
    ApprovalRecord,
    DeploymentChannel,
    EntityType,
    LifecycleState,
    PromotionRequest,
    STATE_TO_CHANNEL,
    VALID_TRANSITIONS,
)


# ── State machine table ─────────────────────────────────────────────────────

def test_valid_transitions_covers_every_state():
    """Every state must appear as a key — even terminal ones with empty
    targets — so a lookup never raises KeyError."""
    expected = {s for s in LifecycleState}
    actual = set(VALID_TRANSITIONS)
    assert actual == expected


def test_draft_only_transitions_to_candidate():
    assert VALID_TRANSITIONS[LifecycleState.DRAFT] == [LifecycleState.CANDIDATE]


def test_candidate_can_skip_to_champion_or_deprecate():
    # CANDIDATE → CHAMPION is the "early-promote" path for trivial entities
    # (e.g. formatting prompts) that don't need staging/shadow/challenger.
    targets = VALID_TRANSITIONS[LifecycleState.CANDIDATE]
    assert LifecycleState.STAGING in targets
    assert LifecycleState.CHAMPION in targets
    assert LifecycleState.DEPRECATED in targets


def test_champion_only_deprecates():
    # No going back from champion except to deprecated. A new champion
    # promotion creates a new version, not a state-flip on the old one.
    assert VALID_TRANSITIONS[LifecycleState.CHAMPION] == [LifecycleState.DEPRECATED]


def test_deprecated_is_terminal():
    assert VALID_TRANSITIONS[LifecycleState.DEPRECATED] == []


def test_staging_progresses_through_shadow():
    # The full validation pipeline: staging → shadow → challenger → champion.
    assert LifecycleState.SHADOW in VALID_TRANSITIONS[LifecycleState.STAGING]
    assert LifecycleState.CHALLENGER in VALID_TRANSITIONS[LifecycleState.SHADOW]
    assert LifecycleState.CHAMPION in VALID_TRANSITIONS[LifecycleState.CHALLENGER]


def test_no_transition_skips_validation_phases():
    # STAGING/SHADOW/CHALLENGER must NOT permit a direct jump to CHAMPION
    # without going through their own next state. Otherwise the
    # promotion gates can be bypassed.
    assert LifecycleState.CHAMPION not in VALID_TRANSITIONS[LifecycleState.STAGING]
    assert LifecycleState.CHAMPION not in VALID_TRANSITIONS[LifecycleState.SHADOW]


# ── Channel mapping ─────────────────────────────────────────────────────────

def test_state_to_channel_covers_every_state():
    expected = {s for s in LifecycleState}
    actual = set(STATE_TO_CHANNEL)
    assert actual == expected


def test_champion_runs_in_production_channel():
    assert STATE_TO_CHANNEL[LifecycleState.CHAMPION] == DeploymentChannel.PRODUCTION


def test_draft_and_candidate_are_development():
    assert STATE_TO_CHANNEL[LifecycleState.DRAFT] == DeploymentChannel.DEVELOPMENT
    assert STATE_TO_CHANNEL[LifecycleState.CANDIDATE] == DeploymentChannel.DEVELOPMENT


def test_staging_state_uses_staging_channel():
    assert STATE_TO_CHANNEL[LifecycleState.STAGING] == DeploymentChannel.STAGING


def test_shadow_uses_shadow_channel():
    assert STATE_TO_CHANNEL[LifecycleState.SHADOW] == DeploymentChannel.SHADOW


def test_challenger_uses_evaluation_channel():
    # CHALLENGER (running on a defined % of production traffic) maps to
    # the EVALUATION channel — its outputs are consumed but compared.
    assert STATE_TO_CHANNEL[LifecycleState.CHALLENGER] == DeploymentChannel.EVALUATION


# ── PromotionRequest ────────────────────────────────────────────────────────

def test_promotion_request_minimal_fields():
    req = PromotionRequest(
        target_state=LifecycleState.CANDIDATE,
        approver_name="Alice",
        rationale="Passed initial review.",
    )
    # All review-flag fields default to False — approvers must opt in.
    assert req.staging_results_reviewed is False
    assert req.ground_truth_reviewed is False
    assert req.fairness_analysis_reviewed is False
    assert req.shadow_metrics_reviewed is False
    assert req.challenger_metrics_reviewed is False
    assert req.model_card_reviewed is False
    assert req.similarity_flags_reviewed is False


def test_promotion_request_rejects_bad_state():
    with pytest.raises(ValidationError):
        PromotionRequest(
            target_state="not_a_state",  # type: ignore[arg-type]
            approver_name="Alice",
            rationale="...",
        )


def test_promotion_request_requires_rationale():
    # Rationale is non-optional — every approval must justify itself.
    with pytest.raises(ValidationError):
        PromotionRequest(
            target_state=LifecycleState.CANDIDATE,
            approver_name="Alice",
            # rationale missing
        )


def test_promotion_request_round_trip():
    req = PromotionRequest(
        target_state=LifecycleState.CHAMPION,
        approver_name="Bob",
        approver_role="MRM",
        rationale="All gates clear.",
        staging_results_reviewed=True,
        ground_truth_reviewed=True,
        fairness_analysis_reviewed=True,
        shadow_metrics_reviewed=True,
        challenger_metrics_reviewed=True,
        model_card_reviewed=True,
    )
    rebuilt = PromotionRequest.model_validate(req.model_dump())
    assert rebuilt == req


# ── ApprovalRecord ──────────────────────────────────────────────────────────

def test_approval_record_required_fields():
    from datetime import datetime, timezone

    record = ApprovalRecord(
        id=uuid.uuid4(),
        entity_type=EntityType.AGENT,
        entity_version_id=uuid.uuid4(),
        gate_type="staging",
        from_state=LifecycleState.CANDIDATE,
        to_state=LifecycleState.STAGING,
        approver_name="Carol",
        approved_at=datetime.now(timezone.utc),
        rationale="Tests passed.",
    )
    assert record.gate_type == "staging"
    assert record.from_state == LifecycleState.CANDIDATE
