"""Unit tests for ``verity.models.prompt``."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from verity.models.lifecycle import ApiRole, GovernanceTier, LifecycleState
from verity.models.prompt import Prompt, PromptVersion


def test_prompt_minimal_construction():
    p = Prompt(id=uuid.uuid4(), name="extract_risk", description="...")
    assert p.display_name is None
    assert p.primary_entity_type is None
    assert p.primary_entity_id is None


def test_prompt_requires_description():
    with pytest.raises(ValidationError):
        Prompt(id=uuid.uuid4(), name="extract_risk")  # missing description


def _make_prompt_version_kwargs(**overrides):
    base = {
        "id": uuid.uuid4(),
        "prompt_id": uuid.uuid4(),
        "content": "You are an underwriting assistant.",
        "api_role": ApiRole.SYSTEM,
        "governance_tier": GovernanceTier.BEHAVIOURAL,
        "change_summary": "Initial.",
    }
    base.update(overrides)
    return base


def test_prompt_version_minimal_construction():
    pv = PromptVersion(**_make_prompt_version_kwargs())
    # Defaults: draft state, high sensitivity, version 1.0.0.
    assert pv.lifecycle_state == LifecycleState.DRAFT
    assert pv.sensitivity_level == "high"
    assert pv.major_version == 1
    assert pv.minor_version == 0
    assert pv.patch_version == 0


def test_prompt_version_accepts_all_api_roles():
    for role in ApiRole:
        pv = PromptVersion(**_make_prompt_version_kwargs(api_role=role))
        assert pv.api_role == role


def test_prompt_version_accepts_all_governance_tiers():
    for tier in GovernanceTier:
        pv = PromptVersion(**_make_prompt_version_kwargs(governance_tier=tier))
        assert pv.governance_tier == tier


def test_prompt_version_rejects_bad_api_role():
    with pytest.raises(ValidationError):
        PromptVersion(**_make_prompt_version_kwargs(api_role="not_a_role"))


def test_prompt_version_change_summary_required():
    kwargs = _make_prompt_version_kwargs()
    del kwargs["change_summary"]
    with pytest.raises(ValidationError):
        PromotionVersion = PromptVersion  # local alias for clarity
        PromotionVersion(**kwargs)


def test_prompt_version_joined_fields_default_none():
    # `prompt_name` and `prompt_description` are populated by JOIN
    # queries; they're None when constructed from a bare row.
    pv = PromptVersion(**_make_prompt_version_kwargs())
    assert pv.prompt_name is None
    assert pv.prompt_description is None
