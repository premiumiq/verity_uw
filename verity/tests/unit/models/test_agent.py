"""Unit tests for ``verity.models.agent``."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from verity.models.agent import Agent, AgentVersion, AgentVersionDelegation
from verity.models.lifecycle import DeploymentChannel, LifecycleState, MaterialityTier


def _make_agent_kwargs(**overrides):
    base = {
        "id": uuid.uuid4(),
        "name": "test_agent",
        "display_name": "Test Agent",
        "description": "...",
        "purpose": "...",
        "materiality_tier": MaterialityTier.LOW,
        "owner_name": "Alice",
    }
    base.update(overrides)
    return base


def _make_agent_version_kwargs(**overrides):
    base = {
        "id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "inference_config_id": uuid.uuid4(),
    }
    base.update(overrides)
    return base


# ── Agent ───────────────────────────────────────────────────────────────────

def test_agent_minimal_construction():
    agent = Agent(**_make_agent_kwargs())
    # Defaults applied for non-required fields.
    assert agent.domain == "underwriting"
    assert agent.owner_email is None
    assert agent.business_context is None
    assert agent.current_champion_version_id is None


def test_agent_rejects_missing_required():
    # `materiality_tier` has no default — required.
    kwargs = _make_agent_kwargs()
    del kwargs["materiality_tier"]
    with pytest.raises(ValidationError):
        Agent(**kwargs)


def test_agent_rejects_bad_materiality_tier():
    with pytest.raises(ValidationError):
        Agent(**_make_agent_kwargs(materiality_tier="extreme"))


def test_agent_accepts_all_materiality_tiers():
    for tier in MaterialityTier:
        agent = Agent(**_make_agent_kwargs(materiality_tier=tier))
        assert agent.materiality_tier == tier


def test_agent_round_trip_via_dict():
    agent = Agent(**_make_agent_kwargs(
        owner_email="owner@example.com",
        business_context="Used in claim triage.",
    ))
    rebuilt = Agent.model_validate(agent.model_dump())
    assert rebuilt == agent


# ── AgentVersion ────────────────────────────────────────────────────────────

def test_agent_version_minimal_construction_uses_draft_state():
    av = AgentVersion(**_make_agent_version_kwargs())
    # Lifecycle defaults: DRAFT in DEVELOPMENT channel — an unreviewed
    # version should never accidentally land somewhere active.
    assert av.lifecycle_state == LifecycleState.DRAFT
    assert av.channel == DeploymentChannel.DEVELOPMENT
    assert av.major_version == 1
    assert av.minor_version == 0
    assert av.patch_version == 0
    assert av.mock_mode_enabled is False


def test_agent_version_gate_flags_default_unset():
    # Gate flags default to None ("not yet evaluated"), not False —
    # False would mean "we evaluated and it failed", which is different.
    av = AgentVersion(**_make_agent_version_kwargs())
    assert av.staging_tests_passed is None
    assert av.ground_truth_passed is None
    assert av.fairness_passed is None


def test_agent_version_traffic_pct_defaults_to_zero():
    av = AgentVersion(**_make_agent_version_kwargs())
    assert av.shadow_traffic_pct == 0
    assert av.challenger_traffic_pct == 0


def test_agent_version_accepts_all_lifecycle_states():
    for state in LifecycleState:
        av = AgentVersion(**_make_agent_version_kwargs(lifecycle_state=state))
        assert av.lifecycle_state == state


def test_agent_version_with_explicit_authority_thresholds():
    av = AgentVersion(**_make_agent_version_kwargs(
        authority_thresholds={"max_premium_amount": 100_000},
    ))
    assert av.authority_thresholds == {"max_premium_amount": 100_000}


# ── AgentVersionDelegation ──────────────────────────────────────────────────

def test_delegation_defaults_to_authorized():
    deleg = AgentVersionDelegation(
        id=uuid.uuid4(),
        parent_agent_version_id=uuid.uuid4(),
        child_agent_name="risk_extractor",
    )
    # `authorized` defaults to True — an inserted row is live by default.
    assert deleg.authorized is True
    assert deleg.scope == {}


def test_delegation_can_be_version_pinned():
    deleg = AgentVersionDelegation(
        id=uuid.uuid4(),
        parent_agent_version_id=uuid.uuid4(),
        child_agent_version_id=uuid.uuid4(),
    )
    # Either child_agent_name OR child_agent_version_id is set; both
    # being None is also valid at the model level (the DB CHECK
    # constraint catches that — out of scope for this unit test).
    assert deleg.child_agent_name is None
    assert deleg.child_agent_version_id is not None
