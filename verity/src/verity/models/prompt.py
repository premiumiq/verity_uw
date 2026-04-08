"""Prompt and PromptVersion models."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.models.lifecycle import (
    ApiRole,
    EntityType,
    GovernanceTier,
    LifecycleState,
)


class Prompt(BaseModel):
    id: UUID
    name: str
    display_name: Optional[str] = None
    description: str
    primary_entity_type: Optional[EntityType] = None
    primary_entity_id: Optional[UUID] = None
    created_at: Optional[datetime] = None


class PromptVersion(BaseModel):
    id: UUID
    prompt_id: UUID
    # 3-part versioning — consistent with agent_version and task_version
    major_version: int = 1
    minor_version: int = 0
    patch_version: int = 0
    version_label: Optional[str] = None
    content: str
    api_role: ApiRole
    governance_tier: GovernanceTier
    lifecycle_state: LifecycleState = LifecycleState.DRAFT
    change_summary: str
    sensitivity_level: str = "high"
    author_name: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    test_required: Optional[bool] = None
    staging_tests_passed: Optional[bool] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    created_at: Optional[datetime] = None

    # Joined fields
    prompt_name: Optional[str] = None
    prompt_description: Optional[str] = None


class PromptAssignment(BaseModel):
    """A prompt version assigned to an agent_version or task_version."""
    assignment_id: Optional[UUID] = None
    prompt_version_id: UUID
    prompt_name: str
    prompt_description: Optional[str] = None
    version_number: int = 0  # Legacy — kept for backward compat with get_entity_prompts query
    prompt_version_number: Optional[int] = None
    version_label: Optional[str] = None
    content: str
    template_variables: list[str] = []
    api_role: ApiRole
    governance_tier: GovernanceTier
    execution_order: int = 1
    is_required: bool = True
    condition_logic: Optional[dict[str, Any]] = None
    lifecycle_state: Optional[LifecycleState] = None
