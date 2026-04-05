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

from enum import Enum
from uuid import UUID

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

    # Register the enumval filter (for explicit use: {{ x | enumval }})
    templates.env.filters["enumval"] = _enum_value

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
        counts = await verity.dashboard_counts()
        recent = await verity.decisions.list_recent_decisions(limit=10)
        return _render(templates, request, "dashboard.html",
            active_page="dashboard",
            counts=counts,
            recent_decisions=recent,
        )

    # ── AGENTS ────────────────────────────────────────────────

    @router.get("/agents", response_class=HTMLResponse)
    async def agents_list(request: Request):
        """List all registered agents."""
        await verity.ensure_connected()
        agents = await verity.list_agents()
        return _render(templates, request, "agents.html",
            active_page="agents",
            agents=agents,
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
                pass

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
        return _render(templates, request, "tasks.html",
            active_page="tasks",
            tasks=tasks,
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
                pass

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
        return _render(templates, request, "prompts.html",
            active_page="prompts",
            prompts=prompts,
        )

    # ── INFERENCE CONFIGS ─────────────────────────────────────

    @router.get("/configs", response_class=HTMLResponse)
    async def configs_list(request: Request):
        await verity.ensure_connected()
        configs = await verity.list_inference_configs()
        return _render(templates, request, "configs.html",
            active_page="configs",
            configs=configs,
        )

    # ── TOOLS ─────────────────────────────────────────────────

    @router.get("/tools", response_class=HTMLResponse)
    async def tools_list(request: Request):
        await verity.ensure_connected()
        tools = await verity.list_tools()
        return _render(templates, request, "tools.html",
            active_page="tools",
            tools=tools,
        )

    # ── PIPELINES ─────────────────────────────────────────────

    @router.get("/pipelines", response_class=HTMLResponse)
    async def pipelines_list(request: Request):
        await verity.ensure_connected()
        pipelines = await verity.list_pipelines()
        return _render(templates, request, "pipelines.html",
            active_page="pipelines",
            pipelines=pipelines,
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

    @router.get("/audit-trail/{submission_id}", response_class=HTMLResponse)
    async def audit_trail(request: Request, submission_id: str):
        """Audit trail by submission_id (legacy — uses business key)."""
        await verity.ensure_connected()
        trail = await verity.get_audit_trail(UUID(submission_id))
        return _render(templates, request, "audit_trail.html",
            active_page="decisions",
            submission_id=submission_id,
            trail=trail,
        )

    @router.get("/audit-trail/run/{pipeline_run_id}", response_class=HTMLResponse)
    async def audit_trail_by_run(request: Request, pipeline_run_id: str):
        """Audit trail by pipeline_run_id (preferred — uses Verity-owned ID).

        This is the correct way to view audit trails. No cross-app collision.
        Used by the UW app's "View in Verity" links.
        """
        await verity.ensure_connected()
        trail = await verity.get_audit_trail_by_run(UUID(pipeline_run_id))
        return _render(templates, request, "audit_trail.html",
            active_page="decisions",
            submission_id=f"Run: {pipeline_run_id[:8]}...",
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
        )

    return router
