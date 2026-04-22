# Plan: Slim Verity to Governance, Extract Runtime, Adopt Claude Agent SDK (Local Docker)

## Context

**Why this change.** The architectural goal is to slim Verity to its governance role — registry, lifecycle, decision log, ground truth, testing, compliance reporting — and extract execution into a replaceable Runtime. The hook is that **agents, tasks, prompts, tools, and pipelines remain database-stored definitions, not code-resident**. The registry is the source of truth for those definitions; every execution resolves a versioned config from the governance plane and logs back the exact version IDs it used. That's what delivers full auditability and version pinning, regardless of which LLM framework runs the actual calls.

**Runtime choice: Claude Agent SDK.** Replaces the custom agentic loop in the current [core/execution.py](../../verity/src/verity/core/execution.py). Reduces maintenance (Anthropic maintains the loop, tool-call handling, context management), aligns Verity with the official agent framework, and leaves Verity free to focus on governance.

**Platform: local Docker, Postgres.** User has free-tier Snowflake only; SPCS and paid Cortex features are unavailable. Snowflake migration is deferred to a later phase once the split is proven locally.

**Decisions locked (from prior turns):** Post-demo refactor · Claude Agent SDK as runtime · Local Docker + Postgres as the deployment target · One Python package (not four distributions).

**Decisions deferred to future phases:** Snowflake migration, SPCS hosting, Cortex adoption, Airflow for batch orchestration.

## Naming Conventions Used in This Plan

| Term | Means |
|---|---|
| **Verity** or **governance plane** | The slimmed `verity` package: registry, lifecycle, decision log, ground truth, testing, compliance, admin UI |
| **Registry** (narrow) | The subset of governance that stores agent/task/prompt/tool/pipeline/inference_config definitions — one capability among several |
| **Runtime** or **execution plane** | The new `verity.runtime` subpackage: agentic loop, pipelines, runners, tool dispatch |
| **Contracts** | The new `verity.contracts` subpackage: Pydantic models on the governance↔runtime boundary |
| **Client** | The new `verity.client` subpackage: consumer SDK (UW and Runtime use it to talk to governance) |

## Physical Layout — One Package, Subpackages

```
verity_uw/
├── verity/                             ← ONE Python package, ONE pyproject.toml
│   ├── pyproject.toml                  (with optional-dependencies for runtime)
│   └── src/verity/
│       ├── contracts/                  ← NEW — Pydantic models on the boundary
│       │   ├── config.py               (ResolvedConfig)
│       │   ├── decision.py             (DecisionLogCreate, ExecutionResult)
│       │   ├── mock.py                 (MockContext)
│       │   └── testing.py              (test/validation result models)
│       │
│       ├── governance/                 ← NEW — what stays with Verity
│       │   ├── registry.py             (from core/registry.py)
│       │   ├── lifecycle.py            (from core/lifecycle.py)
│       │   ├── decisions_reader.py     (audit trail queries from core/decisions.py)
│       │   ├── reporting.py            (from core/reporting.py)
│       │   ├── testing_meta.py         (metadata ops from core/testing.py)
│       │   └── coordinator.py          (internal facade wiring the above)
│       │
│       ├── runtime/                    ← NEW — execution plane
│       │   ├── engine.py               (from core/execution.py; replaced by Claude Agent SDK in Phase 3)
│       │   ├── pipeline.py             (from core/pipeline_executor.py)
│       │   ├── test_runner.py          (from core/test_runner.py)
│       │   ├── validation_runner.py    (from core/validation_runner.py)
│       │   ├── mock_context.py         (from core/mock_context.py)
│       │   ├── metrics.py              (from core/metrics.py)
│       │   ├── decisions_writer.py     (writer half of core/decisions.py)
│       │   ├── tool_registry.py        (tool_implementations dict + register API)
│       │   ├── sdk_backend.py          (Claude Agent SDK adapter — Phase 3)
│       │   └── runtime.py              (internal facade wiring the above)
│       │
│       ├── client/                     ← NEW — consumer SDK
│       │   ├── inprocess.py            (direct Python calls — Phases 1-4)
│       │   └── http.py                 (REST calls — Phase 4+)
│       │
│       ├── db/                         ← shared (unchanged)
│       ├── web/                        ← admin UI (stays with governance)
│       ├── models/                     ← existing; boundary models migrate into contracts/
│       ├── logging.py                  ← shared
│       └── core/                       ← emptied + deleted after Phase 2
│
├── edms/                               ← unchanged
├── uw_demo/                            ← unchanged
├── docker-compose.yml
└── docs/
```

### `core/` → Subpackage Mapping

| `core/` file today | Destination | Notes |
|---|---|---|
| `client.py` | Deleted — split into 3 | `governance/coordinator.py`, `runtime/runtime.py`, `client/inprocess.py` |
| `execution.py` | `runtime/engine.py` | Replaced by Claude Agent SDK in Phase 3 |
| `pipeline_executor.py` | `runtime/pipeline.py` | |
| `test_runner.py` | `runtime/test_runner.py` | |
| `validation_runner.py` | `runtime/validation_runner.py` | |
| `mock_context.py` | `runtime/mock_context.py` | Pydantic shape also in `contracts/mock.py` |
| `metrics.py` | `runtime/metrics.py` | Pure computation; used by runners |
| `registry.py` | `governance/registry.py` | |
| `lifecycle.py` | `governance/lifecycle.py` | |
| `decisions.py` | **SPLIT** | Reader → `governance/decisions_reader.py`; writer → `runtime/decisions_writer.py` |
| `reporting.py` | `governance/reporting.py` | |
| `testing.py` | `governance/testing_meta.py` | Metadata only; execution moves to runtime |

**Net result after Phase 2:** `core/` is gone. Every piece has a natural home in governance, runtime, contracts, or client.

### Imports

```python
# Shared contracts (used by both governance and runtime)
from verity.contracts import ResolvedConfig, DecisionLogCreate, ExecutionResult, MockContext

# Governance plane (registry, lifecycle, audit reader, reporting)
from verity.governance import Registry, Lifecycle, DecisionsReader, Reporting

# Runtime plane (execution)
from verity.runtime import ExecutionEngine, PipelineExecutor, TestRunner, ValidationRunner

# Client SDK (UW and runtime use this to talk to governance)
from verity.client.inprocess import InProcessClient   # Phases 1-4
from verity.client.http import HTTPClient             # Phase 4+
```

### Dependency Footprint

One `pyproject.toml`, optional dependency groups so container images don't drag in deps they don't need:

```toml
[project]
name = "verity"
dependencies = ["pydantic", "fastapi", "psycopg", "jinja2", "httpx"]   # shared

[project.optional-dependencies]
runtime = ["claude-agent-sdk", "anthropic"]
```

Container images:
- **governance** → `pip install -e .` (FastAPI + Jinja admin UI + REST, no LLM deps)
- **runtime** → `pip install -e .[runtime]` (pulls in Claude Agent SDK)

Same codebase, different entry points, different dependency footprints. One version number to bump.

## Current Seam (from code audit)

Split is cleaner than expected. The touch points are well-bounded.

**Moves to Runtime subpackage:**
- [core/execution.py](../../verity/src/verity/core/execution.py) — the agentic loop (replaced by Claude Agent SDK in Phase 3)
- [core/pipeline_executor.py](../../verity/src/verity/core/pipeline_executor.py)
- [core/test_runner.py](../../verity/src/verity/core/test_runner.py)
- [core/validation_runner.py](../../verity/src/verity/core/validation_runner.py)
- [core/mock_context.py](../../verity/src/verity/core/mock_context.py)
- [core/metrics.py](../../verity/src/verity/core/metrics.py)
- `tool_implementations` dict + `register_tool_implementation` API currently hosted on [core/client.py:192](../../verity/src/verity/core/client.py)
- Writer half of [core/decisions.py](../../verity/src/verity/core/decisions.py)

**Stays in Verity (governance plane):**
- [core/registry.py](../../verity/src/verity/core/registry.py) → `governance/registry.py`
- [core/lifecycle.py](../../verity/src/verity/core/lifecycle.py) → `governance/lifecycle.py`
- Reader half of [core/decisions.py](../../verity/src/verity/core/decisions.py) (audit trail queries) → `governance/decisions_reader.py`
- [core/reporting.py](../../verity/src/verity/core/reporting.py) → `governance/reporting.py`
- [core/testing.py](../../verity/src/verity/core/testing.py) → `governance/testing_meta.py`
- All [web/](../../verity/src/verity/web/) routes and templates

**UW wire-up changes (small):**
- [uw_demo/app/main.py](../../uw_demo/app/main.py) — tool registration goes to the runtime, not the governance client
- [uw_demo/app/ui/routes.py](../../uw_demo/app/ui/routes.py) — `verity.execute_pipeline(...)` → `verity.runtime.execute_pipeline(...)`; audit-trail reads stay on `verity.governance.*` (or flat facade proxy)

## Target Architecture (Local Docker)

```
docker-compose.yml
├── postgres:16 (pgvector extension)
│   ├── verity_db
│   ├── edms_db
│   └── pas_db
│
├── minio                ← EDMS blob store (unchanged)
│
├── verity               ← Governance plane: FastAPI + Jinja admin UI + REST API (port 8000)
│                          registry, lifecycle, decision log, ground truth, testing, compliance
├── verity-runtime       ← Execution plane: Claude Agent SDK-based runtime + REST API (port 8100)
│                          calls api.anthropic.com for LLM
└── uw-app               ← UW demo FastAPI (port 8001)
                           consumes verity.client (governance) + runtime client
```

## Phased Plan

### Phase 1 — Create `verity.contracts` subpackage (no behavior change)

Create `verity/src/verity/contracts/` and move Pydantic models that cross the governance/runtime boundary into it. Everything else keeps working unchanged.

- `contracts/config.py` — `ResolvedConfig` (unified view over current `AgentConfig` / `TaskConfig`)
- `contracts/decision.py` — `DecisionLogCreate`, `ExecutionResult`
- `contracts/mock.py` — `MockContext`
- `contracts/testing.py` — test/validation result models
- `contracts/__init__.py` — re-exports
- Existing model files in `verity/models/` that are purely boundary models get moved; ones that are DB-mapped Pydantic stay
- All callers (`verity/core/*`, `uw_demo/app/*`) update imports to `from verity.contracts import ...`

**Acceptance:** existing pytest suite passes; no runtime behavior change.

### Phase 2 — Create `governance/`, `runtime/`, `client/` subpackages

Move files from `core/` to their new homes per the mapping table. Split `decisions.py` into reader (governance) and writer (runtime). Split `client.py` into three: governance coordinator, runtime facade, and consumer client SDK.

After this phase: `core/` is empty and deleted.

**Moves summary:**
- Governance: `registry.py`, `lifecycle.py`, `decisions_reader.py`, `reporting.py`, `testing_meta.py`, `coordinator.py`
- Runtime: `engine.py`, `pipeline.py`, `test_runner.py`, `validation_runner.py`, `mock_context.py`, `metrics.py`, `decisions_writer.py`, `tool_registry.py`, `runtime.py`
- Client: `inprocess.py`

UW call sites:
- [uw_demo/app/main.py](../../uw_demo/app/main.py): tool registration on runtime
- [uw_demo/app/ui/routes.py](../../uw_demo/app/ui/routes.py): `verity.runtime.execute_pipeline(...)`; audit reads from `verity.governance.*`

Optional-deps split added to `pyproject.toml`.

**Acceptance:** existing UW end-to-end flow (submit document → classify → extract → triage → audit trail) produces identical decision_log rows to pre-split baseline; test and validation runners produce identical metrics on seeded data.

### Phase 3 — Swap runtime engine to Claude Agent SDK

Replace the manual agentic loop in `runtime/engine.py` with Claude Agent SDK. Runtime's public interface (`run_agent`, `run_task`, `run_pipeline`, `register_tool`) stays the same — UW doesn't change.

- Add `claude-agent-sdk` to `[project.optional-dependencies].runtime` in `pyproject.toml`
- New `runtime/sdk_backend.py` — wraps `ClaudeAgentSDK.run()` behind the existing engine interface
- Tool adapter: wrap Verity tools (registered Python callables with input_schema/output_schema from the registry) as Claude Agent SDK `@tool` definitions
- **Decision log shape preserved (31 columns):** capture SDK events (LLM turns, tool calls, final output, tokens, duration, status) and project them into `DecisionLogCreate`. `message_history` and `tool_calls_made` populate from SDK events
- Mock/replay semantics: current `MockContext.from_decision_log` depends on controlling the LLM client directly. Options:
  1. Use SDK's built-in testing primitives if available
  2. Keep a minimal "replay mode" that bypasses the SDK for `audit_rerun` to preserve compliance reproducibility
  3. Document the tradeoff in the compliance UI
- Prompt assembly (template variable substitution from registry prompt_version records) stays in Runtime — Verity-specific, not SDK behavior
- Pipeline executor still orchestrates step groups and parallelism; each step calls the SDK-backed `run_agent`/`run_task`

**Acceptance:** UW flows work unchanged; decision logs still contain full `message_history` and `tool_calls_made`; at least one `audit_rerun` scenario reproduces output; token counts and durations align with prior runs within 10%.

### Phase 4 — Governance REST API + HTTP client mode

Add FastAPI REST endpoints to the governance plane so Runtime and UW can talk over HTTP instead of in-process imports. Enables separating services in Phase 5.

Endpoints (minimum):
- `GET /resolve/{entity_type}/{entity_name}?version_id=...&effective_date=...` → `ResolvedConfig`
- `POST /decisions` → record a decision, returns `decision_log_id`
- `GET /audit-trail/context/{id}`, `/audit-trail/run/{id}` → existing audit queries
- All 26+ admin UI routes stay as HTML

`verity.client.http.HTTPClient` implements the same interface as `InProcessClient`. UW and Runtime pick mode based on config.

**Acceptance:** `HTTPClient` roundtrips match `InProcessClient` byte-for-byte (same Pydantic models both sides); admin UI unchanged; OpenAPI spec generated from FastAPI endpoints.

### Phase 5 — Split into multiple Docker services

Break the single container into three services in `docker-compose.yml`:

- `verity` at `localhost:8000` (governance plane: FastAPI + Jinja admin UI + REST)
- `verity-runtime` at `localhost:8100` (execution plane: FastAPI REST wrapping runtime methods)
- `uw-app` at `localhost:8001` (existing UW FastAPI, calls both via HTTPClient)

All share `postgres` and `minio` containers. Anthropic API key injected into runtime service only. Runtime image is `pip install -e .[runtime]`; governance image is `pip install -e .`.

**Acceptance:** `docker-compose up` brings all three services online; UW end-to-end flow works via HTTP clients; independent restart of one service does not disrupt the others.

### Deferred (future work, not in scope for this plan)

- **Snowflake migration:** schema port, Snowpipe Streaming for decision log, connector swap, query dialect rewrites, stored-procedure gatekeeper for SCD Type 2. Re-evaluate when a paid Snowflake account is available.
- **SPCS deployment:** requires paid Snowflake.
- **Cortex adoption:** Cortex Search over document text, Cortex COMPLETE as a secondary LLM backend, Cortex Agents as a second Runtime backend.
- **Airflow for batch workloads:** validation runs over GT datasets, audit reruns, nightly classifications.
- **FC-12 composition immutability via DB triggers:** remains app-layer only.

## Critical Files to Modify

| Area | Path | Action |
|---|---|---|
| Contracts | new: `verity/src/verity/contracts/` | Phase 1: create subpackage, migrate boundary models |
| Governance subpackage | new: `verity/src/verity/governance/` | Phase 2: move registry/lifecycle/decisions_reader/reporting/testing_meta |
| Runtime subpackage | new: `verity/src/verity/runtime/` | Phase 2: move execution/pipeline/runners/mock/metrics/decisions_writer/tool_registry |
| Client subpackage | new: `verity/src/verity/client/` | Phase 2: new InProcessClient; Phase 4: add HTTPClient |
| Delete `core/` | [verity/src/verity/core/](../../verity/src/verity/core/) | Phase 2 end: empty and remove |
| Runtime SDK backend | `verity/src/verity/runtime/sdk_backend.py` | Phase 3: Claude Agent SDK adapter |
| Governance REST API | new: `verity/src/verity/web/api/` | Phase 4: FastAPI endpoints for resolve, decisions, audit |
| Runtime REST API | new: runtime entry point | Phase 5: FastAPI wrapper around runtime methods |
| UW tool registration | [uw_demo/app/main.py](../../uw_demo/app/main.py) | Phase 2: register tools against runtime |
| UW pipeline calls | [uw_demo/app/ui/routes.py](../../uw_demo/app/ui/routes.py) | Phase 2: route execution calls via runtime |
| Docker compose | [docker-compose.yml](../../docker-compose.yml) | Phase 5: three services |
| Pyproject | [verity/pyproject.toml](../../verity/pyproject.toml) | Phase 3 & 5: optional-deps for runtime |

## Reusable Existing Work

- Registry ↔ Runtime seam is already clean per the code audit: ExecutionEngine depends on Registry via constructor injection, reads configs live, writes decisions through Decisions. No bidirectional coupling to unwind.
- The 31-column decision log shape ([DecisionLogCreate](../../verity/src/verity/models/decision.py)) is preserved exactly — the SDK's event stream is projected into the same model.
- The named-query loader in [db/connection.py](../../verity/src/verity/db/connection.py) stays unchanged (still psycopg, still Postgres).
- Prompt assembly logic (`_assemble_prompts`, template variable auto-extraction) is Verity-specific and stays in Runtime untouched — Claude Agent SDK handles the loop but doesn't own prompt templating.
- Pipeline executor's step-ordering and parallelism logic is independent of which LLM backend runs each step; it wraps `run_agent`/`run_task` which become SDK-backed in Phase 3.
- `MockContext`'s Pydantic shape is preserved as a contract; its runtime behavior may need partial reimplementation for SDK-backed runs.

## Verification

**Phase 1:** pytest + mypy strict clean on `verity.contracts`; all callers import boundary models from contracts.

**Phase 2:** UW end-to-end golden path (submit document → classify → extract → triage → audit trail) produces identical decision_log rows to pre-split baseline; run diff on decision_log JSONB fields to confirm; test and validation runners produce identical metrics on seeded data; `core/` directory is gone.

**Phase 3:** Same golden path runs via Claude Agent SDK; `message_history` and `tool_calls_made` populate in the decision log; at least one `audit_rerun` scenario reproduces output; agent with tool calls (triage_agent) executes and logs tool inputs/outputs.

**Phase 4:** `curl` against each REST endpoint returns Pydantic-shaped JSON; admin UI still renders; `HTTPClient` passes the same integration test suite as `InProcessClient`.

**Phase 5:** `docker-compose up` starts all services; UW flow works against HTTP-mode clients; independent restart of one service does not disrupt the others; logs flow to the existing file-based logging setup.
