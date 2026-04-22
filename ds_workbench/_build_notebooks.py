"""Build the top-level setup and cleanup notebooks.

Run inside the ds_workbench container:
    docker exec ds_workbench python /home/jovyan/work/_build_notebooks.py

This emits 00_setup.ipynb and 99_cleanup.ipynb as valid nbformat-v4
JSON. Generated programmatically so notebook structure stays in sync
with the helpers — regenerate whenever the utility signatures change.

Each notebook follows the four-section pattern the plan calls for:
    1. What this demonstrates (markdown)
    2. Prerequisites (markdown + code)
    3. Execute (markdown + code)
    4. Review results (markdown + code with visualizations)
"""

from pathlib import Path

import nbformat as nbf


NB_DIR = Path("/home/jovyan/work")
APP_NAME = "ds_workbench"


def md(text: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(text)


def code(src: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(src)


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
        code(
            "# Make `utility` importable regardless of which folder the\n"
            "# kernel is started in (Docker starts at /home/jovyan/work;\n"
            "# VSCode may start at the repo root).\n"
            "import os, sys\n"
            "HERE = os.getcwd()\n"
            "if os.path.basename(HERE) != 'ds_workbench':\n"
            "    for candidate in (os.path.dirname(HERE), '/home/jovyan/work'):\n"
            "        if os.path.isdir(os.path.join(candidate, 'utility')):\n"
            "            sys.path.insert(0, candidate); break\n"
            "\n"
            "from utility.verity import VerityAPI, VerityAPIError\n"
            "from utility.html import inject_style, badge, render_list, render_detail, render_cards\n"
            "\n"
            "inject_style()   # apply Verity-UI styles to all subsequent cell outputs"
        ),
        code(
            "# Open a client. VERITY_API_URL env var decides the target;\n"
            "# the default lands on localhost for VSCode-on-host users.\n"
            "v = VerityAPI(application='ds_workbench')\n"
            "print(f'base_url           = {v.base_url}')\n"
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
        ),
        md(
            "## Prerequisites\n"
            "\n"
            "The `ds_workbench` application must be registered (run "
            "`00_setup.ipynb` once first). Nothing else.\n"
        ),
        code(
            "import os, sys\n"
            "HERE = os.getcwd()\n"
            "if os.path.basename(HERE) != 'ds_workbench':\n"
            "    for candidate in (os.path.dirname(HERE), '/home/jovyan/work'):\n"
            "        if os.path.isdir(os.path.join(candidate, 'utility')):\n"
            "            sys.path.insert(0, candidate); break\n"
            "\n"
            "from utility.verity import VerityAPI, VerityAPIError\n"
            "from utility.html import inject_style, badge, render_list, render_detail, render_cards\n"
            "\n"
            "inject_style()\n"
            "v = VerityAPI(application='ds_workbench')"
        ),
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


def write_notebook(nb: nbf.NotebookNode, path: Path) -> None:
    path.write_text(nbf.writes(nb), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    write_notebook(build_setup_notebook(),   NB_DIR / "00_setup.ipynb")
    write_notebook(build_cleanup_notebook(), NB_DIR / "99_cleanup.ipynb")
