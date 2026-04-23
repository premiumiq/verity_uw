"""Build every Data Science Workbench notebook from a single script.

Run inside the ds_workbench container:
    docker exec ds_workbench python /home/jovyan/work/_build_notebooks.py

Generates valid nbformat-v4 JSON for each notebook. We keep notebook
structure in a Python builder because hand-editing .ipynb JSON is
error-prone and git-diffs are noisy. Regenerate whenever the utility
signatures change.

Every capability notebook follows the four-section pattern:
    1. What this demonstrates (markdown)
    2. Prerequisites (markdown + code)
    3. Execute (markdown + code)
    4. Review results (markdown + code with visualizations)

Each notebook also imports the utility helpers using a small bootstrap
that works from Docker JupyterLab (cwd=/home/jovyan/work) and from
VSCode on the host (cwd anywhere under the repo).
"""

from pathlib import Path

import nbformat as nbf


NB_DIR = Path("/home/jovyan/work")
APP_NAME = "ds_workbench"

# Shared bootstrap prepended to every code cell that needs the utility
# modules. The setup + cleanup notebooks already have their own tailored
# version, so this constant is for capability notebooks only.
BOOTSTRAP = (
    "import os, sys\n"
    "HERE = os.getcwd()\n"
    "if os.path.basename(HERE) != 'ds_workbench':\n"
    "    for candidate in (os.path.dirname(HERE),\n"
    "                      os.path.dirname(os.path.dirname(HERE)),\n"
    "                      '/home/jovyan/work'):\n"
    "        if os.path.isdir(os.path.join(candidate, 'utility')):\n"
    "            sys.path.insert(0, candidate); break\n"
    "\n"
    "from utility.verity import VerityAPI, VerityAPIError\n"
    "from utility.html import inject_style, badge, render_list, render_detail, render_cards\n"
)


def md(text: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(text)


def code(src: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(src)


# ══════════════════════════════════════════════════════════════
# 00 — Setup
# ══════════════════════════════════════════════════════════════

def build_setup_notebook() -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md(
            "# 00 — Setup\n"
            "\n"
            "## What this demonstrates\n"
            "\n"
            "This notebook establishes the Data Science Workbench as a "
            "registered consumer of the Verity governance platform. After "
            "running it, every subsequent notebook's runtime calls, "
            "execution contexts, and decision-log rows are cleanly "
            "attributed to the `ds_workbench` application — which makes "
            "them trivially separable from any other application's "
            "activity, and trivially cleanable via `99_cleanup.ipynb`.\n"
            "\n"
            "**Verity capabilities exercised**\n"
            "\n"
            "- Reporting dashboard counts (`GET /api/v1/reporting/dashboard-counts`).\n"
            "- Application lookup, registration, and entity mapping "
            "(`/api/v1/applications/*`).\n"
            "- Reading a resolved agent config to seed a typical "
            "workbench interaction (`GET /api/v1/agents/{name}/config`).\n"
        ),
        md(
            "## Prerequisites\n"
            "\n"
            "Only one: the Verity service must be reachable at "
            "`VERITY_API_URL`. The helper reads the env var on "
            "construction and falls back to `http://localhost:8000` — so "
            "inside Docker JupyterLab `VERITY_API_URL=http://verity:8000` "
            "is set by compose, and from VSCode on host the default "
            "localhost URL works.\n"
        ),
        code(BOOTSTRAP + "\ninject_style()   # apply Verity-UI styles to all subsequent cell outputs"),
        code(
            "# Open a client. VERITY_API_URL env var decides the target;\n"
            "# the default lands on localhost for VSCode-on-host users.\n"
            "v = VerityAPI(application='ds_workbench')\n"
            "print(f'base_url            = {v.base_url}')\n"
            "print(f'default application = {v.application}')"
        ),
        code(
            "# Health + dashboard counts — fails fast if Verity is unreachable.\n"
            "counts = v.dashboard_counts()\n"
            "render_cards([\n"
            "    ('Agents',         counts['agent_count'],      None),\n"
            "    ('Tasks',          counts['task_count'],       None),\n"
            "    ('Pipelines',      counts['pipeline_count'],   None),\n"
            "    ('Prompts',        counts['prompt_count'],     None),\n"
            "    ('Tools',          counts['tool_count'],       None),\n"
            "    ('Inference cfg',  counts['config_count'],     None),\n"
            "    ('Decisions',      counts['total_decisions'],  'total'),\n"
            "    ('Overrides',      counts['total_overrides'],  'logged'),\n"
            "    ('Open incidents', counts['open_incidents'],   ''),\n"
            "])"
        ),
        md(
            "## Execute\n"
            "\n"
            "Idempotent registration of the `ds_workbench` application. "
            "If it already exists we reuse it; otherwise a fresh "
            "application row is created.\n"
        ),
        code(
            "app = v.ensure_application_registered(\n"
            "    name='ds_workbench',\n"
            "    display_name='Data Science Workbench',\n"
            "    description='Interactive Verity capability walkthrough notebooks.',\n"
            ")\n"
            "render_detail(\n"
            "    'ds_workbench application',\n"
            "    subtitle=app['name'],\n"
            "    sections=[\n"
            "        {'title': 'Identity', 'fields': [\n"
            "            ('Name',         app.get('name')),\n"
            "            ('Display name', app.get('display_name')),\n"
            "            ('Description',  app.get('description')),\n"
            "            ('ID',           app.get('id')),\n"
            "            ('Created',      app.get('created_at')),\n"
            "        ]},\n"
            "    ],\n"
            ")"
        ),
        md(
            "## Review results\n"
            "\n"
            "The Verity catalog as it exists right now, plus the activity "
            "footprint our workbench has accumulated so far (fresh install "
            "should be zero decisions, zero mappings).\n"
        ),
        code(
            "applications = v.list_applications()\n"
            "render_list(\n"
            "    applications,\n"
            "    columns=[('name','Name'), ('display_name','Display'), ('description','Description')],\n"
            "    title='Registered applications',\n"
            "    description='Every business app that consumes Verity is registered here.',\n"
            ")"
        ),
        code(
            "activity = v.get_app_activity()\n"
            "render_cards([\n"
            "    ('Decisions logged',     activity['decision_count'],           'this app'),\n"
            "    ('Overrides recorded',   activity['override_count'],           'this app'),\n"
            "    ('Execution contexts',   activity['execution_context_count'],  'this app'),\n"
            "    ('Entity mappings',      activity['entity_mapping_count'],     'this app'),\n"
            "])"
        ),
        code(
            "# Sanity check: we can resolve an agent's full config. This is\n"
            "# the blob subsequent notebooks rely on — header + inference\n"
            "# config + prompt assignments + tool authorizations.\n"
            "config = v.get_agent_config('triage_agent')\n"
            "render_detail(\n"
            "    config.get('agent_name', 'agent'),\n"
            "    subtitle=f\"v{config.get('version_label', '?')}\",\n"
            "    header_badges=[\n"
            "        (config.get('lifecycle_state','?'), config.get('lifecycle_state','')),\n"
            "        (config.get('materiality_tier','?'), config.get('materiality_tier','')),\n"
            "    ],\n"
            "    sections=[\n"
            "        {'title': 'Inference config', 'fields': [\n"
            "            ('Name',        config['inference_config'].get('name')),\n"
            "            ('Model',       config['inference_config'].get('model_name')),\n"
            "            ('Temperature', config['inference_config'].get('temperature')),\n"
            "            ('Max tokens',  config['inference_config'].get('max_tokens')),\n"
            "        ]},\n"
            "        {'title': f\"Prompts ({len(config.get('prompts') or [])})\",\n"
            "         'table': {\n"
            "             'columns': [\n"
            "                 ('prompt_name','Prompt'),\n"
            "                 ('version_number','Version'),\n"
            "                 ('api_role','Role','neutral'),\n"
            "                 ('governance_tier','Tier'),\n"
            "                 ('execution_order','Order'),\n"
            "             ],\n"
            "             'rows': config.get('prompts') or [],\n"
            "         }},\n"
            "        {'title': f\"Tools ({len(config.get('tools') or [])})\",\n"
            "         'table': {\n"
            "             'columns': [\n"
            "                 ('tool_name','Tool'),\n"
            "                 ('transport','Transport','neutral'),\n"
            "                 ('mcp_server_name','MCP server'),\n"
            "             ],\n"
            "             'rows': config.get('tools') or [],\n"
            "         }},\n"
            "    ],\n"
            ")"
        ),
        md(
            "---\n"
            "\n"
            "Setup complete. Move on to the component folders under "
            "`notebooks/` to exercise individual Verity capabilities. "
            "When you're done for the session (or want to start clean), "
            "run **`99_cleanup.ipynb`** to purge activity and "
            "unregister this workbench.\n"
        ),
    ]
    return nb


# ══════════════════════════════════════════════════════════════
# 99 — Cleanup
# ══════════════════════════════════════════════════════════════

def build_cleanup_notebook() -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md(
            "# 99 — Cleanup\n"
            "\n"
            "## What this demonstrates\n"
            "\n"
            "Three-step Verity cleanup contract, exercised as the inverse "
            "of `00_setup.ipynb`:\n"
            "\n"
            "1. **Preview activity** — `GET /api/v1/applications/ds_workbench/activity` shows "
            "counts of decisions, overrides, execution contexts, and entity "
            "mappings we accumulated.\n"
            "2. **Purge activity** — `DELETE /api/v1/applications/ds_workbench/activity` "
            "removes decisions, overrides, and execution contexts (guarded "
            "by `VERITY_ALLOW_PURGE=1`). Entity mappings survive because "
            "they are authoring artifacts, not run artifacts.\n"
            "3. **Unregister** — `DELETE /api/v1/applications/ds_workbench` removes "
            "the entity mappings and the application row itself.\n"
            "\n"
            "After the third step, a fresh workbench session can start with "
            "a clean slate by re-running `00_setup.ipynb`.\n"
            "\n"
            "**Safety.** Step 2 is irreversible. `VERITY_ALLOW_PURGE=1` "
            "must be set in the Verity process environment — for local "
            "dev this is baked into `docker-compose.yml`. Without it, the "
            "API returns 400 and no rows are touched.\n"
            "\n"
            "**Note on decision attribution.** Decisions triggered through "
            "the REST runtime endpoints are currently tagged with the "
            "server's `application='default'` (because the API host's "
            "Verity client has that identity). Those decisions are NOT "
            "caught by this app's activity purge. To remove them, use "
            "Verity's admin UI or a direct SQL delete.\n"
        ),
        md(
            "## Prerequisites\n"
            "\n"
            "The `ds_workbench` application must be registered (run "
            "`00_setup.ipynb` once first). Nothing else.\n"
        ),
        code(BOOTSTRAP + "\ninject_style()\nv = VerityAPI(application='ds_workbench')"),
        md(
            "## Preview activity\n"
            "\n"
            "Check what we're about to delete. If all counts are zero, "
            "step 2 (purge) is effectively a no-op but safe to run "
            "anyway — it will just return zero deletes.\n"
        ),
        code(
            "try:\n"
            "    activity = v.get_app_activity()\n"
            "    app = activity['application']\n"
            "except VerityAPIError as exc:\n"
            "    if exc.status == 404:\n"
            "        print('ds_workbench is not registered — nothing to clean up.')\n"
            "        raise SystemExit(0)\n"
            "    raise\n"
            "\n"
            "render_cards([\n"
            "    ('Decisions',           activity['decision_count'],           'to be deleted'),\n"
            "    ('Overrides',           activity['override_count'],           'to be deleted'),\n"
            "    ('Execution contexts',  activity['execution_context_count'],  'to be deleted'),\n"
            "    ('Entity mappings',     activity['entity_mapping_count'],     'survive purge, removed at unregister'),\n"
            "])"
        ),
        md(
            "## Execute — Step 1: purge activity\n"
            "\n"
            "`DELETE /api/v1/applications/ds_workbench/activity` — wipes "
            "decisions, overrides, and execution contexts in one "
            "transactional call (override_log → agent_decision_log → "
            "execution_context, in that order, to respect FK constraints). "
            "Guarded by `VERITY_ALLOW_PURGE=1` in the Verity container.\n"
        ),
        code(
            "try:\n"
            "    purge_result = v.purge_app_activity()\n"
            "    print('Purge result:', purge_result)\n"
            "except VerityAPIError as exc:\n"
            "    print(f'Purge blocked (status={exc.status}):', exc.detail)"
        ),
        md(
            "## Execute — Step 2: unregister the application\n"
            "\n"
            "Now that activity is clear, `DELETE /api/v1/applications/ds_workbench` "
            "drops the entity mappings and the application row. If "
            "activity still remained (purge skipped or blocked), the "
            "`execution_context` FK would reject this delete and the "
            "API would surface a clear 409 with a hint to purge first.\n"
        ),
        code(
            "try:\n"
            "    result = v.unregister_application()\n"
            "    print('Unregister result:', result)\n"
            "except VerityAPIError as exc:\n"
            "    print(f'Unregister failed (status={exc.status}):', exc.detail)"
        ),
        md(
            "## Review results\n"
            "\n"
            "Confirm the app is gone and the catalog is back to its "
            "pre-workbench state.\n"
        ),
        code(
            "try:\n"
            "    v.get_application('ds_workbench')\n"
            "    print('ds_workbench still exists — unregister did not complete.')\n"
            "except VerityAPIError as exc:\n"
            "    if exc.status == 404:\n"
            "        print('Confirmed: ds_workbench is gone.')\n"
            "    else:\n"
            "        raise"
        ),
        code(
            "render_list(\n"
            "    v.list_applications(),\n"
            "    columns=[('name','Name'), ('display_name','Display'), ('description','Description')],\n"
            "    title='Remaining applications',\n"
            ")"
        ),
        md(
            "---\n"
            "\n"
            "Cleanup complete. Re-run `00_setup.ipynb` at any time to "
            "start a fresh workbench session.\n"
        ),
    ]
    return nb


# ══════════════════════════════════════════════════════════════
# runtime/01 — run an agent
# ══════════════════════════════════════════════════════════════

def build_runtime_run_agent_notebook() -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md(
            "# runtime/01 — Run an agent\n"
            "\n"
            "## What this demonstrates\n"
            "\n"
            "End-to-end invocation of a registered agent through the "
            "runtime endpoint: `POST /api/v1/runtime/agents/{name}/run`. "
            "Verity resolves the agent's champion config, composes the "
            "prompts, calls the configured LLM, handles tool-call turns, "
            "and writes a full decision-log row to the database. The "
            "API returns the resulting `ExecutionResult` synchronously.\n"
            "\n"
            "**Verity capabilities exercised**\n"
            "\n"
            "- Config resolution on the server (no client-side pinning).\n"
            "- Real Anthropic LLM call via the configured inference_config.\n"
            "- Tool authorization enforcement (agents can only call tools "
            "  their version is authorized for).\n"
            "- Structured decision-log write with message_history, "
            "  tool_calls, token usage, and duration.\n"
            "\n"
            "**A note on cost.** This notebook makes a real Anthropic API "
            "call. The appetite_agent used below is configured against "
            "`claude-sonnet-4` — a few thousand input tokens per run. "
            "Monitor your Anthropic dashboard if you re-run aggressively.\n"
            "\n"
            "**A note on tools.** The UW business-logic tools "
            "(`get_underwriting_guidelines`, `get_submission_context`) "
            "are registered as Python callables in the UW demo process — "
            "not in the Verity standalone process that serves the REST "
            "API. So when we invoke `appetite_agent` from here, the "
            "agent's tool calls are attempted but the implementations "
            "aren't registered, and the agent returns a graceful "
            "explanation. That's expected — it demonstrates that Verity "
            "cleanly separates governance (the registry, prompts, tool "
            "authorizations) from implementation (where the Python code "
            "actually lives).\n"
        ),
        md(
            "## Prerequisites\n"
            "\n"
            "- `ds_workbench` application registered (run `00_setup.ipynb`).\n"
            "- `appetite_agent` seeded with a champion version (default in "
            "  the project's seed data — no action needed).\n"
        ),
        code(BOOTSTRAP + "\ninject_style()\nv = VerityAPI(application='ds_workbench')"),
        code(
            "# Confirm the agent exists with a champion we can exercise.\n"
            "config = v.get_agent_config('appetite_agent')\n"
            "render_detail(\n"
            "    'appetite_agent',\n"
            "    subtitle=f\"v{config['version_label']}\",\n"
            "    header_badges=[\n"
            "        (config.get('lifecycle_state','?'), config.get('lifecycle_state','')),\n"
            "        (config.get('materiality_tier','?'), config.get('materiality_tier','')),\n"
            "    ],\n"
            "    sections=[\n"
            "        {'title':'Inference config','fields':[\n"
            "            ('Model',       config['inference_config'].get('model_name')),\n"
            "            ('Temperature', config['inference_config'].get('temperature')),\n"
            "            ('Max tokens',  config['inference_config'].get('max_tokens')),\n"
            "        ]},\n"
            "        {'title':f\"Tools authorized ({len(config.get('tools') or [])})\",\n"
            "         'table':{\n"
            "             'columns':[('tool_name','Tool'), ('transport','Transport','neutral')],\n"
            "             'rows': config.get('tools') or [],\n"
            "         }},\n"
            "    ],\n"
            ")"
        ),
        md(
            "## Execute\n"
            "\n"
            "Run the agent with a realistic submission context. The call "
            "returns synchronously when the agent has finished its "
            "agentic loop (all tool turns complete) — which for this "
            "run typically takes 5–15 seconds of wall time depending on "
            "how many tool attempts the agent makes.\n"
        ),
        code(
            "# A realistic UW submission context — the agent's prompt\n"
            "# templates substitute these values into {{producer_name}},\n"
            "# {{lob}}, {{premium_estimate}}, etc.\n"
            "context = {\n"
            "    'submission_id':   'notebook-smoke-001',\n"
            "    'producer_name':   'Acme Specialty Brokers',\n"
            "    'insured_name':    'Skyline Tech Co.',\n"
            "    'lob':             'general_liability',\n"
            "    'industry':        'software',\n"
            "    'effective_date':  '2026-06-01',\n"
            "    'premium_estimate': 45000,\n"
            "}\n"
            "result = v.run_agent('appetite_agent', context=context)\n"
            "print(f\"decision_log_id : {result['decision_log_id']}\")\n"
            "print(f\"status          : {result['status']}\")\n"
            "print(f\"tool_calls      : {len(result.get('tool_calls') or [])}\")\n"
            "print(f\"input tokens    : {result['input_tokens']}\")\n"
            "print(f\"output tokens   : {result['output_tokens']}\")\n"
            "print(f\"duration_ms     : {result['duration_ms']}\")"
        ),
        md(
            "## Review results\n"
            "\n"
            "Two views of the same run:\n"
            "\n"
            "1. The `ExecutionResult` summary returned by the API call.\n"
            "2. The full decision-log row Verity persisted — fetched via "
            "   `GET /api/v1/decisions/{id}` using the id we just got.\n"
        ),
        code(
            "# Short summary from the execution result.\n"
            "render_detail(\n"
            "    'Execution result',\n"
            "    subtitle=result['decision_log_id'],\n"
            "    header_badges=[\n"
            "        (result['status'], result['status']),\n"
            "        (result['entity_type'], result['entity_type']),\n"
            "    ],\n"
            "    sections=[\n"
            "        {'title':'Identity','fields':[\n"
            "            ('Entity',  f\"{result['entity_type']} / {result['entity_name']}\"),\n"
            "            ('Version', result['version_label']),\n"
            "            ('Status',  result['status']),\n"
            "        ]},\n"
            "        {'title':'Output','fields':[\n"
            "            ('Summary', result.get('output_summary') or '(empty)'),\n"
            "        ]},\n"
            "        {'title':'Timing & usage','fields':[\n"
            "            ('Duration (ms)',  result['duration_ms']),\n"
            "            ('Input tokens',   result['input_tokens']),\n"
            "            ('Output tokens',  result['output_tokens']),\n"
            "        ]},\n"
            "        {'title':f\"Tool calls attempted ({len(result.get('tool_calls') or [])})\",\n"
            "         'table':{\n"
            "             'columns':[\n"
            "                 ('tool_name','Tool'),\n"
            "                 ('transport','Transport','neutral'),\n"
            "                 ('status','Status','*'),\n"
            "             ],\n"
            "             'rows': result.get('tool_calls') or [],\n"
            "         }},\n"
            "    ],\n"
            ")"
        ),
        code(
            "# Full persisted decision row — what compliance reviewers see\n"
            "# in the admin UI. Carries message_history for audit replay.\n"
            "decision = v.get_decision(result['decision_log_id'])\n"
            "render_detail(\n"
            "    f\"Decision — {decision.get('entity_name','?')}\",\n"
            "    subtitle=str(decision.get('id','')),\n"
            "    header_badges=[\n"
            "        (decision.get('status','?'), decision.get('status','')),\n"
            "        (decision.get('entity_type','?'), decision.get('entity_type','')),\n"
            "    ],\n"
            "    sections=[\n"
            "        {'title':'Identity','fields':[\n"
            "            ('Entity',      f\"{decision.get('entity_type')} / {decision.get('entity_name')}\"),\n"
            "            ('Version',     decision.get('version_label')),\n"
            "            ('Channel',     decision.get('channel')),\n"
            "            ('Application', decision.get('application')),\n"
            "            ('Created',     decision.get('created_at')),\n"
            "        ]},\n"
            "        {'title':'Timing & usage','fields':[\n"
            "            ('Duration (ms)', decision.get('duration_ms')),\n"
            "            ('Input tokens',  decision.get('input_tokens')),\n"
            "            ('Output tokens', decision.get('output_tokens')),\n"
            "            ('Model',         decision.get('model_used')),\n"
            "        ]},\n"
            "        {'title':f\"Tool calls ({len(decision.get('tool_calls_made') or [])})\",\n"
            "         'table':{\n"
            "             'columns':[\n"
            "                 ('tool_name','Tool'),\n"
            "                 ('transport','Transport','neutral'),\n"
            "                 ('mcp_server_name','MCP server'),\n"
            "                 ('status','Status','*'),\n"
            "             ],\n"
            "             'rows': decision.get('tool_calls_made') or [],\n"
            "         }},\n"
            "    ],\n"
            ")"
        ),
        md(
            "---\n"
            "\n"
            "The decision row is now permanent in the audit trail. "
            "Its id is visible at `/admin/decisions/{id}` in the admin "
            "UI, and can be queried via "
            "`GET /api/v1/decisions/{id}` from any external caller. "
            "Move on to **`compliance/01_decision_log_walkthrough.ipynb`** "
            "to explore the decision-log surface more broadly.\n"
        ),
    ]
    return nb


# ══════════════════════════════════════════════════════════════
# compliance/01 — decision log walkthrough
# ══════════════════════════════════════════════════════════════

def build_compliance_decision_log_notebook() -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md(
            "# compliance/01 — Decision log walkthrough\n"
            "\n"
            "## What this demonstrates\n"
            "\n"
            "The three main audit views Verity exposes:\n"
            "\n"
            "- **Chronological feed.** `GET /api/v1/decisions?limit=&offset=` — "
            "  paginated list, most recent first. Shows what the system "
            "  has been doing.\n"
            "- **Per-decision detail.** `GET /api/v1/decisions/{id}` — full "
            "  row including `message_history`, `tool_calls_made`, "
            "  `inference_config_snapshot`, `risk_factors`, tokens, and "
            "  duration. This is the level compliance reviewers work at.\n"
            "- **Trail by pipeline run.** `GET /api/v1/audit-trail/run/{run_id}` "
            "  — every decision produced by a single pipeline invocation, "
            "  in causal order. Includes sub-agent delegations (decisions "
            "  linked to a parent via `parent_decision_id`).\n"
            "\n"
            "Plus a simple Graphviz tree showing how sub-agent delegations "
            "nest under their parent decisions when the run included any.\n"
            "\n"
            "**Verity capabilities exercised**\n"
            "\n"
            "- Immutable decision log: every LLM turn and tool call is "
            "  captured in a structured row keyed by `decision_log_id`.\n"
            "- Parent/child decision hierarchy (`parent_decision_id`, "
            "  `decision_depth`) that records sub-agent delegation "
            "  relationships.\n"
            "- Execution-context threading: decisions can be looked up by "
            "  the business-level `execution_context_id` as well.\n"
        ),
        md(
            "## Prerequisites\n"
            "\n"
            "- Some decisions already exist (the seed data ships ~24 from "
            "  the UW demo's initial runs; `runtime/01` adds more).\n"
        ),
        code(BOOTSTRAP + "\ninject_style()\nv = VerityAPI(application='ds_workbench')"),
        md(
            "## Execute — chronological feed\n"
            "\n"
            "Pull the 10 most recent decisions across all applications.\n"
        ),
        code(
            "decisions = v.list_decisions(limit=10)\n"
            "render_list(\n"
            "    decisions,\n"
            "    columns=[\n"
            "        ('created_at','Created'),\n"
            "        ('entity_type','Kind','*'),\n"
            "        ('entity_name','Entity'),\n"
            "        ('status','Status','*'),\n"
            "        ('duration_ms','ms'),\n"
            "        ('input_tokens','In tok'),\n"
            "        ('output_tokens','Out tok'),\n"
            "        ('application','App'),\n"
            "    ],\n"
            "    title=f\"Latest {len(decisions)} decisions\",\n"
            "    description='Sorted newest first. Click through to the admin UI for richer filters.',\n"
            "    empty_message='No decisions yet — run `runtime/01_run_agent.ipynb` first.',\n"
            ")"
        ),
        md(
            "## Execute — detail of one decision\n"
            "\n"
            "Pick the first decision from the feed and fetch its full "
            "detail row, including `message_history` (Claude Messages API "
            "conversation) and `tool_calls_made` (the agentic tool turns).\n"
        ),
        code(
            "assert decisions, 'No decisions to drill into — run the runtime notebook first.'\n"
            "first_id = decisions[0]['id']\n"
            "detail = v.get_decision(first_id)\n"
            "\n"
            "# Convert the raw message_history into a preview-sized string\n"
            "# so the detail card stays readable. For full conversations,\n"
            "# use decision_detail page in the admin UI.\n"
            "msgs = detail.get('message_history') or []\n"
            "msg_preview = '\\n\\n'.join(\n"
            "    f\"[{m.get('role','?')}] \" + (\n"
            "        (m['content'][:200] + ('…' if len(m['content']) > 200 else ''))\n"
            "        if isinstance(m.get('content'), str) else '[structured content]'\n"
            "    )\n"
            "    for m in msgs[:6]\n"
            ")\n"
            "\n"
            "render_detail(\n"
            "    f\"Decision — {detail.get('entity_name','?')}\",\n"
            "    subtitle=str(detail['id']),\n"
            "    header_badges=[\n"
            "        (detail.get('status','?'), detail.get('status','')),\n"
            "        (detail.get('entity_type','?'), detail.get('entity_type','')),\n"
            "    ],\n"
            "    sections=[\n"
            "        {'title':'Identity','fields':[\n"
            "            ('Entity',      f\"{detail.get('entity_type')} / {detail.get('entity_name')}\"),\n"
            "            ('Version',     detail.get('version_label')),\n"
            "            ('Channel',     detail.get('channel')),\n"
            "            ('Application', detail.get('application')),\n"
            "            ('Created',     detail.get('created_at')),\n"
            "        ]},\n"
            "        {'title':'Timing & usage','fields':[\n"
            "            ('Duration (ms)', detail.get('duration_ms')),\n"
            "            ('Input tokens',  detail.get('input_tokens')),\n"
            "            ('Output tokens', detail.get('output_tokens')),\n"
            "            ('Model',         detail.get('model_used')),\n"
            "        ]},\n"
            "        {'title':f\"Tool calls made ({len(detail.get('tool_calls_made') or [])})\",\n"
            "         'table':{\n"
            "             'columns':[\n"
            "                 ('tool_name','Tool'),\n"
            "                 ('transport','Transport','neutral'),\n"
            "                 ('mcp_server_name','MCP server'),\n"
            "                 ('status','Status','*'),\n"
            "             ],\n"
            "             'rows': detail.get('tool_calls_made') or [],\n"
            "         }},\n"
            "        {'title':f\"Message history ({len(msgs)} turns)\",\n"
            "         'html': f'<pre style=\"white-space:pre-wrap;font-size:.85rem;color:#4D4D4D;'\n"
            "                 f'background:#F8FAFC;padding:10px;border-radius:4px;\">{msg_preview}</pre>'},\n"
            "    ],\n"
            ")"
        ),
        md(
            "## Review results — trail by pipeline run\n"
            "\n"
            "Find a decision that ran as part of a pipeline (has a "
            "`pipeline_run_id`), then pull the full trail of decisions "
            "from that pipeline invocation.\n"
        ),
        code(
            "# Find a recent decision that was part of a pipeline run.\n"
            "pipelined = next((d for d in decisions if d.get('pipeline_run_id')), None)\n"
            "if pipelined is None:\n"
            "    print('No pipelined decisions found in the recent feed — skipping trail view.')\n"
            "else:\n"
            "    run_id = pipelined['pipeline_run_id']\n"
            "    trail = v.audit_trail_by_run(run_id)\n"
            "    render_list(\n"
            "        trail,\n"
            "        columns=[\n"
            "            ('created_at','Time'),\n"
            "            ('decision_depth','Depth'),\n"
            "            ('entity_type','Kind','*'),\n"
            "            ('entity_name','Entity'),\n"
            "            ('status','Status','*'),\n"
            "            ('duration_ms','ms'),\n"
            "        ],\n"
            "        title=f'Audit trail — pipeline_run {run_id}',\n"
            "        description='Every decision in causal order, including sub-agent delegations.',\n"
            "    )"
        ),
        code(
            "# Optional graphviz view of the parent→child decision tree.\n"
            "# Skips gracefully when we don't have a pipelined trail above.\n"
            "if pipelined is not None:\n"
            "    from utility.visualizations import decision_tree\n"
            "    display(decision_tree(trail, highlight_id=pipelined['id']))"
        ),
        md(
            "---\n"
            "\n"
            "Every view here is read-only — decision rows are immutable "
            "once written. To record a human override of an AI decision, "
            "use `POST /api/v1/overrides`; the override links to the "
            "original `decision_log_id` and is auditable separately.\n"
        ),
    ]
    return nb


# ══════════════════════════════════════════════════════════════
# authoring/01 — register a simple agent
# ══════════════════════════════════════════════════════════════

def build_authoring_register_notebook() -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md(
            "# authoring/01 — Register a simple agent from scratch\n"
            "\n"
            "## What this demonstrates\n"
            "\n"
            "The full agent-authoring flow using the `/api/v1` REST "
            "authoring surface:\n"
            "\n"
            "    POST /api/v1/agents                         # header\n"
            "    POST /api/v1/agents/{name}/versions          # draft v1.0.0\n"
            "    POST /api/v1/prompts                         # prompt header\n"
            "    POST /api/v1/prompts/{name}/versions         # prompt v1.0.0\n"
            "    POST /api/v1/agents/{name}/versions/{id}/prompts  # assignment\n"
            "    POST /api/v1/applications/ds_workbench/entities   # map to our app\n"
            "\n"
            "The new agent stays in `draft` state throughout — no "
            "promotion, so the cleanup cell at the end can simply "
            "`DELETE` it via the draft-delete endpoint and leave the "
            "database exactly as it started.\n"
            "\n"
            "**Verity capabilities exercised**\n"
            "\n"
            "- Header + version entity model (agents are named, versions "
            "  are immutable once promoted).\n"
            "- Automatic `{{variable}}` extraction from prompt content.\n"
            "- Prompt-to-version assignment (many-to-many via "
            "  `entity_prompt_assignment`).\n"
            "- Multi-tenant entity mapping (`application_entity`).\n"
        ),
        md(
            "## Prerequisites\n"
            "\n"
            "- `ds_workbench` application registered (`00_setup.ipynb`).\n"
            "- At least one inference_config exists (the seeded data "
            "  includes several — we pick the first).\n"
        ),
        code(BOOTSTRAP + "\ninject_style()\nv = VerityAPI(application='ds_workbench')"),
        code(
            "# Pick an inference_config to reference. Any registered\n"
            "# config works; we'll use the first one for simplicity.\n"
            "configs = v.call('list_inference_configs')\n"
            "assert configs, 'No inference configs registered — Verity seed likely missing.'\n"
            "cfg = configs[0]\n"
            "print(f\"Using inference_config: {cfg['name']} ({cfg['model_name']})\")\n"
            "INFERENCE_CONFIG_ID = cfg['id']"
        ),
        md(
            "## Execute\n"
            "\n"
            "Six REST calls in order: agent header → agent draft version "
            "→ prompt header → prompt version → prompt assignment → app "
            "mapping.\n"
        ),
        code(
            "# 1) Agent header.\n"
            "AGENT_NAME = 'workbench_demo_agent'\n"
            "# Delete any leftover from a prior run so this notebook is\n"
            "# safe to re-execute.\n"
            "try:\n"
            "    existing_versions = v.list_agent_versions(AGENT_NAME)\n"
            "    for ev in existing_versions:\n"
            "        if ev['lifecycle_state'] == 'draft':\n"
            "            v.call('delete_agent_version',\n"
            "                   path_params={'name': AGENT_NAME, 'version_id': ev['id']})\n"
            "except VerityAPIError:\n"
            "    pass  # agent doesn't exist yet — first run\n"
            "\n"
            "try:\n"
            "    agent_header = v.call('register_agent', json={\n"
            "        'name': AGENT_NAME,\n"
            "        'display_name': 'Workbench Demo Agent',\n"
            "        'description': 'Created from authoring/01 for demo purposes.',\n"
            "        'purpose': 'Demonstrate the Verity authoring REST surface.',\n"
            "        'domain': 'demo',\n"
            "        'materiality_tier': 'low',\n"
            "        'owner_name': 'ds_workbench',\n"
            "        'owner_email': None,\n"
            "        'business_context': None,\n"
            "        'known_limitations': None,\n"
            "        'regulatory_notes': None,\n"
            "    })\n"
            "    print(f\"agent header created: id={agent_header['id']}\")\n"
            "except VerityAPIError as exc:\n"
            "    if exc.status == 400 and 'duplicate key' in str(exc.detail):\n"
            "        # Header already exists from a prior run; look it up.\n"
            "        existing = v.list_agents()\n"
            "        agent_header = next(a for a in existing if a['name'] == AGENT_NAME)\n"
            "        print(f\"agent header reused: id={agent_header['id']}\")\n"
            "    else:\n"
            "        raise"
        ),
        code(
            "# 2) Agent draft version.\n"
            "ver = v.call('register_agent_version', path_params={'name': AGENT_NAME}, json={\n"
            "    'major_version': 1, 'minor_version': 0, 'patch_version': 0,\n"
            "    'lifecycle_state': 'draft',\n"
            "    'channel': 'development',\n"
            "    'inference_config_id': INFERENCE_CONFIG_ID,\n"
            "    'output_schema': {'type':'object','properties':{'answer':{'type':'string'}}},\n"
            "    'authority_thresholds': {},\n"
            "    'mock_mode_enabled': False,\n"
            "    'decision_log_detail': 'full',\n"
            "    'developer_name': 'ds_workbench',\n"
            "    'change_summary': 'Initial version — demo notebook.',\n"
            "    'change_type': 'initial',\n"
            "})\n"
            "AGENT_VERSION_ID = ver['id']\n"
            "print(f\"agent v1.0.0 (draft) id={AGENT_VERSION_ID}\")"
        ),
        code(
            "# 3) Prompt header.\n"
            "PROMPT_NAME = 'workbench_demo_system_prompt'\n"
            "try:\n"
            "    prompt_header = v.call('register_prompt', json={\n"
            "        'name': PROMPT_NAME,\n"
            "        'display_name': 'Workbench demo system prompt',\n"
            "        'description': 'System message for the workbench demo agent.',\n"
            "        'primary_entity_type': 'agent',\n"
            "        'primary_entity_id':   agent_header['id'],\n"
            "    })\n"
            "    print(f\"prompt header created: id={prompt_header['id']}\")\n"
            "except VerityAPIError as exc:\n"
            "    if exc.status == 400 and 'duplicate key' in str(exc.detail):\n"
            "        prompt_header = next(p for p in v.call('list_prompts') if p['name'] == PROMPT_NAME)\n"
            "        print(f\"prompt header reused: id={prompt_header['id']}\")\n"
            "    else:\n"
            "        raise\n"
            "\n"
            "# 4) Prompt draft version (template variable {{audience}} will\n"
            "# be auto-extracted and stored in template_variables).\n"
            "pv = v.call('register_prompt_version', path_params={'name': PROMPT_NAME}, json={\n"
            "    'major_version': 1, 'minor_version': 0, 'patch_version': 0,\n"
            "    'content': 'You are a friendly assistant. Tailor your responses to the {{audience}}.',\n"
            "    'api_role': 'system',\n"
            "    'governance_tier': 'behavioural',\n"
            "    'lifecycle_state': 'draft',\n"
            "    'change_summary': 'initial',\n"
            "    'sensitivity_level': 'low',\n"
            "    'author_name': 'ds_workbench',\n"
            "})\n"
            "PROMPT_VERSION_ID = pv['id']\n"
            "print(f\"prompt v1.0.0 (draft) id={PROMPT_VERSION_ID}\")"
        ),
        code(
            "# 5) Assign the prompt to the agent version.\n"
            "assignment = v.call(\n"
            "    'assign_prompt_to_agent',\n"
            "    path_params={'name': AGENT_NAME, 'version_id': AGENT_VERSION_ID},\n"
            "    json={\n"
            "        'prompt_version_id': PROMPT_VERSION_ID,\n"
            "        'api_role': 'system',\n"
            "        'governance_tier': 'behavioural',\n"
            "        'execution_order': 1,\n"
            "        'is_required': True,\n"
            "        'condition_logic': None,\n"
            "    },\n"
            ")\n"
            "print(f\"prompt assignment id={assignment['id']}\")\n"
            "\n"
            "# 6) Map the agent to the workbench application so our\n"
            "# cleanup notebook can scope it correctly.\n"
            "try:\n"
            "    mapping = v.map_entity(entity_type='agent', entity_id=agent_header['id'])\n"
            "    print(f\"application_entity mapping id={mapping['id']}\")\n"
            "except VerityAPIError as exc:\n"
            "    # POST application_entity is ON CONFLICT DO NOTHING, but\n"
            "    # the API wrapper treats empty rows differently; ignore.\n"
            "    print(f\"mapping skipped or already present: {exc.detail}\")"
        ),
        md(
            "## Review results\n"
            "\n"
            "Resolve the full config for our new draft agent and render "
            "it the same way the admin UI would — the prompt assignment "
            "should flow through automatically.\n"
        ),
        code(
            "config = v.get_agent_config(AGENT_NAME, version_id=AGENT_VERSION_ID)\n"
            "render_detail(\n"
            "    AGENT_NAME,\n"
            "    subtitle=f\"v{config['version_label']}\",\n"
            "    header_badges=[\n"
            "        (config.get('lifecycle_state','?'), config.get('lifecycle_state','')),\n"
            "        (config.get('materiality_tier','?'), config.get('materiality_tier','')),\n"
            "    ],\n"
            "    sections=[\n"
            "        {'title':'Inference config','fields':[\n"
            "            ('Name',        config['inference_config'].get('name')),\n"
            "            ('Model',       config['inference_config'].get('model_name')),\n"
            "            ('Temperature', config['inference_config'].get('temperature')),\n"
            "        ]},\n"
            "        {'title':f\"Prompts ({len(config.get('prompts') or [])})\",\n"
            "         'table':{\n"
            "             'columns':[\n"
            "                 ('prompt_name','Prompt'),\n"
            "                 ('version_number','Version'),\n"
            "                 ('api_role','Role','neutral'),\n"
            "                 ('governance_tier','Tier'),\n"
            "             ],\n"
            "             'rows': config.get('prompts') or [],\n"
            "         }},\n"
            "    ],\n"
            ")"
        ),
        code(
            "# Version lineage — shows the 1.0.0 draft hanging off the\n"
            "# agent header with nothing promoted above it yet. As the\n"
            "# author iterates (clone → PATCH → promote), more nodes\n"
            "# and clone-edges appear.\n"
            "from utility.visualizations import version_lineage_graph\n"
            "versions = v.list_agent_versions(AGENT_NAME)\n"
            "version_lineage_graph(versions)"
        ),
        md(
            "## Cleanup\n"
            "\n"
            "Delete the draft version + entity mapping so this notebook "
            "is idempotent. The agent header row remains, which is fine — "
            "re-running the notebook will skip the duplicate-key error "
            "and reuse it.\n"
        ),
        code(
            "try:\n"
            "    v.call('delete_agent_version',\n"
            "           path_params={'name': AGENT_NAME, 'version_id': AGENT_VERSION_ID})\n"
            "    print('draft version deleted')\n"
            "except VerityAPIError as exc:\n"
            "    print(f'draft delete failed: {exc.detail}')\n"
            "\n"
            "try:\n"
            "    v.call('unmap_entity',\n"
            "           path_params={'name': 'ds_workbench',\n"
            "                        'entity_type': 'agent',\n"
            "                        'entity_id': agent_header['id']})\n"
            "    print('app entity mapping removed')\n"
            "except VerityAPIError as exc:\n"
            "    if exc.status == 404:\n"
            "        print('mapping was already gone')\n"
            "    else:\n"
            "        raise"
        ),
        md(
            "---\n"
            "\n"
            "Note: `delete_prompt_version` is only valid on drafts, but "
            "our draft prompt is still assigned to the agent (if the "
            "agent draft is gone first, the prompt is orphaned and can "
            "be removed separately). Re-running this notebook handles "
            "the reuse path automatically.\n"
            "\n"
            "Move on to **`authoring/02_clone_and_edit_draft.ipynb`** to "
            "see the clone-and-edit workflow against an existing champion.\n"
        ),
    ]
    return nb


# ══════════════════════════════════════════════════════════════
# authoring/02 — clone and edit a draft
# ══════════════════════════════════════════════════════════════

def build_authoring_clone_notebook() -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md(
            "# authoring/02 — Clone an existing agent version and edit the draft\n"
            "\n"
            "## What this demonstrates\n"
            "\n"
            "The clone-and-edit workflow — the right way to make a "
            "governed change to a promoted agent. Instead of mutating "
            "the existing champion (which would break the audit trail), "
            "Verity lets you:\n"
            "\n"
            "    GET   /api/v1/agents/{name}/config?version_id=<champion>\n"
            "    POST  /api/v1/agents/{name}/versions/{champion_id}/clone\n"
            "      → new draft with copied prompts + tools + delegations\n"
            "          plus cloned_from_version_id pointing back at the source\n"
            "    PATCH /api/v1/agents/{name}/versions/{draft_id}\n"
            "      → edit the draft in place (only valid while lifecycle_state='draft')\n"
            "\n"
            "The immutability contract: any version that has moved past "
            "`draft` (`candidate` / `staging` / `shadow` / `challenger` / "
            "`champion` / `deprecated`) is permanently frozen. PATCH on "
            "anything else returns `409 Conflict` with a message telling "
            "you to clone instead.\n"
            "\n"
            "**Verity capabilities exercised**\n"
            "\n"
            "- Transactional clone: one call produces the new version row "
            "  and all its prompt/tool/delegation associations.\n"
            "- Clone provenance via the `cloned_from_version_id` column "
            "  — visible in the lineage graph below.\n"
            "- Draft-only PATCH (immutability for promoted versions).\n"
            "- Draft delete for clean rollback of the demo.\n"
        ),
        md(
            "## Prerequisites\n"
            "\n"
            "- `ds_workbench` application registered (`00_setup.ipynb`).\n"
            "- `triage_agent` has a champion version (default seed).\n"
        ),
        code(BOOTSTRAP + "\ninject_style()\nv = VerityAPI(application='ds_workbench')"),
        code(
            "# Find the current champion version of triage_agent and its\n"
            "# lineage context.\n"
            "versions = v.list_agent_versions('triage_agent')\n"
            "champion = next((ver for ver in versions if ver['lifecycle_state'] == 'champion'), None)\n"
            "assert champion is not None, 'triage_agent has no champion version.'\n"
            "CHAMPION_ID = champion['id']\n"
            "print(f\"champion: v{champion['version_label']}  id={CHAMPION_ID}\")\n"
            "\n"
            "# Pick a version label that isn't already taken.\n"
            "taken = {vr['version_label'] for vr in versions}\n"
            "DRAFT_LABEL = next(\n"
            "    f\"99.{minor}.0\"\n"
            "    for minor in range(100)\n"
            "    if f\"99.{minor}.0\" not in taken\n"
            ")\n"
            "print(f\"will clone into draft v{DRAFT_LABEL}\")"
        ),
        md(
            "## Execute — step 1: clone the champion into a new draft\n"
            "\n"
            "One API call. Copies the version row + every prompt "
            "assignment + every tool authorization + every delegation "
            "row onto the new draft, and sets `cloned_from_version_id` "
            "so the provenance is visible.\n"
        ),
        code(
            "clone = v.clone_agent_version(\n"
            "    name='triage_agent',\n"
            "    source_version_id=CHAMPION_ID,\n"
            "    new_version_label=DRAFT_LABEL,\n"
            "    change_summary='authoring/02 clone demo — tweak temperature',\n"
            "    developer_name='ds_workbench',\n"
            ")\n"
            "DRAFT_ID = clone['id']\n"
            "print(f\"draft v{clone['version_label']}  id={DRAFT_ID}\")"
        ),
        md(
            "## Execute — step 2: PATCH the draft\n"
            "\n"
            "Modify something mutable on the draft. Here we swap the "
            "inference_config — typical reason for a clone is to try a "
            "cheaper or faster config against the existing prompt and "
            "tool set. Any field omitted from the PATCH body is left "
            "untouched (SQL COALESCE pattern).\n"
        ),
        code(
            "# Grab another inference_config to swap to — anything\n"
            "# different from the current one.\n"
            "configs = v.call('list_inference_configs')\n"
            "current_cfg_id = champion['inference_config_id']\n"
            "alt = next((c for c in configs if c['id'] != current_cfg_id), None)\n"
            "assert alt is not None, 'Need at least 2 inference_configs registered.'\n"
            "print(f\"swapping inference_config: {alt['name']} ({alt['model_name']})\")\n"
            "\n"
            "patched = v.call(\n"
            "    'update_agent_version',\n"
            "    path_params={'name': 'triage_agent', 'version_id': DRAFT_ID},\n"
            "    json={\n"
            "        'inference_config_id': alt['id'],\n"
            "        'change_summary': f\"swap inference_config to {alt['name']}\",\n"
            "    },\n"
            ")\n"
            "print(f\"PATCH result: {patched}\")"
        ),
        md(
            "## Execute — demonstrate the immutability guard\n"
            "\n"
            "A PATCH against the champion (or anything non-draft) "
            "returns 409 Conflict. That's the contract that makes "
            "decision-log replay meaningful: past decisions always "
            "refer to a stable configuration.\n"
        ),
        code(
            "try:\n"
            "    v.call(\n"
            "        'update_agent_version',\n"
            "        path_params={'name': 'triage_agent', 'version_id': CHAMPION_ID},\n"
            "        json={'change_summary': 'this should fail'},\n"
            "    )\n"
            "    print('unexpected: PATCH on champion succeeded!')\n"
            "except VerityAPIError as exc:\n"
            "    print(f\"expected {exc.status} — detail: {exc.detail}\")"
        ),
        md(
            "## Review results\n"
            "\n"
            "The version lineage graph shows the new draft hanging off "
            "the champion via the clone edge (dashed purple). The "
            "resolved config confirms our PATCH landed on the draft — "
            "its inference config is the one we swapped in, while the "
            "champion still uses the original.\n"
        ),
        code(
            "from utility.visualizations import version_lineage_graph\n"
            "version_lineage_graph(v.list_agent_versions('triage_agent'))"
        ),
        code(
            "draft_config = v.get_agent_config('triage_agent', version_id=DRAFT_ID)\n"
            "champ_config = v.get_agent_config('triage_agent', version_id=CHAMPION_ID)\n"
            "\n"
            "render_list(\n"
            "    [\n"
            "        {'field':'version_label',\n"
            "         'champion': champ_config.get('version_label'),\n"
            "         'draft':    draft_config.get('version_label')},\n"
            "        {'field':'lifecycle_state',\n"
            "         'champion': champ_config.get('lifecycle_state'),\n"
            "         'draft':    draft_config.get('lifecycle_state')},\n"
            "        {'field':'inference_config.name',\n"
            "         'champion': champ_config['inference_config'].get('name'),\n"
            "         'draft':    draft_config['inference_config'].get('name')},\n"
            "        {'field':'inference_config.model',\n"
            "         'champion': champ_config['inference_config'].get('model_name'),\n"
            "         'draft':    draft_config['inference_config'].get('model_name')},\n"
            "        {'field':'prompts.count',\n"
            "         'champion': len(champ_config.get('prompts') or []),\n"
            "         'draft':    len(draft_config.get('prompts') or [])},\n"
            "        {'field':'tools.count',\n"
            "         'champion': len(champ_config.get('tools') or []),\n"
            "         'draft':    len(draft_config.get('tools') or [])},\n"
            "    ],\n"
            "    columns=[\n"
            "        ('field','Field'),\n"
            "        ('champion','Champion'),\n"
            "        ('draft','Draft (ours)'),\n"
            "    ],\n"
            "    title='Champion vs draft — what changed',\n"
            "    description='Clone copied prompts and tools; only the inference_config differs.',\n"
            ")"
        ),
        md(
            "## Cleanup\n"
            "\n"
            "Remove the draft so the notebook is safe to re-run and the "
            "database ends up exactly where it started.\n"
        ),
        code(
            "try:\n"
            "    v.call('delete_agent_version',\n"
            "           path_params={'name': 'triage_agent', 'version_id': DRAFT_ID})\n"
            "    print(f'draft v{DRAFT_LABEL} deleted')\n"
            "except VerityAPIError as exc:\n"
            "    print(f'draft delete failed: {exc.detail}')"
        ),
        md(
            "---\n"
            "\n"
            "To see the draft promoted (instead of deleted) into "
            "`candidate` and through the rest of the 7-state lifecycle, "
            "use the promote / rollback endpoints covered in "
            "`lifecycle/01_promote_and_rollback.ipynb`.\n"
        ),
    ]
    return nb


# ══════════════════════════════════════════════════════════════
# Writer + main
# ══════════════════════════════════════════════════════════════

def write_notebook(nb: nbf.NotebookNode, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(nbf.writes(nb), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    write_notebook(build_setup_notebook(),              NB_DIR / "00_setup.ipynb")
    write_notebook(build_cleanup_notebook(),            NB_DIR / "99_cleanup.ipynb")
    write_notebook(build_runtime_run_agent_notebook(),  NB_DIR / "notebooks/runtime/01_run_agent.ipynb")
    write_notebook(build_compliance_decision_log_notebook(), NB_DIR / "notebooks/compliance/01_decision_log_walkthrough.ipynb")
    write_notebook(build_authoring_register_notebook(), NB_DIR / "notebooks/authoring/01_register_simple_agent.ipynb")
    write_notebook(build_authoring_clone_notebook(),    NB_DIR / "notebooks/authoring/02_clone_and_edit_draft.ipynb")
