"""Verity — consumer-facing SDK client (in-process mode).

Usage:
    verity = Verity(database_url="postgresql://...", anthropic_api_key="sk-...")
    await verity.connect()

    # Registry: get config at runtime
    config = await verity.get_agent_config("triage_agent")
    config = await verity.get_task_config("document_classifier")

    # Execution: run agents and tasks with full governance
    result = await verity.execute_agent("triage_agent", context={...})
    result = await verity.execute_task("document_classifier", input_data={...})

    # Decisions: query the audit trail
    trail = await verity.get_audit_trail(execution_context_id)

    # Reporting
    inventory = await verity.model_inventory_agents()

    await verity.close()

DESIGN:
Internally the Verity class holds a GovernanceCoordinator and a Runtime.
Both share the same Database connection pool. Methods delegate to
coordinator.* (reads, lifecycle, audit, reporting) or runtime.* (execute,
register_tool, test runs, validation runs).

The flat facade preserves backward compatibility with code that wrote
`verity.registry.*`, `verity.execution.*`, `verity.decisions.log_decision(...)`,
etc. before the governance/runtime split. Every public attribute the
earlier monolithic Verity class exposed is preserved here, pointing at
the new underlying module instances.
"""

from typing import Any, Callable, Optional
from uuid import UUID

from verity.db.connection import Database
from verity.governance.coordinator import GovernanceCoordinator
from verity.governance.decisions import DecisionsReader
from verity.governance.runs import RunsReader
from verity.models.decision import (
    AuditTrailEntry,
    DecisionLog,
    DecisionLogDetail,
    OverrideLogCreate,
)
from verity.models.lifecycle import EntityType, LifecycleState, PromotionRequest
from verity.models.reporting import DashboardCounts, ModelInventoryAgent, ModelInventoryTask
from verity.runtime.decisions_writer import DecisionsWriter
from verity.runtime.runs_writer import RunsWriter
from verity.runtime.engine import ExecutionResult
from verity.runtime.mock_context import MockContext
from verity.runtime.runtime import Runtime


# ── UNIFIED DECISIONS CLASS (backward-compat helper) ──────────
# Consuming code written before the split sometimes does:
#   await verity.decisions.log_decision(...)        # writer
#   await verity.decisions.record_override(...)     # reader-side write
#   count = await verity.decisions.count_decisions() # reader
# To preserve that flat API, we expose a single attribute `verity.decisions`
# pointing at a class that has BOTH the reader and writer methods. Defined
# inline here because it's a pure backward-compat convenience for the
# in-process client — the governance REST API (Phase 4) exposes these as
# separate endpoints.

class _UnifiedDecisions(DecisionsReader, DecisionsWriter):
    """Combined reader+writer interface for `verity.decisions.*` callers.

    Both parents' __init__ just set self.db, so multiple inheritance is
    unambiguous. Stateless besides the shared DB — safe to have multiple
    instances pointing at the same pool.
    """
    pass


class Verity:
    """PremiumIQ Verity SDK client.

    Single entry point for all governance + runtime operations:
    registry, lifecycle, execution, decisions, testing, reporting, pipelines.

    Internal structure:
        self._gov : GovernanceCoordinator (registry + lifecycle + decisions_reader + reporting + testing)
        self._rt  : Runtime (execution + test/validation runners + decisions_writer)
        self.db   : shared Database connection pool

    Backward-compatible attribute surface:
        self.registry, self.lifecycle, self.reporting, self.testing,
        self.execution, self.test_runner, self.validation_runner,
        self.decisions (unified reader+writer), self.runs_reader,
        self.runs_writer.
    """

    def __init__(self, database_url: str, anthropic_api_key: str = "", application: str = "default"):
        self.database_url = database_url
        self.anthropic_api_key = anthropic_api_key
        self.application = application
        self.db = Database(database_url)
        self._connected = False
        self._application_id = None  # Resolved on first use

        # ── Governance plane: read configs, lifecycle, audit, reports ──
        self._gov = GovernanceCoordinator(self.db, application=application)

        # ── Runtime plane: execute, pipeline, testing, validation ──
        # Runtime pulls the registry + testing from governance — this is
        # the version-pinning seam in code form: execution ALWAYS resolves
        # configs through the governance registry.
        self._rt = Runtime(
            db=self.db,
            registry=self._gov.registry,
            testing=self._gov.testing,
            anthropic_api_key=anthropic_api_key,
            application=application,
            models=self._gov.models,
        )

        # ── Backward-compat attribute surface ──
        # Existing code (web routes, register_all seed script, etc.)
        # reaches into these attributes directly. Keep them pointing at
        # the concrete instances inside _gov and _rt.
        self.registry = self._gov.registry
        self.lifecycle = self._gov.lifecycle
        self.reporting = self._gov.reporting
        self.testing = self._gov.testing
        self.models = self._gov.models
        self.quotas = self._gov.quotas
        self.execution = self._rt.execution
        self.test_runner = self._rt.test_runner
        self.validation_runner = self._rt.validation_runner

        # Unified Decisions (reader + writer) for legacy `verity.decisions.*`
        # callers. Stateless — the DB is the only state, and it's shared.
        self.decisions = _UnifiedDecisions(self.db)

        # Run-tracking (event-sourced async runs). Reader serves the
        # /runs UI + polling endpoints; writer is called by the API
        # submit endpoint and the worker. Kept as separate attributes
        # because nothing else conflates the two surfaces today.
        self.runs_reader = RunsReader(self.db)
        self.runs_writer = RunsWriter(self.db)

    async def connect(self) -> None:
        """Open the database connection pool."""
        if not self._connected:
            await self.db.connect()
            self._connected = True

    async def close(self) -> None:
        """Close runtime resources and the database connection pool.

        Drains any open MCP server connections first (Phase 4c), then
        closes the DB pool. Safe to call multiple times.
        """
        if self._connected:
            await self._rt.close()
            await self.db.close()
            self._connected = False

    async def ensure_connected(self) -> None:
        """Connect if not already connected."""
        if not self._connected:
            await self.connect()

    # ── REGISTRY (runtime config resolution) ──────────────────

    async def get_agent_config(self, agent_name: str, effective_date=None, version_id=None):
        """Resolve agent config. Default=current champion. Pass effective_date for date-pinning or version_id for direct lookup."""
        await self.ensure_connected()
        return await self._gov.registry.get_agent_config(agent_name, effective_date=effective_date, version_id=version_id)

    async def get_task_config(self, task_name: str, effective_date=None, version_id=None):
        """Resolve task config. Default=current champion. Pass effective_date for date-pinning or version_id for direct lookup."""
        await self.ensure_connected()
        return await self._gov.registry.get_task_config(task_name, effective_date=effective_date, version_id=version_id)

    # ── EXECUTION (agent + task + pipeline invocation) ──────────

    async def execute_agent(
        self,
        agent_name: str,
        context: dict[str, Any],
        channel: str = "production",
        workflow_run_id: Optional[UUID] = None,
        mock: Optional[MockContext] = None,
        stream: bool = False,
        execution_context_id: Optional[UUID] = None,
        application: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute an agent with full governance.

        Pass execution_context_id to link this decision to a business context.
        Pass mock=MockContext(...) to control mocking behavior.
        Pass application="<name>" to stamp the decision row with a caller
        identity different from this client's default. Used by the REST
        runtime endpoints to attribute workbench / external runs correctly.
        """
        await self.ensure_connected()
        return await self._rt.execution.run_agent(
            agent_name=agent_name,
            context=context,
            channel=channel,
            workflow_run_id=workflow_run_id,
            mock=mock,
            stream=stream,
            execution_context_id=execution_context_id,
            application=application,
        )

    async def execute_task(
        self,
        task_name: str,
        input_data: dict[str, Any],
        channel: str = "production",
        workflow_run_id: Optional[UUID] = None,
        mock: Optional[MockContext] = None,
        stream: bool = False,
        execution_context_id: Optional[UUID] = None,
        application: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a task with single-turn structured output.

        `application=<name>` overrides the decision-row attribution
        (see execute_agent for the rationale).
        """
        await self.ensure_connected()
        return await self._rt.execution.run_task(
            task_name=task_name,
            input_data=input_data,
            channel=channel,
            workflow_run_id=workflow_run_id,
            mock=mock,
            stream=stream,
            execution_context_id=execution_context_id,
            application=application,
        )

    def register_tool_implementation(self, tool_name: str, func: Callable):
        """Register a Python function as a tool implementation for agents."""
        self._rt.execution.register_tool_implementation(tool_name, func)

    # ── ASYNC RUNS (submit / poll / cancel) ───────────────────
    # Parallel surface to execute_task / execute_agent: instead of
    # blocking until the run finishes, submit() returns a run_id
    # immediately and a separate worker process picks up the row,
    # dispatches it, and writes terminal state back. Callers poll via
    # get_run() or block via wait_for_run(). Useful when the consuming
    # app already has its own scheduler / queue / async story.

    async def submit_task(
        self,
        task_name: str,
        input_data: dict[str, Any],
        *,
        channel: str = "production",
        execution_context_id: Optional[UUID] = None,
        workflow_run_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        application: Optional[str] = None,
        mock_mode: bool = False,
        write_mode: Optional[str] = None,
        submitted_by: Optional[str] = None,
    ) -> UUID:
        """Submit a task run. Returns run_id; worker picks it up async.

        Resolves the task's champion version at submit time. The worker
        re-resolves the full config when it dispatches. To poll the run,
        use get_run(); to block until terminal, wait_for_run().
        """
        return await self._submit_run(
            entity_kind="task",
            entity_name=task_name,
            input_data=input_data,
            channel=channel,
            execution_context_id=execution_context_id,
            workflow_run_id=workflow_run_id,
            parent_decision_id=parent_decision_id,
            application=application,
            mock_mode=mock_mode,
            write_mode=write_mode,
            enforce_output_schema=None,
            submitted_by=submitted_by,
        )

    async def submit_agent(
        self,
        agent_name: str,
        input_data: dict[str, Any],
        *,
        channel: str = "production",
        execution_context_id: Optional[UUID] = None,
        workflow_run_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        application: Optional[str] = None,
        mock_mode: bool = False,
        write_mode: Optional[str] = None,
        enforce_output_schema: bool = False,
        submitted_by: Optional[str] = None,
    ) -> UUID:
        """Submit an agent run. Returns run_id; worker picks it up async.

        `enforce_output_schema=True` (Phase F) injects a submit_output
        tool and forces tool_choice on the terminal turn. Off by default.
        """
        return await self._submit_run(
            entity_kind="agent",
            entity_name=agent_name,
            input_data=input_data,
            channel=channel,
            execution_context_id=execution_context_id,
            workflow_run_id=workflow_run_id,
            parent_decision_id=parent_decision_id,
            application=application,
            mock_mode=mock_mode,
            write_mode=write_mode,
            enforce_output_schema=enforce_output_schema,
            submitted_by=submitted_by,
        )

    async def _submit_run(
        self,
        *,
        entity_kind: str,
        entity_name: str,
        input_data: dict[str, Any],
        channel: str,
        execution_context_id: Optional[UUID],
        workflow_run_id: Optional[UUID],
        parent_decision_id: Optional[UUID],
        application: Optional[str],
        mock_mode: bool,
        write_mode: Optional[str],
        enforce_output_schema: Optional[bool],
        submitted_by: Optional[str],
    ) -> UUID:
        """Shared submission path. Resolves entity_name to a champion
        version_id, then writes the execution_run + initial submitted
        status row in one transaction.
        """
        from verity.contracts.run import RunSubmission

        if entity_kind == "task":
            row = await self.db.fetch_one("get_task_champion", {"task_name": entity_name})
            if not row:
                raise ValueError(
                    f"Task '{entity_name}' has no champion version registered.",
                )
            version_id = UUID(str(row["task_version_id"]))
        elif entity_kind == "agent":
            row = await self.db.fetch_one("get_agent_champion", {"agent_name": entity_name})
            if not row:
                raise ValueError(
                    f"Agent '{entity_name}' has no champion version registered.",
                )
            version_id = UUID(str(row["agent_version_id"]))
        else:
            raise ValueError(f"Unknown entity_kind: {entity_kind!r}")

        request = RunSubmission(
            entity_kind=entity_kind,
            entity_name=entity_name,
            input=input_data,
            channel=channel,
            execution_context_id=execution_context_id,
            workflow_run_id=workflow_run_id,
            parent_decision_id=parent_decision_id,
            application=application or self.application,
            mock_mode=mock_mode,
            write_mode=write_mode,
            enforce_output_schema=enforce_output_schema,
            submitted_by=submitted_by,
        )
        response = await self.runs_writer.submit(
            request=request, entity_version_id=version_id,
        )
        return response.run_id

    async def get_run(self, run_id: UUID):
        """Read current state of a run (or None if not found)."""
        return await self.runs_reader.get_run(run_id)

    async def list_runs(self, **filters):
        """List runs with optional filters. See RunsReader.list_runs for
        the supported keyword args (execution_context_id,
        workflow_run_id, entity_kind, entity_name, channel, application,
        status, limit, offset)."""
        return await self.runs_reader.list_runs(**filters)

    async def get_run_result(self, run_id: UUID):
        """Canonical ExecutionEnvelope for a completed run.

        Returns None if the run hasn't reached a terminal state.
        Otherwise returns the unified envelope (status-discriminated
        output/error, telemetry, provenance, identity).
        """
        return await self.runs_reader.get_run_result(run_id)

    async def wait_for_run(
        self,
        run_id: UUID,
        *,
        timeout: float = 300.0,
        poll_interval: float = 0.5,
    ):
        """Block until the run reaches a terminal state, then return it.

        Polls get_run() on the supplied interval. Raises TimeoutError
        if the timeout elapses before the run terminates. The default
        timeout (5 min) is generous for an LLM-heavy task; trim for
        shorter tasks to fail faster on stuck workers.
        """
        import asyncio
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            run = await self.get_run(run_id)
            if run and run.current_status.value in (
                "complete", "cancelled", "failed",
            ):
                return run
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(
                    f"Run {run_id} did not reach a terminal state within "
                    f"{timeout}s (last status: {run.current_status.value if run else 'missing'}).",
                )
            await asyncio.sleep(poll_interval)

    async def cancel_run(self, run_id: UUID) -> bool:
        """Request cancellation. Returns True if accepted, False if the
        run was already terminal."""
        return await self.runs_writer.cancel(run_id)

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
        return await self._gov.lifecycle.promote(
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
        return await self._gov.lifecycle.rollback(
            entity_type=EntityType(entity_type),
            entity_version_id=entity_version_id,
            approver_name=approver_name,
            rationale=rationale,
        )

    # ── DECISIONS (audit trail) ───────────────────────────────

    async def get_audit_trail(self, execution_context_id: UUID) -> list[AuditTrailEntry]:
        """Get all decisions for an execution context (spans multiple pipeline runs)."""
        await self.ensure_connected()
        return await self._gov.decisions_reader.get_audit_trail(execution_context_id)

    async def get_audit_trail_by_run(self, workflow_run_id: UUID) -> list[AuditTrailEntry]:
        """Get the full decision chain for a pipeline run (preferred — uses Verity-owned ID).

        This is the correct way to query audit trails. Uses workflow_run_id
        which is unique per execution — no cross-application collision.
        """
        await self.ensure_connected()
        return await self._gov.decisions_reader.get_audit_trail_by_run(workflow_run_id)

    async def get_decision(self, decision_id: UUID) -> Optional[DecisionLogDetail]:
        """Get full details for a single decision."""
        await self.ensure_connected()
        return await self._gov.decisions_reader.get_decision(decision_id)

    async def list_decisions(self, limit: int = 50, offset: int = 0) -> list[DecisionLog]:
        """List decisions (most recent first)."""
        await self.ensure_connected()
        return await self._gov.decisions_reader.list_decisions(limit=limit, offset=offset)

    async def record_override(self, override: OverrideLogCreate) -> dict:
        """Record a human override of an AI decision."""
        await self.ensure_connected()
        return await self._gov.decisions_reader.record_override(override)

    async def get_decisions_by_context(self, execution_context_id) -> list[dict]:
        """Get all decisions for an execution context."""
        await self.ensure_connected()
        return await self._gov.decisions_reader.get_decisions_by_context(execution_context_id)

    # ── REPORTING ─────────────────────────────────────────────

    async def dashboard_counts(self) -> DashboardCounts:
        """Get entity counts for the admin dashboard."""
        await self.ensure_connected()
        return await self._gov.reporting.dashboard_counts()

    async def model_inventory_agents(self) -> list[ModelInventoryAgent]:
        """Model inventory: all champion agents with metrics."""
        await self.ensure_connected()
        return await self._gov.reporting.model_inventory_agents()

    async def model_inventory_tasks(self) -> list[ModelInventoryTask]:
        """Model inventory: all champion tasks with metrics."""
        await self.ensure_connected()
        return await self._gov.reporting.model_inventory_tasks()

    # ── REGISTRY (listing and browsing) ───────────────────────

    async def list_agents(self) -> list[dict]:
        await self.ensure_connected()
        return await self._gov.registry.list_agents()

    async def list_tasks(self) -> list[dict]:
        await self.ensure_connected()
        return await self._gov.registry.list_tasks()

    async def list_prompts(self) -> list[dict]:
        await self.ensure_connected()
        return await self._gov.registry.list_prompts()

    async def list_inference_configs(self) -> list[dict]:
        await self.ensure_connected()
        return await self._gov.registry.list_inference_configs()

    async def list_tools(self) -> list[dict]:
        await self.ensure_connected()
        return await self._gov.registry.list_tools()

    async def list_pipelines(self) -> list[dict]:
        await self.ensure_connected()
        return await self._gov.registry.list_pipelines()

    # ── APPLICATIONS & EXECUTION CONTEXT ──────────────────────

    async def register_application(self, name: str, display_name: str, description: str = "") -> dict:
        """Register a consuming application with Verity."""
        await self.ensure_connected()
        return await self._gov.registry.register_application(
            name=name, display_name=display_name, description=description,
        )

    async def map_entity_to_application(self, application_name: str, entity_type: str, entity_id) -> dict:
        """Map an entity to an application."""
        await self.ensure_connected()
        app = await self._gov.registry.get_application_by_name(application_name)
        if not app:
            raise ValueError(f"Application '{application_name}' not found")
        return await self._gov.registry.map_entity_to_application(
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
        app = await self._gov.registry.get_application_by_name(app_name)
        if not app:
            raise ValueError(f"Application '{app_name}' not found. Register it first.")
        return await self._gov.registry.create_execution_context(
            application_id=app["id"],
            context_ref=context_ref,
            context_type=context_type,
            metadata=metadata,
        )

    async def list_applications(self) -> list[dict]:
        await self.ensure_connected()
        return await self._gov.registry.list_applications()


__all__ = ["Verity"]
