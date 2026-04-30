# Verity Testing Roadmap

**Owner:** Anil
**Started:** 2026-04-30
**Status as of last update:** 353 tests, 20 commits on `feature/schema-security-pytest`

This is the working tracker for the Verity comprehensive-testing
initiative. Each completed wave is checked off; each backlog item has a
short scope note so a future session can pick it up cold.

---

## Status snapshot

### What's covered

| Surface | Layer | Tests | Notes |
|---|---|---|---|
| SQL splitter, named-query loader | Unit | 14 | Pure-Python, no I/O |
| Pydantic models (agent, task, prompt, tool, lifecycle, application, inference_config) | Unit | ~30 | Validation, defaults, round-trips |
| Schema apply + invariants (no collisions, expected schemas, FK integrity) | Integration | 9 | Includes `verity_compliance` rename guard |
| All ~150 named queries parse against current schema | Integration | 1 | EXPLAIN-every-query smoke |
| Cross-schema FKs (runtime → governance) | Integration | 5 | RESTRICT + CASCADE behavior |
| Migration idempotency, search_path persistence | Integration | 3 | apply_schema can run twice |
| Connection pool concurrency | Integration | 3 | 20-30 parallel queries |
| Domain factory builders (`make_agent`, `make_complete_agent`, `promote`, `set_champion`, …) | Integration | 17 | Used by every later test |
| Engine gateway: LLM (retry matrix, no-key, exhaustion) | Integration | 11 | `_gateway_llm_call` |
| Engine gateway: tool (mock paths, dispatch, errors, unknown transport) | Integration | 10 | `_gateway_tool_call` |
| Engine `run_agent`: step-mock, single-turn, multi-turn-with-tool, decision-log shape | Integration | 4 | Happy paths |
| Engine `run_agent` errors (depth limit, unknown agent, mock-missing) | Integration | 5 | Error matrix |
| Engine `run_task` happy paths | Integration | 4 | Step-mock + JSON parse |
| Engine `_delegate_to_agent`: shape/depth/auth guards + happy path | Integration | 7 | Includes FK-fixed nested delegation |
| Engine `_resolve_sources` (input./const:/fetch:, malformed, mock) | Integration | 5 | Wiring DSL |
| Engine `_write_targets` + `_effective_write_mode` | Integration | 12 | Pure-unit gate + integration writes |
| Engine `run_tool` (post entity_type CHECK fix) | Integration | 5 | Now writes audit rows correctly |
| Governance lifecycle: every legal/illegal transition, gate semantics | Integration | 13 | 7-state machine |
| Governance approval gates (staging→shadow, shadow→challenger, full champion gate, fast-track) | Integration | 8 | Per-gate evidence |
| Governance champion swap (pointer flip, prior deprecation) | Integration | 3 |  |
| Governance rollback (champion → deprecated, audit row) | Integration | 4 |  |
| TestRunner orchestration (run_suite, _compute_metrics) | Integration + Unit | 10 | Fake engine for orchestration |
| REST API: registry, lifecycle, applications, decisions, models, runs, authoring, draft_edit | Integration | ~50 | Happy + 404 + 422 + 400 across sub-routers |
| REST API: quotas, usage, reporting, compliance_meta, runtime | Integration | ~25 | Most sub-routers near 100% line coverage |
| Compliance seeders (seed_static, seed_data) + coverage rollup | Integration | 11 | @pytest.mark.slow |
| Web admin UI smoke (landing pages + secondary + filters + compliance pages) | Integration | 39 | Renders-without-500 across ~25 routes |

**Cumulative: ~353 tests across unit + integration. Total coverage was 41% the
last time it was measured (after W2.5); subsequent waves added more without
measuring.**

### What's deferred (the backlog)

| Wave | Scope | Estimated tests | Why deferred |
|---|---|---|---|
| **W3.5** | ValidationRunner — ground-truth dataset + records + annotations + run_validation flow | 8-12 | Heavyweight setup; smaller coverage payoff than completed waves |
| **W4** | CLI smoke — `verity init`, `verity compliance show`, `seed-static`, `seed-data`, `seed-reports`, `export`, `publish` | 10-15 | Lower-priority; mostly thin argparse wrappers |
| **W5** | Worker — `verity_worker` startup, dispatch loop, run claim/release | 8-12 | Requires the worker process + a queue setup |
| **W6** | Web UI deeper — form-submit handlers, HTMX endpoints, filter/search variations, date-preset edge cases on `/runs` and `/decisions` | 15-20 | The biggest single uncovered file is `web/routes.py` (~514 unexercised lines) |
| **W7** | Real-LLM E2E (opt-in via `@pytest.mark.llm_real`, gated on `ANTHROPIC_API_KEY`) | 5-8 | Cost + flakiness; only run pre-release |
| **W8** | Snapshot tests via `syrupy` for engine `agent_decision_log` shape, resolved report dataset, export bundle manifest | 5-8 | Library is in dev deps, not yet wired |
| **W9** | Performance / load (concurrent `run_agent`, pool exhaustion under load) | 5-10 | Needs separate harness; smoke pool concurrency already covered |
| **W10** | Mutation testing (e.g. `mutmut` over `verity/src/verity/runtime`) | – | Run after coverage stabilizes; surfaces weak assertions |
| **W11** | Security sweep — SQL injection, log redaction, RBAC enforcement | 8-12 | Some pieces covered piecemeal already (parameter binding); needs targeted tests |
| **W12** | Connector providers — fetch happy paths through real `_resolve_sources` with registered fakes | 5-8 | Provider machinery is exercised via end-to-end engine tests; deeper unit tests would help |

---

## Known issues surfaced during the build

These are real bugs / gaps that the testing exposed; some are fixed,
some need follow-up.

| # | Issue | Status |
|---|---|---|
| 1 | `agent_decision_log.entity_type` CHECK rejected `'tool'`; `run_tool` silently produced `failed` ExecutionResults | **Fixed** in commit `135bac0` (CHECK widened to `IN ('agent', 'task', 'tool')`). Existing dev DBs need an `ALTER TABLE` (see migration snippet at the bottom of this doc) |
| 2 | `TestRunner._run_case` reads `case.get("entity_name", "")` and passes it to `engine.run_agent(agent_name=…)`, but the test_case row carries no `entity_name` column. The runner falls back to empty string and the registry lookup fails. | **Open** — production callers depend on this through `web/routes.py` line 1173. Two fixes possible: (a) JOIN through suite.entity_id → agent.name in `list_test_cases_for_suite`; (b) resolve entity_name once at `run_suite` start from the suite row. |
| 3 | `_delegate_to_agent` happy path requires the parent decision_log row to exist for the sub-agent's `parent_decision_id` FK — calling the method directly with a fabricated UUID fails. Production threads in the parent's pre-generated `self_decision_id` BEFORE the parent's row is written. The flow is correct, but the FK timing is fragile. | **Documented** — test pre-inserts a parent decision row to satisfy the FK. Worth a comment in `engine.run_agent` explaining the timing. |
| 4 | Multiple files have `psycopg_pool` deprecation warnings: `opening the async pool AsyncConnectionPool in the constructor is deprecated`. Affects every Database connect() call. | **Open** — switch to `await pool.open()` or context-manager form. |
| 5 | `web/api/feed.py` line 142 uses `regex=` query param (deprecated in FastAPI; should be `pattern=`) | **Open** — one-line change |

---

## Test infrastructure — quick reference

### Layout

```
verity/tests/
  conftest.py                    # session template DB + per-test clone
  fixtures/
    builders.py                  # make_agent, make_task, …, promote,
                                 #   set_champion, make_test_suite,
                                 #   make_test_case, set_gate_flags
    canonical_seed.py            # seeded into the template once
    fakes.py                     # FakeAnthropicClient, FakeEdmsProvider,
                                 #   text_response, tool_use_response
  unit/
    models/                      # Pydantic model tests
  integration/
    db/                          # schema, FKs, idempotency, pool, queries
    governance/                  # lifecycle, approvals, registry, builders
    engine/                      # gateways, run_agent, run_task,
                                 #   delegation, sources, write_targets,
                                 #   run_tool, test_runner
    api/                         # one file per FastAPI sub-router
    web/                         # admin web UI smoke + extended
    compliance/                  # seed_static, seed_data, coverage rollup
```

Auto-marker hook in `tests/conftest.py` applies layer + domain markers
based on file path. So `pytest -m engine`, `pytest -m unit`,
`pytest -m 'integration and db'`, `pytest -m 'not slow'` all work
without per-test decorators.

### Running

```bash
# Full suite
./scripts/test.sh

# Fast loop (no Docker required)
pytest -m unit

# Skip slow tests (compliance seeders + web compliance pages)
pytest -m 'not slow'

# By domain
pytest -m engine
pytest -m governance

# With coverage
pytest --cov                           # uses .coveragerc
pytest --cov --cov-report=html         # HTML report in htmlcov/

# Preserve a failing test's DB clone for psql inspection
pytest --preserve-test-db
```

### CI safety

`tests/conftest.py:pytest_configure` refuses to run if
`VERITY_TEST_DATABASE_URL` points at any application database
(`verity_db`, `uw_db`, `edms_db`, `pas_db`). The fixture creates
per-test `verity_test_<uuid>` clones from a session template
(`verity_test_template`).

---

## Sequencing recommendation

If picking this up cold, the highest-value next chunks (in order):

1. **Fix issue #2 (TestRunner.entity_name)** — production has a real
   gap; fixing it lets W3.5 (ValidationRunner) and a deeper
   TestRunner test pass against real engine.run_agent (no fake
   needed). Small SDK change + 2-3 new tests.
2. **W6 (web routes deeper)** — biggest single uncovered file
   (~514 lines). HTMX + form handlers are real surfaces users hit.
   Existing web smoke tests already cover the read path; this is
   incremental.
3. **W3.5 (ValidationRunner)** — once issue #2 is fixed, this
   exercises the test-runner-style flow against ground-truth
   datasets. Higher coverage than CLI/worker.
4. **W4 (CLI) + W5 (worker)** — lower priority; thin wrappers.
5. **W11 (security sweep)** — pre-release; some pieces already
   covered.

W7-W10 are post-stabilization (E2E, snapshot, perf, mutation).

---

## Migration snippet for issue #1

For dev/staging DBs that were created before `135bac0`:

```bash
docker exec verity_postgres psql -U verityuser -d verity_db -c "
  ALTER TABLE runtime.agent_decision_log
      DROP CONSTRAINT agent_decision_log_entity_type_check;
  ALTER TABLE runtime.agent_decision_log
      ADD  CONSTRAINT agent_decision_log_entity_type_check
      CHECK (entity_type IN ('agent', 'task', 'tool'));
"
```

Test DBs created via `apply_schema` get the wider CHECK automatically.

---

## Branch state at the time of this doc

20 commits on `feature/schema-security-pytest`:

```
135bac0 fix(db): widen agent_decision_log entity_type CHECK to include 'tool'
1d2c79e test(verity): W3.4 — extended web UI smoke
5022789 test(verity): W2.8 — run_tool tests pin known schema-CHECK bug
d33509b test(verity): W2.7 — engine _write_targets + write-mode gate
d52cd70 test(verity): W2.6 — engine delegation + source resolution
48b5022 test(verity): W2.5 — quotas, usage, reporting, compliance_meta, runtime API
b2b5e8c test(verity): W2.4 — TestRunner orchestration + metric helpers
fe63f70 test(verity): W2.3 — runs, authoring, draft-edit REST endpoints
442a453 test(verity): W3.3 — web UI smoke tests
3d62af1 test(verity): W3.1 — compliance seeders + coverage rollup
… plus the earlier W1.x and PR1-3 schema work
```
