"""Unit tests for ``verity.models.application``."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from verity.models.application import Application, ApplicationEntity, ExecutionContext
from verity.models.lifecycle import EntityType


def test_application_minimal():
    app = Application(id=uuid.uuid4(), name="uw_demo", display_name="UW Demo")
    assert app.description is None


def test_application_entity_requires_entity_type():
    with pytest.raises(ValidationError):
        ApplicationEntity(
            id=uuid.uuid4(),
            application_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
            # entity_type missing
        )


def test_application_entity_accepts_each_entity_type():
    for et in EntityType:
        ae = ApplicationEntity(
            id=uuid.uuid4(),
            application_id=uuid.uuid4(),
            entity_type=et,
            entity_id=uuid.uuid4(),
        )
        assert ae.entity_type == et


def test_execution_context_minimal():
    ctx = ExecutionContext(
        id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        context_ref="account-123",
    )
    assert ctx.context_type is None
    assert ctx.metadata == {}


def test_execution_context_carries_metadata():
    ctx = ExecutionContext(
        id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        context_ref="submission-42",
        context_type="submission",
        metadata={"premium_band": "high", "lob": "gl"},
    )
    assert ctx.metadata["premium_band"] == "high"
