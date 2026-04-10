"""Verity Web UI Routes — Server-side rendered HTML pages.

Each route:
1. Calls the Verity SDK to fetch data
2. Passes data to a Jinja2 template
3. Returns rendered HTML

All routes are GET endpoints that return HTML responses.
No JSON APIs here — those live in verity/api/.

IMPORTANT: The 'active_page' variable is passed to every template
to highlight the current page in the sidebar navigation.

NOTE ON STARLETTE 1.0: TemplateResponse signature is:
    TemplateResponse(request, template_name, context_dict)
    (request is the FIRST argument, not inside the context dict)
"""

import logging
from enum import Enum
from uuid import UUID

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def _enum_value(value):
    """Jinja2 filter: extract .value from Python enums.

    Converts EntityType.AGENT → "agent", GovernanceTier.BEHAVIOURAL → "behavioural".
    If the value is already a plain string/number, returns it unchanged.

    Usage in templates:
        {{ entity.entity_type | enumval }}
        {{ prompt.governance_tier | enumval }}

    This filter is registered globally on the Jinja2 environment,
    so it works in ALL templates without any per-template setup.
    """
    if isinstance(value, Enum):
        return value.value
    return value


def _short_id(value):
    """Jinja2 filter: format a UUID as first 4 chars + ... + last 4 chars.

    Turns 'aaaa0001-0001-0001-0001-000000000001' into 'aaaa...0001'
    Much more readable in tables than full UUIDs or truncated starts.
    """
    s = str(value) if value else ''
    if len(s) > 12:
        return f"{s[:4]}...{s[-4:]}"
    return s


def _render(templates, request, template_name, **context):
    """Helper to render a template with consistent API.

    Wraps Starlette 1.0's TemplateResponse(request, name, context).
    Usage: return _render(templates, request, "page.html", foo=bar, baz=qux)
    """
    return templates.TemplateResponse(request, template_name, context)


def create_routes(verity, templates_dir: str) -> APIRouter:
    """Create all web UI routes.

    Args:
        verity: Initialized Verity SDK client.
        templates_dir: Path to the Jinja2 templates directory.

    Returns:
        APIRouter with all page routes.
    """
    router = APIRouter()
    templates = Jinja2Templates(directory=templates_dir)

    # Register custom Jinja2 filters
    templates.env.filters["enumval"] = _enum_value
    templates.env.filters["short_id"] = _short_id

    # ── SHARED DATA LOADERS ───────────────────────────────────
    # These load cross-reference data used by multiple pages.

    async def _load_entity_apps() -> dict:
        """Load entity_id → application display names map.
        Returns {(entity_type, entity_id_str): "App1, App2"}
        """
        rows = await verity.db.fetch_all("get_entity_applications")
        return {(r["entity_type"], r["entity_id"]): r["application_names"] for r in rows}

    async def _load_agent_summaries() -> dict:
        """Load agent_id → {prompt_names, tool_names} for cross-reference columns."""
        rows = await verity.db.fetch_all("get_agent_prompts_and_tools_summary")
        return {r["agent_id"]: r for r in rows}

    async def _load_task_summaries() -> dict:
        """Load task_id → {prompt_names} for cross-reference columns."""
        rows = await verity.db.fetch_all("get_task_prompts_summary")
        return {r["task_id"]: r for r in rows}

    # ALSO set finalize on the Jinja2 environment — this automatically
    # converts enums to their .value whenever they're rendered in {{ }}.
    # Without this, templates show "EntityType.AGENT" instead of "agent".
    # This is a global fix — no need to add | enumval to every template.
    templates.env.finalize = _enum_value

    # ── DASHBOARD ─────────────────────────────────────────────
    # Landing page showing entity counts and recent decisions.

    @router.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        await verity.ensure_connected()

        # Card counts + deltas
        counts = await verity.dashboard_counts()
        governance_stats = await verity.db.fetch_one("dashboard_governance_stats") or {}
        deltas = await verity.db.fetch_one("dashboard_30d_deltas") or {}

        # Registry data for slicers
        agents = await verity.list_agents()
        tasks = await verity.list_tasks()
        tools = await verity.list_tools()
        prompts = await verity.list_prompts()
        pipelines = await verity.list_pipelines()
        applications = await verity.list_applications()

        # Chart data — convert dates to strings for JSON serialization
        def _date_str(rows, date_field):
            return [{**r, date_field: str(r[date_field])} for r in rows]

        decisions_by_date = _date_str(await verity.db.fetch_all("dashboard_decisions_by_date"), "decision_date")
        decisions_by_entity = await verity.db.fetch_all("dashboard_decisions_by_entity")
        decisions_by_type = await verity.db.fetch_all("dashboard_decisions_by_type")
        pipeline_runs_by_date = _date_str(await verity.db.fetch_all("dashboard_pipeline_runs_by_date"), "run_date")
        top_pipelines = await verity.db.fetch_all("dashboard_top_pipelines")
        overrides_by_date = _date_str(await verity.db.fetch_all("dashboard_overrides_by_date"), "override_date")
        overrides_by_entity = await verity.db.fetch_all("dashboard_overrides_by_entity")

        # Recent additions
        recent_additions_raw = await verity.db.fetch_all("dashboard_recent_additions")
        recent_additions = [{**r, "created_at": str(r["created_at"])[:10]} for r in recent_additions_raw]

        return _render(templates, request, "dashboard.html",
            active_page="home",
            counts=counts,
            governance_stats=governance_stats,
            deltas=deltas,
            agents=agents,
            tasks=tasks,
            tools=tools,
            prompts=prompts,
            pipelines=pipelines,
            applications=applications,
            decisions_by_date=decisions_by_date,
            decisions_by_entity=decisions_by_entity,
            decisions_by_type=decisions_by_type,
            pipeline_runs_by_date=pipeline_runs_by_date,
            top_pipelines=top_pipelines,
            overrides_by_date=overrides_by_date,
            overrides_by_entity=overrides_by_entity,
            recent_additions=recent_additions,
        )

    # ── AGENTS ────────────────────────────────────────────────

    @router.get("/agents", response_class=HTMLResponse)
    async def agents_list(request: Request):
        """List all registered agents with cross-references."""
        await verity.ensure_connected()
        agents = await verity.list_agents()
        entity_apps = await _load_entity_apps()
        agent_summaries = await _load_agent_summaries()
        return _render(templates, request, "agents.html",
            active_page="agents",
            agents=agents,
            entity_apps=entity_apps,
            agent_summaries=agent_summaries,
        )

    @router.get("/agents/{agent_name}", response_class=HTMLResponse)
    async def agent_detail(request: Request, agent_name: str):
        """Show full detail for one agent: versions, prompts, tools, model card."""
        await verity.ensure_connected()

        agent = await verity.registry.get_agent_by_name(agent_name)
        if not agent:
            return HTMLResponse("<h1>Agent not found</h1>", status_code=404)

        versions = await verity.registry.list_agent_versions(agent["id"])

        prompts = []
        tools = []
        model_cards = []
        validation = None

        if agent.get("current_champion_version_id"):
            champion_id = agent["current_champion_version_id"]
            try:
                config = await verity.get_agent_config(agent_name)
                prompts = config.prompts
                tools = config.tools
            except Exception:
                logger.warning("Could not load champion config for detail page", exc_info=True)

            model_cards = await verity.testing.list_model_cards("agent", champion_id)
            validation = await verity.testing.get_latest_validation("agent", champion_id)

        return _render(templates, request, "agent_detail.html",
            active_page="agents",
            agent=agent,
            versions=versions,
            prompts=prompts,
            tools=tools,
            model_cards=model_cards,
            validation=validation,
        )

    # ── TASKS ─────────────────────────────────────────────────

    @router.get("/tasks", response_class=HTMLResponse)
    async def tasks_list(request: Request):
        await verity.ensure_connected()
        tasks = await verity.list_tasks()
        entity_apps = await _load_entity_apps()
        task_summaries = await _load_task_summaries()
        return _render(templates, request, "tasks.html",
            active_page="tasks",
            tasks=tasks,
            entity_apps=entity_apps,
            task_summaries=task_summaries,
        )

    @router.get("/tasks/{task_name}", response_class=HTMLResponse)
    async def task_detail(request: Request, task_name: str):
        await verity.ensure_connected()

        task = await verity.registry.get_task_by_name(task_name)
        if not task:
            return HTMLResponse("<h1>Task not found</h1>", status_code=404)

        versions = await verity.registry.list_task_versions(task["id"])

        prompts = []
        tools = []
        model_cards = []
        validation = None

        if task.get("current_champion_version_id"):
            champion_id = task["current_champion_version_id"]
            try:
                config = await verity.get_task_config(task_name)
                prompts = config.prompts
                tools = config.tools
            except Exception:
                logger.warning("Could not load champion config for detail page", exc_info=True)

            model_cards = await verity.testing.list_model_cards("task", champion_id)
            validation = await verity.testing.get_latest_validation("task", champion_id)

        return _render(templates, request, "agent_detail.html",
            active_page="tasks",
            agent=task,
            versions=versions,
            prompts=prompts,
            tools=tools,
            model_cards=model_cards,
            validation=validation,
        )

    # ── PROMPTS ───────────────────────────────────────────────

    @router.get("/prompts", response_class=HTMLResponse)
    async def prompts_list(request: Request):
        await verity.ensure_connected()
        prompts = await verity.list_prompts()
        entity_apps = await _load_entity_apps()
        return _render(templates, request, "prompts.html",
            active_page="prompts",
            prompts=prompts,
            entity_apps=entity_apps,
        )

    @router.get("/prompts/{prompt_name}", response_class=HTMLResponse)
    async def prompt_detail(request: Request, prompt_name: str):
        """Show full detail for one prompt: versions with content and validity."""
        await verity.ensure_connected()
        prompt = await verity.registry.db.fetch_one("get_prompt_by_name", {"prompt_name": prompt_name})
        if not prompt:
            return HTMLResponse("<h1>Prompt not found</h1>", status_code=404)
        versions = await verity.registry.list_prompt_versions(prompt["id"])
        return _render(templates, request, "prompt_detail.html",
            active_page="prompts",
            prompt=prompt,
            versions=versions,
        )

    # ── INFERENCE CONFIGS ─────────────────────────────────────

    @router.get("/configs", response_class=HTMLResponse)
    async def configs_list(request: Request):
        await verity.ensure_connected()
        configs = await verity.list_inference_configs()
        entity_apps = await _load_entity_apps()
        return _render(templates, request, "configs.html",
            active_page="configs",
            configs=configs,
            entity_apps=entity_apps,
        )

    @router.get("/configs/{config_name}", response_class=HTMLResponse)
    async def config_detail(request: Request, config_name: str):
        """Show full detail for an inference config with usage."""
        await verity.ensure_connected()
        config = await verity.registry.db.fetch_one("get_inference_config_by_name", {"config_name": config_name})
        if not config:
            return HTMLResponse("<h1>Config not found</h1>", status_code=404)
        usage = await verity.db.fetch_all("get_config_usage", {"config_id": str(config["id"])})
        return _render(templates, request, "config_detail.html",
            active_page="configs",
            config=config,
            usage=usage,
        )

    # ── TOOLS ─────────────────────────────────────────────────

    @router.get("/tools", response_class=HTMLResponse)
    async def tools_list(request: Request):
        await verity.ensure_connected()
        tools = await verity.list_tools()

        # Build cross-reference: which agents/tasks use each tool
        usage_rows = await verity.db.fetch_all("get_tool_usage")
        tool_usage = {}  # {tool_id_str: [{entity_type, entity_name}, ...]}
        for row in usage_rows:
            tid = row["tool_id"]
            if tid not in tool_usage:
                tool_usage[tid] = []
            tool_usage[tid].append({"entity_type": row["entity_type"], "entity_name": row["entity_name"]})

        return _render(templates, request, "tools.html",
            active_page="tools",
            tools=tools,
            tool_usage=tool_usage,
        )

    @router.get("/tools/{tool_name}", response_class=HTMLResponse)
    async def tool_detail(request: Request, tool_name: str):
        """Show full detail for a tool with schemas and usage."""
        await verity.ensure_connected()
        tool = await verity.registry.db.fetch_one("get_tool_by_name", {"tool_name": tool_name})
        if not tool:
            return HTMLResponse("<h1>Tool not found</h1>", status_code=404)
        # Get which agents/tasks use this tool
        usage_rows = await verity.db.fetch_all("get_tool_usage")
        usage = [r for r in usage_rows if r["tool_id"] == str(tool["id"])]
        return _render(templates, request, "tool_detail.html",
            active_page="tools",
            tool=tool,
            usage=usage,
        )

    # ── PIPELINES ─────────────────────────────────────────────

    @router.get("/pipelines", response_class=HTMLResponse)
    async def pipelines_list(request: Request):
        await verity.ensure_connected()
        pipelines = await verity.list_pipelines()
        entity_apps = await _load_entity_apps()
        return _render(templates, request, "pipelines.html",
            active_page="pipelines",
            pipelines=pipelines,
            entity_apps=entity_apps,
        )

    @router.get("/pipelines/{pipeline_name}", response_class=HTMLResponse)
    async def pipeline_detail(request: Request, pipeline_name: str):
        """Show full detail for a pipeline: metadata + steps."""
        await verity.ensure_connected()
        pipeline = await verity.registry.get_pipeline_by_name(pipeline_name)
        if not pipeline:
            return HTMLResponse("<h1>Pipeline not found</h1>", status_code=404)
        entity_apps = await _load_entity_apps()
        apps = entity_apps.get(('pipeline', str(pipeline["id"])), '—')
        return _render(templates, request, "pipeline_detail.html",
            active_page="pipelines",
            pipeline=pipeline,
            entity_apps=apps,
        )

    # ── APPLICATIONS ──────────────────────────────────────────

    @router.get("/applications", response_class=HTMLResponse)
    async def applications_list(request: Request):
        """Show registered applications with mapped entities."""
        await verity.ensure_connected()
        apps = await verity.list_applications()
        for app in apps:
            app["entities"] = await verity.registry.list_application_entities(app["id"])
        return _render(templates, request, "applications.html",
            active_page="applications",
            applications=apps,
        )

    @router.get("/applications/{app_name}", response_class=HTMLResponse)
    async def application_detail(request: Request, app_name: str):
        """Show full detail for an application: metadata + mapped entities + stats."""
        await verity.ensure_connected()
        app = await verity.registry.get_application_by_name(app_name)
        if not app:
            return HTMLResponse("<h1>Application not found</h1>", status_code=404)
        entities = await verity.registry.list_application_entities(app["id"])
        # Count decisions and overrides for this app
        decision_row = await verity.db.fetch_one_raw(
            "SELECT COUNT(*) AS cnt FROM agent_decision_log WHERE application = %(app_name)s",
            {"app_name": app_name},
        )
        override_row = await verity.db.fetch_one_raw(
            "SELECT COUNT(*) AS cnt FROM override_log ol "
            "JOIN agent_decision_log adl ON adl.id = ol.decision_log_id "
            "WHERE adl.application = %(app_name)s",
            {"app_name": app_name},
        )
        return _render(templates, request, "application_detail.html",
            active_page="applications",
            app=app,
            entities=entities,
            decision_count=decision_row["cnt"] if decision_row else 0,
            override_count=override_row["cnt"] if override_row else 0,
        )

    # ── DECISION LOG ──────────────────────────────────────────

    @router.get("/decisions", response_class=HTMLResponse)
    async def decisions_list(request: Request):
        await verity.ensure_connected()
        decisions = await verity.list_decisions(limit=100)
        total = await verity.decisions.count_decisions()
        return _render(templates, request, "decisions.html",
            active_page="decisions",
            decisions=decisions,
            total=total,
        )

    @router.get("/decisions/{decision_id}", response_class=HTMLResponse)
    async def decision_detail_page(request: Request, decision_id: str):
        await verity.ensure_connected()
        decision = await verity.get_decision(UUID(decision_id))
        if not decision:
            return HTMLResponse("<h1>Decision not found</h1>", status_code=404)
        return _render(templates, request, "decision_detail.html",
            active_page="decisions",
            decision=decision,
        )

    # ── AUDIT TRAIL ───────────────────────────────────────────

    @router.get("/audit-trail/run/{pipeline_run_id}", response_class=HTMLResponse)
    async def audit_trail_by_run(request: Request, pipeline_run_id: str):
        """Audit trail for one pipeline execution.

        Shows all decisions (steps) from a single pipeline run.
        """
        await verity.ensure_connected()
        trail = await verity.get_audit_trail_by_run(UUID(pipeline_run_id))
        return _render(templates, request, "audit_trail.html",
            active_page="decisions",
            pipeline_run_id=pipeline_run_id,
            trail=trail,
        )

    @router.get("/audit-trail/context/{execution_context_id}", response_class=HTMLResponse)
    async def audit_trail_by_context(request: Request, execution_context_id: str):
        """Audit trail for a business context (spans all pipeline runs).

        Shows every decision across every pipeline run linked to this
        execution context. Useful for viewing the full history of a
        submission, policy, or other business operation.
        """
        await verity.ensure_connected()
        trail = await verity.get_audit_trail(UUID(execution_context_id))
        return _render(templates, request, "audit_trail.html",
            active_page="decisions",
            execution_context_id=execution_context_id,
            trail=trail,
        )

    # ── MODEL INVENTORY ───────────────────────────────────────

    @router.get("/model-inventory", response_class=HTMLResponse)
    async def model_inventory(request: Request):
        await verity.ensure_connected()
        agents = await verity.model_inventory_agents()
        tasks = await verity.model_inventory_tasks()
        return _render(templates, request, "model_inventory.html",
            active_page="model_inventory",
            agents=agents,
            tasks=tasks,
        )

    # ── LIFECYCLE (placeholder) ───────────────────────────────

    @router.get("/lifecycle", response_class=HTMLResponse)
    async def lifecycle_page(request: Request):
        await verity.ensure_connected()
        agents = await verity.list_agents()
        tasks = await verity.list_tasks()
        return _render(templates, request, "agents.html",
            active_page="lifecycle",
            agents=agents + tasks,
        )

    # ── TEST RESULTS (placeholder) ────────────────────────────

    @router.get("/test-results", response_class=HTMLResponse)
    async def test_results_page(request: Request):
        await verity.ensure_connected()
        counts = await verity.dashboard_counts()
        return _render(templates, request, "dashboard.html",
            active_page="test_results",
            counts=counts,
            recent_decisions=[],
            agents=[], tasks=[],
        )

    # ── GROUND TRUTH ──────────────────────────────────────────

    @router.get("/ground-truth", response_class=HTMLResponse)
    async def ground_truth_page(request: Request):
        """Ground truth datasets — placeholder."""
        await verity.ensure_connected()
        counts = await verity.dashboard_counts()
        return _render(templates, request, "dashboard.html",
            active_page="ground_truth",
            counts=counts,
            recent_decisions=[],
            agents=[], tasks=[],
        )

    # ── PIPELINE RUNS ───────────────────────────────────────────

    @router.get("/pipeline-runs", response_class=HTMLResponse)
    async def pipeline_runs_page(request: Request):
        """Show all pipeline runs grouped by pipeline_run_id."""
        await verity.ensure_connected()
        runs = await verity.db.fetch_all("list_pipeline_runs")
        return _render(templates, request, "pipeline_runs.html",
            active_page="pipeline_runs",
            runs=runs,
        )

    # ── OVERRIDES ─────────────────────────────────────────────

    @router.get("/overrides", response_class=HTMLResponse)
    async def overrides_page(request: Request):
        """Show all human overrides of AI decisions."""
        await verity.ensure_connected()
        overrides = await verity.db.fetch_all("list_all_overrides")
        return _render(templates, request, "overrides.html",
            active_page="overrides",
            overrides=overrides,
        )

    return router
