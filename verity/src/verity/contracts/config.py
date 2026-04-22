"""Resolved configs — what governance hands to runtime to execute an entity.

AgentConfig and TaskConfig are the complete, version-pinned views the
governance plane produces when the runtime asks "what is the current
config for this entity?". Every field inside is either a value or a
boundary model — nothing here depends on database internals.

The runtime never mutates these. It reads them, executes, and logs
back the version IDs it received so the decision log points to exactly
this config.
"""

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.contracts.enums import CapabilityType, LifecycleState, MaterialityTier
from verity.contracts.inference import InferenceConfig, InferenceConfigSnapshot
from verity.contracts.prompt import PromptAssignment
from verity.contracts.tool import ToolAuthorization


class AgentConfig(BaseModel):
    """Complete runtime config for an agent invocation.

    Returned by the governance plane's registry.get_agent_config(). The
    execution engine uses this to run the agent — every parameter that
    controls behaviour is present here. Nothing about how the agent
    behaves is hardcoded in the runtime code.
    """
    agent_id: UUID
    agent_name: str
    display_name: str
    description: str
    materiality_tier: MaterialityTier
    purpose: str
    domain: str

    agent_version_id: UUID
    version_label: str
    lifecycle_state: LifecycleState

    # Inference configuration (resolved from inference_config_id)
    inference_config: InferenceConfig

    # Prompts (system + user, ordered by execution_order)
    prompts: list[PromptAssignment] = []

    # Authorized tools
    tools: list[ToolAuthorization] = []

    # Authority thresholds (HITL triggers, auto-approve thresholds, etc.)
    authority_thresholds: dict[str, Any] = {}
    output_schema: Optional[dict[str, Any]] = None

    def get_inference_snapshot(self) -> InferenceConfigSnapshot:
        """Create a snapshot of the inference config for decision logging.

        This snapshot is stored with every decision log entry so the exact
        parameters used can be audited even if the config is later modified.
        """
        ic = self.inference_config
        return InferenceConfigSnapshot(
            config_name=ic.name,
            model_name=ic.model_name,
            temperature=ic.temperature,
            max_tokens=ic.max_tokens,
            top_p=ic.top_p,
            top_k=ic.top_k,
            stop_sequences=ic.stop_sequences,
            extended_params=ic.extended_params,
        )


class TaskConfig(BaseModel):
    """Complete runtime config for a task invocation.

    Tasks are single-turn, structured-output LLM calls (no agentic loop).
    Like AgentConfig, everything the runtime needs is here — including the
    input/output schemas used for structured-output enforcement.
    """
    task_id: UUID
    task_name: str
    display_name: str
    description: str
    capability_type: CapabilityType
    materiality_tier: MaterialityTier
    purpose: str
    domain: str

    task_version_id: UUID
    version_label: str
    lifecycle_state: LifecycleState

    # Inference configuration
    inference_config: InferenceConfig

    # Input/output schemas (task-level, from the task table)
    task_input_schema: dict[str, Any]
    task_output_schema: dict[str, Any]

    # Prompts
    prompts: list[PromptAssignment] = []

    # Tools (tasks may have authorized tools, though they don't run an agentic loop)
    tools: list[ToolAuthorization] = []

    def get_inference_snapshot(self) -> InferenceConfigSnapshot:
        """Create a snapshot of the inference config for decision logging."""
        ic = self.inference_config
        return InferenceConfigSnapshot(
            config_name=ic.name,
            model_name=ic.model_name,
            temperature=ic.temperature,
            max_tokens=ic.max_tokens,
            top_p=ic.top_p,
            top_k=ic.top_k,
            stop_sequences=ic.stop_sequences,
            extended_params=ic.extended_params,
        )
