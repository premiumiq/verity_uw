"""Unit tests for ``verity.models.task``."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from verity.models.lifecycle import (
    CapabilityType,
    DeploymentChannel,
    LifecycleState,
    MaterialityTier,
)
from verity.models.task import Task, TaskVersion


def _make_task_kwargs(**overrides):
    base = {
        "id": uuid.uuid4(),
        "name": "test_task",
        "display_name": "Test Task",
        "description": "...",
        "capability_type": CapabilityType.EXTRACTION,
        "purpose": "...",
        "materiality_tier": MaterialityTier.MEDIUM,
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "owner_name": "Alice",
    }
    base.update(overrides)
    return base


def _make_task_version_kwargs(**overrides):
    base = {
        "id": uuid.uuid4(),
        "task_id": uuid.uuid4(),
        "inference_config_id": uuid.uuid4(),
    }
    base.update(overrides)
    return base


# ── Task ────────────────────────────────────────────────────────────────────

def test_task_minimal_construction():
    task = Task(**_make_task_kwargs())
    assert task.domain == "underwriting"
    assert task.input_schema == {"type": "object"}
    assert task.output_schema == {"type": "object"}


def test_task_rejects_bad_capability_type():
    with pytest.raises(ValidationError):
        Task(**_make_task_kwargs(capability_type="not_a_capability"))


def test_task_accepts_all_capability_types():
    for cap in CapabilityType:
        task = Task(**_make_task_kwargs(capability_type=cap))
        assert task.capability_type == cap


def test_task_input_schema_required():
    kwargs = _make_task_kwargs()
    del kwargs["input_schema"]
    with pytest.raises(ValidationError):
        Task(**kwargs)


def test_task_round_trip():
    task = Task(**_make_task_kwargs(
        owner_email="owner@example.com",
        regulatory_notes="Subject to Colorado SB21-169 reporting.",
    ))
    assert Task.model_validate(task.model_dump()) == task


# ── TaskVersion ─────────────────────────────────────────────────────────────

def test_task_version_minimal_construction_uses_draft_state():
    tv = TaskVersion(**_make_task_version_kwargs())
    assert tv.lifecycle_state == LifecycleState.DRAFT
    assert tv.channel == DeploymentChannel.DEVELOPMENT


def test_task_version_gate_flags_default_unset():
    tv = TaskVersion(**_make_task_version_kwargs())
    assert tv.staging_tests_passed is None
    assert tv.ground_truth_passed is None
    assert tv.fairness_passed is None


def test_task_version_accepts_all_lifecycle_states():
    for state in LifecycleState:
        tv = TaskVersion(**_make_task_version_kwargs(lifecycle_state=state))
        assert tv.lifecycle_state == state
