"""Verity Registry — register and retrieve all governed entities.

The registry is the source of truth for all AI component definitions.
No agent, task, prompt, or tool exists outside of Verity's registry.
"""

import json
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
        params = _prepare_json_params(kwargs, json_fields=["output_schema", "authority_thresholds"])
        return await self.db.execute_returning("insert_agent_version", params)

    async def register_task(self, **kwargs) -> dict:
        """Register a task (header record, no version yet)."""
        params = _prepare_json_params(kwargs, json_fields=["input_schema", "output_schema"])
        return await self.db.execute_returning("insert_task", params)

    async def register_task_version(self, **kwargs) -> dict:
        """Register a task version."""
        params = _prepare_json_params(kwargs, json_fields=["output_schema"])
        return await self.db.execute_returning("insert_task_version", params)

    async def register_prompt(self, **kwargs) -> dict:
        """Register a prompt (header record)."""
        return await self.db.execute_returning("insert_prompt", kwargs)

    async def register_prompt_version(self, **kwargs) -> dict:
        """Register a prompt version."""
        return await self.db.execute_returning("insert_prompt_version", kwargs)

    async def assign_prompt(self, **kwargs) -> dict:
        """Assign a prompt version to an agent_version or task_version."""
        params = _prepare_json_params(kwargs, json_fields=["condition_logic"])
        return await self.db.execute_returning("insert_entity_prompt_assignment", params)

    async def register_tool(self, **kwargs) -> dict:
        """Register a tool."""
        params = _prepare_json_params(kwargs, json_fields=["input_schema", "output_schema"])
        return await self.db.execute_returning("insert_tool", params)

    async def authorize_agent_tool(self, **kwargs) -> dict:
        """Authorize a tool for an agent version."""
        return await self.db.execute_returning("insert_agent_version_tool", kwargs)

    async def authorize_task_tool(self, **kwargs) -> dict:
        """Authorize a tool for a task version."""
        return await self.db.execute_returning("insert_task_version_tool", kwargs)

    async def register_pipeline(self, **kwargs) -> dict:
        """Register a pipeline."""
        return await self.db.execute_returning("insert_pipeline", kwargs)

    async def register_pipeline_version(self, **kwargs) -> dict:
        """Register a pipeline version."""
        params = _prepare_json_params(kwargs, json_fields=["steps"])
        return await self.db.execute_returning("insert_pipeline_version", params)

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

    async def register_validation_run(self, **kwargs) -> dict:
        params = _prepare_json_params(kwargs, json_fields=[
            "confusion_matrix", "field_accuracy", "fairness_metrics",
            "threshold_details", "inference_config_snapshot",
        ])
        return await self.db.execute_returning("insert_validation_run", params)

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

    async def list_pipelines(self) -> list[dict]:
        return await self.db.fetch_all("list_pipelines")

    async def get_agent_by_name(self, name: str) -> Optional[dict]:
        return await self.db.fetch_one("get_agent_by_name", {"agent_name": name})

    async def get_task_by_name(self, name: str) -> Optional[dict]:
        return await self.db.fetch_one("get_task_by_name", {"task_name": name})

    async def list_agent_versions(self, agent_id: UUID) -> list[dict]:
        return await self.db.fetch_all("list_agent_versions", {"agent_id": str(agent_id)})

    async def list_task_versions(self, task_id: UUID) -> list[dict]:
        return await self.db.fetch_all("list_task_versions", {"task_id": str(task_id)})

    async def list_prompt_versions(self, prompt_id: UUID) -> list[dict]:
        return await self.db.fetch_all("list_prompt_versions", {"prompt_id": str(prompt_id)})

    async def get_pipeline_by_name(self, name: str) -> Optional[dict]:
        return await self.db.fetch_one("get_pipeline_by_name", {"pipeline_name": name})

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

    async def list_application_entities(self, application_id) -> list[dict]:
        return await self.db.fetch_all("list_application_entities", {"application_id": str(application_id)})

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
