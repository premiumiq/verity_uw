"""Domain factories for tests.

Each ``make_*`` helper inserts a single row through the same named-query
that production code uses (``db.execute_returning("insert_X", …)``) and
returns a populated Pydantic model. Defaults are sensible for tests but
override-able through kwargs.

Why these belong here, not as pytest fixtures:
  - Fixtures share state across a single test; tests usually want to
    create *several* agents / tasks / prompts each with different setup.
  - Plain helpers compose freely without fighting fixture scoping.
  - Test reads top-to-bottom: ``av = await make_agent_version(db, …)``
    is clearer than yet another decorator.

Naming convention: ``make_<entity>(db, …) -> <Entity>``.
For lifecycle transitions, ``promote(db, version, to_state)`` updates
the version's state via the same named query the governance plane uses.

Example:

    async def test_something(db):
        agent = await make_agent(db, name="risk_extractor")
        av = await make_agent_version(db, agent_id=agent.id)
        await promote(db, av, to_state="candidate")
        # …
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, NamedTuple
from uuid import UUID

from verity.db.connection import Database
from verity.models.agent import Agent, AgentVersion
from verity.models.lifecycle import (
    DeploymentChannel,
    LifecycleState,
    STATE_TO_CHANNEL,
)
from verity.models.prompt import Prompt, PromptVersion
from verity.models.task import Task, TaskVersion
from verity.models.tool import Tool


# ── Helpers ─────────────────────────────────────────────────────────────────

def _unique(prefix: str) -> str:
    """Short unique suffix so test rows don't collide on UNIQUE(name)."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _get_test_inference_config_id(db: Database) -> UUID:
    """Look up the inference_config seeded into the template DB.

    Caches via attribute on the function so the lookup happens once per
    test (the per-test cloned DB has the same UUID since it's copied
    from the template, but a fresh fixture lookup is robust).
    """
    row = await db.fetch_one_raw(
        "SELECT id FROM inference_config WHERE name = %(name)s",
        {"name": "test_default_config"},
    )
    if row is None:
        raise RuntimeError(
            "Canonical seed inference_config 'test_default_config' is "
            "missing from the test template DB. Check tests/fixtures/"
            "canonical_seed.py and tests/conftest.py:_setup_template."
        )
    return row["id"]


# ── inference_config ───────────────────────────────────────────────────────

async def make_inference_config(
    db: Database,
    *,
    name: str | None = None,
    display_name: str | None = None,
    description: str = "Test inference config.",
    intended_use: str = "Test usage.",
    model_name: str = "claude-sonnet-4-20250514",
    temperature: float | None = 0.0,
    max_tokens: int | None = 4096,
    extended_params: dict[str, Any] | None = None,
) -> UUID:
    """Insert an inference_config row. Returns its id."""
    name = name or _unique("ic")
    display_name = display_name or name
    row = await db.execute_returning(
        "insert_inference_config",
        {
            "name": name,
            "display_name": display_name,
            "description": description,
            "intended_use": intended_use,
            "model_name": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": None,
            "top_k": None,
            "stop_sequences": None,
            "extended_params": json.dumps(extended_params or {}),
        },
    )
    assert row is not None
    return row["id"]


# ── agent ──────────────────────────────────────────────────────────────────

async def make_agent(
    db: Database,
    *,
    name: str | None = None,
    display_name: str | None = None,
    description: str = "Test agent.",
    purpose: str = "Test purpose.",
    domain: str = "underwriting",
    materiality_tier: str = "low",
    owner_name: str = "Test Owner",
    owner_email: str | None = None,
) -> Agent:
    """Insert an agent header row. Returns the populated Agent model."""
    name = name or _unique("agent")
    display_name = display_name or name
    row = await db.execute_returning(
        "insert_agent",
        {
            "name": name,
            "display_name": display_name,
            "description": description,
            "purpose": purpose,
            "domain": domain,
            "materiality_tier": materiality_tier,
            "owner_name": owner_name,
            "owner_email": owner_email,
            "business_context": None,
            "known_limitations": None,
            "regulatory_notes": None,
        },
    )
    assert row is not None
    return Agent(
        id=row["id"],
        name=name,
        display_name=display_name,
        description=description,
        purpose=purpose,
        domain=domain,
        materiality_tier=materiality_tier,
        owner_name=owner_name,
        owner_email=owner_email,
        created_at=row.get("created_at"),
    )


async def make_agent_version(
    db: Database,
    *,
    agent_id: UUID | None = None,
    inference_config_id: UUID | None = None,
    lifecycle_state: str = "draft",
    channel: str = "development",
    output_schema: dict[str, Any] | None = None,
    mock_mode_enabled: bool = True,
    developer_name: str = "tests",
    change_summary: str = "Created by builder.",
    change_type: str = "initial",
    major_version: int = 1,
    minor_version: int = 0,
    patch_version: int = 0,
) -> AgentVersion:
    """Insert an agent_version row. If ``agent_id`` is omitted a fresh
    Agent is created on the spot — convenient for tests that only need
    a version and don't care about the parent agent's identity."""
    if agent_id is None:
        agent_id = (await make_agent(db)).id
    if inference_config_id is None:
        inference_config_id = await _get_test_inference_config_id(db)

    row = await db.execute_returning(
        "insert_agent_version",
        {
            "agent_id": str(agent_id),
            "major_version": major_version,
            "minor_version": minor_version,
            "patch_version": patch_version,
            "lifecycle_state": lifecycle_state,
            "channel": channel,
            "inference_config_id": str(inference_config_id),
            "output_schema": json.dumps(output_schema) if output_schema else None,
            "authority_thresholds": "{}",
            "mock_mode_enabled": mock_mode_enabled,
            "decision_log_detail": "standard",
            "developer_name": developer_name,
            "change_summary": change_summary,
            "change_type": change_type,
            "cloned_from_version_id": None,
        },
    )
    assert row is not None
    return AgentVersion(
        id=row["id"],
        agent_id=agent_id,
        inference_config_id=inference_config_id,
        major_version=major_version,
        minor_version=minor_version,
        patch_version=patch_version,
        version_label=row.get("version_label"),
        lifecycle_state=LifecycleState(lifecycle_state),
        channel=DeploymentChannel(channel),
        output_schema=output_schema,
        mock_mode_enabled=mock_mode_enabled,
        developer_name=developer_name,
        change_summary=change_summary,
        change_type=change_type,
        created_at=row.get("created_at"),
    )


# ── task ───────────────────────────────────────────────────────────────────

async def make_task(
    db: Database,
    *,
    name: str | None = None,
    display_name: str | None = None,
    description: str = "Test task.",
    capability_type: str = "extraction",
    purpose: str = "Test purpose.",
    domain: str = "underwriting",
    materiality_tier: str = "low",
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    owner_name: str = "Test Owner",
) -> Task:
    """Insert a task header row. Returns the populated Task model."""
    name = name or _unique("task")
    display_name = display_name or name
    input_schema = input_schema or {"type": "object", "properties": {}}
    output_schema = output_schema or {"type": "object", "properties": {}}
    row = await db.execute_returning(
        "insert_task",
        {
            "name": name,
            "display_name": display_name,
            "description": description,
            "capability_type": capability_type,
            "purpose": purpose,
            "domain": domain,
            "materiality_tier": materiality_tier,
            "input_schema": json.dumps(input_schema),
            "output_schema": json.dumps(output_schema),
            "owner_name": owner_name,
            "owner_email": None,
            "business_context": None,
            "known_limitations": None,
            "regulatory_notes": None,
        },
    )
    assert row is not None
    return Task(
        id=row["id"],
        name=name,
        display_name=display_name,
        description=description,
        capability_type=capability_type,
        purpose=purpose,
        domain=domain,
        materiality_tier=materiality_tier,
        input_schema=input_schema,
        output_schema=output_schema,
        owner_name=owner_name,
        created_at=row.get("created_at"),
    )


async def make_task_version(
    db: Database,
    *,
    task_id: UUID | None = None,
    inference_config_id: UUID | None = None,
    lifecycle_state: str = "draft",
    channel: str = "development",
    output_schema: dict[str, Any] | None = None,
    mock_mode_enabled: bool = True,
    major_version: int = 1,
    minor_version: int = 0,
    patch_version: int = 0,
) -> TaskVersion:
    """Insert a task_version row, creating the parent task if needed."""
    if task_id is None:
        task_id = (await make_task(db)).id
    if inference_config_id is None:
        inference_config_id = await _get_test_inference_config_id(db)

    row = await db.execute_returning(
        "insert_task_version",
        {
            "task_id": str(task_id),
            "major_version": major_version,
            "minor_version": minor_version,
            "patch_version": patch_version,
            "lifecycle_state": lifecycle_state,
            "channel": channel,
            "inference_config_id": str(inference_config_id),
            "output_schema": json.dumps(output_schema) if output_schema else None,
            "mock_mode_enabled": mock_mode_enabled,
            "decision_log_detail": "standard",
            "developer_name": "tests",
            "change_summary": "Created by builder.",
            "change_type": "initial",
            "cloned_from_version_id": None,
        },
    )
    assert row is not None
    return TaskVersion(
        id=row["id"],
        task_id=task_id,
        inference_config_id=inference_config_id,
        major_version=major_version,
        minor_version=minor_version,
        patch_version=patch_version,
        version_label=row.get("version_label"),
        lifecycle_state=LifecycleState(lifecycle_state),
        channel=DeploymentChannel(channel),
        output_schema=output_schema,
        mock_mode_enabled=mock_mode_enabled,
        created_at=row.get("created_at"),
    )


# ── prompt ─────────────────────────────────────────────────────────────────

async def make_prompt(
    db: Database,
    *,
    name: str | None = None,
    display_name: str | None = None,
    description: str = "Test prompt.",
) -> Prompt:
    """Insert a prompt header row."""
    name = name or _unique("prompt")
    row = await db.execute_returning(
        "insert_prompt",
        {
            "name": name,
            "display_name": display_name or name,
            "description": description,
            "primary_entity_type": None,
            "primary_entity_id": None,
        },
    )
    assert row is not None
    return Prompt(
        id=row["id"],
        name=name,
        display_name=display_name or name,
        description=description,
        created_at=row.get("created_at"),
    )


async def make_prompt_version(
    db: Database,
    *,
    prompt_id: UUID | None = None,
    content: str = "You are a helpful test assistant. Reply concisely.",
    api_role: str = "system",
    governance_tier: str = "behavioural",
    lifecycle_state: str = "draft",
    change_summary: str = "Created by builder.",
    sensitivity_level: str = "high",
    major_version: int = 1,
    minor_version: int = 0,
    patch_version: int = 0,
) -> PromptVersion:
    """Insert a prompt_version row, creating the parent prompt if needed."""
    if prompt_id is None:
        prompt_id = (await make_prompt(db)).id
    row = await db.execute_returning(
        "insert_prompt_version",
        {
            "prompt_id": str(prompt_id),
            "major_version": major_version,
            "minor_version": minor_version,
            "patch_version": patch_version,
            "content": content,
            # template_variables is TEXT[] in Postgres — pass a list, not JSON.
            "template_variables": [],
            "api_role": api_role,
            "governance_tier": governance_tier,
            "lifecycle_state": lifecycle_state,
            "change_summary": change_summary,
            "sensitivity_level": sensitivity_level,
            "author_name": "tests",
            "cloned_from_version_id": None,
        },
    )
    assert row is not None
    return PromptVersion(
        id=row["id"],
        prompt_id=prompt_id,
        major_version=major_version,
        minor_version=minor_version,
        patch_version=patch_version,
        version_label=row.get("version_label"),
        content=content,
        api_role=api_role,
        governance_tier=governance_tier,
        lifecycle_state=LifecycleState(lifecycle_state),
        change_summary=change_summary,
        sensitivity_level=sensitivity_level,
        author_name="tests",
        created_at=row.get("created_at"),
    )


# ── tool ───────────────────────────────────────────────────────────────────

async def make_tool(
    db: Database,
    *,
    name: str | None = None,
    display_name: str | None = None,
    description: str = "Test tool.",
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    transport: str = "python_inprocess",
    implementation_path: str | None = None,
    mock_mode_enabled: bool = True,
    mock_response_key: str = "default",
    is_write_operation: bool = False,
) -> Tool:
    """Insert a tool registry row."""
    name = name or _unique("tool")
    display_name = display_name or name
    input_schema = input_schema or {"type": "object", "properties": {}}
    output_schema = output_schema or {"type": "object", "properties": {}}
    implementation_path = implementation_path or f"tests.tools.{name}"
    row = await db.execute_returning(
        "insert_tool",
        {
            "name": name,
            "display_name": display_name,
            "description": description,
            "input_schema": json.dumps(input_schema),
            "output_schema": json.dumps(output_schema),
            "transport": transport,
            "mcp_server_name": None,
            "mcp_tool_name": None,
            "implementation_path": implementation_path,
            "mock_mode_enabled": mock_mode_enabled,
            "mock_response_key": mock_response_key,
            "data_classification_max": "tier3_confidential",
            "is_write_operation": is_write_operation,
            "requires_confirmation": False,
            "tags": [],
        },
    )
    assert row is not None
    return Tool(
        id=row["id"],
        name=name,
        display_name=display_name,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
        transport=transport,
        implementation_path=implementation_path,
        mock_mode_enabled=mock_mode_enabled,
        mock_response_key=mock_response_key,
        is_write_operation=is_write_operation,
        created_at=row.get("created_at"),
    )


# ── wiring (prompt assignment, tool authorization, champion pointer) ──────

async def assign_prompt(
    db: Database,
    *,
    entity_version: AgentVersion | TaskVersion,
    prompt_version: PromptVersion,
    api_role: str = "system",
    governance_tier: str = "behavioural",
    execution_order: int = 1,
    is_required: bool = True,
) -> UUID:
    """Wire a prompt_version to an agent_version or task_version.

    Returns the entity_prompt_assignment row id.
    """
    if isinstance(entity_version, AgentVersion):
        entity_type = "agent"
    elif isinstance(entity_version, TaskVersion):
        entity_type = "task"
    else:
        raise TypeError(
            f"assign_prompt() expects AgentVersion or TaskVersion, got "
            f"{type(entity_version).__name__}"
        )
    row = await db.execute_returning(
        "insert_entity_prompt_assignment",
        {
            "entity_type": entity_type,
            "entity_version_id": str(entity_version.id),
            "prompt_version_id": str(prompt_version.id),
            "api_role": api_role,
            "governance_tier": governance_tier,
            "execution_order": execution_order,
            "is_required": is_required,
            "condition_logic": None,
        },
    )
    assert row is not None
    return row["id"]


async def authorize_tool(
    db: Database,
    *,
    agent_version: AgentVersion,
    tool: Tool,
    notes: str | None = None,
) -> UUID:
    """Authorize an agent_version to call a tool. Returns the
    agent_version_tool row id."""
    row = await db.execute_returning(
        "insert_agent_version_tool",
        {
            "agent_version_id": str(agent_version.id),
            "tool_id": str(tool.id),
            "authorized": True,
            "notes": notes,
        },
    )
    assert row is not None
    return row["id"]


async def set_champion(db: Database, agent_version: AgentVersion) -> None:
    """Promote an agent_version to champion AND update the agent's
    current_champion_version_id pointer.

    Production lifecycle would route through governance.lifecycle.promote()
    which handles approvals + audit; for tests we want the resulting state
    without the gate ceremony. Use this builder for engine tests that
    need a champion to resolve via ``Registry.get_agent_config``.
    """
    await promote(db, agent_version, to_state="champion")
    await db.execute(
        "set_agent_champion",
        {
            "agent_id": str(agent_version.agent_id),
            "version_id": str(agent_version.id),
        },
    )


class CompleteAgent(NamedTuple):
    """The bundle ``make_complete_agent`` returns.

    Tests use ``.name`` for ``run_agent(agent_name=…)`` and ``.version``
    for any direct version-id work. Returning a NamedTuple instead of
    monkey-patching the Pydantic AgentVersion keeps Pydantic's strict
    validation intact.
    """
    version: AgentVersion
    name: str
    agent: Agent


async def make_complete_agent(
    db: Database,
    *,
    name: str | None = None,
    system_prompt: str = "You are a helpful test assistant. Be concise.",
    tools: list[Tool] | None = None,
    promote_to_champion: bool = True,
) -> CompleteAgent:
    """One-call setup for a fully-wired agent ready for ``run_agent``.

    Creates: agent, agent_version (mock_mode_enabled=False so the engine
    actually calls the LLM gateway), prompt + prompt_version, prompt
    assignment. Optionally authorizes a list of tools and promotes the
    version to champion (default True — most engine tests want the
    agent resolvable via ``get_agent_champion``).

    Returns a ``CompleteAgent`` namedtuple with the version, the agent
    name (for ``run_agent`` invocation), and the agent header.
    """
    agent = await make_agent(db, name=name)
    av = await make_agent_version(db, agent_id=agent.id, mock_mode_enabled=False)

    prompt = await make_prompt(db, name=f"system_{agent.name}")
    pv = await make_prompt_version(db, prompt_id=prompt.id, content=system_prompt)
    await assign_prompt(db, entity_version=av, prompt_version=pv)

    if tools:
        for tool in tools:
            await authorize_tool(db, agent_version=av, tool=tool)

    if promote_to_champion:
        await set_champion(db, av)

    return CompleteAgent(version=av, name=agent.name, agent=agent)


# ── lifecycle promotion ────────────────────────────────────────────────────

async def promote(
    db: Database,
    version: AgentVersion | TaskVersion,
    *,
    to_state: str,
    channel: str | None = None,
) -> None:
    """Update a version's lifecycle_state via the governance named query.

    Skips approval-record bookkeeping — that's the governance plane's job
    and gets exercised by the lifecycle tests in W1.4. This helper is for
    setting up state in tests that aren't *about* the promotion gate
    (e.g., 'an engine test needs a champion agent_version, just put it
    there').

    For tests that exercise the gate semantics, call the governance API
    directly instead of this helper.
    """
    target = LifecycleState(to_state)
    channel = channel or STATE_TO_CHANNEL[target].value

    if isinstance(version, AgentVersion):
        query_name = "update_agent_version_state"
    elif isinstance(version, TaskVersion):
        query_name = "update_task_version_state"
    else:
        raise TypeError(
            f"promote() expects AgentVersion or TaskVersion, got "
            f"{type(version).__name__}"
        )

    await db.execute(
        query_name,
        {
            "version_id": str(version.id),
            "new_state": to_state,
            "channel": channel,
        },
    )

    # Mutate the in-memory model so the caller's reference stays current.
    version.lifecycle_state = target
    version.channel = DeploymentChannel(channel)
