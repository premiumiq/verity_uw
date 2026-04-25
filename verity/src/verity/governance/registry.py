"""Verity Registry — register and retrieve all governed entities.

The registry is the source of truth for all AI component definitions.
No agent, task, prompt, or tool exists outside of Verity's registry.
"""

import json
import os
import re
from typing import Any, Optional
from uuid import UUID

from verity.db.connection import Database
from verity.models.agent import AgentConfig
from verity.models.inference_config import InferenceConfig
from verity.models.lifecycle import EntityType
from verity.models.prompt import PromptAssignment
from verity.models.task import TaskConfig
from verity.models.tool import ToolAuthorization


class Registry:
    """Register and retrieve agents, tasks, prompts, configs, tools, pipelines."""

    def __init__(self, db: Database):
        self.db = db

    # ── AGENT CONFIG (runtime resolution) ─────────────────────

    async def get_agent_config(
        self, agent_name: str, effective_date=None, version_id=None,
    ) -> AgentConfig:
        """Resolve the full config for a named agent.

        Resolution priority:
        1. version_id (if provided): direct version lookup, ignores dates
        2. effective_date (if provided): SCD Type 2 temporal resolution
        3. Default: current champion via pointer (fastest)
        """
        if version_id:
            row = await self.db.fetch_one("get_agent_version_by_id", {"version_id": str(version_id)})
        elif effective_date:
            row = await self.db.fetch_one("get_agent_champion_at_date", {
                "agent_name": agent_name, "effective_date": effective_date,
            })
        else:
            row = await self.db.fetch_one("get_agent_champion", {"agent_name": agent_name})
        if not row:
            raise ValueError(f"Agent '{agent_name}' not found or has no champion version")

        # Build the inference config
        inference_config = InferenceConfig(
            id=row["inference_config_id"],
            name=row["inference_config_name"],
            description="",
            intended_use="",
            model_name=row["model_name"],
            temperature=_to_float(row.get("temperature")),
            max_tokens=row.get("max_tokens"),
            top_p=_to_float(row.get("top_p")),
            top_k=row.get("top_k"),
            stop_sequences=row.get("stop_sequences"),
            extended_params=row.get("extended_params") or {},
        )

        # Get prompts assigned to this agent version
        prompt_rows = await self.db.fetch_all("get_entity_prompts", {
            "entity_type": "agent",
            "entity_version_id": row["agent_version_id"],
        })
        prompts = [
            PromptAssignment(
                assignment_id=p.get("assignment_id"),
                prompt_version_id=p["prompt_version_id"],
                prompt_name=p["prompt_name"],
                prompt_description=p.get("prompt_description"),
                version_number=p["prompt_version_number"],
                content=p["content"],
                api_role=p["api_role"],
                governance_tier=p["governance_tier"],
                execution_order=p["execution_order"],
                is_required=p["is_required"],
                condition_logic=p.get("condition_logic"),
                lifecycle_state=p.get("prompt_lifecycle_state"),
            )
            for p in prompt_rows
        ]

        # Get authorized tools
        tool_rows = await self.db.fetch_all("get_entity_tools", {
            "entity_version_id": row["agent_version_id"],
        })
        tools = [
            ToolAuthorization(
                authorization_id=t.get("authorization_id"),
                tool_id=t["tool_id"],
                name=t["name"],
                display_name=t["display_name"],
                description=t["description"],
                input_schema=t["input_schema"],
                output_schema=t["output_schema"],
                transport=t.get("transport", "python_inprocess"),
                mcp_server_name=t.get("mcp_server_name"),
                mcp_tool_name=t.get("mcp_tool_name"),
                implementation_path=t["implementation_path"],
                mock_mode_enabled=t["mock_mode_enabled"],
                mock_response_key=t.get("mock_response_key"),
                data_classification_max=t.get("data_classification_max", "tier3_confidential"),
                is_write_operation=t["is_write_operation"],
                requires_confirmation=t["requires_confirmation"],
            )
            for t in tool_rows
        ]

        return AgentConfig(
            agent_id=row["agent_id"],
            agent_name=row["name"],
            display_name=row["display_name"],
            description=row["description"],
            materiality_tier=row["materiality_tier"],
            purpose=row.get("purpose", ""),
            domain=row.get("domain", "underwriting"),
            agent_version_id=row["agent_version_id"],
            version_label=row["version_label"],
            lifecycle_state=row["lifecycle_state"],
            inference_config=inference_config,
            prompts=prompts,
            tools=tools,
            authority_thresholds=row.get("authority_thresholds") or {},
            output_schema=row.get("output_schema"),
        )

    # ── TASK CONFIG (runtime resolution) ──────────────────────

    async def get_task_config(
        self, task_name: str, effective_date=None, version_id=None,
    ) -> TaskConfig:
        """Resolve the full config for a named task. Same resolution as get_agent_config."""
        if version_id:
            row = await self.db.fetch_one("get_task_version_by_id", {"version_id": str(version_id)})
        elif effective_date:
            row = await self.db.fetch_one("get_task_champion_at_date", {
                "task_name": task_name, "effective_date": effective_date,
            })
        else:
            row = await self.db.fetch_one("get_task_champion", {"task_name": task_name})
        if not row:
            raise ValueError(f"Task '{task_name}' not found or has no champion version")

        inference_config = InferenceConfig(
            id=row["inference_config_id"],
            name=row["inference_config_name"],
            description="",
            intended_use="",
            model_name=row["model_name"],
            temperature=_to_float(row.get("temperature")),
            max_tokens=row.get("max_tokens"),
            top_p=_to_float(row.get("top_p")),
            top_k=row.get("top_k"),
            stop_sequences=row.get("stop_sequences"),
            extended_params=row.get("extended_params") or {},
        )

        prompt_rows = await self.db.fetch_all("get_entity_prompts", {
            "entity_type": "task",
            "entity_version_id": row["task_version_id"],
        })
        prompts = [
            PromptAssignment(
                assignment_id=p.get("assignment_id"),
                prompt_version_id=p["prompt_version_id"],
                prompt_name=p["prompt_name"],
                prompt_description=p.get("prompt_description"),
                version_number=p["prompt_version_number"],
                content=p["content"],
                api_role=p["api_role"],
                governance_tier=p["governance_tier"],
                execution_order=p["execution_order"],
                is_required=p["is_required"],
                condition_logic=p.get("condition_logic"),
                lifecycle_state=p.get("prompt_lifecycle_state"),
            )
            for p in prompt_rows
        ]

        tool_rows = await self.db.fetch_all("get_task_tools", {
            "entity_version_id": row["task_version_id"],
        })
        tools = [
            ToolAuthorization(
                authorization_id=t.get("authorization_id"),
                tool_id=t["tool_id"],
                name=t["name"],
                display_name=t["display_name"],
                description=t["description"],
                input_schema=t["input_schema"],
                output_schema=t["output_schema"],
                transport=t.get("transport", "python_inprocess"),
                mcp_server_name=t.get("mcp_server_name"),
                mcp_tool_name=t.get("mcp_tool_name"),
                implementation_path=t["implementation_path"],
                mock_mode_enabled=t["mock_mode_enabled"],
                mock_response_key=t.get("mock_response_key"),
                data_classification_max=t.get("data_classification_max", "tier3_confidential"),
                is_write_operation=t["is_write_operation"],
                requires_confirmation=t["requires_confirmation"],
            )
            for t in tool_rows
        ]

        return TaskConfig(
            task_id=row["task_id"],
            task_name=row["name"],
            display_name=row["display_name"],
            description=row["description"],
            capability_type=row["capability_type"],
            materiality_tier=row["materiality_tier"],
            purpose=row.get("purpose", ""),
            domain=row.get("domain", "underwriting"),
            task_version_id=row["task_version_id"],
            version_label=row["version_label"],
            lifecycle_state=row["lifecycle_state"],
            inference_config=inference_config,
            task_input_schema=row.get("task_input_schema") or {},
            task_output_schema=row.get("task_output_schema") or {},
            prompts=prompts,
            tools=tools,
        )

    # ── REGISTRATION (seed time) ──────────────────────────────

    async def register_inference_config(self, **kwargs) -> dict:
        """Register a named inference config."""
        params = _prepare_json_params(kwargs, json_fields=["extended_params"])
        return await self.db.execute_returning("insert_inference_config", params)

    async def register_agent(self, **kwargs) -> dict:
        """Register an agent (header record, no version yet)."""
        return await self.db.execute_returning("insert_agent", kwargs)

    async def register_agent_version(self, **kwargs) -> dict:
        """Register an agent version."""
        kwargs.setdefault("cloned_from_version_id", None)
        params = _prepare_json_params(kwargs, json_fields=["output_schema", "authority_thresholds"])
        return await self.db.execute_returning("insert_agent_version", params)

    async def register_task(self, **kwargs) -> dict:
        """Register a task (header record, no version yet)."""
        params = _prepare_json_params(kwargs, json_fields=["input_schema", "output_schema"])
        return await self.db.execute_returning("insert_task", params)

    async def register_task_version(self, **kwargs) -> dict:
        """Register a task version."""
        kwargs.setdefault("cloned_from_version_id", None)
        params = _prepare_json_params(kwargs, json_fields=["output_schema"])
        return await self.db.execute_returning("insert_task_version", params)

    async def register_prompt(self, **kwargs) -> dict:
        """Register a prompt (header record)."""
        return await self.db.execute_returning("insert_prompt", kwargs)

    async def register_prompt_version(self, **kwargs) -> dict:
        """Register a prompt version.

        Auto-extracts {{variable}} placeholders from the prompt content
        and stores them in template_variables. These are validated at
        execution time to catch missing context values.
        """
        # Auto-extract template variables from content if not explicitly provided
        if "template_variables" not in kwargs and "content" in kwargs:
            variables = re.findall(r"\{\{(\w+)\}\}", kwargs["content"])
            # Deduplicate while preserving order
            seen = set()
            unique_vars = []
            for v in variables:
                if v not in seen:
                    seen.add(v)
                    unique_vars.append(v)
            kwargs["template_variables"] = unique_vars
        elif "template_variables" not in kwargs:
            kwargs["template_variables"] = []
        kwargs.setdefault("cloned_from_version_id", None)
        return await self.db.execute_returning("insert_prompt_version", kwargs)

    async def assign_prompt(self, **kwargs) -> dict:
        """Assign a prompt version to an agent_version or task_version."""
        params = _prepare_json_params(kwargs, json_fields=["condition_logic"])
        return await self.db.execute_returning("insert_entity_prompt_assignment", params)

    async def register_tool(self, **kwargs) -> dict:
        """Register a tool.

        New dispatch columns (Phase 4a / FC-14) have sensible defaults so
        existing Python-in-process tool registrations don't need to pass
        them explicitly:
          - transport defaults to 'python_inprocess'
          - mcp_server_name / mcp_tool_name default to None (NULL in DB)
        MCP-sourced tools pass transport='mcp_stdio' | 'mcp_sse' | 'mcp_http'
        and mcp_server_name to bind the tool to a registered mcp_server row.
        """
        kwargs.setdefault("transport", "python_inprocess")
        kwargs.setdefault("mcp_server_name", None)
        kwargs.setdefault("mcp_tool_name", None)
        params = _prepare_json_params(kwargs, json_fields=["input_schema", "output_schema"])
        return await self.db.execute_returning("insert_tool", params)

    # ── MCP SERVERS (Phase 4a groundwork) ──────────────────────

    async def register_mcp_server(self, **kwargs) -> dict:
        """Register an MCP server. Used in FC-14b+ when wiring actual servers.

        Required kwargs: name, display_name, transport.
        Transport-dependent kwargs:
          - transport='stdio': command (required), args (optional list[str])
          - transport='sse' | 'http': url (required)
        Optional: env (dict), auth_config (dict), description, active.
        """
        kwargs.setdefault("description", None)
        kwargs.setdefault("command", None)
        kwargs.setdefault("args", [])
        kwargs.setdefault("url", None)
        kwargs.setdefault("env", {})
        kwargs.setdefault("auth_config", {})
        kwargs.setdefault("active", True)
        params = _prepare_json_params(kwargs, json_fields=["env", "auth_config"])
        return await self.db.execute_returning("insert_mcp_server", params)

    async def list_mcp_servers(self) -> list[dict]:
        """All active MCP servers registered with Verity."""
        return await self.db.fetch_all("list_mcp_servers")

    async def get_mcp_server_by_name(self, mcp_server_name: str) -> Optional[dict]:
        """Look up one MCP server by name (runtime uses this during dispatch)."""
        return await self.db.fetch_one(
            "get_mcp_server_by_name",
            {"mcp_server_name": mcp_server_name},
        )

    async def authorize_agent_tool(self, **kwargs) -> dict:
        """Authorize a tool for an agent version."""
        return await self.db.execute_returning("insert_agent_version_tool", kwargs)

    async def authorize_task_tool(self, **kwargs) -> dict:
        """Authorize a tool for a task version."""
        return await self.db.execute_returning("insert_task_version_tool", kwargs)

    # ── AGENT VERSION DELEGATION (FC-1) ────────────────────────
    # First-class governance of "agent A can delegate to agent B"
    # relationships. These methods back the agent_version_delegation
    # table — see schema.sql and docs for the semantics.

    async def register_delegation(self, **kwargs) -> dict:
        """Register a delegation from a parent agent_version to a child agent.

        Required:
          - parent_agent_version_id: UUID of the parent agent version
          - Exactly ONE of:
              child_agent_name:     str, champion-tracking sub-agent by name
              child_agent_version_id: UUID, pin to a specific child version

        Optional:
          - scope: dict  (per-relationship constraints, freeform JSONB)
          - authorized: bool (default True)
          - rationale: str (why this delegation is allowed — governance audit)
          - notes: str

        Raises ValueError if the child target is under- or over-specified.
        """
        child_name = kwargs.get("child_agent_name")
        child_version_id = kwargs.get("child_agent_version_id")
        if (child_name is None) == (child_version_id is None):
            raise ValueError(
                "register_delegation requires EXACTLY one of child_agent_name "
                "(champion-tracking) or child_agent_version_id (version-pinned), "
                f"got child_agent_name={child_name!r}, "
                f"child_agent_version_id={child_version_id!r}."
            )

        kwargs.setdefault("scope", {})
        kwargs.setdefault("authorized", True)
        kwargs.setdefault("rationale", None)
        kwargs.setdefault("notes", None)
        kwargs.setdefault("child_agent_name", None)
        kwargs.setdefault("child_agent_version_id", None)

        # Coerce UUIDs to strings for psycopg.
        params = dict(kwargs)
        if params["parent_agent_version_id"] is not None:
            params["parent_agent_version_id"] = str(params["parent_agent_version_id"])
        if params["child_agent_version_id"] is not None:
            params["child_agent_version_id"] = str(params["child_agent_version_id"])
        params = _prepare_json_params(params, json_fields=["scope"])

        return await self.db.execute_returning("insert_agent_version_delegation", params)

    async def check_delegation_authorized(
        self,
        parent_agent_version_id: UUID,
        child_agent_name: str,
    ) -> Optional[dict]:
        """Runtime gate for the delegate_to_agent meta-tool.

        Returns a dict with `delegation_id`, `scope`, and the resolved
        `resolved_child_version_id` when (parent, child) has an authorized
        delegation row. Returns None when not authorized — the engine
        surfaces this as a tool_result error to the calling agent.

        Champion-tracking rows resolve via agent.current_champion_version_id
        at query time, so delegation follows champion promotions without
        parent version reauthorization (unless pinned).
        """
        return await self.db.fetch_one(
            "check_delegation_authorized",
            {
                "parent_version_id": str(parent_agent_version_id),
                "child_name": child_agent_name,
            },
        )

    async def list_delegations_for_parent(
        self,
        parent_agent_version_id: UUID,
    ) -> list[dict]:
        """Enumerate all delegations authorized from a parent agent_version.

        Used by the admin UI's "this agent can delegate to:" view and by
        the engine's error-path hint when an unauthorized delegation is
        attempted (Claude sees the list of authorized targets).
        """
        return await self.db.fetch_all(
            "list_delegations_for_parent",
            {"parent_version_id": str(parent_agent_version_id)},
        )

    async def list_delegations_to_agent(self, agent_name: str) -> list[dict]:
        """Inverse query: which parents can delegate to this agent?

        Handles both name-based and version-pinned rows. Used by the
        admin UI's "this agent is delegated to by:" view.
        """
        return await self.db.fetch_all(
            "list_delegations_to_agent",
            {"agent_name": agent_name},
        )

    async def register_test_suite(self, **kwargs) -> dict:
        return await self.db.execute_returning("insert_test_suite", kwargs)

    async def register_test_case(self, **kwargs) -> dict:
        params = _prepare_json_params(kwargs, json_fields=["input_data", "expected_output", "metric_config"])
        return await self.db.execute_returning("insert_test_case", params)

    async def register_model_card(self, **kwargs) -> dict:
        return await self.db.execute_returning("insert_model_card", kwargs)

    async def register_metric_threshold(self, **kwargs) -> dict:
        return await self.db.execute_returning("insert_metric_threshold", kwargs)

    async def register_ground_truth_dataset(self, **kwargs) -> dict:
        return await self.db.execute_returning("insert_ground_truth_dataset", kwargs)

    async def register_ground_truth_record(self, **kwargs) -> dict:
        """Register one input record in a ground truth dataset."""
        params = _prepare_json_params(kwargs, json_fields=[
            "input_data",
        ])
        return await self.db.execute_returning("insert_ground_truth_record", params)

    async def register_ground_truth_annotation(self, **kwargs) -> dict:
        """Register one annotator's label for a ground truth record."""
        params = _prepare_json_params(kwargs, json_fields=[
            "expected_output",
        ])
        return await self.db.execute_returning("insert_ground_truth_annotation", params)

    async def register_validation_run(self, **kwargs) -> dict:
        params = _prepare_json_params(kwargs, json_fields=[
            "confusion_matrix", "field_accuracy", "fairness_metrics",
            "threshold_details", "inference_config_snapshot",
        ])
        return await self.db.execute_returning("insert_validation_run", params)

    # ── DRAFT-STATE EDITS ─────────────────────────────────────
    # Each update is guarded at the SQL layer by
    #     WHERE lifecycle_state = 'draft'
    # When the row isn't a draft, the UPDATE matches zero rows and we
    # return None; the API layer converts that into a 409 Conflict.
    # Non-draft rows (candidate / staging / shadow / challenger /
    # champion / deprecated) stay immutable — that immutability is
    # what makes decision-log replay meaningful.

    async def update_agent_version_draft(self, version_id, **fields) -> Optional[dict]:
        """Update mutable fields on a draft agent_version. Returns the
        updated row on success, None if the version isn't in draft."""
        params = dict(fields)
        params["version_id"] = str(version_id)
        # SQL uses COALESCE — missing keys must be present as None so
        # psycopg has something to bind each placeholder to.
        for key in ("inference_config_id", "output_schema", "authority_thresholds",
                    "mock_mode_enabled", "decision_log_detail",
                    "developer_name", "change_summary", "change_type",
                    "limitations_this_version"):
            params.setdefault(key, None)
        if params["inference_config_id"] is not None:
            params["inference_config_id"] = str(params["inference_config_id"])
        params = _prepare_json_params(params, json_fields=["output_schema", "authority_thresholds"])
        return await self.db.execute_returning("update_agent_version_draft", params)

    async def update_task_version_draft(self, version_id, **fields) -> Optional[dict]:
        params = dict(fields)
        params["version_id"] = str(version_id)
        for key in ("inference_config_id", "output_schema", "mock_mode_enabled",
                    "decision_log_detail", "developer_name", "change_summary", "change_type"):
            params.setdefault(key, None)
        if params["inference_config_id"] is not None:
            params["inference_config_id"] = str(params["inference_config_id"])
        params = _prepare_json_params(params, json_fields=["output_schema"])
        return await self.db.execute_returning("update_task_version_draft", params)

    async def update_prompt_version_draft(self, version_id, **fields) -> Optional[dict]:
        params = dict(fields)
        params["version_id"] = str(version_id)
        for key in ("content", "api_role", "governance_tier",
                    "change_summary", "sensitivity_level", "author_name"):
            params.setdefault(key, None)
        return await self.db.execute_returning("update_prompt_version_draft", params)

    async def update_pipeline_version_draft(self, version_id, **fields) -> Optional[dict]:
        params = dict(fields)
        params["version_id"] = str(version_id)
        for key in ("steps", "change_summary", "developer_name"):
            params.setdefault(key, None)
        params = _prepare_json_params(params, json_fields=["steps"])
        return await self.db.execute_returning("update_pipeline_version_draft", params)

    async def delete_draft_version(self, entity_type: str, version_id) -> Optional[dict]:
        """Delete a draft version. Cascades through associations for
        agent / task. Non-draft rows return None (surface as 409).

        For prompt_version, FK from entity_prompt_assignment means the
        DB rejects the DELETE if the prompt is still assigned somewhere;
        psycopg raises an IntegrityError that the API layer turns into
        a 400 with a clear message.
        """
        query_name = {
            "agent":    "delete_draft_agent_version_cascade",
            "task":     "delete_draft_task_version_cascade",
            "prompt":   "delete_draft_prompt_version",
            "pipeline": "delete_draft_pipeline_version",
        }.get(entity_type)
        if not query_name:
            raise ValueError(
                f"delete_draft_version: entity_type must be one of "
                f"agent/task/prompt/pipeline, got {entity_type!r}"
            )
        return await self.db.execute_returning(
            query_name, {"version_id": str(version_id)},
        )

    # ── REPLACE ASSOCIATION SETS ─────────────────────────────
    # "Replace the entire list of prompts/tools/delegations on this
    # draft version with this new list." Transactional DELETE + batch
    # INSERT through the transaction handle so a partial-write failure
    # rolls the whole set back.

    async def _assert_draft(self, tx, guard_query: str, version_id) -> None:
        row = await tx.fetch_one(guard_query, {"version_id": str(version_id)})
        if not row:
            raise ValueError(
                f"Version {version_id} is not in draft state; "
                f"associations on promoted versions are immutable."
            )

    async def replace_agent_prompt_assignments(
        self, agent_version_id, assignments: list[dict],
    ) -> list[dict]:
        """Replace all prompt assignments on a draft agent_version."""
        results: list[dict] = []
        async with self.db.transaction() as tx:
            await self._assert_draft(tx, "check_agent_version_is_draft", agent_version_id)
            await tx.execute(
                "delete_agent_prompt_assignments_for_version",
                {"version_id": str(agent_version_id)},
            )
            for a in assignments:
                params = {
                    "entity_type": "agent",
                    "entity_version_id": str(agent_version_id),
                    "prompt_version_id": a["prompt_version_id"],
                    "api_role": a["api_role"],
                    "governance_tier": a["governance_tier"],
                    "execution_order": a["execution_order"],
                    "is_required": a.get("is_required", True),
                    "condition_logic": a.get("condition_logic"),
                }
                params = _prepare_json_params(params, json_fields=["condition_logic"])
                row = await tx.execute_returning("insert_entity_prompt_assignment", params)
                if row:
                    results.append(row)
        return results

    async def replace_task_prompt_assignments(
        self, task_version_id, assignments: list[dict],
    ) -> list[dict]:
        results: list[dict] = []
        async with self.db.transaction() as tx:
            await self._assert_draft(tx, "check_task_version_is_draft", task_version_id)
            await tx.execute(
                "delete_task_prompt_assignments_for_version",
                {"version_id": str(task_version_id)},
            )
            for a in assignments:
                params = {
                    "entity_type": "task",
                    "entity_version_id": str(task_version_id),
                    "prompt_version_id": a["prompt_version_id"],
                    "api_role": a["api_role"],
                    "governance_tier": a["governance_tier"],
                    "execution_order": a["execution_order"],
                    "is_required": a.get("is_required", True),
                    "condition_logic": a.get("condition_logic"),
                }
                params = _prepare_json_params(params, json_fields=["condition_logic"])
                row = await tx.execute_returning("insert_entity_prompt_assignment", params)
                if row:
                    results.append(row)
        return results

    async def replace_agent_tool_authorizations(
        self, agent_version_id, authorizations: list[dict],
    ) -> list[dict]:
        results: list[dict] = []
        async with self.db.transaction() as tx:
            await self._assert_draft(tx, "check_agent_version_is_draft", agent_version_id)
            await tx.execute(
                "delete_agent_tool_authorizations_for_version",
                {"version_id": str(agent_version_id)},
            )
            for a in authorizations:
                row = await tx.execute_returning("insert_agent_version_tool", {
                    "agent_version_id": str(agent_version_id),
                    "tool_id": a["tool_id"],
                    "authorized": a.get("authorized", True),
                    "notes": a.get("notes"),
                })
                if row:
                    results.append(row)
        return results

    async def replace_task_tool_authorizations(
        self, task_version_id, authorizations: list[dict],
    ) -> list[dict]:
        results: list[dict] = []
        async with self.db.transaction() as tx:
            await self._assert_draft(tx, "check_task_version_is_draft", task_version_id)
            await tx.execute(
                "delete_task_tool_authorizations_for_version",
                {"version_id": str(task_version_id)},
            )
            for a in authorizations:
                row = await tx.execute_returning("insert_task_version_tool", {
                    "task_version_id": str(task_version_id),
                    "tool_id": a["tool_id"],
                    "authorized": a.get("authorized", True),
                    "notes": a.get("notes"),
                })
                if row:
                    results.append(row)
        return results

    async def replace_agent_delegations(
        self, agent_version_id, delegations: list[dict],
    ) -> list[dict]:
        """Replace delegation authorizations on a draft agent_version."""
        results: list[dict] = []
        async with self.db.transaction() as tx:
            await self._assert_draft(tx, "check_agent_version_is_draft", agent_version_id)
            await tx.execute(
                "delete_agent_delegations_for_parent",
                {"version_id": str(agent_version_id)},
            )
            for d in delegations:
                child_name = d.get("child_agent_name")
                child_vid = d.get("child_agent_version_id")
                if (child_name is None) == (child_vid is None):
                    raise ValueError(
                        "Each delegation must specify EXACTLY ONE of "
                        "child_agent_name (champion-tracking) or "
                        "child_agent_version_id (version-pinned)."
                    )
                params = {
                    "parent_agent_version_id": str(agent_version_id),
                    "child_agent_name": child_name,
                    "child_agent_version_id": str(child_vid) if child_vid else None,
                    "scope": d.get("scope", {}),
                    "authorized": d.get("authorized", True),
                    "rationale": d.get("rationale"),
                    "notes": d.get("notes"),
                }
                params = _prepare_json_params(params, json_fields=["scope"])
                row = await tx.execute_returning("insert_agent_version_delegation", params)
                if row:
                    results.append(row)
        return results

    # ── CLONE A VERSION INTO A NEW DRAFT ─────────────────────
    # Reads the source version row + all its associations, inserts a
    # new version with the supplied label (draft state, carrying the
    # source id in cloned_from_version_id for provenance), and
    # duplicates every association row onto the new version. One
    # transaction — if any insert fails the whole clone rolls back.

    async def clone_agent_version(
        self, source_version_id, new_version_label: str,
        change_summary: str = "Cloned", developer_name: Optional[str] = None,
    ) -> dict:
        """Clone an agent_version into a new draft with all associations."""
        major, minor, patch = _parse_version_label(new_version_label)
        async with self.db.transaction() as tx:
            src = await tx.fetch_one(
                "get_agent_version_row", {"version_id": str(source_version_id)},
            )
            if not src:
                raise ValueError(f"Source agent_version {source_version_id} not found")

            new_params = {
                "agent_id": str(src["agent_id"]),
                "major_version": major, "minor_version": minor, "patch_version": patch,
                "lifecycle_state": "draft",
                "channel": src.get("channel") or "development",
                "inference_config_id": str(src["inference_config_id"]),
                "output_schema": src.get("output_schema") or {},
                "authority_thresholds": src.get("authority_thresholds") or {},
                "mock_mode_enabled": src.get("mock_mode_enabled", False),
                "decision_log_detail": src.get("decision_log_detail") or "standard",
                "developer_name": developer_name or src.get("developer_name"),
                "change_summary": change_summary,
                "change_type": "minor",
                "cloned_from_version_id": str(source_version_id),
            }
            new_params = _prepare_json_params(
                new_params, json_fields=["output_schema", "authority_thresholds"],
            )
            new_ver = await tx.execute_returning("insert_agent_version", new_params)

            # Copy prompt assignments
            for a in await tx.fetch_all(
                "get_agent_prompt_assignments_raw",
                {"version_id": str(source_version_id)},
            ):
                params = {
                    "entity_type": "agent",
                    "entity_version_id": str(new_ver["id"]),
                    "prompt_version_id": str(a["prompt_version_id"]),
                    "api_role": a["api_role"],
                    "governance_tier": a["governance_tier"],
                    "execution_order": a["execution_order"],
                    "is_required": a.get("is_required", True),
                    "condition_logic": a.get("condition_logic"),
                }
                params = _prepare_json_params(params, json_fields=["condition_logic"])
                await tx.execute_returning("insert_entity_prompt_assignment", params)

            # Copy tool authorizations
            for t in await tx.fetch_all(
                "get_agent_tool_authorizations_raw",
                {"version_id": str(source_version_id)},
            ):
                await tx.execute_returning("insert_agent_version_tool", {
                    "agent_version_id": str(new_ver["id"]),
                    "tool_id": str(t["tool_id"]),
                    "authorized": t.get("authorized", True),
                    "notes": t.get("notes"),
                })

            # Copy delegation authorizations
            for d in await tx.fetch_all(
                "get_agent_delegations_raw",
                {"version_id": str(source_version_id)},
            ):
                params = {
                    "parent_agent_version_id": str(new_ver["id"]),
                    "child_agent_name": d.get("child_agent_name"),
                    "child_agent_version_id": (
                        str(d["child_agent_version_id"])
                        if d.get("child_agent_version_id") else None
                    ),
                    "scope": d.get("scope") or {},
                    "authorized": d.get("authorized", True),
                    "rationale": d.get("rationale"),
                    "notes": d.get("notes"),
                }
                params = _prepare_json_params(params, json_fields=["scope"])
                await tx.execute_returning("insert_agent_version_delegation", params)

            return new_ver

    async def clone_task_version(
        self, source_version_id, new_version_label: str,
        change_summary: str = "Cloned", developer_name: Optional[str] = None,
    ) -> dict:
        major, minor, patch = _parse_version_label(new_version_label)
        async with self.db.transaction() as tx:
            src = await tx.fetch_one(
                "get_task_version_row", {"version_id": str(source_version_id)},
            )
            if not src:
                raise ValueError(f"Source task_version {source_version_id} not found")
            new_params = {
                "task_id": str(src["task_id"]),
                "major_version": major, "minor_version": minor, "patch_version": patch,
                "lifecycle_state": "draft",
                "channel": src.get("channel") or "development",
                "inference_config_id": str(src["inference_config_id"]),
                "output_schema": src.get("output_schema") or {},
                "mock_mode_enabled": src.get("mock_mode_enabled", False),
                "decision_log_detail": src.get("decision_log_detail") or "standard",
                "developer_name": developer_name or src.get("developer_name"),
                "change_summary": change_summary,
                "change_type": "minor",
                "cloned_from_version_id": str(source_version_id),
            }
            new_params = _prepare_json_params(new_params, json_fields=["output_schema"])
            new_ver = await tx.execute_returning("insert_task_version", new_params)

            for a in await tx.fetch_all(
                "get_task_prompt_assignments_raw",
                {"version_id": str(source_version_id)},
            ):
                params = {
                    "entity_type": "task",
                    "entity_version_id": str(new_ver["id"]),
                    "prompt_version_id": str(a["prompt_version_id"]),
                    "api_role": a["api_role"],
                    "governance_tier": a["governance_tier"],
                    "execution_order": a["execution_order"],
                    "is_required": a.get("is_required", True),
                    "condition_logic": a.get("condition_logic"),
                }
                params = _prepare_json_params(params, json_fields=["condition_logic"])
                await tx.execute_returning("insert_entity_prompt_assignment", params)

            for t in await tx.fetch_all(
                "get_task_tool_authorizations_raw",
                {"version_id": str(source_version_id)},
            ):
                await tx.execute_returning("insert_task_version_tool", {
                    "task_version_id": str(new_ver["id"]),
                    "tool_id": str(t["tool_id"]),
                    "authorized": t.get("authorized", True),
                    "notes": t.get("notes"),
                })

            return new_ver

    async def clone_prompt_version(
        self, source_version_id, new_version_label: str,
        change_summary: str = "Cloned", author_name: Optional[str] = None,
    ) -> dict:
        major, minor, patch = _parse_version_label(new_version_label)
        async with self.db.transaction() as tx:
            src = await tx.fetch_one(
                "get_prompt_version_row", {"version_id": str(source_version_id)},
            )
            if not src:
                raise ValueError(f"Source prompt_version {source_version_id} not found")
            new_params = {
                "prompt_id": str(src["prompt_id"]),
                "major_version": major, "minor_version": minor, "patch_version": patch,
                "content": src["content"],
                "template_variables": src.get("template_variables") or [],
                "api_role": src["api_role"],
                "governance_tier": src["governance_tier"],
                "lifecycle_state": "draft",
                "change_summary": change_summary,
                "sensitivity_level": src.get("sensitivity_level") or "high",
                "author_name": author_name or src.get("author_name"),
                "cloned_from_version_id": str(source_version_id),
            }
            return await tx.execute_returning("insert_prompt_version", new_params)

    async def clone_pipeline_version(
        self, source_version_id, new_version_number: int,
        change_summary: str = "Cloned", developer_name: Optional[str] = None,
    ) -> dict:
        async with self.db.transaction() as tx:
            src = await tx.fetch_one(
                "get_pipeline_version_row", {"version_id": str(source_version_id)},
            )
            if not src:
                raise ValueError(f"Source pipeline_version {source_version_id} not found")
            new_params = {
                "pipeline_id": str(src["pipeline_id"]),
                "version_number": new_version_number,
                "lifecycle_state": "draft",
                "steps": src["steps"],
                "change_summary": change_summary,
                "developer_name": developer_name or src.get("developer_name"),
                "cloned_from_version_id": str(source_version_id),
            }
            new_params = _prepare_json_params(new_params, json_fields=["steps"])
            return await tx.execute_returning("insert_pipeline_version", new_params)

    # ── LISTING (browsing) ────────────────────────────────────

    async def list_agents(self) -> list[dict]:
        return await self.db.fetch_all("list_agents")

    async def list_tasks(self) -> list[dict]:
        return await self.db.fetch_all("list_tasks")

    async def list_prompts(self) -> list[dict]:
        return await self.db.fetch_all("list_prompts")

    async def list_inference_configs(self) -> list[dict]:
        return await self.db.fetch_all("list_inference_configs")

    async def list_tools(self) -> list[dict]:
        return await self.db.fetch_all("list_tools")

    async def get_agent_by_name(self, name: str) -> Optional[dict]:
        return await self.db.fetch_one("get_agent_by_name", {"agent_name": name})

    async def get_task_by_name(self, name: str) -> Optional[dict]:
        return await self.db.fetch_one("get_task_by_name", {"task_name": name})

    async def get_prompt_by_name(self, name: str) -> Optional[dict]:
        return await self.db.fetch_one("get_prompt_by_name", {"prompt_name": name})

    async def list_agent_versions(self, agent_id: UUID) -> list[dict]:
        return await self.db.fetch_all("list_agent_versions", {"agent_id": str(agent_id)})

    async def list_task_versions(self, task_id: UUID) -> list[dict]:
        return await self.db.fetch_all("list_task_versions", {"task_id": str(task_id)})

    async def list_prompt_versions(self, prompt_id: UUID) -> list[dict]:
        return await self.db.fetch_all("list_prompt_versions", {"prompt_id": str(prompt_id)})

    # ── APPLICATION & CONTEXT ─────────────────────────────────

    async def register_application(self, **kwargs) -> dict:
        """Register a consuming application."""
        return await self.db.execute_returning("insert_application", kwargs)

    async def map_entity_to_application(self, application_id, entity_type: str, entity_id) -> dict:
        """Map an entity (agent, task, prompt, tool, pipeline) to an application."""
        return await self.db.execute_returning("insert_application_entity", {
            "application_id": str(application_id),
            "entity_type": entity_type,
            "entity_id": str(entity_id),
        })

    async def create_execution_context(self, application_id, context_ref: str,
                                        context_type: str = None, metadata: dict = None) -> dict:
        """Create or update an execution context for a business operation."""
        import json as _json
        return await self.db.execute_returning("insert_execution_context", {
            "application_id": str(application_id),
            "context_ref": context_ref,
            "context_type": context_type,
            "metadata": _json.dumps(metadata) if metadata else "{}",
        })

    async def list_applications(self) -> list[dict]:
        return await self.db.fetch_all("list_applications")

    async def get_application_by_name(self, name: str) -> Optional[dict]:
        return await self.db.fetch_one("get_application_by_name", {"app_name": name})

    async def list_application_entities(
        self, application_id, entity_type: Optional[str] = None,
    ) -> list[dict]:
        """List entities mapped to an application, optionally filtered
        by entity_type (agent / task / prompt / tool / pipeline)."""
        if entity_type is None:
            return await self.db.fetch_all(
                "list_all_application_entities",
                {"app_id": str(application_id)},
            )
        return await self.db.fetch_all(
            "list_application_entities_by_type",
            {"app_id": str(application_id), "entity_type": entity_type},
        )

    async def unmap_entity_from_application(
        self, application_id, entity_type: str, entity_id,
    ) -> Optional[dict]:
        """Remove a single entity mapping from an application. Returns
        the deleted row on success, None if no such mapping existed."""
        return await self.db.execute_returning(
            "delete_application_entity_row",
            {
                "app_id": str(application_id),
                "entity_type": entity_type,
                "entity_id": str(entity_id),
            },
        )

    async def get_application_activity(self, name: str) -> Optional[dict]:
        """Count all artifacts tied to the named application:
        decisions, overrides, execution_contexts, entity_mappings.

        Returns None if no such application is registered. The cleanup
        notebook shows these counts before asking for confirmation
        to purge.
        """
        app = await self.get_application_by_name(name)
        if not app:
            return None
        counts = await self.db.fetch_one(
            "get_application_activity_counts",
            {"app_name": name, "app_id": str(app["id"])},
        )
        return {"application": app, **(counts or {})}

    async def purge_application_activity(self, name: str) -> dict:
        """Delete all decisions, overrides, and execution_contexts
        owned by this application. Leaves the application row itself
        and its entity mappings intact — call unregister_application
        after a purge to remove those too.

        Guarded by the VERITY_ALLOW_PURGE environment flag so this
        irreversible operation can't be hit accidentally in prod.
        Returns per-table counts of rows removed.
        """
        if os.environ.get("VERITY_ALLOW_PURGE") != "1":
            raise ValueError(
                "purge_application_activity requires the VERITY_ALLOW_PURGE=1 "
                "environment variable to be set. This is an irreversible "
                "operation and is disabled by default."
            )
        app = await self.get_application_by_name(name)
        if not app:
            raise ValueError(f"Application '{name}' not found")

        async with self.db.transaction() as tx:
            # Order matters: override_log → agent_decision_log (FK) →
            # execution_context (referenced by agent_decision_log).
            # Both log purges match by app_name AND by execution_context
            # → application_id, so REST-runtime decisions tagged with the
            # server's 'default' identity still get caught when they
            # reference a context this app owns.
            params = {"app_name": name, "app_id": str(app["id"])}
            await tx.execute("purge_override_logs_for_application", params)
            dec_rows = await tx.fetch_all("purge_decisions_for_application", params)
            ctx_rows = await tx.fetch_all(
                "purge_execution_contexts_for_application",
                {"app_id": str(app["id"])},
            )
        return {
            "decisions_deleted": len(dec_rows),
            "execution_contexts_deleted": len(ctx_rows),
        }

    async def unregister_application(self, name: str) -> dict:
        """Delete the application row and all its entity mappings.

        Does NOT delete decisions / overrides / execution_contexts —
        those must be cleared first via purge_application_activity,
        otherwise the execution_context FK blocks the delete and
        this method raises.
        """
        app = await self.get_application_by_name(name)
        if not app:
            raise ValueError(f"Application '{name}' not found")
        async with self.db.transaction() as tx:
            unmapped = await tx.fetch_all(
                "delete_all_application_entity_rows",
                {"app_id": str(app["id"])},
            )
            deleted = await tx.execute_returning(
                "delete_application_row", {"app_id": str(app["id"])},
            )
        return {
            "deleted_id": deleted["id"] if deleted else None,
            "unmapped_entity_count": len(unmapped),
        }

    async def get_execution_context(self, context_id) -> Optional[dict]:
        return await self.db.fetch_one("get_execution_context", {"context_id": str(context_id)})

    async def get_execution_context_by_ref(self, application_id, context_ref: str) -> Optional[dict]:
        return await self.db.fetch_one("get_execution_context_by_ref", {
            "application_id": str(application_id),
            "context_ref": context_ref,
        })


def _to_float(val) -> Optional[float]:
    """Convert Decimal or other numeric to float, or None."""
    if val is None:
        return None
    return float(val)


def _prepare_json_params(params: dict, json_fields: list[str]) -> dict:
    """Convert dict/list fields to JSON strings for JSONB columns."""
    result = dict(params)
    for field in json_fields:
        val = result.get(field)
        if val is not None and not isinstance(val, str):
            result[field] = json.dumps(val)
    return result


def _parse_version_label(label: str) -> tuple[int, int, int]:
    """Parse a `major.minor.patch` semver label into its three parts.

    Used by the clone workflow — callers supply the target label as a
    string because notebook users read/write labels as strings.
    """
    try:
        parts = label.strip().split(".")
        if len(parts) != 3:
            raise ValueError
        return int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, AttributeError):
        raise ValueError(
            f"version_label must be 'major.minor.patch' (e.g. '2.0.0'), got {label!r}"
        )
