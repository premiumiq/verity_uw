"""Prompt and PromptVersion models.

PromptAssignment was moved to verity.contracts.prompt as of Phase 1 of
the Registry/Runtime split. It is re-exported here for backward
compatibility.

What stays here (governance-internal DB read shapes):
- Prompt — the prompt header row
- PromptVersion — a versioned prompt definition with content and lifecycle
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from verity.models.lifecycle import (
    ApiRole,
    EntityType,
    GovernanceTier,
    LifecycleState,
)

# Re-export boundary model from contracts for backward compatibility.
from verity.contracts.prompt import PromptAssignment  # noqa: F401


class Prompt(BaseModel):
    """Prompt header — one row per named prompt (N versions reference it)."""
    id: UUID
    name: str
    display_name: Optional[str] = None
    description: str
    primary_entity_type: Optional[EntityType] = None
    primary_entity_id: Optional[UUID] = None
    created_at: Optional[datetime] = None


class PromptVersion(BaseModel):
    """One versioned prompt: content + governance metadata + lifecycle state."""
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

    # Joined fields (populated by list/detail queries, not in the DB row)
    prompt_name: Optional[str] = None
    prompt_description: Optional[str] = None
