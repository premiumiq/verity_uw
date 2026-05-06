"""Pydantic models for the Verity YAML bundle format.

The bundle is the unit of import/export — see docs/plans/
studio-build-plan.md §"YAML format for review" for the design notes.

Format conventions (encoded in field order and validators):

* References between entities are by **name + version_label**, never by
  UUID. Bundles re-import cleanly into a different DB because there are
  no environment-specific identifiers.
* A header (Prompt, Task, Agent) carries its versions inline under
  ``versions:``. The 1:N header→versions relationship is universal in
  the Verity schema, so nesting is the natural shape.
* ``lifecycle_state`` is recorded on export for audit/diff but is
  ignored on import — every imported version is created as ``draft``.
* Derived and audit fields (id, created_at, updated_at, version_label
  components, content_embedding, valid_from/to) never appear in YAML.
* Top-level entries are a discriminated union keyed on ``kind``.

Slice 4A (this file) defines the models. Slice 4B will add the
importer that consumes them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field


# ── Sub-models used inside agent/task version entries ───────────────────────


class PromptAssignment(BaseModel):
    """One prompt attached to an agent_version or task_version.

    References a prompt by ``(prompt, version)`` — both are name-based
    so the assignment survives re-importing into a different DB.
    """
    prompt: str
    version: str
    api_role: Optional[str] = None
    governance_tier: Optional[str] = None
    execution_order: Optional[int] = None
    is_required: Optional[bool] = None
    condition_logic: Optional[dict[str, Any]] = None


class ToolAuthorization(BaseModel):
    """One tool authorized for an agent_version or task_version."""
    tool: str
    authorized: bool = True
    notes: Optional[str] = None


class SourceBindingEntry(BaseModel):
    """One pre-prompt source binding (unified reference grammar).

    The ``reference`` is a string in the four-pattern grammar
    described in docs/architecture/execution.md
    (input.* / source.* / literal.* / context.*). It is captured
    verbatim — the YAML format is grammar-agnostic.
    """
    template_var: str
    reference: str
    required: Optional[bool] = None
    execution_order: Optional[int] = None
    description: Optional[str] = None


class TargetPayloadFieldEntry(BaseModel):
    """One payload field on a write_target."""
    payload_field: str
    reference: str
    required: Optional[bool] = None
    execution_order: Optional[int] = None
    description: Optional[str] = None


class WriteTargetEntry(BaseModel):
    """One declarative write target on an agent_version or task_version.

    The connector is referenced by name. Payload field references use
    the same grammar strings as SourceBindingEntry.
    """
    name: str
    connector: str
    write_method: str
    container: Optional[str] = None
    required: Optional[bool] = None
    execution_order: Optional[int] = None
    description: Optional[str] = None
    payload_fields: list[TargetPayloadFieldEntry] = Field(default_factory=list)


class DelegationEntry(BaseModel):
    """One sub-agent delegation row.

    ``child_agent`` is the child agent's name (required). ``child_version``
    is an optional version_label — when present, the delegation is
    pinned to that exact version of the child; when absent, the
    delegation is champion-tracking (always uses the child's current
    champion).

    The exporter always enqueues ``child_agent`` for transitive
    closure, so an exported bundle is self-contained: the parent
    agent and every agent it delegates to (transitively) appear as
    top-level entries in the same bundle.
    """
    child_agent: str
    child_version: Optional[str] = None
    scope: dict[str, Any] = Field(default_factory=dict)
    authorized: bool = True
    rationale: Optional[str] = None
    notes: Optional[str] = None


# ── Header entries (top-level discriminated union) ──────────────────────────


class InferenceConfigEntry(BaseModel):
    """An inference_config row — global, not versioned."""
    kind: Literal["InferenceConfig"] = "InferenceConfig"
    name: str
    display_name: str
    description: Optional[str] = None
    model_name: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    extended_params: Optional[dict[str, Any]] = None


class ToolEntry(BaseModel):
    """A tool row — global, not versioned.

    The ``mock_responses`` field is JSONB in the schema and may be
    either a list of mock samples or a dict keyed by call args; the
    YAML format keeps it as a free-form JSON value.
    """
    kind: Literal["Tool"] = "Tool"
    name: str
    display_name: str
    description: Optional[str] = None
    transport: str
    mcp_server_name: Optional[str] = None
    mcp_tool_name: Optional[str] = None
    implementation_path: Optional[str] = None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    is_write_operation: Optional[bool] = None
    requires_confirmation: Optional[bool] = None
    mock_mode_enabled: Optional[bool] = None
    mock_responses: Optional[Union[dict[str, Any], list[Any]]] = None


class DataConnectorEntry(BaseModel):
    """A data_connector row — global, not versioned."""
    kind: Literal["DataConnector"] = "DataConnector"
    name: str
    display_name: str
    description: Optional[str] = None
    connector_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    owner_name: Optional[str] = None


class PromptVersionEntry(BaseModel):
    """One row from prompt_version, attached to a PromptEntry header.

    ``lifecycle_state`` is informational on export — re-importing
    creates the row as 'draft' regardless of what the YAML says.
    """
    version_label: str
    lifecycle_state: Optional[str] = None
    api_role: str
    governance_tier: str
    change_summary: str
    sensitivity_level: Optional[str] = None
    author_name: Optional[str] = None
    content: str


class PromptEntry(BaseModel):
    """A prompt header plus all its versions."""
    kind: Literal["Prompt"] = "Prompt"
    name: str
    display_name: str
    description: str
    primary_entity_type: Optional[str] = None
    primary_entity_id: Optional[str] = None  # name reference if we ever wire this
    versions: list[PromptVersionEntry] = Field(default_factory=list)


class TaskVersionEntry(BaseModel):
    """One row from task_version, with all its wiring inline."""
    version_label: str
    lifecycle_state: Optional[str] = None
    change_summary: Optional[str] = None
    change_type: Optional[str] = None
    developer_name: Optional[str] = None
    inference_config: Optional[str] = None
    output_schema: Optional[dict[str, Any]] = None
    mock_mode_enabled: Optional[bool] = None
    decision_log_detail: Optional[str] = None
    prompts: list[PromptAssignment] = Field(default_factory=list)
    tools: list[ToolAuthorization] = Field(default_factory=list)
    sources: list[SourceBindingEntry] = Field(default_factory=list)
    targets: list[WriteTargetEntry] = Field(default_factory=list)


class TaskEntry(BaseModel):
    """A task header plus all its versions."""
    kind: Literal["Task"] = "Task"
    name: str
    display_name: str
    description: Optional[str] = None
    capability_type: str
    purpose: Optional[str] = None
    domain: Optional[str] = None
    materiality_tier: Optional[str] = None
    owner_name: Optional[str] = None
    business_context: Optional[str] = None
    known_limitations: Optional[str] = None
    regulatory_notes: Optional[str] = None
    input_schema: Optional[dict[str, Any]] = None
    output_schema: Optional[dict[str, Any]] = None
    versions: list[TaskVersionEntry] = Field(default_factory=list)


class AgentVersionEntry(BaseModel):
    """One row from agent_version, with all its wiring inline.

    Sub-agent delegations are first-class on agents (not tasks) so
    they appear here but not on TaskVersionEntry.
    """
    version_label: str
    lifecycle_state: Optional[str] = None
    change_summary: Optional[str] = None
    change_type: Optional[str] = None
    developer_name: Optional[str] = None
    inference_config: Optional[str] = None
    output_schema: Optional[dict[str, Any]] = None
    authority_thresholds: Optional[dict[str, Any]] = None
    mock_mode_enabled: Optional[bool] = None
    decision_log_detail: Optional[str] = None
    limitations_this_version: Optional[str] = None
    prompts: list[PromptAssignment] = Field(default_factory=list)
    tools: list[ToolAuthorization] = Field(default_factory=list)
    sources: list[SourceBindingEntry] = Field(default_factory=list)
    targets: list[WriteTargetEntry] = Field(default_factory=list)
    delegations: list[DelegationEntry] = Field(default_factory=list)


class AgentEntry(BaseModel):
    """An agent header plus all its versions."""
    kind: Literal["Agent"] = "Agent"
    name: str
    display_name: str
    description: Optional[str] = None
    purpose: Optional[str] = None
    domain: Optional[str] = None
    materiality_tier: Optional[str] = None
    owner_name: Optional[str] = None
    business_context: Optional[str] = None
    known_limitations: Optional[str] = None
    regulatory_notes: Optional[str] = None
    versions: list[AgentVersionEntry] = Field(default_factory=list)


# ── Top-level discriminated union ───────────────────────────────────────────

# Pydantic v2 picks the right concrete class by reading the ``kind``
# field on each entry. The order of the union members is irrelevant
# because the discriminator handles dispatch.
Entry = Annotated[
    Union[
        InferenceConfigEntry,
        ToolEntry,
        DataConnectorEntry,
        PromptEntry,
        TaskEntry,
        AgentEntry,
    ],
    Field(discriminator="kind"),
]


class Bundle(BaseModel):
    """A complete YAML bundle — one or more top-level entries.

    Field declaration order is the YAML output order (the serializer
    keeps field order rather than alphabetising) so files read
    top-down: format metadata, then content.
    """
    apiVersion: Literal["studio.verity.ai/v1"] = "studio.verity.ai/v1"
    kind: Literal["Bundle"] = "Bundle"
    exported_at: Optional[datetime] = None
    exported_from: Optional[str] = None
    entities: list[Entry] = Field(default_factory=list)
