# Task Data Sources & Targets — Implementation Plan

**Status:** **SUPERSEDED 2026-04-24** by
[verity_execution_architecture.md](verity_execution_architecture.md) and the
`source_binding` + `write_target` + `target_payload_field` tables defined
there. The conceptual goal (declarative input resolution and output writes
for Tasks) is preserved; the concrete schema is now the unified grammar
applied symmetrically to Tasks and Agents.

**Original status:** Design approved, ready to implement
**Original date:** 2026-04-21
**Scope:** Give Tasks first-class declarative I/O so they can resolve data from
external systems (EDMS v1) without the caller pre-resolving it. Symmetric
sinks (targets) for writes. Full mocking support for test & validation runs.

---

## Why

Today, a Task receives an `input_data` dict and substitutes template variables.
If a Task needs a document from EDMS, the **caller** must fetch it first. That
pushes EDMS knowledge into every caller (pipeline, validation runner, test
runner, UI, seed scripts). The immediate bug: validation runs on ground-truth
records fail because no caller fetched `document_text` before calling the Task.

Tasks cannot call tools (that's an Agent). So the answer is **declarative,
pre-call resolution**: a TaskVersion declares which input fields are *references*
resolved via a registered connector, and where the resolved payload binds in
the prompt. Mirror on the output side with optional targets for writes.

---

## Concepts

- **Data connector** — a registered integration (e.g., `edms`). Verity stores
  the name + config; the consuming app wires a provider callable at startup.
  Verity never imports EDMS.
- **Source** — per-TaskVersion row: "if the caller passes `policy_ref`, resolve
  via connector X using method Y, bind result to template var `policy_text`."
- **Target** — per-TaskVersion row: "take output field `extracted_policy` and
  write via connector X using method Y." Fired only in production-class runs.
- **Mock** — overrides source/target resolution in test/validation runs. Uses
  the existing `test_case_mock` / `ground_truth_record_mock` tables, extended
  with a discriminator column.

---

## Schema changes

### New table: `data_connector`

```sql
CREATE TABLE data_connector (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(100) NOT NULL UNIQUE,   -- "edms"
    connector_type  VARCHAR(50)  NOT NULL,          -- "edms" (only type in v1)
    display_name    VARCHAR(200) NOT NULL,
    description     TEXT,
    config          JSONB NOT NULL DEFAULT '{}',    -- base_url, auth_ref, etc.
    owner_name      VARCHAR(200),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

Registered once at app startup by `uw_demo/app/setup/register_all.py` (v1: one
row, `name='edms'`).

### New table: `task_version_source`

```sql
CREATE TABLE task_version_source (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_version_id         UUID NOT NULL REFERENCES task_version(id) ON DELETE CASCADE,
    input_field_name        VARCHAR(100) NOT NULL,   -- caller passes this key
    connector_id            UUID NOT NULL REFERENCES data_connector(id),
    fetch_method            VARCHAR(100) NOT NULL,   -- "get_document_text"
    maps_to_template_var    VARCHAR(100) NOT NULL,   -- "{{document_text}}"
    required                BOOLEAN NOT NULL DEFAULT TRUE,
    execution_order         INTEGER NOT NULL DEFAULT 1,
    description             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tvs_field UNIQUE (task_version_id, input_field_name),
    CONSTRAINT uq_tvs_var   UNIQUE (task_version_id, maps_to_template_var)
);

CREATE INDEX idx_tvs_task_version ON task_version_source(task_version_id);
```

### New table: `task_version_target`

```sql
CREATE TABLE task_version_target (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_version_id         UUID NOT NULL REFERENCES task_version(id) ON DELETE CASCADE,
    output_field_name       VARCHAR(100) NOT NULL,   -- key in Task output
    connector_id            UUID NOT NULL REFERENCES data_connector(id),
    write_method            VARCHAR(100) NOT NULL,   -- "create_document"
    target_container        VARCHAR(200),            -- optional collection/folder
    required                BOOLEAN NOT NULL DEFAULT FALSE,
    execution_order         INTEGER NOT NULL DEFAULT 1,
    description             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tvt_field UNIQUE (task_version_id, output_field_name)
);

CREATE INDEX idx_tvt_task_version ON task_version_target(task_version_id);
```

### Extend `test_case_mock` and `ground_truth_record_mock`

Add a discriminator + rename `tool_name` to `mock_key` (generalized):

```sql
ALTER TABLE test_case_mock
    ADD COLUMN mock_kind VARCHAR(20) NOT NULL DEFAULT 'tool'
        CHECK (mock_kind IN ('tool', 'source', 'target'));
ALTER TABLE test_case_mock RENAME COLUMN tool_name TO mock_key;

ALTER TABLE ground_truth_record_mock
    ADD COLUMN mock_kind VARCHAR(20) NOT NULL DEFAULT 'tool'
        CHECK (mock_kind IN ('tool', 'source', 'target'));
ALTER TABLE ground_truth_record_mock RENAME COLUMN tool_name TO mock_key;
```

Semantics:
- `mock_kind='tool'` + `mock_key='get_loss_runs'` → Agent tool mock (unchanged).
- `mock_kind='source'` + `mock_key='policy_ref'` → Task source mock; engine
  skips connector, binds `mock_response` to the mapped template var.
- `mock_kind='target'` + `mock_key='extracted_policy'` → Task target mock;
  engine logs intended write, does not call connector.

---

## Code changes

### `verity/src/verity/models/` — new models

- `DataConnector` — matches `data_connector` table.
- `TaskVersionSource`, `TaskVersionTarget` — match new tables.
- Extend `TestCaseMock` / `GroundTruthRecordMock` with `mock_kind`, rename
  field to `mock_key`.

### `verity/src/verity/core/connectors.py` — new module

Pluggable provider registry. Verity exposes:

```python
class ConnectorProvider(Protocol):
    async def fetch(self, method: str, ref: Any) -> Any: ...
    async def write(self, method: str, container: str | None, payload: Any) -> Any: ...

_REGISTRY: dict[str, ConnectorProvider] = {}

def register_provider(name: str, provider: ConnectorProvider) -> None: ...
def get_provider(name: str) -> ConnectorProvider: ...
```

The consuming app (`uw_demo`) registers `edms` at startup with an `EdmsProvider`
that wraps the existing `EdmsClient`. Verity does not import EDMS.

### `verity/src/verity/core/execution.py` — source/target resolution

Add to the Task execution path (before prompt build, after MockContext is set):

```python
async def _resolve_sources(task_version_id, input_data, mock_ctx) -> dict:
    """Returns dict of template_var -> resolved_value."""
    sources = await load_task_version_sources(task_version_id)
    resolved = {}
    for src in sources:
        ref = input_data.get(src.input_field_name)
        if ref is None:
            if src.required:
                raise MissingSourceRef(src.input_field_name)
            continue
        # Check mock first
        if mock_ctx and src.input_field_name in mock_ctx.source_mocks:
            resolved[src.maps_to_template_var] = mock_ctx.source_mocks[src.input_field_name]
            continue
        provider = get_provider(connector_name_for(src.connector_id))
        resolved[src.maps_to_template_var] = await provider.fetch(src.fetch_method, ref)
    return resolved
```

Merge `resolved` into the template context before prompt substitution.

Targets run *after* the Task's structured output is available, gated on
execution channel (only `champion` / `production` fire real writes; test,
validation, shadow log-only).

### `MockContext` extension

```python
@dataclass
class MockContext:
    tool_mocks: dict[str, Any] = field(default_factory=dict)
    source_mocks: dict[str, Any] = field(default_factory=dict)
    target_mocks: set[str] = field(default_factory=set)
```

Loaders in `test_runner.py` and `validation_runner.py` populate all three from
the `*_mock` tables by `mock_kind`.

### SQL queries — new files/sections

- `verity/src/verity/db/queries/connectors.sql` — CRUD for `data_connector`.
- `verity/src/verity/db/queries/registration.sql` — add inserts for
  `task_version_source`, `task_version_target`.
- `verity/src/verity/db/queries/registry.sql` — add `list_task_version_sources`,
  `list_task_version_targets`.
- `verity/src/verity/db/queries/testing.sql` — update mock queries to accept
  `mock_kind`; add filters by kind.

### Registry / Client API

Extend `verity.register_task_version(...)` to accept optional
`sources=[...]` and `targets=[...]` lists. Each entry is a small dict:

```python
sources=[
    {"input_field": "document_ref", "connector": "edms",
     "method": "get_document_text", "template_var": "document_text", "required": True}
]
```

### Decision log

Every resolved source / fired target / mocked call gets a structured entry in
`agent_decision_log` under a new `decision_log_detail` category:

```json
{
  "event": "source_resolved",
  "input_field": "document_ref",
  "connector": "edms",
  "method": "get_document_text",
  "ref": "doc-abc",
  "mocked": false,
  "bytes_returned": 14523
}
```

This is how governance knows what Tasks actually read/wrote.

---

## UI changes

### Task detail page

New "Data Sources" section listing sources for the current version (connector,
method, template var, required). New "Data Targets" section (usually empty).

### Ground-truth record detail

Existing "Mocks" section becomes tabbed: **Tool mocks | Source mocks | Target
mocks**. Add-mock form has a kind dropdown; key field becomes a dropdown of
the TaskVersion's declared sources/targets when kind is source/target.

### Validation run detail

Show which sources were resolved vs. mocked for each record. Helps debug
"Claude saw no document" issues in one glance.

---

## Migration / Application strategy

1. Add the new tables and extend `*_mock` tables in `schema.sql`.
2. Drop & recreate the database (demo-only — no production data). Seed script
   runs from clean.
3. Update `seed_governance_artifacts` to register the `edms` connector and
   declare sources on the classifier / extractor TaskVersions.
4. Update ground-truth seeding: records store `document_ref` in `input_data`,
   not pre-resolved `document_text`. Validation resolves at run time.

---

## Implementation order (one PR each; run tests between)

### Phase 1 — Schema + models + connector registry (no behavior change)
1. Add `data_connector`, `task_version_source`, `task_version_target` tables.
2. Extend `*_mock` tables with `mock_kind` + rename to `mock_key`.
3. Pydantic models for all new tables.
4. SQL queries (CRUD for connector, registration, listing).
5. `core/connectors.py` provider registry (empty at this phase).
6. **Verify:** `docker compose up` works, schema loads, existing flows still run
   (no tasks have sources yet, so execution path is unchanged).

### Phase 2 — Execution engine wires source resolution
7. Extend `MockContext` with `source_mocks` / `target_mocks`.
8. Add `_resolve_sources` to execution path; merge into template context.
9. Load mocks by `mock_kind` in `test_runner.py` and `validation_runner.py`.
10. Decision log entries for source resolution (`event: source_resolved`).
11. **Verify:** run an existing task that has no declared sources — behavior
    unchanged.

### Phase 3 — EDMS provider + first real source
12. Create `uw_demo/app/edms_provider.py` implementing `ConnectorProvider`
    over the existing `EdmsClient`.
13. Register the `edms` connector + provider at app startup.
14. Declare `document_ref → document_text` source on the classifier TaskVersion
    (and extractor).
15. Change ground-truth seeding to pass `document_ref` only.
16. **Verify:** run validation on a GT dataset — Claude now receives
    `document_text` resolved from EDMS. The "0 annotated / empty output" bug
    goes away.

### Phase 4 — Targets (optional for v1 if time-constrained)
17. Add target resolution post-output, gated by execution channel.
18. Wire one target on the extractor: writes extracted JSON as an EDMS
    document linked to the original.
19. **Verify:** production-class run writes; validation run logs but doesn't
    write.

### Phase 5 — UI
20. Task detail: Sources / Targets sections.
21. GT record detail: tabbed mocks; kind-aware add form.
22. Validation run detail: "source resolution" column.

---

## Decisions (locked in 2026-04-23)

1. **Connector config storage.** Env vars for secrets (API keys, auth tokens).
   DB `data_connector.config` JSONB for non-secret tuning only (base URLs for
   dev/prod split, timeouts, feature flags).
2. **Target firing rule.** Default gate: only `champion` writes for real;
   every other channel is log-only. **Runtime override required**: callers
   can pass `dry_run=True` to force log-only even on champion (useful for
   replay, debugging, shadow comparisons). Implementation: execution engine
   accepts an explicit `write_mode` parameter — `"auto"` (channel-gated,
   default), `"log_only"` (forced dry run), `"write"` (forced, requires
   explicit opt-in, used only by production callers).
3. **Source resolution.** Eager — all required sources resolved before prompt
   build. Resolution order = `task_version_source.execution_order`.
4. **Error policy.** Any source resolution failure is a hard fail —
   `SourceResolutionError`. `required=False` only means "caller may omit the
   ref"; if a ref *is* provided, it must resolve successfully.

---

## Files touched (summary)

**New:**
- `verity/src/verity/core/connectors.py`
- `verity/src/verity/db/queries/connectors.sql`
- `uw_demo/app/edms_provider.py`

**Modified:**
- `verity/src/verity/db/schema.sql`
- `verity/src/verity/db/queries/registration.sql`
- `verity/src/verity/db/queries/registry.sql`
- `verity/src/verity/db/queries/testing.sql`
- `verity/src/verity/models/` (new model files + mock model updates)
- `verity/src/verity/core/execution.py`
- `verity/src/verity/core/test_runner.py`
- `verity/src/verity/core/validation_runner.py`
- `verity/src/verity/core/client.py` (register_task_version signature)
- `verity/src/verity/core/registry.py`
- `verity/src/verity/web/routes.py`
- `verity/src/verity/web/templates/task_detail.html`
- `verity/src/verity/web/templates/ground_truth_record.html`
- `verity/src/verity/web/templates/validation_run_detail.html`
- `uw_demo/app/setup/register_all.py` (register connector + sources)
- `uw_demo/app/setup/seed_edms.py` (no change — already returns doc IDs)
