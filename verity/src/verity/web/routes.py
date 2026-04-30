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

from fastapi import APIRouter, HTTPException, Query, Request
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


def _resolve_date_preset(
    preset: str,
    custom_after: Optional[str],
    custom_before: Optional[str],
):
    """Turn a date-range preset into a concrete (after, before) datetime
    pair for the Runs UI submission-window filter.

    Returns (None, None) when the preset is "all" or unknown — meaning
    "no date filter." Times are computed in UTC because submitted_at is
    a timestamptz; returning aware datetimes lets psycopg do the cast
    without ambiguity.

    Preset values mirror the dropdown in runs_list.html. "custom" uses
    whatever the user typed in the inline datetime inputs; if either
    side is missing, that side stays open (e.g., custom with only
    `submitted_after` filled = "from this date forward").
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    if preset == "all":
        return None, None

    if preset == "last_24h":
        return now - timedelta(hours=24), None
    if preset == "last_7d":
        return now - timedelta(days=7), None
    if preset == "last_30d":
        return now - timedelta(days=30), None
    if preset == "last_90d":
        return now - timedelta(days=90), None

    if preset == "current_month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, None

    if preset == "previous_month":
        start_of_this_month = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0,
        )
        # Step into the previous month by subtracting one second from the
        # start of this month, then snap that back to the 1st.
        last_day_prev = start_of_this_month - timedelta(seconds=1)
        start_prev = last_day_prev.replace(day=1)
        return start_prev, start_of_this_month  # exclusive upper

    if preset == "year_to_date":
        start = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0,
        )
        return start, None

    if preset == "custom":
        # ISO-8601 strings from <input type="datetime-local"> (no tz),
        # interpreted as UTC for consistency with the timestamptz column.
        # An empty/missing side leaves that bound open.
        def _parse(s: Optional[str]):
            if not s:
                return None
            try:
                dt = datetime.fromisoformat(s)
            except ValueError:
                return None
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        return _parse(custom_after), _parse(custom_before)

    # Unknown preset → treat as "all" rather than 500ing.
    return None, None


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

        # Workflow-run total — distinct workflow_run_ids on the decision
        # log. Scoped when apps are selected; otherwise reuse the unscoped
        # number already in governance_stats. Renamed from "pipeline runs"
        # now that workflow_run_id is caller-supplied (not Verity-owned).
        if selected_ids:
            pr_row = await verity.db.fetch_one(
                "dashboard_workflow_runs_scoped",
                {"app_ids": [str(i) for i in selected_ids], "app_names": selected_names},
            ) or {}
            total_workflow_runs = pr_row.get("total_workflow_runs") or 0
        else:
            total_workflow_runs = governance_stats.get("total_workflow_runs") or 0

        # ── Month-to-date cost + invocations (scoped to selected apps)
        # for the home page's "Usage & Spend" section. Same usage_totals
        # call the /admin/usage dashboard uses, with the window pinned
        # to the first of the current UTC month → now.
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        month_start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        mtd_totals = await verity.models.usage_totals(
            from_ts=month_start, to_ts=now_utc,
            app_names=selected_names,
        ) or {}
        mtd = {
            "month_label": month_start.strftime("%B %Y"),     # e.g. "April 2026"
            "from_date":   month_start.date().isoformat(),
            "to_date":     now_utc.date().isoformat(),
            "total_cost_usd":   float(mtd_totals.get("total_cost_usd") or 0),
            "invocation_count": int(mtd_totals.get("invocation_count") or 0),
            "input_tokens":     int(mtd_totals.get("input_tokens") or 0),
            "output_tokens":    int(mtd_totals.get("output_tokens") or 0),
        }

        return _render(templates, request, "dashboard.html",
            active_page="home",
            counts=counts,
            governance_stats=governance_stats,
            total_workflow_runs=total_workflow_runs,
            applications=applications,
            selected_app_names=selected_names,
            mtd=mtd,
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
            entity_kind="agent",
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
        model_cards = []
        validation = None

        if task.get("current_champion_version_id"):
            champion_id = task["current_champion_version_id"]
            try:
                config = await verity.get_task_config(task_name)
                prompts = config.prompts
                # Tasks are single-call structured-output units — no
                # dynamic tool dispatch loop. Don't read or pass
                # config.tools so the shared template can suppress the
                # Authorized Tools section for tasks.
            except Exception:
                logger.warning("Could not load champion config for detail page", exc_info=True)

            model_cards = await verity.testing.list_model_cards("task", champion_id)
            validation = await verity.testing.get_latest_validation("task", champion_id)

        # Render via the shared agent_detail.html template; entity_kind
        # discriminates so agent-only sections (Authorized Tools,
        # Sub-Agent Delegation Authorizations) are skipped for tasks.
        return _render(templates, request, "agent_detail.html",
            active_page="tasks",
            entity_kind="task",
            agent=task,
            versions=versions,
            prompts=prompts,
            tools=[],
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

    # ── MCP SERVERS ─────────────────────────
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

        # Parse window (default: last 7 days). Same logic as the
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

        # Preserve what the user typed (for the form input value + the
        # chart's axis max); shift the SQL upper bound to end-of-day
        # when the user entered a date with no time. Otherwise
        # `to=2026-04-22` would map to midnight exactly and the
        # SQL's `started_at < to_ts` would EXCLUDE everything that
        # happened during that day — counterintuitive for a date
        # picker that says "through April 22".
        to_display = to_ts.date().isoformat()
        if to and "T" not in to and " " not in to:
            to_ts = to_ts + timedelta(days=1)
        from_display = from_ts.date().isoformat()

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
            # `from_ts` / `to_ts` are the user-facing dates (what the
            # date-picker inputs show, what the chart axis uses). The
            # actual SQL window was shifted by one day on the `to`
            # side to make the date inclusive — see the comment above.
            from_ts=from_display,
            to_ts=to_display,
            applications=applications,
            selected_app_names=selected_app_names,
            totals=totals,
            by_model=by_model,
            by_agent=by_agent,
            by_task=by_task,
            by_application=by_app,
            over_time=over_time,
        )

    # ── QUOTAS ────────────────────────────────────────────────

    @router.get("/quotas", response_class=HTMLResponse)
    async def quotas_list(request: Request):
        """List quotas + inline latest-check summary + create form."""
        await verity.ensure_connected()
        quotas = await verity.quotas.list_quotas()
        latest_checks = await verity.quotas.latest_checks()
        latest_by_quota = {row["quota_id"]: row for row in latest_checks}

        # Lookup tables for the scope dropdown in the create form.
        applications = await verity.list_applications()
        agents       = await verity.list_agents()
        tasks        = await verity.list_tasks()
        models       = await verity.models.list_models()

        return _render(templates, request, "quotas.html",
            active_page="quotas",
            quotas=quotas,
            latest_by_quota=latest_by_quota,
            applications=applications,
            agents=agents,
            tasks=tasks,
            models=models,
        )

    @router.post("/quotas/new", response_class=HTMLResponse)
    async def quotas_create(request: Request):
        """Handle the create form POST. Redirects back to /admin/quotas."""
        from fastapi.responses import RedirectResponse
        await verity.ensure_connected()
        form = await request.form()
        # Scope dropdown value is encoded as "<scope_type>:<scope_id>:<scope_name>"
        # — lets one <select> cover apps / agents / tasks / models and carry
        # the display name without a second lookup server-side.
        scope_raw = (form.get("scope") or "").strip()
        if not scope_raw or ":" not in scope_raw:
            return HTMLResponse("<h1>Bad scope</h1>", status_code=400)
        parts = scope_raw.split(":", 2)
        if len(parts) != 3:
            return HTMLResponse("<h1>Bad scope</h1>", status_code=400)
        scope_type, scope_id, scope_name = parts
        try:
            await verity.quotas.register_quota(
                scope_type=scope_type,
                scope_id=scope_id,
                scope_name=scope_name,
                period=form.get("period", "daily"),
                budget_usd=float(form.get("budget_usd") or 0),
                alert_threshold_pct=int(form.get("alert_threshold_pct") or 80),
                notes=(form.get("notes") or "").strip() or None,
            )
        except (ValueError, Exception) as exc:
            return HTMLResponse(f"<h1>Create failed</h1><pre>{exc}</pre>", status_code=400)
        return RedirectResponse(url="/admin/quotas", status_code=303)

    @router.post("/quotas/check", response_class=HTMLResponse)
    async def quotas_check_now(request: Request):
        """Click handler for the 'Run check now' button on /admin/quotas.

        Runs run_all_checks() and redirects back so the page reloads
        with fresh latest-check summaries visible.
        """
        from fastapi.responses import RedirectResponse
        await verity.ensure_connected()
        await verity.quotas.run_all_checks()
        return RedirectResponse(url="/admin/quotas", status_code=303)

    @router.post("/quotas/{quota_id}/delete", response_class=HTMLResponse)
    async def quotas_delete(request: Request, quota_id: str):
        """Delete one quota and its check history. Form POST so no JS needed."""
        from fastapi.responses import RedirectResponse
        await verity.ensure_connected()
        try:
            from uuid import UUID as _UUID
            await verity.quotas.delete_quota(_UUID(quota_id))
        except Exception as exc:
            return HTMLResponse(f"<h1>Delete failed</h1><pre>{exc}</pre>", status_code=400)
        return RedirectResponse(url="/admin/quotas", status_code=303)

    # ── INCIDENTS ─────────────────────────────────────────────

    @router.get("/incidents", response_class=HTMLResponse)
    async def incidents_list(request: Request):
        """Unified incidents page — governance incidents + active
        quota breaches in one list. The Home page's Open Incidents
        tile uses the same union."""
        await verity.ensure_connected()
        rows = await verity.db.fetch_all("list_open_incidents")
        # Separate counts for the two source tiles at the top of the page.
        governance_count = sum(1 for r in rows if r.get("source") == "governance")
        quota_count      = sum(1 for r in rows if r.get("source") == "quota")
        return _render(templates, request, "incidents.html",
            active_page="incidents",
            incidents=rows,
            governance_count=governance_count,
            quota_count=quota_count,
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
            # hitl_override carries application directly — no need
            # to join through agent_decision_log.
            "SELECT COUNT(*) AS cnt FROM hitl_override "
            "WHERE application = %(app_name)s",
            {"app_name": app_name},
        )
        return _render(templates, request, "application_detail.html",
            active_page="applications",
            app=app,
            entities=entities,
            decision_count=decision_row["cnt"] if decision_row else 0,
            override_count=override_row["cnt"] if override_row else 0,
        )

    # ── RUNS (unified view over execution_run_current) ─────────
    # Replaces the descoped /admin/pipeline-runs page. Every async
    # task / agent run submitted through the Verity worker surfaces
    # here in one table, regardless of entity kind. Filters are
    # AND'd; missing filters disable that constraint.

    @router.get("/runs", response_class=HTMLResponse)
    async def runs_list_page(
        request: Request,
        status: Optional[str] = None,
        entity_kind: Optional[str] = None,
        entity_name: Optional[str] = None,
        entity_name_contains: Optional[str] = None,
        application: Optional[str] = None,
        channel: Optional[str] = None,
        date_preset: Optional[str] = None,
        submitted_after: Optional[str] = None,
        submitted_before: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        execution_context_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ):
        await verity.ensure_connected()
        # Malformed UUIDs in the query string surface as 400 rather
        # than 500 — the listing page gets deep-linked from UW submission
        # pages, and a typoed context id shouldn't look like a crash.
        try:
            workflow_uuid = UUID(workflow_run_id) if workflow_run_id else None
            context_uuid = UUID(execution_context_id) if execution_context_id else None
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid UUID: {exc}")

        # Date-range preset resolution. A missing date_preset is treated
        # as "current_month" so first-time visitors see a useful slice
        # rather than every run ever. To opt out, pick "all" explicitly.
        effective_preset = date_preset or "current_month"
        after_dt, before_dt = _resolve_date_preset(
            effective_preset, submitted_after, submitted_before,
        )

        filters = {
            "status": status or None,
            "entity_kind": entity_kind or None,
            "entity_name": entity_name or None,
            "entity_name_contains": entity_name_contains or None,
            "application": application or None,
            "channel": channel or None,
            "date_preset": effective_preset,
            # Echo back the user's typed values so the custom date inputs
            # stay sticky. We don't echo the resolved-from-preset window
            # because the dropdown already encodes that choice.
            "submitted_after": submitted_after or None,
            "submitted_before": submitted_before or None,
            "workflow_run_id": workflow_uuid,
            "execution_context_id": context_uuid,
        }
        # Pass the typed filters to the reader and the string-ish ones
        # back to the template so the form inputs stay sticky.
        runs = await verity.runs_reader.list_runs(
            limit=limit, offset=offset,
            status=filters["status"],
            entity_kind=filters["entity_kind"],
            entity_name=filters["entity_name"],
            entity_name_contains=filters["entity_name_contains"],
            application=filters["application"],
            channel=filters["channel"],
            submitted_after=after_dt,
            submitted_before=before_dt,
            workflow_run_id=filters["workflow_run_id"],
            execution_context_id=filters["execution_context_id"],
        )
        total = await verity.runs_reader.count_runs(
            status=filters["status"],
            entity_kind=filters["entity_kind"],
            entity_name=filters["entity_name"],
            entity_name_contains=filters["entity_name_contains"],
            application=filters["application"],
            channel=filters["channel"],
            submitted_after=after_dt,
            submitted_before=before_dt,
            workflow_run_id=filters["workflow_run_id"],
            execution_context_id=filters["execution_context_id"],
        )
        # Build a query string that preserves every filter for the
        # next/prev pagination links. urlencode skips None/empty values.
        from urllib.parse import urlencode
        filter_qs = urlencode({
            k: v for k, v in {
                "status": status, "entity_kind": entity_kind,
                "entity_name": entity_name,
                "entity_name_contains": entity_name_contains,
                "application": application, "channel": channel,
                "date_preset": date_preset,
                "submitted_after": submitted_after,
                "submitted_before": submitted_before,
                "workflow_run_id": workflow_run_id,
                "execution_context_id": execution_context_id,
            }.items() if v
        })
        # Dropdown options.
        # - applications: distinct values from execution_run (deliberately
        #   scoped to apps that have at least one run, so the dropdown
        #   never offers zero-result values).
        # - entity names: catalog UNION (task ∪ agent), O(catalog) — does
        #   show entities with zero runs but the source tables are tiny.
        # - channels: hardcoded enum universe, no DB call.
        application_options = await verity.runs_reader.list_filter_applications()
        entity_name_options = await verity.runs_reader.list_filter_entity_names()
        channel_options = verity.runs_reader.list_filter_channels()
        return _render(templates, request, "runs_list.html",
            active_page="runs",
            runs=runs,
            total=total,
            filters=filters,
            limit=limit,
            offset=offset,
            filter_qs=filter_qs,
            application_options=application_options,
            entity_name_options=entity_name_options,
            channel_options=channel_options,
        )

    @router.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail_page(request: Request, run_id: str):
        """Single-run drill-through: header, lifecycle timeline, envelope.

        The page fetches three things:
          - ExecutionRunCurrent (the view row)
          - RunLifecycleEvent[] (every status/completion/error event)
          - ExecutionEnvelope (present only when terminal)
        It's okay for envelope to be None on in-flight runs — the
        template renders just the header + lifecycle in that case.
        """
        await verity.ensure_connected()
        try:
            rid = UUID(run_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"Invalid run UUID: {run_id!r}")
        run = await verity.runs_reader.get_run(rid)
        if not run:
            return HTMLResponse("<h1>Run not found</h1>", status_code=404)
        lifecycle = await verity.runs_reader.get_run_lifecycle(rid)
        # Envelope only available for terminal runs. RunsReader.get_run_result
        # returns None for in-flight, which the template handles.
        envelope = await verity.runs_reader.get_run_result(rid)
        return _render(templates, request, "run_detail.html",
            active_page="runs",
            run=run,
            lifecycle=lifecycle,
            envelope=envelope,
        )

    @router.get("/workflows/{workflow_run_id}", response_class=HTMLResponse)
    async def workflow_detail_page(request: Request, workflow_run_id: str):
        """All runs sharing one caller-supplied workflow_run_id.

        Drives the "show me the whole multi-step workflow" drill-through.
        Runs are returned in submitted_at order by
        RunsReader.list_runs_for_workflow.
        """
        await verity.ensure_connected()
        try:
            wid = UUID(workflow_run_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid workflow UUID: {workflow_run_id!r}",
            )
        runs = await verity.runs_reader.list_runs_for_workflow(wid)
        return _render(templates, request, "workflow_detail.html",
            active_page="runs",
            workflow_run_id=wid,
            runs=runs,
        )

    # ── DECISION LOG ──────────────────────────────────────────

    @router.get("/decisions", response_class=HTMLResponse)
    async def decisions_list(
        request: Request,
        status: Optional[str] = None,
        entity_type: Optional[str] = None,
        decision_log_detail: Optional[str] = None,
        application: Optional[str] = None,
        entity_name_contains: Optional[str] = None,
        date_preset: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        """Decision-log list with the same server-side filter shape as
        /admin/runs. Capped at 1000 to match the parquet/feed export upper
        bound — the page is client-side searchable/sortable on top of the
        server-filtered slice."""
        await verity.ensure_connected()

        # Date preset resolution — shared helper with runs. Default
        # "current_month" so the page lands on a useful slice instead
        # of every decision ever logged.
        effective_preset = date_preset or "current_month"
        after_dt, before_dt = _resolve_date_preset(
            effective_preset, created_after, created_before,
        )

        filters = {
            "status": status or None,
            "entity_type": entity_type or None,
            "decision_log_detail": decision_log_detail or None,
            "application": application or None,
            "entity_name_contains": entity_name_contains or None,
            "date_preset": effective_preset,
            "created_after": created_after or None,
            "created_before": created_before or None,
        }

        # Direct call into the reader (not through the client wrapper)
        # because the wrapper signature only takes limit/offset; going
        # direct keeps the kwargs surface explicit and avoids growing
        # the wrapper for a UI-specific call site.
        decisions = await verity.decisions.list_decisions(
            limit=limit,
            status=filters["status"],
            entity_type=filters["entity_type"],
            decision_log_detail=filters["decision_log_detail"],
            application=filters["application"],
            entity_name_contains=filters["entity_name_contains"],
            created_after=after_dt,
            created_before=before_dt,
        )
        total = await verity.decisions.count_decisions(
            status=filters["status"],
            entity_type=filters["entity_type"],
            decision_log_detail=filters["decision_log_detail"],
            application=filters["application"],
            entity_name_contains=filters["entity_name_contains"],
            created_after=after_dt,
            created_before=before_dt,
        )

        # Dropdown options.
        # - statuses, log_details, entity_types: hardcoded universes
        #   (see DecisionsReader.DECISION_STATUSES etc.). No DB call.
        # - applications: every registered application (small, indexed
        #   table). Cheaper than DISTINCT-scanning agent_decision_log.
        # - entity names: shared with runs via the catalog UNION
        #   (task ∪ agent), backs the <datalist> autocomplete.
        application_options = await verity.list_applications()
        entity_name_options = await verity.runs_reader.list_filter_entity_names()
        status_options = verity.decisions.list_filter_statuses()
        log_detail_options = verity.decisions.list_filter_log_details()
        entity_type_options = verity.decisions.list_filter_entity_types()

        return _render(templates, request, "decisions.html",
            active_page="decisions",
            decisions=decisions,
            total=total,
            limit=limit,
            filters=filters,
            application_options=application_options,
            entity_name_options=entity_name_options,
            status_options=status_options,
            log_detail_options=log_detail_options,
            entity_type_options=entity_type_options,
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

    @router.get("/audit-trail/run/{workflow_run_id}", response_class=HTMLResponse)
    async def audit_trail_by_run(request: Request, workflow_run_id: str):
        """Audit trail for one pipeline execution.

        Shows all decisions (steps) from a single pipeline run.
        """
        await verity.ensure_connected()
        trail = await verity.get_audit_trail_by_run(UUID(workflow_run_id))
        return _render(templates, request, "audit_trail.html",
            active_page="decisions",
            workflow_run_id=workflow_run_id,
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

    # ── OVERRIDES ─────────────────────────────────────────────

    @router.get("/overrides", response_class=HTMLResponse)
    async def overrides_page(request: Request):
        """Show every per-field human override recorded across all
        applications. Source: hitl_override (the structured,
        JSONPath-anchored table)."""
        await verity.ensure_connected()
        overrides = await verity.db.fetch_all("list_all_hitl_overrides")
        return _render(templates, request, "overrides.html",
            active_page="overrides",
            overrides=overrides,
        )

    @router.get("/overrides/{override_id}", response_class=HTMLResponse)
    async def override_detail_page(request: Request, override_id: str):
        """Single-override detail view. Resolves application
        display name + decision context (entity, version, run id)
        for navigation back into the audit trail."""
        await verity.ensure_connected()
        ov = await verity.db.fetch_one("get_hitl_override_by_id",
                                       {"override_id": override_id})
        if not ov:
            return HTMLResponse("Override not found", status_code=404)
        return _render(templates, request, "override_detail.html",
            active_page="overrides",
            override=ov,
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

    # ── COMPLIANCE ────────────────────────────────────────────
    # L3 metamodel review pages. Read-only; YAML is source of truth.
    # See docs/architecture/compliance-stack.md.

    def _matrix_groups(rows, frameworks):
        """Convert flat rows from list_canonical_requirements_with_bridges
        into [{theme_code, theme_name, rows: [...]}] grouped by theme,
        with each canonical row's bridges indexed by framework_code for
        easy O(1) lookup in the template.
        """
        fw_codes = {f["code"] for f in frameworks}
        groups = []
        cur = None
        for r in rows:
            bridges_by_fw = {}
            for b in (r.get("bridges") or []):
                if b["framework_code"] in fw_codes:
                    bridges_by_fw[b["framework_code"]] = b
            r = dict(r)
            r["bridges_by_framework"] = bridges_by_fw
            if cur is None or cur["theme_code"] != r["theme_code"]:
                cur = {
                    "theme_code": r["theme_code"],
                    "theme_name": r["theme_name"],
                    "rows": [],
                }
                groups.append(cur)
            cur["rows"].append(r)
        return groups

    @router.get("/compliance/", response_class=HTMLResponse)
    async def compliance_overview(
        request: Request,
        framework: Optional[str] = Query(None),
        theme: Optional[str] = Query(None),
        coverage: Optional[str] = Query(None),
    ):
        await verity.ensure_connected()

        all_frameworks = await verity.db.fetch_all("list_compliance_frameworks_for_matrix")
        themes = await verity.db.fetch_all("list_compliance_themes")
        rows = await verity.db.fetch_all("list_canonical_requirements_with_bridges")
        rollup = await verity.db.fetch_all("compliance_coverage_rollup")
        overall = await verity.db.fetch_one("compliance_overall_counts") or {}

        coverage_counts = {r["coverage_level"]: r["canonical_count"] for r in rollup if r["coverage_level"]}

        # Filter rows.
        filtered = []
        for r in rows:
            if theme and r["theme_code"] != theme:
                continue
            if coverage and r["coverage_level"] != coverage:
                continue
            if framework:
                bridge_codes = {b["framework_code"] for b in (r.get("bridges") or [])}
                if framework not in bridge_codes:
                    continue
            filtered.append(r)

        # If filtering by framework, only show that column. Otherwise show all.
        if framework:
            display_frameworks = [f for f in all_frameworks if f["code"] == framework]
        else:
            display_frameworks = list(all_frameworks)

        return _render(
            templates, request, "compliance_overview.html",
            active_page="compliance",
            subnav_active="overview",
            frameworks=display_frameworks,
            themes=themes,
            matrix_groups=_matrix_groups(filtered, display_frameworks),
            visible_canonical_count=len(filtered),
            coverage_counts=coverage_counts,
            overall=overall,
            filter_framework=framework or "",
            filter_theme=theme or "",
            filter_coverage=coverage or "",
        )

    @router.get("/compliance/frameworks", response_class=HTMLResponse)
    async def compliance_frameworks(request: Request):
        await verity.ensure_connected()
        frameworks = await verity.db.fetch_all("list_frameworks_with_stats")
        return _render(
            templates, request, "compliance_frameworks.html",
            active_page="compliance",
            subnav_active="frameworks",
            frameworks=frameworks,
        )

    @router.get("/compliance/frameworks/{framework_code}", response_class=HTMLResponse)
    async def compliance_framework_detail(request: Request, framework_code: str):
        await verity.ensure_connected()
        framework = await verity.db.fetch_one(
            "get_framework_by_code", {"framework_code": framework_code}
        )
        if not framework:
            raise HTTPException(status_code=404, detail="Framework not found")
        provisions = await verity.db.fetch_all(
            "list_provisions_for_framework", {"framework_code": framework_code}
        )
        return _render(
            templates, request, "compliance_framework_detail.html",
            active_page="compliance",
            subnav_active="frameworks",
            framework=framework,
            provisions=provisions,
        )

    @router.get("/compliance/provisions/{provision_id}", response_class=HTMLResponse)
    async def compliance_provision_detail(request: Request, provision_id: UUID):
        await verity.ensure_connected()
        provision = await verity.db.fetch_one(
            "get_provision_by_id", {"provision_id": str(provision_id)}
        )
        if not provision:
            raise HTTPException(status_code=404, detail="Provision not found")
        canonical_links = await verity.db.fetch_all(
            "list_canonicals_for_provision", {"provision_id": str(provision_id)}
        )
        return _render(
            templates, request, "compliance_provision_detail.html",
            active_page="compliance",
            subnav_active="frameworks",
            provision=provision,
            canonical_links=canonical_links,
        )

    @router.get("/compliance/canonicals", response_class=HTMLResponse)
    async def compliance_canonicals(
        request: Request,
        theme: Optional[str] = Query(None),
        coverage: Optional[str] = Query(None),
    ):
        await verity.ensure_connected()
        themes = await verity.db.fetch_all("list_compliance_themes")
        rows = await verity.db.fetch_all("list_canonicals_grouped")

        filtered = []
        for r in rows:
            if theme and r["theme_code"] != theme:
                continue
            if coverage and r["coverage_level"] != coverage:
                continue
            filtered.append(r)

        groups: list[dict] = []
        cur = None
        for r in filtered:
            if cur is None or cur["theme_code"] != r["theme_code"]:
                cur = {"theme_code": r["theme_code"], "theme_name": r["theme_name"], "rows": []}
                groups.append(cur)
            cur["rows"].append(r)

        return _render(
            templates, request, "compliance_canonicals.html",
            active_page="compliance",
            subnav_active="canonicals",
            themes=themes,
            canonicals=filtered,
            groups=groups,
            filter_theme=theme or "",
            filter_coverage=coverage or "",
        )

    @router.get("/compliance/canonicals/{canonical_code}", response_class=HTMLResponse)
    async def compliance_canonical_detail(request: Request, canonical_code: str):
        await verity.ensure_connected()
        canonical = await verity.db.fetch_one(
            "get_canonical_requirement_by_code", {"canonical_code": canonical_code}
        )
        if not canonical:
            raise HTTPException(status_code=404, detail="Canonical requirement not found")
        provisions = await verity.db.fetch_all(
            "list_provisions_for_canonical", {"canonical_code": canonical_code}
        )
        features = await verity.db.fetch_all(
            "list_features_for_canonical", {"canonical_code": canonical_code}
        )
        reports = await verity.db.fetch_all(
            "list_reports_for_canonical", {"canonical_code": canonical_code}
        )
        return _render(
            templates, request, "compliance_canonical_detail.html",
            active_page="compliance",
            subnav_active="canonicals",
            canonical=canonical,
            provisions=provisions,
            features=features,
            reports=reports,
        )

    @router.get("/compliance/features", response_class=HTMLResponse)
    async def compliance_features(request: Request):
        await verity.ensure_connected()
        rows = await verity.db.fetch_all("list_features_grouped")

        # Pivot flat rows into plane → capability → feature tree.
        planes_by_code: dict[str, dict] = {}
        for r in rows:
            p_code = r["plane_code"]
            plane = planes_by_code.get(p_code)
            if plane is None:
                plane = {
                    "code": p_code, "name": r["plane_name"],
                    "sort": r["plane_sort"],
                    "capabilities": [],
                    "_caps_by_code": {},
                    "feature_total": 0,
                }
                planes_by_code[p_code] = plane

            c_code = r["capability_code"]
            cap = plane["_caps_by_code"].get(c_code)
            if cap is None:
                cap = {
                    "code": c_code, "name": r["capability_name"],
                    "sort": r["capability_sort"],
                    "features": [],
                }
                plane["capabilities"].append(cap)
                plane["_caps_by_code"][c_code] = cap

            cap["features"].append({
                "feature_code": r["feature_code"],
                "feature_name": r["feature_name"],
                "feature_description": r["feature_description"],
                "status": r["status"],
                "canonical_link_count": r["canonical_link_count"],
            })
            plane["feature_total"] += 1

        planes = sorted(planes_by_code.values(), key=lambda x: x["sort"])
        for p in planes:
            p["capabilities"].sort(key=lambda c: c["sort"])
            p.pop("_caps_by_code", None)

        return _render(
            templates, request, "compliance_features.html",
            active_page="compliance",
            subnav_active="features",
            planes=planes,
        )

    @router.get("/compliance/features/{feature_code}", response_class=HTMLResponse)
    async def compliance_feature_detail(request: Request, feature_code: str):
        await verity.ensure_connected()
        feature = await verity.db.fetch_one(
            "get_feature_by_code", {"feature_code": feature_code}
        )
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        canonicals = await verity.db.fetch_all(
            "list_canonicals_for_feature", {"feature_code": feature_code}
        )
        return _render(
            templates, request, "compliance_feature_detail.html",
            active_page="compliance",
            subnav_active="features",
            feature=feature,
            canonicals=canonicals,
        )

    @router.get("/compliance/reports", response_class=HTMLResponse)
    async def compliance_reports_list(request: Request):
        await verity.ensure_connected()
        reports     = await verity.db.fetch_all("list_active_reports")
        recent_runs = await verity.db.fetch_all("list_recent_report_runs")
        return _render(
            templates, request, "compliance_reports.html",
            active_page="compliance",
            subnav_active="reports",
            reports=reports,
            recent_runs=recent_runs,
        )

    @router.get("/compliance/reports/{report_code}", response_class=HTMLResponse)
    async def compliance_report_detail(
        request: Request,
        report_code: str,
        error: Optional[str] = Query(None),
    ):
        from datetime import date
        from verity.reporting import (
            get_report_definition,
            get_report_canonicals,
            get_report_field_manifest,
        )
        await verity.ensure_connected()

        report = await get_report_definition(verity, report_code)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        canonicals = await get_report_canonicals(verity, report_code)
        manifest   = await get_report_field_manifest(verity, report_code)

        # Pre-resolve picker option lists for known fields so the form can
        # render a <select> instead of a free-text input. Keys match the
        # JSON-Schema property names in scope_params.
        picker_options: dict[str, list[dict]] = {}
        if "execution_context_id" in (
            (report.get("scope_params") or {}).get("properties") or {}
        ):
            picker_options["execution_context_id"] = await verity.db.fetch_all(
                "list_recent_execution_contexts_for_picker"
            )

        return _render(
            templates, request, "compliance_report_detail.html",
            active_page="compliance",
            subnav_active="reports",
            report=report,
            canonicals=canonicals,
            manifest=manifest,
            picker_options=picker_options,
            today_iso=date.today().isoformat(),
            error_message=error,
        )

    @router.post("/compliance/reports/{report_code}/generate")
    async def compliance_report_generate(request: Request, report_code: str):
        """Resolve dataset, render DOCX, log run, stream the file."""
        from datetime import datetime
        from urllib.parse import urlencode
        from fastapi.responses import FileResponse, RedirectResponse
        import json
        import time
        from verity.reporting import (
            get_report_definition,
            resolve_dataset,
            render_docx,
        )
        await verity.ensure_connected()

        report = await get_report_definition(verity, report_code)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        # Build scope from form data. Strip whitespace defensively — hidden
        # input values rendered through templates can pick up surrounding
        # whitespace from Jinja's default whitespace handling.
        form = await request.form()
        scope = {
            k: (v.strip() if isinstance(v, str) else v)
            for k, v in form.items()
            if v and (not isinstance(v, str) or v.strip())
        }

        # Server-side required-field validation. JSON Schema's `required`
        # array lists property names that must be present and non-empty.
        required = (report.get("scope_params") or {}).get("required") or []
        missing = [name for name in required if not scope.get(name)]
        if missing:
            err = f"Missing required field(s): {', '.join(missing)}"
            return RedirectResponse(
                url=f"/admin/compliance/reports/{report_code}?{urlencode({'error': err})}",
                status_code=303,
            )

        # Audit row (insert as 'pending'; finalize after render).
        row = await verity.db.fetch_one_raw(
            """
            INSERT INTO compliance.report_run_log
                (report_id, requested_by, scope_params, output_formats, status)
            VALUES (%(report_id)s, %(by)s, %(scope)s::jsonb, %(formats)s, 'pending')
            RETURNING id
            """,
            {
                "report_id": str(report["id"]),
                "by": "admin",  # TODO: real auth (rest-api-auth.md enhancement)
                "scope": json.dumps(scope),
                "formats": ["docx"],
            },
        )
        run_id = row["id"]

        t0 = time.perf_counter()
        try:
            dataset = await resolve_dataset(verity, report_code, scope)
            ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            output_path = f"/tmp/verity-reports/{report_code}__{ts}.docx"
            saved = render_docx(
                dataset,
                report_code=report_code,
                docx_template=report.get("docx_template"),
                output_path=output_path,
            )
            duration_ms = int((time.perf_counter() - t0) * 1000)
            await verity.db.execute_raw(
                """
                UPDATE compliance.report_run_log
                SET status = 'succeeded',
                    artifact_uris = %(artifacts)s::jsonb,
                    duration_ms   = %(dur)s,
                    completed_at  = now()
                WHERE id = %(id)s
                """,
                {
                    "artifacts": json.dumps({"docx": str(saved)}),
                    "dur":       duration_ms,
                    "id":        str(run_id),
                },
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            await verity.db.execute_raw(
                """
                UPDATE compliance.report_run_log
                SET status = 'failed',
                    error_message = %(msg)s,
                    duration_ms   = %(dur)s,
                    completed_at  = now()
                WHERE id = %(id)s
                """,
                {"msg": str(exc), "dur": duration_ms, "id": str(run_id)},
            )
            raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")

        download_name = f"{report_code}__{ts}.docx"
        return FileResponse(
            path=str(saved),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=download_name,
        )

    @router.get("/compliance/feeds", response_class=HTMLResponse)
    async def compliance_feeds(request: Request):
        """Browse the available data feeds + sample-pull links."""
        await verity.ensure_connected()
        feed_views = await verity.db.fetch_all("list_active_feed_views")

        # Best-effort row-count + watermark range per view. Cheap because
        # all our views have small underlying tables; fast enough for a
        # browse page.
        for v in feed_views:
            try:
                stats = await verity.db.fetch_one_raw(
                    f"SELECT count(*) AS row_count, "
                    f"       min(ingest_ts) AS min_ingest_ts, "
                    f"       max(ingest_ts) AS max_ingest_ts "
                    f"FROM analytics.{v['view_name']}"
                )
                v["row_count"]     = stats["row_count"]     if stats else 0
                v["min_ingest_ts"] = stats.get("min_ingest_ts") if stats else None
                v["max_ingest_ts"] = stats.get("max_ingest_ts") if stats else None
            except Exception:
                v["row_count"]     = 0
                v["min_ingest_ts"] = None
                v["max_ingest_ts"] = None

        return _render(
            templates, request, "compliance_feeds.html",
            active_page="compliance",
            subnav_active="feeds",
            feed_views=feed_views,
        )

    @router.get("/compliance/bridges", response_class=HTMLResponse)
    async def compliance_bridges(
        request: Request,
        tab: str = Query("provision_canonical"),
        framework: Optional[str] = Query(None),
        canonical: Optional[str] = Query(None),
        mapping_source: Optional[str] = Query(None),
        min_match: Optional[str] = Query(None),
        plane: Optional[str] = Query(None),
        feature: Optional[str] = Query(None),
        role: Optional[str] = Query(None),
    ):
        await verity.ensure_connected()
        active_tab = tab if tab in ("provision_canonical", "canonical_feature") else "provision_canonical"

        frameworks = await verity.db.fetch_all("list_compliance_frameworks_for_matrix")
        planes_rows = await verity.db.fetch_all_raw(
            "SELECT code, name FROM compliance.feature_plane ORDER BY sort_seq, code"
        )

        pc_bridges: list[dict] = []
        cf_bridges: list[dict] = []

        if active_tab == "provision_canonical":
            try:
                min_match_val = float(min_match) if min_match else None
            except ValueError:
                min_match_val = None
            pc_bridges = await verity.db.fetch_all(
                "list_provision_canonical_bridges",
                {
                    "framework_code": framework or None,
                    "canonical_code": canonical or None,
                    "mapping_source": mapping_source or None,
                    "min_match_strength": min_match_val,
                },
            )
        else:
            cf_bridges = await verity.db.fetch_all(
                "list_canonical_feature_bridges",
                {
                    "canonical_code": canonical or None,
                    "feature_code": feature or None,
                    "plane_code": plane or None,
                    "role": role or None,
                },
            )

        return _render(
            templates, request, "compliance_bridges.html",
            active_page="compliance",
            subnav_active="bridges",
            active_tab=active_tab,
            frameworks=frameworks,
            planes=planes_rows,
            pc_bridges=pc_bridges,
            cf_bridges=cf_bridges,
            filter_framework=framework or "",
            filter_mapping_source=mapping_source or "",
            filter_min_match=min_match or "",
            filter_plane=plane or "",
            filter_role=role or "",
        )

    return router
