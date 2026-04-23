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

from typing import Optional

from fastapi import APIRouter, Query, Request
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
        """Decluttered home dashboard.

        Structure (top-to-bottom):
            1. Brief intro to Verity.
            2. Application cards — each toggles itself in/out of the
               page-level filter via the `?apps=` query string. When the
               filter is non-empty, the count cards below show scoped
               counts (catalog via application_entity mapping, activity
               via the decision/execution_context predicate).
            3. Catalog cards.
            4. Activity cards.
            5. Governance cards.

        All charts and 30d-delta widgets were removed in the declutter —
        dashboard_decisions_by_* / overrides_by_* / pipeline_runs_by_date
        / top_pipelines / recent_additions / 30d_deltas / asset_relationships
        are gone from the reporting SQL too.
        """
        await verity.ensure_connected()

        # ── Parse ?apps=a,b,c into the set the user has toggled on ──
        raw = (request.query_params.get("apps") or "").strip()
        selected_names = [s for s in (x.strip() for x in raw.split(",")) if s]

        applications = await verity.list_applications()
        apps_by_name = {a["name"]: a for a in applications}
        # Drop any name in the URL that doesn't match a real app — keeps
        # the filter robust against stale links or typos.
        selected_names = [n for n in selected_names if n in apps_by_name]
        selected_ids = [apps_by_name[n]["id"] for n in selected_names]

        # Scoped or unscoped counts depending on the filter.
        counts = await verity.reporting.dashboard_counts(
            app_ids=selected_ids or None,
            app_names=selected_names or None,
        )
        governance_stats = await verity.db.fetch_one("dashboard_governance_stats") or {}

        # Pipeline-run total — scoped when apps are selected, otherwise
        # just reuse the unscoped number already in governance_stats.
        if selected_ids:
            pr_row = await verity.db.fetch_one(
                "dashboard_pipeline_runs_scoped",
                {"app_ids": [str(i) for i in selected_ids], "app_names": selected_names},
            ) or {}
            total_pipeline_runs = pr_row.get("total_pipeline_runs") or 0
        else:
            total_pipeline_runs = governance_stats.get("total_pipeline_runs") or 0

        return _render(templates, request, "dashboard.html",
            active_page="home",
            counts=counts,
            governance_stats=governance_stats,
            total_pipeline_runs=total_pipeline_runs,
            applications=applications,
            selected_app_names=selected_names,
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
        """Show full detail for one agent: versions, prompts, tools, model card, delegations."""
        await verity.ensure_connected()

        agent = await verity.registry.get_agent_by_name(agent_name)
        if not agent:
            return HTMLResponse("<h1>Agent not found</h1>", status_code=404)

        versions = await verity.registry.list_agent_versions(agent["id"])

        prompts = []
        tools = []
        model_cards = []
        validation = None
        # Outbound delegations FROM this agent's champion version (FC-1d).
        delegations_out: list[dict] = []

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

            # Outbound: what this champion version is authorized to delegate to.
            delegations_out = await verity.registry.list_delegations_for_parent(
                parent_agent_version_id=champion_id,
            )

        # Inbound: all delegations that target THIS agent, across any
        # parent version. Useful for "which agents delegate to me?".
        delegations_in = await verity.registry.list_delegations_to_agent(
            agent_name=agent_name,
        )

        return _render(templates, request, "agent_detail.html",
            active_page="agents",
            agent=agent,
            versions=versions,
            prompts=prompts,
            tools=tools,
            model_cards=model_cards,
            validation=validation,
            delegations_out=delegations_out,
            delegations_in=delegations_in,
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

    # ── MCP SERVERS (Phase 4f / FC-14) ─────────────────────────
    # Registry view of MCP servers Verity knows about. One row per
    # mcp_server record; each page shows its transport config and the
    # tools bound to it. Tool rows on /admin/tools link here via the
    # MCP: <server> badge in the Transport column.

    @router.get("/mcp-servers", response_class=HTMLResponse)
    async def mcp_servers_list(request: Request):
        """Browse registered MCP servers with per-server tool counts."""
        await verity.ensure_connected()
        servers = await verity.registry.list_mcp_servers()
        # Per-server tool count (how many Verity tools dispatch through each)
        all_tools = await verity.list_tools()
        counts: dict[str, int] = {}
        for t in all_tools:
            name = t.get("mcp_server_name")
            if name:
                counts[name] = counts.get(name, 0) + 1
        return _render(templates, request, "mcp_servers.html",
            active_page="mcp-servers",
            servers=servers,
            tool_counts=counts,
        )

    @router.get("/mcp-servers/{server_name}", response_class=HTMLResponse)
    async def mcp_server_detail(request: Request, server_name: str):
        """Show one MCP server's config plus the tools bound to it."""
        await verity.ensure_connected()
        server = await verity.registry.get_mcp_server_by_name(server_name)
        if not server:
            return HTMLResponse("<h1>MCP server not found</h1>", status_code=404)
        # Filter the tool list to just tools bound to this server.
        all_tools = await verity.list_tools()
        bound_tools = [t for t in all_tools if t.get("mcp_server_name") == server_name]
        return _render(templates, request, "mcp_server_detail.html",
            active_page="mcp-servers",
            server=server,
            tools=bound_tools,
        )

    # ── MODELS ────────────────────────────────────────────────

    @router.get("/models", response_class=HTMLResponse)
    async def models_list(request: Request):
        """Model catalog with currently-active prices. Clicking a row
        takes you to the model detail page (price history + usage)."""
        await verity.ensure_connected()
        models = await verity.models.list_models()
        return _render(templates, request, "models.html",
            active_page="models",
            models=models,
        )

    # ── USAGE & SPEND ─────────────────────────────────────────

    @router.get("/usage", response_class=HTMLResponse)
    async def usage_dashboard(
        request: Request,
        from_: Optional[str] = Query(None, alias="from"),
        to: Optional[str] = Query(None),
        apps: Optional[str] = Query(None),
    ):
        """Usage + spend dashboard. Defaults: last 7 days, all apps."""
        from datetime import datetime, timedelta, timezone

        await verity.ensure_connected()

        # Parse window (default: last 7 days). Same helper logic as the
        # /api/v1/usage/* endpoints; kept inline here so the template
        # stays route-local.
        now = datetime.now(timezone.utc)
        try:
            from_ts = datetime.fromisoformat(from_) if from_ else (now - timedelta(days=7))
            to_ts   = datetime.fromisoformat(to)    if to    else now
        except ValueError:
            return HTMLResponse("<h1>Bad date</h1>", status_code=400)
        if from_ts.tzinfo is None:
            from_ts = from_ts.replace(tzinfo=timezone.utc)
        if to_ts.tzinfo is None:
            to_ts = to_ts.replace(tzinfo=timezone.utc)

        # Parse apps filter, same pattern as the home dashboard.
        raw_apps = (apps or "").strip()
        selected_app_names = [s for s in (x.strip() for x in raw_apps.split(",")) if s]
        applications = await verity.list_applications()
        valid_names = {a["name"] for a in applications}
        selected_app_names = [n for n in selected_app_names if n in valid_names]

        # ECharts needs plain JSON on the client — psycopg returns
        # Decimal and date objects from aggregation queries which break
        # `| tojson`. Normalize to float + ISO string before handing
        # the rollup to the template's <script> block.
        def _jsonable(rows):
            out = []
            for r in rows:
                nr = {}
                for k, v in r.items():
                    if hasattr(v, "as_integer_ratio") and not isinstance(v, int):
                        nr[k] = float(v)    # Decimal → float
                    elif hasattr(v, "isoformat"):
                        nr[k] = v.isoformat()   # datetime / date → iso string
                    else:
                        nr[k] = v
                out.append(nr)
            return out

        totals     = await verity.models.usage_totals(from_ts, to_ts, selected_app_names)
        by_model   = await verity.models.usage_by_model(from_ts, to_ts, selected_app_names)
        by_agent   = await verity.models.usage_by_agent(from_ts, to_ts, selected_app_names)
        by_task    = await verity.models.usage_by_task(from_ts, to_ts, selected_app_names)
        by_app     = await verity.models.usage_by_application(from_ts, to_ts, selected_app_names)
        over_time  = _jsonable(
            await verity.models.usage_over_time_daily(from_ts, to_ts, selected_app_names),
        )

        return _render(templates, request, "usage.html",
            active_page="usage",
            from_ts=from_ts.date().isoformat(),
            to_ts=to_ts.date().isoformat(),
            applications=applications,
            selected_app_names=selected_app_names,
            totals=totals,
            by_model=by_model,
            by_agent=by_agent,
            by_task=by_task,
            by_application=by_app,
            over_time=over_time,
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

    # ── LIFECYCLE MANAGEMENT ─────────────────────────────────

    @router.get("/lifecycle", response_class=HTMLResponse)
    async def lifecycle_page(request: Request):
        """All entity versions grouped by entity with lifecycle state."""
        await verity.ensure_connected()
        versions = await verity.db.fetch_all("list_all_entity_versions_with_state", {})
        return _render(templates, request, "lifecycle.html",
            active_page="lifecycle",
            versions=versions,
        )

    # ── TESTING ──────────────────────────────────────────────

    @router.get("/testing", response_class=HTMLResponse)
    async def testing_page(request: Request):
        """Test suites overview."""
        await verity.ensure_connected()
        suites = await verity.db.fetch_all("list_all_test_suites", {})
        return _render(templates, request, "testing.html",
            active_page="testing",
            suites=suites,
        )

    @router.get("/testing/{suite_id}", response_class=HTMLResponse)
    async def test_suite_detail_page(request: Request, suite_id: str):
        """Test suite detail with cases and results."""
        await verity.ensure_connected()
        suites = await verity.db.fetch_all("get_test_suite", {"suite_id": suite_id})
        if not suites:
            return HTMLResponse("<h1>Test suite not found</h1>", status_code=404)
        suite = suites[0]
        cases = await verity.db.fetch_all("list_test_cases_for_suite", {"suite_id": suite_id})
        results = await verity.db.fetch_all("list_test_results_for_suite", {"suite_id": suite_id})
        return _render(templates, request, "test_suite_detail.html",
            active_page="testing",
            suite=suite,
            cases=cases,
            results=results,
        )

    @router.post("/testing/{suite_id}/run", response_class=HTMLResponse)
    async def run_test_suite(request: Request, suite_id: str):
        """Run a test suite and redirect back to detail page with results."""
        await verity.ensure_connected()
        from fastapi.responses import RedirectResponse
        try:
            # Get suite to find entity info
            suites = await verity.db.fetch_all("get_test_suite", {"suite_id": suite_id})
            if not suites:
                return HTMLResponse("<h1>Suite not found</h1>", status_code=404)
            suite = suites[0]

            # Find the champion version for this entity
            entity_type = suite["entity_type"]
            entity_name = suite.get("entity_name")
            if entity_type == "agent":
                agent = await verity.db.fetch_one("get_agent_by_name", {"agent_name": entity_name})
                version_id = agent["current_champion_version_id"] if agent else None
            else:
                task = await verity.db.fetch_one("get_task_by_name", {"task_name": entity_name})
                version_id = task["current_champion_version_id"] if task else None

            if not version_id:
                logger.warning("No champion version found for %s %s", entity_type, entity_name)
                return RedirectResponse(url=f"/admin/testing/{suite_id}", status_code=303)

            # Read mock_llm from form - defaults to False (real Claude calls).
            form = await request.form()
            use_mock = form.get("mock_llm", "false").lower() == "true"

            from uuid import UUID
            result = await verity.test_runner.run_suite(
                entity_type=entity_type,
                entity_version_id=UUID(str(version_id)),
                suite_id=UUID(suite_id),
                mock_llm=use_mock,
                channel="staging",
            )
            logger.info("Test suite completed: %s (%d/%d passed)",
                         suite.get("name"), result.passed_cases, result.total_cases)
        except Exception:
            logger.error("Test suite run failed", exc_info=True)

        return RedirectResponse(url=f"/admin/testing/{suite_id}", status_code=303)

    # Keep old URL as redirect for bookmarks
    @router.get("/test-results", response_class=HTMLResponse)
    async def test_results_redirect(request: Request):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin/testing", status_code=301)

    # ── GROUND TRUTH ─────────────────────────────────────────

    @router.get("/ground-truth", response_class=HTMLResponse)
    async def ground_truth_page(request: Request):
        """Ground truth datasets."""
        await verity.ensure_connected()
        datasets = await verity.db.fetch_all("list_all_ground_truth_datasets", {})
        return _render(templates, request, "ground_truth.html",
            active_page="ground_truth",
            datasets=datasets,
        )

    @router.get("/ground-truth/{dataset_id}", response_class=HTMLResponse)
    async def ground_truth_detail_page(request: Request, dataset_id: str):
        """Ground truth dataset detail with records."""
        await verity.ensure_connected()
        dataset = await verity.db.fetch_one("get_ground_truth_dataset", {"dataset_id": dataset_id})
        if not dataset:
            return HTMLResponse("<h1>Dataset not found</h1>", status_code=404)
        records = await verity.db.fetch_all("list_authoritative_annotations", {"dataset_id": dataset_id})
        # Check if a validation is currently running for this dataset
        running_run = await verity.db.fetch_one_raw(
            "SELECT id FROM validation_run WHERE dataset_id = %(did)s AND status = 'running' LIMIT 1",
            {"did": dataset_id},
        )
        return _render(templates, request, "ground_truth_detail.html",
            active_page="ground_truth",
            dataset=dataset,
            records=records,
            has_running_validation=running_run is not None,
        )

    @router.get("/ground-truth/{dataset_id}/records/{record_id}", response_class=HTMLResponse)
    async def ground_truth_record_page(request: Request, dataset_id: str, record_id: str):
        """Ground truth record detail with annotations and tool mocks."""
        await verity.ensure_connected()
        dataset = await verity.db.fetch_one("get_ground_truth_dataset", {"dataset_id": dataset_id})
        if not dataset:
            return HTMLResponse("<h1>Dataset not found</h1>", status_code=404)
        record = await verity.db.fetch_one("get_ground_truth_record", {"record_id": record_id})
        if not record:
            return HTMLResponse("<h1>Record not found</h1>", status_code=404)
        annotations = await verity.db.fetch_all("list_annotations_for_record", {"record_id": record_id})
        record_mocks = await verity.db.fetch_all("list_ground_truth_record_mocks", {"record_id": record_id})
        return _render(templates, request, "ground_truth_record.html",
            active_page="ground_truth",
            dataset=dataset,
            record=record,
            annotations=annotations,
            record_mocks=record_mocks,
        )

    @router.post("/ground-truth/{dataset_id}/records/{record_id}/mocks", response_class=HTMLResponse)
    async def add_record_mock(request: Request, dataset_id: str, record_id: str):
        """Add a tool mock to a ground truth record."""
        await verity.ensure_connected()
        from fastapi.responses import RedirectResponse
        import json as _json
        form = await request.form()
        tool_name = form.get("tool_name", "")
        mock_response_str = form.get("mock_response", "{}")
        description = form.get("description")
        try:
            mock_response = _json.loads(mock_response_str)
        except _json.JSONDecodeError:
            mock_response = {"raw": mock_response_str}
        await verity.db.execute_returning("insert_ground_truth_record_mock", {
            "record_id": record_id,
            "tool_name": tool_name,
            "call_order": 1,
            "mock_response": _json.dumps(mock_response),
            "description": description,
        })
        return RedirectResponse(url=f"/admin/ground-truth/{dataset_id}/records/{record_id}", status_code=303)

    @router.post("/ground-truth/{dataset_id}/records/{record_id}/mocks/{mock_id}/delete", response_class=HTMLResponse)
    async def delete_record_mock(request: Request, dataset_id: str, record_id: str, mock_id: str):
        """Delete a tool mock from a ground truth record."""
        await verity.ensure_connected()
        from fastapi.responses import RedirectResponse
        await verity.db.execute_returning("delete_ground_truth_record_mock", {"mock_id": mock_id})
        return RedirectResponse(url=f"/admin/ground-truth/{dataset_id}/records/{record_id}", status_code=303)

    @router.post("/ground-truth/{dataset_id}/validate", response_class=HTMLResponse)
    async def run_validation(request: Request, dataset_id: str):
        """Run validation for a dataset against the champion version."""
        await verity.ensure_connected()
        from fastapi.responses import RedirectResponse
        from uuid import UUID

        try:
            dataset = await verity.db.fetch_one("get_ground_truth_dataset", {"dataset_id": dataset_id})
            if not dataset:
                return HTMLResponse("<h1>Dataset not found</h1>", status_code=404)

            entity_type = dataset["entity_type"]
            entity_name = dataset.get("entity_name")

            # Find champion version
            if entity_type == "agent":
                entity = await verity.db.fetch_one("get_agent_by_name", {"agent_name": entity_name})
            else:
                entity = await verity.db.fetch_one("get_task_by_name", {"task_name": entity_name})

            version_id = entity.get("current_champion_version_id") if entity else None
            if not version_id:
                logger.warning("No champion version for %s %s", entity_type, entity_name)
                return RedirectResponse(url=f"/admin/ground-truth/{dataset_id}", status_code=303)

            # Read mock_llm from form - defaults to False (real Claude calls).
            # User must explicitly check "Mock LLM" on the UI to skip real execution.
            form = await request.form()
            use_mock = form.get("mock_llm", "false").lower() == "true"

            result = await verity.validation_runner.run_validation(
                entity_type=entity_type,
                entity_version_id=UUID(str(version_id)),
                dataset_id=UUID(dataset_id),
                run_by="Verity Admin UI",
                mock_llm=use_mock,
                channel="staging",
            )
            logger.info("Validation complete: %s (passed=%s, f1=%.2f)",
                         dataset.get("name"), result.passed, result.f1)

            # Redirect to the validation run detail
            if result.validation_run_id:
                return RedirectResponse(url=f"/admin/validation-runs/{result.validation_run_id}", status_code=303)
        except Exception:
            logger.error("Validation run failed", exc_info=True)

        return RedirectResponse(url=f"/admin/ground-truth/{dataset_id}", status_code=303)

    # ── VALIDATION RUNS ──────────────────────────────────────

    @router.get("/validation-runs", response_class=HTMLResponse)
    async def validation_runs_page(request: Request):
        """All validation runs."""
        await verity.ensure_connected()
        runs = await verity.db.fetch_all("list_validation_runs", {})
        return _render(templates, request, "validation_runs.html",
            active_page="validation_runs",
            runs=runs,
        )

    @router.get("/validation-runs/{run_id}", response_class=HTMLResponse)
    async def validation_run_detail_page(request: Request, run_id: str):
        """Validation run detail with metrics and per-record results."""
        await verity.ensure_connected()
        run = await verity.db.fetch_one("get_validation_run_by_id", {"run_id": run_id})
        if not run:
            return HTMLResponse("<h1>Validation run not found</h1>", status_code=404)
        records = await verity.db.fetch_all("list_validation_record_results", {"validation_run_id": run_id})
        record_failures = [r for r in records if not r.get("correct")]
        return _render(templates, request, "validation_run_detail.html",
            active_page="validation_runs",
            run=run,
            records=records,
            record_failures=record_failures,
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

    # ── PLATFORM SETTINGS ──────────────────────────────────────

    async def _load_platform_settings():
        """Read platform_settings grouped by category."""
        rows = await verity.db.fetch_all_raw(
            "SELECT * FROM platform_settings ORDER BY category, sort_order"
        )
        by_category = {}
        for s in rows:
            by_category.setdefault(s.get("category", "general"), []).append(s)
        return by_category

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        """Show Verity platform settings grouped by category."""
        await verity.ensure_connected()
        try:
            settings_by_category = await _load_platform_settings()
        except Exception:
            logger.warning("Could not load platform settings", exc_info=True)
            settings_by_category = {}

        return _render(templates, request, "settings.html",
            active_page="settings",
            settings_by_category=settings_by_category,
        )

    @router.post("/settings/save", response_class=HTMLResponse)
    async def save_settings(request: Request):
        """Update platform settings from the settings form."""
        await verity.ensure_connected()
        form = await request.form()
        try:
            for key, value in form.items():
                await verity.db.execute_raw(
                    "UPDATE platform_settings SET value = %(value)s, updated_at = NOW() WHERE key = %(key)s",
                    {"value": value, "key": key},
                )
            logger.info("Platform settings updated: %s", dict(form))
        except Exception:
            logger.error("Failed to save platform settings", exc_info=True)

        try:
            settings_by_category = await _load_platform_settings()
        except Exception:
            settings_by_category = {}

        return _render(templates, request, "settings.html",
            active_page="settings",
            settings_by_category=settings_by_category,
            saved=True,
        )

    return router
