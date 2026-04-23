# Verity REST API and Data Science Workbench

**Status:** Delivered 2026-04-22. All twelve planned steps landed across ten commits ([b8c58c8](../../../../commit/b8c58c8) → [88432e2](../../../../commit/88432e2) for the API; plus [ec3354c](../../../../commit/ec3354c) for the Docker service, [7e35b84](../../../../commit/7e35b84) for workbench utilities, and [8b1bd8d](../../../../commit/8b1bd8d) for starter notebooks).

The **[As-delivered summary](#as-delivered-summary)** at the end of this document captures the final API surface, workbench structure, and known limitations.

**Companion working copy:** `.claude/plans/where-are-you-stuck-swirling-kurzweil.md` (planning artifact, may be overwritten in future plan sessions). **This file is the canonical project reference.**

---

## 1. Context

### What exists today
- Verity ships a rich Python SDK (the `Verity` class in [verity/src/verity/client/inprocess.py](../../verity/src/verity/client/inprocess.py)) covering governance (registry / lifecycle / reporting / testing) and runtime (execute_agent / execute_task / execute_pipeline) capabilities.
- Verity's web surface today is **Jinja-rendered HTML only** — 30+ admin routes under `/admin/*`. **No JSON REST API.**
- The only consumer, `uw_demo`, imports Verity in-process and shares the Verity container. That's fine for the embedded demo but blocks external integration.

### Why we're adding the API + workbench
1. **Validate Verity as a genuinely external governance platform.** That's the core value proposition for CIO/CTO audiences; the API makes it real.
2. **Enable notebook-driven interactive demos** of every Verity capability. A data-science-style workbench with markdown explainers + code + visualizations is a much better demo experience than clicking through the admin UI, and doubles as a capability-level regression suite.
3. **Establish a clean separation of concerns.** Moving notebooks into their own Docker container that speaks only HTTP proves Verity's SDK and persistence are process-boundary-clean.

### Intended outcome
- JupyterLab runs as `ds-workbench` service. A developer or demo-presenter opens a notebook (in Docker *or* VSCode), reads the capability explainer, runs a few cells, and sees tables / charts / flow diagrams / relationship graphs.
- A single `00_setup.ipynb` registers the workbench as a Verity application.
- A single `99_cleanup.ipynb` unregisters the application and purges all its activity so runs can start clean.

### Locked design decisions
- **No auth on the initial API.** Bound to the docker network / localhost. Add auth before any production deploy.
- **Sync `httpx.Client`** in notebooks — works identically in Docker Jupyter and VSCode, no event-loop complications.
- **`jupyter/scipy-notebook:latest`** as the base image (ships pandas / numpy / matplotlib). Port `8888`.
- **Notebook tree at repo root under `ds_workbench/`** so VSCode-edit and Docker-run share the same files via bind-mount.
- **Plotly** for interactive charts; **graphviz / networkx** for flow and relationship diagrams.

---

## 2. Part A — Verity JSON REST API

Mounted on the existing Verity FastAPI app at `/api/v1/*`. Thin JSON wrappers over the existing SDK facade. FastAPI auto-generates `/api/v1/docs` (Swagger UI) and `/api/v1/openapi.json`.

### 2.1 Read (catalog + resolve)

| Method | Path | Wraps |
|---|---|---|
| GET | `/api/v1/agents` | `registry.list_agents` |
| GET | `/api/v1/tasks` | `registry.list_tasks` |
| GET | `/api/v1/prompts` | `registry.list_prompts` |
| GET | `/api/v1/tools` | `registry.list_tools` |
| GET | `/api/v1/pipelines` | `registry.list_pipelines` |
| GET | `/api/v1/inference-configs` | `registry.list_inference_configs` |
| GET | `/api/v1/mcp-servers` | new thin wrapper |
| GET | `/api/v1/agents/{name}/config` | `registry.get_agent_config` — full resolved blob (agent row + inference_config + prompt assignments + tool authorizations + delegations). Accepts `?version_id=` or `?effective_date=`. |
| GET | `/api/v1/tasks/{name}/config` | `registry.get_task_config` |
| GET | `/api/v1/agents/{name}/versions` | new — list all versions (all states) |
| GET | `/api/v1/tasks/{name}/versions` | new |
| GET | `/api/v1/prompts/{name}/versions` | new |
| GET | `/api/v1/pipelines/{name}/versions` | new |

`get_*_config` IS the "complete entity config of a version" — it's the read half of the clone-and-edit workflow.

### 2.2 Runtime

| Method | Path | Wraps |
|---|---|---|
| POST | `/api/v1/runtime/agents/{name}/run` | `execution.run_agent` |
| POST | `/api/v1/runtime/tasks/{name}/run` | `execution.run_task` |
| POST | `/api/v1/runtime/pipelines/{name}/run` | `pipeline_executor.run_pipeline` |

### 2.3 Authoring (one endpoint per `register_*` SDK method)

**Headers:**
| Method | Path | Wraps |
|---|---|---|
| POST | `/api/v1/agents` | `registry.register_agent` |
| POST | `/api/v1/tasks` | `registry.register_task` |
| POST | `/api/v1/prompts` | `registry.register_prompt` |
| POST | `/api/v1/tools` | `registry.register_tool` |
| POST | `/api/v1/pipelines` | `registry.register_pipeline` |
| POST | `/api/v1/inference-configs` | `registry.register_inference_config` |
| POST | `/api/v1/mcp-servers` | `registry.register_mcp_server` |

**Versions (always created in `draft` state):**
| Method | Path | Wraps |
|---|---|---|
| POST | `/api/v1/agents/{name}/versions` | `registry.register_agent_version` |
| POST | `/api/v1/tasks/{name}/versions` | `registry.register_task_version` |
| POST | `/api/v1/prompts/{name}/versions` | `registry.register_prompt_version` |
| POST | `/api/v1/pipelines/{name}/versions` | `registry.register_pipeline_version` (steps JSONB embedded) |

**Associations (junction tables):**
| Method | Path | Wraps |
|---|---|---|
| POST | `/api/v1/agents/{name}/versions/{version_id}/prompts` | `registry.assign_prompt` (entity_type='agent') |
| POST | `/api/v1/tasks/{name}/versions/{version_id}/prompts` | `registry.assign_prompt` (entity_type='task') |
| POST | `/api/v1/agents/{name}/versions/{version_id}/tools` | `registry.authorize_agent_tool` |
| POST | `/api/v1/tasks/{name}/versions/{version_id}/tools` | `registry.authorize_task_tool` |
| POST | `/api/v1/agents/{name}/versions/{version_id}/delegations` | `registry.register_delegation` |

**Governance artifacts:**
| Method | Path | Wraps |
|---|---|---|
| POST | `/api/v1/ground-truth/datasets` | `registry.register_ground_truth_dataset` |
| POST | `/api/v1/ground-truth/datasets/{id}/records` | `registry.register_ground_truth_record` |
| POST | `/api/v1/ground-truth/records/{id}/annotations` | `registry.register_ground_truth_annotation` |
| POST | `/api/v1/validation-runs` | `registry.register_validation_run` |
| POST | `/api/v1/model-cards` | `registry.register_model_card` |
| POST | `/api/v1/metric-thresholds` | `registry.register_metric_threshold` |
| POST | `/api/v1/test-suites` | `registry.register_test_suite` |
| POST | `/api/v1/test-suites/{id}/cases` | `registry.register_test_case` |

### 2.4 Draft edit and clone (the "get config → modify → create new" workflow)

Verity's immutability model forbids editing any version that has left `draft` (candidate / staging / shadow / challenger / champion / deprecated are audit-load-bearing and stay immutable). Two patterns cover every authoring-edit case:

**Pattern 1 — In-place draft edits.** New SDK methods write via new named SQL queries with a `WHERE lifecycle_state = 'draft'` guard. Non-draft attempts return `409 Conflict` with the current state in the body.

| Method | Path | New SDK method |
|---|---|---|
| PATCH | `/api/v1/agents/{name}/versions/{version_id}` | `registry.update_agent_version_draft(version_id, **fields)` |
| PATCH | `/api/v1/tasks/{name}/versions/{version_id}` | `registry.update_task_version_draft` |
| PATCH | `/api/v1/prompts/{name}/versions/{version_id}` | `registry.update_prompt_version_draft` |
| PATCH | `/api/v1/pipelines/{name}/versions/{version_id}` | `registry.update_pipeline_version_draft` |
| PUT | `/api/v1/agents/{name}/versions/{version_id}/prompts` | `registry.replace_agent_prompt_assignments` |
| PUT | `/api/v1/agents/{name}/versions/{version_id}/tools` | `registry.replace_agent_tool_authorizations` |
| PUT | `/api/v1/agents/{name}/versions/{version_id}/delegations` | `registry.replace_agent_delegations` |
| PUT | `/api/v1/tasks/{name}/versions/{version_id}/prompts` | `registry.replace_task_prompt_assignments` |
| PUT | `/api/v1/tasks/{name}/versions/{version_id}/tools` | `registry.replace_task_tool_authorizations` |
| DELETE | `/api/v1/agents/{name}/versions/{version_id}` | `registry.delete_draft_version('agent', version_id)` |
| DELETE | `/api/v1/tasks/{name}/versions/{version_id}` | `registry.delete_draft_version('task', ...)` |
| DELETE | `/api/v1/prompts/{name}/versions/{version_id}` | `registry.delete_draft_version('prompt', ...)` |
| DELETE | `/api/v1/pipelines/{name}/versions/{version_id}` | `registry.delete_draft_version('pipeline', ...)` |

**Pattern 2 — Clone a version into a new draft.** Copies the version row + all its associations (prompt assignments, tool authorizations, delegations) into a new version row with a caller-supplied label and `lifecycle_state='draft'`. The new draft carries a `cloned_from_version_id` reference for provenance.

| Method | Path | New SDK method |
|---|---|---|
| POST | `/api/v1/agents/{name}/versions/{source_version_id}/clone` | `registry.clone_agent_version(source_version_id, new_version_label, change_summary)` |
| POST | `/api/v1/tasks/{name}/versions/{source_version_id}/clone` | `registry.clone_task_version` |
| POST | `/api/v1/prompts/{name}/versions/{source_version_id}/clone` | `registry.clone_prompt_version` |
| POST | `/api/v1/pipelines/{name}/versions/{source_version_id}/clone` | `registry.clone_pipeline_version` |

**Typical edit workflow:**
```
GET  /api/v1/agents/my_agent/config?version_id={champion_id}
POST /api/v1/agents/my_agent/versions/{champion_id}/clone            # → {draft_version_id}
PATCH /api/v1/agents/my_agent/versions/{draft_version_id}
PUT   /api/v1/agents/my_agent/versions/{draft_version_id}/prompts
PUT   /api/v1/agents/my_agent/versions/{draft_version_id}/tools
POST  /api/v1/lifecycle/promote
```

**Typical "build from scratch" workflow:**
```
POST /api/v1/agents                                                   # header
POST /api/v1/agents/my_agent/versions                                  # draft version
POST /api/v1/agents/my_agent/versions/{id}/prompts  (×N)
POST /api/v1/agents/my_agent/versions/{id}/tools    (×N)
POST /api/v1/agents/my_agent/versions/{id}/delegations (×N)
POST /api/v1/lifecycle/promote                                         # draft → … → champion
POST /api/v1/applications/ds_workbench/entities                        # map to workbench app
```

### 2.5 Lifecycle

| Method | Path | Wraps |
|---|---|---|
| POST | `/api/v1/lifecycle/promote` | `lifecycle.promote` |
| POST | `/api/v1/lifecycle/rollback` | `lifecycle.rollback` |
| GET | `/api/v1/lifecycle/approvals?entity_type=&entity_version_id=` | new — list approvals for audit |

### 2.6 Application management

| Method | Path | Wraps |
|---|---|---|
| POST | `/api/v1/applications` | `registry.register_application` |
| GET | `/api/v1/applications` | `registry.list_applications` |
| GET | `/api/v1/applications/{name}` | new — single-app fetch |
| DELETE | `/api/v1/applications/{name}` | new — `registry.unregister_application` |
| GET | `/api/v1/applications/{name}/entities?entity_type=` | new — `registry.list_application_entities` |
| POST | `/api/v1/applications/{name}/entities` | `registry.map_entity_to_application` |
| DELETE | `/api/v1/applications/{name}/entities/{entity_type}/{entity_id}` | new — `registry.unmap_entity_from_application` |
| GET | `/api/v1/applications/{name}/activity` | new — `registry.get_application_activity` |
| DELETE | `/api/v1/applications/{name}/activity` | new — `registry.purge_application_activity` (env-flag guarded) |
| POST | `/api/v1/execution-contexts` | `registry.create_execution_context` |

### 2.7 Audit and decisions

| Method | Path | Wraps |
|---|---|---|
| GET | `/api/v1/decisions` | `decisions.list_decisions` |
| GET | `/api/v1/decisions/{id}` | `decisions.get_decision` |
| GET | `/api/v1/audit-trail/context/{id}` | `decisions.get_audit_trail` |
| GET | `/api/v1/audit-trail/run/{id}` | `decisions.get_audit_trail_by_run` |
| POST | `/api/v1/overrides` | `decisions.record_override` |

### 2.8 Reporting

| Method | Path | Wraps |
|---|---|---|
| GET | `/api/v1/reporting/dashboard-counts` | `reporting.dashboard_counts` |
| GET | `/api/v1/reporting/agents` | `reporting.model_inventory_agents` |
| GET | `/api/v1/reporting/tasks` | `reporting.model_inventory_tasks` |

### 2.9 New SDK methods and SQL required

New named SQL queries (location: [verity/src/verity/db/queries/registration.sql](../../verity/src/verity/db/queries/registration.sql) or a new `authoring.sql`):
- `update_agent_version_draft`, `update_task_version_draft`, `update_prompt_version_draft`, `update_pipeline_version_draft` — all draft-guarded.
- `delete_draft_{agent,task,prompt,pipeline}_version` — cascades via FK ON DELETE CASCADE where present.
- `replace_agent_prompt_assignments` / `replace_agent_tool_authorizations` / `replace_agent_delegations` — transactional DELETE + batch INSERT, draft-guarded.
- Equivalent `replace_task_*`.
- `clone_agent_version` / `clone_task_version` / `clone_prompt_version` / `clone_pipeline_version` — transactional clone + association duplication, sets `cloned_from_version_id`.
- `list_{agent,task,prompt,pipeline}_versions`.
- `list_application_entities`, `unmap_entity_from_application`.
- `unregister_application`, `get_application_activity`, `purge_application_activity`.

**Schema addition** — new `cloned_from_version_id UUID` column on each `*_version` table for provenance of cloned drafts.

New Pydantic request/response models in a new [verity/src/verity/web/api/schemas.py](../../verity/src/verity/web/api/schemas.py); responses reuse existing `AgentConfig`, `TaskConfig`, etc.

### 2.10 Implementation layout

```
verity/src/verity/web/api/
├── __init__.py
├── router.py          ← build_api_router(verity_client) → APIRouter
├── schemas.py         ← request/response Pydantic models
├── registry.py        ← registry routes
├── lifecycle.py       ← lifecycle routes
├── runtime.py         ← run_agent/task/pipeline routes
├── decisions.py       ← decision + audit-trail routes
├── reporting.py       ← dashboard + inventory routes
└── applications.py    ← application CRUD + activity
```

Wired in [verity/src/verity/main.py](../../verity/src/verity/main.py) after `CorrelationMiddleware`, before `/admin` mount:
```python
from verity.web.api.router import build_api_router
app.include_router(build_api_router(verity_client))
```

JSON-boundary helper (used everywhere): `_dump(x)` calls `.model_dump(mode="json")` if the value is a Pydantic model, else returns it unchanged.

---

## 3. Part B — Data Science Workbench

### 3.1 Docker service

Added to [docker-compose.yml](../../docker-compose.yml):
```yaml
ds-workbench:
  image: jupyter/scipy-notebook:latest
  ports:
    - "8888:8888"
  volumes:
    - ./ds_workbench:/home/jovyan/work
  environment:
    VERITY_API_URL: http://verity:8000
    JUPYTER_TOKEN: "dev"
    CHOWN_HOME: "yes"
  depends_on:
    verity:
      condition: service_healthy
  command: >
    start-notebook.sh
    --NotebookApp.token=dev
    --NotebookApp.allow_origin='*'
    --NotebookApp.notebook_dir=/home/jovyan/work
```

`requirements.txt` extras installed on first run (either a tiny wrapper Dockerfile or a `postBuild` step; decided during implementation).

### 3.2 Repo layout

```
ds_workbench/
├── README.md                     ← how to run (docker + VSCode)
├── requirements.txt              ← httpx, pandas, plotly, graphviz, networkx, ipycytoscape
├── utility/
│   ├── __init__.py
│   ├── verity.py                 ← VerityAPI client + endpoint registry
│   └── visualizations.py         ← reusable viz helpers
├── 00_setup.ipynb                ← register "ds_workbench" application if missing
├── 99_cleanup.ipynb              ← purge activity + unregister
└── notebooks/
    ├── registry/
    ├── authoring/
    │   ├── 01_register_simple_agent.ipynb
    │   ├── 02_clone_and_edit_draft.ipynb
    │   ├── 03_register_pipeline_end_to_end.ipynb
    │   ├── 04_register_mcp_server_and_tool.ipynb
    │   └── 05_draft_edit_and_delete.ipynb
    ├── lifecycle/
    ├── runtime/
    ├── compliance/
    ├── testing/
    ├── validation/
    ├── mcp/
    └── delegation/
```

### 3.3 `utility/verity.py`

- `VerityAPI(base_url=None, default_application="ds_workbench")`:
  - `base_url` defaults to `os.environ.get("VERITY_API_URL", "http://localhost:8000")`.
  - Wraps `httpx.Client(base_url=..., timeout=30)`.
  - `ENDPOINTS: dict[str, tuple[str, str]]` — logical name → `(HTTP_METHOD, URL_TEMPLATE)`.
  - Core `call(endpoint_name, path_params=None, query=None, json=None)` — resolves template, dispatches, raises on non-2xx with structured error, returns parsed JSON.
  - Convenience wrappers: `register_application`, `ensure_application_registered`, `list_agents`, `get_agent_config`, `run_agent`, `run_pipeline`, `get_decision`, `get_audit_trail_by_context`, `get_audit_trail_by_run`, `promote`, `get_application_activity`, `purge_application`, `unregister_application`.
  - Debug mode (`verbose=True`) logs request URL + status + body shape.

### 3.4 `utility/visualizations.py`

Reusable across notebooks. Returns displayable objects (`IPython.display.HTML`/`SVG` or `plotly.graph_objects.Figure`).
- `as_dataframe(records)` — list-of-dict → pandas DataFrame.
- `catalog_table(records, columns=None)` — styled pandas table.
- `dashboard_counts_bar(counts)` — horizontal bar chart.
- `pipeline_run_gantt(steps)` — gantt timeline of pipeline steps colored by status.
- `decision_timeline(audit_trail)` — timeline of decisions in an execution context.
- `decision_tree(decisions_root)` — parent→sub decision tree (graphviz) — showcases sub-agent delegation.
- `tool_call_sankey(decision)` — sankey of tool_name → output-class within one decision.
- `lifecycle_state_heatmap(entity_versions)` — entity × state heatmap.
- `application_relationship_graph(app_name, entities)` — app → entity relationship diagram.
- `validation_metrics_panel(validation_run)` — precision/recall/F1 panel + per-record confusion view.
- `agent_composition_diagram(agent_config)` — block diagram of an agent's full config (header + inference_config + prompts + tools + delegations), driven directly by `GET /api/v1/agents/{name}/config`.
- `version_lineage_graph(versions)` — lineage graph including `cloned_from_version_id` edges, coloured by lifecycle_state.

### 3.5 Notebook template

Every capability notebook follows the same four sections:

1. **What this demonstrates** — markdown: 1–2 paragraphs on the Verity capability and why it matters for governance.
2. **Prerequisites** — markdown + code: what must already exist; minimal setup calls if missing.
3. **Execute** — markdown + code: the capability call(s).
4. **Review results** — markdown + code: pull artifacts via API, render with visualizations helper.

### 3.6 Setup and cleanup notebooks

**`00_setup.ipynb`:**
1. `GET /health` to confirm the API is reachable.
2. `GET /api/v1/applications` to check for `ds_workbench`; `POST` if missing.
3. Print the registration summary.
4. Seed a handful of `execution_context` rows for sample use.

**`99_cleanup.ipynb`:**
1. `GET /api/v1/applications/ds_workbench/activity` — show counts to be deleted.
2. Interactive confirmation cell.
3. `DELETE /api/v1/applications/ds_workbench/activity` — cascading purge.
4. `DELETE /api/v1/applications/ds_workbench` — unregister + unmap entities.
5. Follow-up `GET` to verify.

### 3.7 Running from VSCode and Docker

- **Docker JupyterLab:** `docker-compose up ds-workbench` → `http://localhost:8888?token=dev`. `VERITY_API_URL=http://verity:8000`.
- **VSCode on host:** open `ds_workbench/` in VSCode, Jupyter extension uses a local `.venv` with `requirements.txt` installed, `VERITY_API_URL=http://localhost:8000`.
- `utility/verity.py` reads `VERITY_API_URL` from env (localhost default), so the same notebook runs unchanged in both.

---

## 4. Critical files

| Path | Action |
|---|---|
| new: `verity/src/verity/web/api/` package | Router + per-facade route modules + schemas |
| [verity/src/verity/main.py](../../verity/src/verity/main.py) | `include_router(build_api_router(...))` before `/admin` mount |
| [verity/src/verity/governance/registry.py](../../verity/src/verity/governance/registry.py) | All new SDK methods listed in §2.9 |
| [verity/src/verity/db/queries/registration.sql](../../verity/src/verity/db/queries/registration.sql) or new `authoring.sql` | All new named SQL queries |
| [verity/src/verity/db/schema.sql](../../verity/src/verity/db/schema.sql) | `cloned_from_version_id UUID` column on `agent_version`, `task_version`, `prompt_version`, `pipeline_version` |
| [docker-compose.yml](../../docker-compose.yml) | Add `ds-workbench` service |
| new: `ds_workbench/` tree | As §3.2 |
| new: `ds_workbench/utility/verity.py` | HTTP helper + endpoint dict |
| new: `ds_workbench/utility/visualizations.py` | Viz helpers |
| new: `ds_workbench/requirements.txt` | httpx, pandas, plotly, graphviz, networkx, ipycytoscape |
| new: `ds_workbench/00_setup.ipynb`, `ds_workbench/99_cleanup.ipynb` | Top-level notebooks |
| new: `ds_workbench/notebooks/<component>/*.ipynb` | Starter capability notebooks |

---

## 5. Reusable existing work
- The `Verity` SDK facade → REST is a thin JSON wrapper; no governance/runtime business logic changes beyond the new SDK methods in §2.9.
- `application` / `application_entity` tables already exist in [schema.sql](../../verity/src/verity/db/schema.sql).
- `httpx` is already in Verity's base dependencies — same library on both sides.
- `CorrelationMiddleware` ([verity/src/verity/web/middleware.py](../../verity/src/verity/web/middleware.py)) already wraps the FastAPI app → API requests inherit structured logging and trace IDs for free.
- `jupyter/scipy-notebook` image ships pandas / numpy / matplotlib — no custom build needed.

---

## 6. Implementation order

1. **API plumbing** — new `api/` package, wire router, single smoke-test endpoint (`GET /api/v1/reporting/dashboard-counts`).
2. **Read endpoints** (§2.1).
3. **Runtime endpoints** (§2.2).
4. **Authoring endpoints — headers, versions, associations** (§2.3).
5. **Schema addition + new SDK methods + draft-edit / clone endpoints** (§2.4 + §2.9). One coordinated pass.
6. **Application management + activity + cleanup endpoints** (§2.6).
7. **Lifecycle, audit, reporting endpoints** (§2.5, §2.7, §2.8).
8. **docker-compose `ds-workbench` service**; verify it can curl the API from inside the container.
9. **Utility modules** — `utility/verity.py`, `utility/visualizations.py`. Exercise via a scratch notebook.
10. **Setup and cleanup notebooks.**
11. **Starter capability notebooks** — prioritized: `runtime/01_run_agent.ipynb`, `compliance/01_decision_log_walkthrough.ipynb`, `authoring/01_register_simple_agent.ipynb`, `authoring/02_clone_and_edit_draft.ipynb`.
12. **Update this doc** with the delivered design + OpenAPI snapshot.

---

## 7. Verification

1. **API health:** `curl http://localhost:8000/api/v1/docs` shows Swagger; `GET /api/v1/reporting/dashboard-counts` returns JSON matching the admin dashboard counts.
2. **Docker up:** `docker-compose up ds-workbench` starts JupyterLab on `:8888`; `docker-compose exec ds-workbench curl -f http://verity:8000/health` returns 200.
3. **Setup notebook:** run from Docker → `ds_workbench` appears in `/admin/applications`. Run same notebook from VSCode against `localhost:8000` → same outcome.
4. **Runtime notebook:** `runtime/01_run_agent.ipynb` executes a seeded agent; visualization cells render a decision-log table and parent→sub decision tree; row visible at `/admin/decisions/`.
5. **Authoring end-to-end:** `authoring/01_register_simple_agent.ipynb` creates header + draft version + prompt + tool authorization, promotes draft → candidate → champion, and confirms the new champion via `GET /api/v1/agents/{name}/config`.
6. **Clone-and-edit:** `authoring/02_clone_and_edit_draft.ipynb` clones champion into a draft, PATCHes, PUTs new prompts, promotes; asserts the resulting champion differs; `version_lineage_graph` shows the `cloned_from_version_id` edge.
7. **Draft immutability guard:** PATCH on a non-draft version returns 409 Conflict with the current lifecycle_state in the error body.
8. **Cleanup notebook:** `GET /api/v1/applications` no longer lists `ds_workbench`; `SELECT COUNT(*) FROM agent_decision_log WHERE application='ds_workbench'` returns 0.
9. **VSCode round-trip:** any notebook opened in VSCode, executed with a local `.venv`, produces the same visualizations as the Docker kernel.

---

## As-delivered summary

What actually shipped, captured live from the running system on 2026-04-22. The design sections above remain the "intent" reference; this section is the "reality" reference.

### 8. Delivered API surface

**78 operations across 54 paths and 8 tags.** Live Swagger UI at `http://localhost:8000/docs`; machine-readable spec at `http://localhost:8000/openapi.json`.

#### applications (10)

| Method | Path |
|---|---|
| GET | `/api/v1/applications` |
| POST | `/api/v1/applications` |
| GET | `/api/v1/applications/{name}` |
| DELETE | `/api/v1/applications/{name}` |
| GET | `/api/v1/applications/{name}/activity` |
| DELETE | `/api/v1/applications/{name}/activity` |
| GET | `/api/v1/applications/{name}/entities` |
| POST | `/api/v1/applications/{name}/entities` |
| DELETE | `/api/v1/applications/{name}/entities/{entity_type}/{entity_id}` |
| POST | `/api/v1/execution-contexts` |

#### authoring (24)

| Method | Path |
|---|---|
| POST | `/api/v1/agents` |
| POST | `/api/v1/agents/{name}/versions` |
| POST | `/api/v1/agents/{name}/versions/{version_id}/prompts` |
| POST | `/api/v1/agents/{name}/versions/{version_id}/tools` |
| POST | `/api/v1/agents/{name}/versions/{version_id}/delegations` |
| POST | `/api/v1/tasks` |
| POST | `/api/v1/tasks/{name}/versions` |
| POST | `/api/v1/tasks/{name}/versions/{version_id}/prompts` |
| POST | `/api/v1/tasks/{name}/versions/{version_id}/tools` |
| POST | `/api/v1/prompts` |
| POST | `/api/v1/prompts/{name}/versions` |
| POST | `/api/v1/pipelines` |
| POST | `/api/v1/pipelines/{name}/versions` |
| POST | `/api/v1/tools` |
| POST | `/api/v1/inference-configs` |
| POST | `/api/v1/mcp-servers` |
| POST | `/api/v1/ground-truth/datasets` |
| POST | `/api/v1/ground-truth/datasets/{dataset_id}/records` |
| POST | `/api/v1/ground-truth/records/{record_id}/annotations` |
| POST | `/api/v1/validation-runs` |
| POST | `/api/v1/model-cards` |
| POST | `/api/v1/metric-thresholds` |
| POST | `/api/v1/test-suites` |
| POST | `/api/v1/test-suites/{suite_id}/cases` |

#### draft-edit (17)

| Method | Path |
|---|---|
| PATCH | `/api/v1/agents/{name}/versions/{version_id}` |
| DELETE | `/api/v1/agents/{name}/versions/{version_id}` |
| PUT | `/api/v1/agents/{name}/versions/{version_id}/prompts` |
| PUT | `/api/v1/agents/{name}/versions/{version_id}/tools` |
| PUT | `/api/v1/agents/{name}/versions/{version_id}/delegations` |
| POST | `/api/v1/agents/{name}/versions/{source_version_id}/clone` |
| PATCH | `/api/v1/tasks/{name}/versions/{version_id}` |
| DELETE | `/api/v1/tasks/{name}/versions/{version_id}` |
| PUT | `/api/v1/tasks/{name}/versions/{version_id}/prompts` |
| PUT | `/api/v1/tasks/{name}/versions/{version_id}/tools` |
| POST | `/api/v1/tasks/{name}/versions/{source_version_id}/clone` |
| PATCH | `/api/v1/prompts/{name}/versions/{version_id}` |
| DELETE | `/api/v1/prompts/{name}/versions/{version_id}` |
| POST | `/api/v1/prompts/{name}/versions/{source_version_id}/clone` |
| PATCH | `/api/v1/pipelines/{name}/versions/{version_id}` |
| DELETE | `/api/v1/pipelines/{name}/versions/{version_id}` |
| POST | `/api/v1/pipelines/{name}/versions/{source_version_id}/clone` |

#### registry (13)

| Method | Path |
|---|---|
| GET | `/api/v1/agents` |
| GET | `/api/v1/agents/{name}/config` |
| GET | `/api/v1/agents/{name}/versions` |
| GET | `/api/v1/tasks` |
| GET | `/api/v1/tasks/{name}/config` |
| GET | `/api/v1/tasks/{name}/versions` |
| GET | `/api/v1/prompts` |
| GET | `/api/v1/prompts/{name}/versions` |
| GET | `/api/v1/pipelines` |
| GET | `/api/v1/pipelines/{name}/versions` |
| GET | `/api/v1/tools` |
| GET | `/api/v1/inference-configs` |
| GET | `/api/v1/mcp-servers` |

#### lifecycle (3)

| Method | Path |
|---|---|
| POST | `/api/v1/lifecycle/promote` |
| POST | `/api/v1/lifecycle/rollback` |
| GET | `/api/v1/lifecycle/approvals` |

#### decisions (5)

| Method | Path |
|---|---|
| GET | `/api/v1/decisions` |
| GET | `/api/v1/decisions/{decision_id}` |
| GET | `/api/v1/audit-trail/context/{execution_context_id}` |
| GET | `/api/v1/audit-trail/run/{pipeline_run_id}` |
| POST | `/api/v1/overrides` |

#### runtime (3)

| Method | Path |
|---|---|
| POST | `/api/v1/runtime/agents/{name}/run` |
| POST | `/api/v1/runtime/tasks/{name}/run` |
| POST | `/api/v1/runtime/pipelines/{name}/run` |

#### reporting (3)

| Method | Path |
|---|---|
| GET | `/api/v1/reporting/dashboard-counts` |
| GET | `/api/v1/reporting/agents` |
| GET | `/api/v1/reporting/tasks` |

### 9. Delivered workbench

| Path | Role |
|---|---|
| [ds_workbench/Dockerfile](../../../ds_workbench/Dockerfile) | Image = `jupyter/scipy-notebook` + system `graphviz` + `ds_workbench/requirements.txt` (httpx, plotly, graphviz, networkx, ipycytoscape) |
| [ds_workbench/utility/verity.py](../../../ds_workbench/utility/verity.py) | `VerityAPI` sync HTTP client; 70 logical endpoints in `ENDPOINTS`; convenience wrappers for the ~15 highest-traffic operations; `VerityAPIError` carries status + detail |
| [ds_workbench/utility/html.py](../../../ds_workbench/utility/html.py) | Six Verity-UI-styled building blocks: `inject_style`, `badge`, `kv`, `render_list`, `render_detail`, `render_cards`. Inline stylesheet (no CDN) ported from `verity.css`. |
| [ds_workbench/utility/visualizations.py](../../../ds_workbench/utility/visualizations.py) | Plotly charts + Graphviz diagrams: timeline, decision tree, agent composition, version lineage, application relationships, lifecycle heatmap |
| [ds_workbench/00_setup.ipynb](../../../ds_workbench/00_setup.ipynb) | Idempotent registration of `ds_workbench`; renders catalog and resolved agent config |
| [ds_workbench/99_cleanup.ipynb](../../../ds_workbench/99_cleanup.ipynb) | Three-step cleanup: preview → purge → unregister |
| [ds_workbench/notebooks/runtime/01_run_agent.ipynb](../../../ds_workbench/notebooks/runtime/01_run_agent.ipynb) | Real LLM call through `POST /runtime/agents/{name}/run`; renders `ExecutionResult` + persisted `DecisionLog` |
| [ds_workbench/notebooks/compliance/01_decision_log_walkthrough.ipynb](../../../ds_workbench/notebooks/compliance/01_decision_log_walkthrough.ipynb) | List / detail / audit-trail / Graphviz decision tree |
| [ds_workbench/notebooks/authoring/01_register_simple_agent.ipynb](../../../ds_workbench/notebooks/authoring/01_register_simple_agent.ipynb) | Full register-from-scratch flow (6 POSTs) + idempotent cleanup |
| [ds_workbench/notebooks/authoring/02_clone_and_edit_draft.ipynb](../../../ds_workbench/notebooks/authoring/02_clone_and_edit_draft.ipynb) | Clone champion → PATCH draft → lineage graph → 409 guard → cleanup |
| [ds_workbench/_build_notebooks.py](../../../ds_workbench/_build_notebooks.py) | Regenerates every `.ipynb` from Python code. Hand-editing the JSON is not recommended. |

All six notebooks were executed end-to-end against the live API: **0 errors / 40 code cells total**.

### 10. Known limitations and next steps

**Decision-attribution gap.** Decisions triggered through the REST `/runtime/*` endpoints are tagged with `application='default'` (the Verity server process's client identity), not with the caller's application name. The `DELETE /api/v1/applications/{name}/activity` endpoint matches decisions by the `application` VARCHAR column, so workbench-initiated runs are **not** caught by the activity purge. Documented in `99_cleanup.ipynb`. Two follow-ups would close the gap:
1. Add an `application` override field to the runtime request bodies and thread it through to the SDK's decision writer.
2. Broaden the purge SQL to also delete decisions linked via `execution_context.application_id` (not just by `application` name match).

**No auth.** The API binds to the docker network and localhost only. Before any shared deployment, an auth layer (bearer or per-app API keys) must be added.

**Notebook coverage is starter-set.** Six notebooks shipped. The per-component folders under `notebooks/` have placeholders for more — in particular `lifecycle/`, `testing/`, `validation/`, `mcp/`, `delegation/`, and additional `registry/`, `runtime/`, `compliance/` scenarios. Add them by extending `_build_notebooks.py` and running the generator.

**The `_build_notebooks.py` script is a dev tool, not a runtime dependency.** Shipping it in the repo keeps notebook maintenance a one-command operation. If the script grows too large, it can be split by component folder (one builder module per `notebooks/<tag>/`).

### 11. Running the delivered stack

Three commands:

```bash
# Bring everything up (postgres, minio, edms, verity, uw-demo, ds-workbench).
docker compose up -d

# Open the admin UI and the workbench side by side.
open http://localhost:8000/admin      # Verity admin UI
open http://localhost:8888?token=dev  # JupyterLab — run 00_setup.ipynb first

# From VSCode on the host (alternative to Docker JupyterLab):
export VERITY_API_URL=http://localhost:8000
pip install -r ds_workbench/requirements.txt
# then open any .ipynb under ds_workbench/ in VSCode's Jupyter extension.
```
