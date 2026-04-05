"""Verity client — main entry point for all SDK operations.

Usage:
    verity = Verity(database_url="postgresql://...", anthropic_api_key="sk-...")
    await verity.connect()

    # Registry: get config at runtime
    config = await verity.get_agent_config("triage_agent")
    config = await verity.get_task_config("document_classifier")

    # Execution: run agents and tasks with full governance
    result = await verity.execute_agent("triage_agent", context={...}, submission_id=uuid)
    result = await verity.execute_task("document_classifier", input_data={...})

    # Decisions: query the audit trail
    trail = await verity.get_audit_trail(submission_id)

    # Reporting
    inventory = await verity.model_inventory()

    await verity.close()
"""

from typing import Any, Callable, Optional
from uuid import UUID

from verity.core.decisions import Decisions
from verity.core.execution import ExecutionEngine, ExecutionResult
from verity.core.lifecycle import Lifecycle
from verity.core.mock_context import MockContext
from verity.core.pipeline_executor import PipelineExecutor, PipelineResult
from verity.core.registry import Registry
from verity.core.reporting import Reporting
from verity.core.testing import Testing
from verity.db.connection import Database
from verity.models.decision import (
    AuditTrailEntry,
    DecisionLog,
    DecisionLogDetail,
    OverrideLogCreate,
)
from verity.models.lifecycle import EntityType, LifecycleState, PromotionRequest
from verity.models.reporting import DashboardCounts, ModelInventoryAgent, ModelInventoryTask


class Verity:
    """PremiumIQ Verity SDK client.

    Single entry point for all governance operations:
    registry, lifecycle, execution, decisions, testing, reporting, pipelines.
    """

    def __init__(self, database_url: str, anthropic_api_key: str = "", application: str = "default"):
        self.database_url = database_url
        self.anthropic_api_key = anthropic_api_key
        self.application = application
        self.db = Database(database_url)
        self._connected = False
        self._application_id = None  # Resolved on first use

        # Core modules — initialized eagerly, they share the db instance
        self.registry = Registry(self.db)
        self.lifecycle = Lifecycle(self.db)
        self.decisions = Decisions(self.db)
        self.reporting = Reporting(self.db)
        self.testing = Testing(self.db)
        self.execution = ExecutionEngine(
            registry=self.registry,
            decisions=self.decisions,
            anthropic_api_key=anthropic_api_key,
            application=application,
        )
        self.pipeline_executor = PipelineExecutor(
            registry=self.registry,
            execution_engine=self.execution,
        )

    async def connect(self) -> None:
        """Open database connection pool."""
        if not self._connected:
            await self.db.connect()
            self._connected = True

    async def close(self) -> None:
        """Close database connection pool."""
        if self._connected:
            await self.db.close()
            self._connected = False

    async def ensure_connected(self) -> None:
        """Connect if not already connected."""
        if not self._connected:
            await self.connect()

    # ── REGISTRY (runtime config resolution) ──────────────────

    async def get_agent_config(self, agent_name: str):
        """Resolve the full champion config for a named agent."""
        await self.ensure_connected()
        return await self.registry.get_agent_config(agent_name)

    async def get_task_config(self, task_name: str):
        """Resolve the full champion config for a named task."""
        await self.ensure_connected()
        return await self.registry.get_task_config(task_name)

    # ── EXECUTION (agent + task + pipeline invocation) ──────────

    async def execute_agent(
        self,
        agent_name: str,
        context: dict[str, Any],
        submission_id: Optional[UUID] = None,
        channel: str = "production",
        pipeline_run_id: Optional[UUID] = None,
        mock: Optional[MockContext] = None,
        stream: bool = False,
    ) -> ExecutionResult:
        """Execute an agent with full governance.

        Pass mock=MockContext(...) to control mocking behavior.
        See MockContext for usage examples.
        """
        await self.ensure_connected()
        return await self.execution.run_agent(
            agent_name=agent_name,
            context=context,
            submission_id=submission_id,
            channel=channel,
            pipeline_run_id=pipeline_run_id,
            mock=mock,
            stream=stream,
        )

    async def execute_task(
        self,
        task_name: str,
        input_data: dict[str, Any],
        submission_id: Optional[UUID] = None,
        channel: str = "production",
        pipeline_run_id: Optional[UUID] = None,
        mock: Optional[MockContext] = None,
        stream: bool = False,
    ) -> ExecutionResult:
        """Execute a task with single-turn structured output."""
        await self.ensure_connected()
        return await self.execution.run_task(
            task_name=task_name,
            input_data=input_data,
            submission_id=submission_id,
            channel=channel,
            pipeline_run_id=pipeline_run_id,
            mock=mock,
            stream=stream,
        )

    async def execute_pipeline(
        self,
        pipeline_name: str,
        context: dict[str, Any],
        submission_id: Optional[UUID] = None,
        channel: str = "production",
        mock: Optional[MockContext] = None,
        execution_context_id: Optional[UUID] = None,
    ) -> PipelineResult:
        """Execute a full pipeline with dependency resolution and parallel groups.

        Pass execution_context_id to link all decisions to a business context.
        Pass mock=MockContext(...) to mock all steps.
        """
        await self.ensure_connected()
        return await self.pipeline_executor.run_pipeline(
            pipeline_name=pipeline_name,
            context=context,
            submission_id=submission_id,
            channel=channel,
            mock=mock,
            execution_context_id=execution_context_id,
        )

    def register_tool_implementation(self, tool_name: str, func: Callable):
        """Register a Python function as a tool implementation for agents."""
        self.execution.register_tool_implementation(tool_name, func)

    # ── LIFECYCLE (promotion, rollback) ───────────────────────

    async def promote(
        self,
        entity_type: str,
        entity_version_id: UUID,
        target_state: str,
        approver_name: str,
        rationale: str,
        approver_role: Optional[str] = None,
        **evidence_flags,
    ) -> dict:
        """Promote an entity version through the 7-state lifecycle."""
        await self.ensure_connected()
        request = PromotionRequest(
            target_state=LifecycleState(target_state),
            approver_name=approver_name,
            approver_role=approver_role,
            rationale=rationale,
            **evidence_flags,
        )
        return await self.lifecycle.promote(
            entity_type=EntityType(entity_type),
            entity_version_id=entity_version_id,
            request=request,
        )

    async def rollback(
        self,
        entity_type: str,
        entity_version_id: UUID,
        approver_name: str,
        rationale: str,
    ) -> dict:
        """Rollback a champion version."""
        await self.ensure_connected()
        return await self.lifecycle.rollback(
            entity_type=EntityType(entity_type),
            entity_version_id=entity_version_id,
            approver_name=approver_name,
            rationale=rationale,
        )

    # ── DECISIONS (audit trail) ───────────────────────────────

    async def get_audit_trail(self, submission_id: UUID) -> list[AuditTrailEntry]:
        """Get the full decision chain for a submission (legacy — uses business key)."""
        await self.ensure_connected()
        return await self.decisions.get_audit_trail(submission_id)

    async def get_audit_trail_by_run(self, pipeline_run_id: UUID) -> list[AuditTrailEntry]:
        """Get the full decision chain for a pipeline run (preferred — uses Verity-owned ID).

        This is the correct way to query audit trails. Uses pipeline_run_id
        which is unique per execution — no cross-application collision.
        """
        await self.ensure_connected()
        return await self.decisions.get_audit_trail_by_run(pipeline_run_id)

    async def get_decision(self, decision_id: UUID) -> Optional[DecisionLogDetail]:
        """Get full details for a single decision."""
        await self.ensure_connected()
        return await self.decisions.get_decision(decision_id)

    async def list_decisions(self, limit: int = 50, offset: int = 0) -> list[DecisionLog]:
        """List decisions (most recent first)."""
        await self.ensure_connected()
        return await self.decisions.list_decisions(limit=limit, offset=offset)

    async def record_override(self, override: OverrideLogCreate) -> dict:
        """Record a human override of an AI decision."""
        await self.ensure_connected()
        return await self.decisions.record_override(override)

    # ── REPORTING ─────────────────────────────────────────────

    async def dashboard_counts(self) -> DashboardCounts:
        """Get entity counts for the admin dashboard."""
        await self.ensure_connected()
        return await self.reporting.dashboard_counts()

    async def model_inventory_agents(self) -> list[ModelInventoryAgent]:
        """Model inventory: all champion agents with metrics."""
        await self.ensure_connected()
        return await self.reporting.model_inventory_agents()

    async def model_inventory_tasks(self) -> list[ModelInventoryTask]:
        """Model inventory: all champion tasks with metrics."""
        await self.ensure_connected()
        return await self.reporting.model_inventory_tasks()

    # ── REGISTRY (listing and browsing) ───────────────────────

    async def list_agents(self) -> list[dict]:
        await self.ensure_connected()
        return await self.registry.list_agents()

    async def list_tasks(self) -> list[dict]:
        await self.ensure_connected()
        return await self.registry.list_tasks()

    async def list_prompts(self) -> list[dict]:
        await self.ensure_connected()
        return await self.registry.list_prompts()

    async def list_inference_configs(self) -> list[dict]:
        await self.ensure_connected()
        return await self.registry.list_inference_configs()

    async def list_tools(self) -> list[dict]:
        await self.ensure_connected()
        return await self.registry.list_tools()

    async def list_pipelines(self) -> list[dict]:
        await self.ensure_connected()
        return await self.registry.list_pipelines()

    # ── APPLICATIONS & EXECUTION CONTEXT ──────────────────────

    async def register_application(self, name: str, display_name: str, description: str = "") -> dict:
        """Register a consuming application with Verity."""
        await self.ensure_connected()
        return await self.registry.register_application(
            name=name, display_name=display_name, description=description,
        )

    async def map_entity_to_application(self, application_name: str, entity_type: str, entity_id) -> dict:
        """Map an entity to an application."""
        await self.ensure_connected()
        app = await self.registry.get_application_by_name(application_name)
        if not app:
            raise ValueError(f"Application '{application_name}' not found")
        return await self.registry.map_entity_to_application(
            application_id=app["id"], entity_type=entity_type, entity_id=entity_id,
        )

    async def create_execution_context(
        self, context_ref: str, context_type: str = None, metadata: dict = None,
        application_name: str = None,
    ) -> dict:
        """Create an execution context for a business operation.

        Uses self.application if application_name not specified.
        Returns {"id": uuid, "created_at": timestamp}.
        """
        await self.ensure_connected()
        app_name = application_name or self.application
        app = await self.registry.get_application_by_name(app_name)
        if not app:
            raise ValueError(f"Application '{app_name}' not found. Register it first.")
        return await self.registry.create_execution_context(
            application_id=app["id"],
            context_ref=context_ref,
            context_type=context_type,
            metadata=metadata,
        )

    async def get_decisions_by_context(self, execution_context_id) -> list[dict]:
        """Get all decisions for an execution context."""
        await self.ensure_connected()
        return await self.decisions.get_decisions_by_context(execution_context_id)

    async def list_applications(self) -> list[dict]:
        await self.ensure_connected()
        return await self.registry.list_applications()
