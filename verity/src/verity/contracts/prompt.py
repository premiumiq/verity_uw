"""Prompt assignment — a prompt version bound to an agent/task version.

Only PromptAssignment lives in contracts: it's what the runtime needs to
assemble messages for an LLM call. The governance-internal Prompt and
PromptVersion DB models stay in verity.models.prompt.
"""

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.contracts.enums import ApiRole, GovernanceTier, LifecycleState


class PromptAssignment(BaseModel):
    """A prompt version assigned to an agent_version or task_version.

    Carries everything the runtime needs to render and order the prompt
    during execution: the content, any template variables, its role
    (system/user/prefill), and the execution order within the assignment.
    """
    assignment_id: Optional[UUID] = None
    prompt_version_id: UUID
    prompt_name: str
    prompt_description: Optional[str] = None
    # Legacy — kept for backward compat with get_entity_prompts query
    version_number: int = 0
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
