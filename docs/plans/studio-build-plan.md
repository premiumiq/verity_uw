# Verity Studio — Build Plan

**Status:** design proposed 2026-04-30. Awaiting approval before any code lands.
**Scope:** Vision, architecture, development guidelines, testing strategy, and phased work plan for the Verity Studio capability — the authoring/governance frontend for non-developer users.
**Predecessors:** [docs/enhancements/verity-studio.md](../enhancements/verity-studio.md) (sketch, superseded by this doc), [docs/architecture/execution.md](../architecture/execution.md) (locked I/O architecture).
**Audience:** Verity engineering (build), product (sequencing), governance officers and UW analysts (eventual users).

---

## 1. Vision

### 1.1 Today
Composing AI assets in Verity is a developer activity. Registering an agent, wiring its source bindings, authorizing tools, building test cases, uploading ground truth, and driving the lifecycle all require Python scripts (canonical example: `uw_demo/app/setup/seed_uw.py`). The Admin UI offers read-only views — a console, not an authoring surface.

The people accountable for AI behavior — underwriters, governance reviewers, compliance officers, SMEs — cannot author or modify the assets directly. Every change funnels through engineering, which slows iteration, decouples accountability from authorship, and limits adoption past the demo stage.

### 1.2 Tomorrow
Verity Studio is the authoring environment for Verity assets. SMEs compose, validate, deploy, and govern AI components themselves. Engineers continue to use the SDK and YAML for batch and scripted work. Both surfaces feed the same registry over the same `/api/v1/*` API; nothing Studio writes bypasses governance.

### 1.3 Beachhead
The first audience is the UW underwriting demo: UW analysts as authors, governance officers as approvers, the CIO/CTO as observer. Studio's first end-to-end loop is "an underwriter clones the champion decision agent, edits a system prompt, runs validation against ground-truth submissions, and promotes a candidate" — without writing any Python.

### 1.4 Anti-goals
- **Not a generic AI-workflow builder.** LangFlow, n8n, Flowise exist. Studio is governance-first, schema-strict, lifecycle-aware. We will not optimize for "look how many nodes you can drag".
- **Not an LLM playground.** The DS workbench (JupyterLab) is for ad-hoc experimentation. Studio is for assets that will be governed.
- **Not a VS Code replacement.** Studio is a web app. A future thin VS Code extension calling the Verity CLI is acceptable; a custom IDE inside Studio is not.
- **Not a runtime.** Studio composes; the runtime executes. Studio's preview pane calls the existing `/run_agent` and `/run_task` endpoints; it does not contain its own execution loop.

### 1.5 Success criteria
A non-developer SME can, via Studio alone:
1. Clone a champion agent_version, modify its prompts and source bindings, save as draft.
2. Run a validation batch against ground-truth records, see per-case pass/fail.
3. Promote the draft through the lifecycle (draft → candidate → staging → shadow → challenger), ending one approval short of champion.
4. Export the resulting agent_version and all its dependencies as a YAML bundle, re-import it in a clean environment, and produce a byte-identical registry state.

---

## 2. Architecture

### 2.1 Position in the stack
Studio is a **UI plane** layered on the existing REST API. It introduces no parallel write paths; every authoring action ultimately calls a `/api/v1/*` endpoint.

```
┌─────────────────────────────────────────────────────────────┐
│  Verity Studio (web UI, served by main FastAPI app)         │
│  /studio/compose · /studio/validate · /studio/deploy        │
│  /studio/govern                                             │
└──────────────────────────┬──────────────────────────────────┘
                           │  /api/v1/* — same endpoints SDK + CLI use
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Verity Registry & Runtime (governance schema + engine)     │
└─────────────────────────────────────────────────────────────┘
```

Studio is **not** a separate Docker service. It mounts at `/studio/*` on the existing FastAPI process — same pattern the Admin UI uses today. One process, one auth boundary, one deployment.

### 2.2 Four-mode information architecture
Top-level navigation (left rail):

| Mode | Purpose | Primary entities | Primary actions |
|---|---|---|---|
| **Compose** | Author packages | agent_version, task_version, prompt, tool, inference_config, data_connector | clone-to-draft, edit, wire, fork-to-private, promote-to-library |
| **Validate** | Test before promoting | validation_run, test_suite, ground_truth_dataset | run preview, run batch, drill-down per case, attach as evidence |
| **Deploy** | Drive lifecycle | agent_version, task_version, prompt_version, approval_record | promote, rollback, multi-select promote, diff-against-champion |
| **Govern** | Oversight + policy | approval_record, promotion_policy, redundancy reports | review approvals inbox, configure policies, review duplication, audit trail |

A future **Compliance** plane (mappings, gap analyses, evidence packages, remediation reports) sits as a peer top-level above Studio. It is out of scope here; reference: `docs/architecture/compliance-stack.md`.

### 2.3 The unit of composition
The `agent_version` (or `task_version`) row IS the package manifest. Everything Studio composes hangs off it:

- One `inference_config` (FK)
- N prompts via `entity_prompt_assignment`
- N tools via `agent_version_tool` / `task_version_tool`
- N source bindings via `source_binding`
- N write targets via `write_target` + `target_payload_field`

Studio's editor is therefore a **version editor**: the user is always editing a draft `*_version` row. Cloning is the primary authoring gesture — non-draft versions are immutable; "edit" silently means "clone to draft, then edit the draft".

### 2.4 Embed vs. share (Option B for prompts)

Today every prompt lives in a flat global namespace (`governance.prompt`). This causes three problems at scale: pollution of the shared list, accidental blast radius when editing a "shared" prompt, and naming theater (`uw_decision_system_prompt_v2_revised_FINAL`).

**Resolution:** two-tier scoping for prompts only.

```sql
ALTER TABLE governance.prompt ADD COLUMN scope TEXT NOT NULL
  DEFAULT 'global' CHECK (scope IN ('global','private'));
ALTER TABLE governance.prompt ADD COLUMN owner_entity_type TEXT;
ALTER TABLE governance.prompt ADD COLUMN owner_entity_id UUID;
-- Constraint: scope='private' requires owner_entity_*; scope='global' forbids it.
```

Two new authoring gestures:
- **Fork to Private** — clone a global prompt into a private prompt scoped to the current draft, so this agent's needs no longer affect others.
- **Promote to Library** — convert a private prompt to global when it earns reuse.

UI consequences:
- The "+Add Prompt" picker in Compose has two sections: "Library" and "This agent" (private).
- Editing a global prompt shows a live "Used by N versions" panel listing each consumer's lifecycle state. If any consumer is in `champion` or `challenger`, the editor blocks in-place save and forces clone-to-draft. This rule is the cheap insurance policy that makes accidental production changes structurally impossible.

**Tools stay global.** They are code/integration assets bound to `implementation_path`; "private tool" makes no sense.

**Inference configs stay global.** Add scoping later only if the prompt model proves it.

### 2.5 Reference grammar in the UI
The four-pattern grammar from `docs/architecture/execution.md` (`input.*`, `source.*`, `literal.*`, `context.*`) becomes a first-class UI surface:

- An **autocomplete control** in source-binding and target-payload editors. Typing `$.` opens a tree picker over the available references for the current draft.
- The picker is computed server-side per draft (Studio asks: "what references are valid for this agent_version?"); no client-side schema duplication.
- Validation runs on save: invalid references block save with a precise error.

### 2.6 YAML round-trip
Every entity has a YAML representation. The unit of export is a **bundle**: an entity plus everything it depends on (prompts, tools, configs, connectors, source bindings, target payload fields). On import, the bundle is validated, then created as drafts (never as champion — champion always requires explicit human promotion).

Two new endpoints:
- `POST /api/v1/yaml/export` — body: `{entity_type, entity_id}`. Returns: YAML text containing the version + all transitive dependencies, with stable ordering.
- `POST /api/v1/yaml/import` — body: YAML text. Returns: list of created/skipped entities with their new IDs. Idempotent on (name, version_label) pairs — re-importing the same bundle is a no-op.

A `verity` CLI wraps both: `verity export agent uw_decision > uw.yaml`, `verity import < uw.yaml`, `verity diff uw.yaml`. This is the side door for power users who want git, diffs, and their editor of choice.

### 2.7 Preview against any LLM (ephemeral overrides)
"Test using any LLM model available" requires running an existing agent_version against a different model without polluting the registry.

- New endpoint: `POST /api/v1/runs/preview`. Same shape as `/run_agent` but accepts an `inference_config_override` payload (model_name, temperature, max_tokens).
- Runs are tagged `experimental=true` in `decision_log`. Excluded from production telemetry.
- Hard rule: preview runs against `champion` versions are allowed but always tagged; they never count as production traffic.

### 2.8 Promote-from-batch (three modes, sequenced)
Implementation order matters for governance safety:

**First (S4):** *Promote with batch as evidence.* Author runs a validation batch in Validate, sees results, clicks Promote with the batch attached. Single-entity, human-driven, but gate inputs come pre-filled from the batch.

```sql
ALTER TABLE governance.approval_record ADD COLUMN evidence_run_id UUID
  REFERENCES governance.validation_run(id);
```

**Second (S4 late):** *Multi-select bulk promote.* Deploy view's pending list supports multi-select → single rationale → all advance. Hard guardrail: never allowed for transitions to `champion`. Champion promotion is always single-entity, single-rationale, deliberate.

**Third (S5+):** *Policy-driven auto-promotion.* New table:

```sql
CREATE TABLE governance.promotion_policy (
  id UUID PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  trigger TEXT NOT NULL CHECK (trigger IN ('validation_pass','shadow_period_complete','challenger_period_complete')),
  -- Hard rule enforced in app code, repeated as CHECK for safety:
  CHECK (to_state NOT IN ('champion'))
);
```

Auto-promotion is forbidden into `champion` and out of `draft`. Allowed only for `candidate→staging` and `shadow→challenger`.

### 2.9 AI-assisted authoring
A single endpoint, intent-routed:

```
POST /api/v1/studio/assist
{
  "intent": "improve_prompt" | "explain_agent" | "review_for_redundancy" | "suggest_schema_from_examples",
  "subject_type": "prompt_version" | "agent_version" | ...,
  "subject_id": "...",
  "context": {...}
}
```

Internally, `studio_assist` is a Verity task (yes — Studio dogfoods Verity). Its prompts and inference config are governed assets, versioned and lifecycle-controlled like any other. This means the assistant itself is auditable.

Redundancy review uses the existing `prompt_version.content_embedding` (vector(1536)). A nightly job populates pairwise similarity scores; Studio surfaces clusters above a threshold for human review.

### 2.10 Schema additions (consolidated)

| Change | Purpose | Phase |
|---|---|---|
| `updated_at TIMESTAMPTZ` (and optional `last_editor_name TEXT`) on each editable draft table where missing | Optimistic concurrency stamp (§2.14) | S0 |
| `prompt.scope`, `prompt.owner_entity_type`, `prompt.owner_entity_id` | Two-tier prompt scoping | S2 |
| `entity_prompt_assignment.is_local_copy` | Distinguishes a forked-private prompt from a library reference | S2 |
| `agent_version.editor_state` JSONB, `task_version.editor_state` JSONB | Studio's UI state per draft (tree expansion, selected node). Wiped on promotion. | S2 |
| `approval_record.evidence_run_id` UUID NULL FK | Links approval to validation evidence | S4 |
| `promotion_policy` table | Auto-promotion rules | S5 |
| `studio_assist_run` table | Audit log of AI-assisted authoring requests | S5 |

All migrations are additive. No existing column is dropped or retyped.

### 2.11 New API endpoints (consolidated)

| Endpoint | Purpose | Phase |
|---|---|---|
| `POST /api/v1/yaml/export` | Bundle out | S0 |
| `POST /api/v1/yaml/import` | Bundle in (creates drafts) | S0 |
| `GET /api/v1/where-used/{entity_type}/{id}` | Reverse lookup of consumers | S0 |
| `POST /api/v1/runs/preview` | Ephemeral inference_config override; tagged experimental | S3 |
| `GET /api/v1/redundancy/prompts` | Embedding-similarity clusters | S5 |
| `POST /api/v1/lifecycle/promote-batch` | Multi-entity promotion | S4 |
| `POST /api/v1/studio/assist` | AI-assisted authoring (intent-routed) | S5 |

No existing endpoint changes shape. Studio backend work is purely additive.

### 2.12 Frontend stack decision
Verity's existing UI is **Jinja + HTMX + Alpine + DaisyUI/Tailwind**. Studio stays in this family. Reasons:

- The user (and the broader Verity team) are not React developers. Adding a SPA toolchain is a tax we pay forever.
- HTMX with `hx-target` and `hx-swap` handles four-pane layouts cleanly. Each pane is its own swap target. Tree state lives in URL fragments; navigation is browser-native.
- Alpine.js handles small bits of client-side state (modal open/close, autocomplete dropdowns, drag-reorder).
- For "live preview against LLM" (streaming), HTMX SSE is sufficient.
- For drag-reorder of prompt assignments, Alpine + `Sortable.js` (small CDN library) is enough. Alternative: up/down buttons. Start with buttons.

What we are **not** adding: React, TypeScript build pipeline, separate Studio Docker service, CSS-in-JS.

The four-pane editor is the only screen with non-trivial interactivity. We accept that this screen will feel less fluid than a native SPA. That is a worthwhile trade for a simpler stack.

### 2.13 Where-used as a first-class concept
Every entity reference is bidirectional from Studio's perspective. A single SQL view computes consumers on demand:

```sql
CREATE VIEW governance.entity_consumers AS
  -- prompt -> agents/tasks consuming it
  SELECT 'prompt' AS used_type, p.id AS used_id,
         epa.entity_type AS consumer_type, epa.entity_version_id AS consumer_id
  FROM governance.entity_prompt_assignment epa
  JOIN governance.prompt_version pv ON pv.id = epa.prompt_version_id
  JOIN governance.prompt p ON p.id = pv.prompt_id
  UNION ALL
  -- tool -> agents/tasks
  SELECT 'tool', tool_id, 'agent_version', agent_version_id
  FROM governance.agent_version_tool
  UNION ALL
  SELECT 'tool', tool_id, 'task_version', task_version_id
  FROM governance.task_version_tool
  -- ... (configs, connectors)
;
```

Studio's "where used" warning panel is one query against this view. This is the foundation of the safe-edit guarantee in §2.4.

### 2.14 Concurrency model — optimistic, conflict-at-save

**Decision:** optimistic concurrency. Two users can open the same draft in parallel; the conflict is caught at save time, not edit time. We deliberately do **not** introduce locks, heartbeats, or admin force-release flows — that complexity is not justified for our user counts.

**How it works.**
- Every editable draft entity has an `updated_at TIMESTAMPTZ` column (most already do; we add it where missing as part of S0).
- On read, the API response includes the row's current `updated_at`.
- On save, the client sends back the `updated_at` it last saw, in a body field `expected_updated_at`.
- The server compares. If the row's current `updated_at` is newer than `expected_updated_at`, the save is rejected with `409 Conflict` and a payload identifying who saved last and when.

**UI behavior.**
- The editor shows a small "Last saved by Alice at 14:32" indicator — informational only, not a lock signal.
- On a `409` at save, Studio shows a modal: *"Alice saved changes at 14:42 after you started editing. Your edits are still here in the form. Click Reload to see Alice's changes (your edits will be preserved in a copy you can paste back), or click Overwrite to ignore Alice's changes."* The "preserve to copy" gesture lets the user keep their work even when reloading.
- Overwrite is allowed but writes an audit note (`approval_record`-adjacent) so a deliberate overwrite is visible after the fact.

**Schema impact.**
- Add `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` to any editable draft table that doesn't already have it. A trigger on update bumps it.
- Optional: `last_editor_name TEXT` on each draft table, so the conflict message can name the prior editor without a join.

**API impact.**
- Every PATCH endpoint that edits a draft accepts `expected_updated_at` in the request body and returns the new `updated_at` in the response.
- A new `409` shape, used uniformly: `{error_code: "stale_write", current_updated_at, last_editor_name, last_editor_at}`.

**What this gives us.** No silent overwrites — every save is checked against current state. Recovery is one reload + paste away.

**What it does not give us.** Proactive "another user is editing" awareness. Two SMEs can start editing the same draft in parallel and the second will only learn at save time. We accept this.

**Phase placement.** Schema additions and the `expected_updated_at` contract: **S0**. Editor integration (sending the field, handling 409): **S1**, alongside the first edit forms.

---

## 3. Development guidelines

### 3.1 Inherit from CLAUDE.md
All conventions in `/CLAUDE.md` apply to Studio code:
- All SQL in `.sql` files, never inline.
- All data models are Pydantic.
- The Verity package never imports from `uw_demo/`.
- Every AI invocation goes through the execution engine.
- No hardcoded AI parameters in business code.

### 3.2 Studio-specific conventions

**Naming.** Every user-facing string in Studio uses business vocabulary, not schema vocabulary. The schema says `agent_version`; the UI says "package" or "version". The schema says `entity_prompt_assignment`; the UI says "attached prompts". This is a translation layer in templates, not in code.

**Vault, not EDMS.** Per existing memory: UI says "Vault"; internal code keeps "EDMS" (variables, env vars, column names). Studio inherits this rule.

**Phase names.** Per existing memory: never "Phase 5", "S2", or similar in code, comments, docstrings, or test names. These appear only in this doc and in commit messages. Code names features (e.g., `prompt_scope`, `bulk_promote`), not phases.

**Routing.**
- `/studio/compose/...` — authoring views.
- `/studio/validate/...` — preview, test, batch.
- `/studio/deploy/...` — promotion workflow.
- `/studio/govern/...` — approvals inbox, audit, policy, redundancy.
- The four mode roots are real pages; deep links into them work and are share-able.

**Templates.** New templates live under `verity/src/verity/web/templates/studio/`, mirrored to the four modes. Shared partials in `studio/_partials/`. No template logic beyond `{% if %}` / `{% for %}`; computation lives in route handlers.

**Routes.** New route modules under `verity/src/verity/web/studio/`, one module per mode (`compose.py`, `validate.py`, `deploy.py`, `govern.py`). Plus `_shell.py` for the four-pane layout helpers.

**HTMX patterns.**
- Forms POST to a route that returns a partial; `hx-swap="outerHTML"` on the form replaces it with the saved view.
- Long-running actions (validation batch, preview run) return immediately with a "running" partial that polls via `hx-get` on a 1s interval until done.
- Streaming previews use SSE via `hx-ext="sse"`.

**Alpine.js usage.** Only for client-only state (dropdown open/close, tree expansion, modal visibility). Anything that touches the database goes through HTMX → server. No data fetching in Alpine.

**Error surface.** Every Studio action that can fail surfaces a human-readable error to a `#studio-toast` region. Stack traces never reach the user. The full error is logged with the run ID for engineering follow-up.

**Loading states.** Every async action shows a skeleton or spinner. Silence is a bug.

**Authentication.** Studio is unusable without per-user identity (so `approval_record.approver_name` is meaningful). Studio's auth dependency is the OIDC layer planned in `docs/enhancements/rest-api-auth.md`. Until that ships, Studio runs in a `single_user_mode=true` configuration with the approver name read from an environment variable. This is a development affordance, not a production posture.

**Code style.** Per existing user preference: simple, modular, copious comments, no cryptic names. Studio is the surface most likely to be read by non-engineers; readability of the code matters as much as the UI.

### 3.3 API design

- All Studio backend endpoints are under `/api/v1/`. There is no separate `/studio/api`. The web UI is one consumer of the same API the SDK and CLI use.
- New endpoints follow the existing patterns in `verity/src/verity/web/api/` — Pydantic request/response models, async handlers, dependency injection for the registry/runtime.
- No endpoint returns HTML. HTML is rendered in the route handler, never in the API.
- Every new endpoint has an OpenAPI description; the auto-generated `/docs` is the contract.

### 3.4 Governance gates

- Studio never bypasses lifecycle rules. Promotion still goes through `governance.lifecycle.promote()`. Studio is a UI over the rules, not an exception to them.
- The `lifecycle_state` of a draft is shown in the editor header at all times. If a user navigates to a non-draft version, the editor is read-only with a single CTA: "Clone to Draft".
- Every write action records who did it. Approval records include `approver_name` (from auth) and `approver_role` (from auth claims, if present).

### 3.5 Accessibility

- Keyboard navigation is required, not optional. The four-pane editor must be operable without a mouse.
- ARIA labels on tree nodes, form fields, and modals.
- Color is never the only indicator of lifecycle state — text and icon also.
- Focus rings visible.

This matters because governance officers may use assistive tech and because accessibility violations are sometimes regulatory issues for our domain.

---

## 4. Testing strategy

### 4.1 Test pyramid

| Layer | Tool | Scope | Run on |
|---|---|---|---|
| Unit | pytest | Pydantic models, YAML serializers, validators, reference-grammar parser | every commit |
| DB | pytest + template-DB cloning (already in place per commit `ebf9389`) | Schema migrations, where-used view, lifecycle state machine | every commit |
| API integration | pytest + httpx async client | Each new endpoint, end-to-end against a live test DB | every commit |
| Browser | Playwright | Golden paths through Compose / Validate / Deploy / Govern | nightly + pre-merge |
| Property | hypothesis | YAML round-trip, lifecycle state machine | nightly |

### 4.2 Specific test commitments

**YAML round-trip.** A property test: generate a random valid agent_version (with prompts, tools, bindings, targets), export to YAML, import to a clean DB, export again. The two exports must be byte-identical. This guards against silent serialization drift.

**Where-used integrity.** For every entity type, a fixture creates N consumers, deletes some, and asserts the where-used view returns exactly the live consumers. Run after every schema change.

**Lifecycle gates with bulk promotion.** Integration test: create 10 candidates, half passing gates and half failing, attempt bulk promote. Expected: passing ones promote, failing ones do not, the response reports per-entity status, no champion-bound entities are touched.

**Champion safety.** A negative test asserts that no code path — including bulk promote, auto-promote policy, YAML import, AI-assist — can advance an entity to `champion` without a human-issued single-entity `approve()` call.

**Stale-write rejection (§2.14).** Integration test: client A reads a draft, client B reads and saves the same draft, client A then attempts to save with the original `expected_updated_at`. Expected: client A's save fails with `409 stale_write`, the response names client B and the new timestamp, and the row's content is exactly what client B wrote. A second test confirms the same flow with the explicit "Overwrite" path: client A retries with `force_overwrite=true` and the row reflects A's content with an audit row recording the overwrite.

**Studio dogfood.** The AI-assist endpoint's own prompts are Verity prompt_version rows. Test: edit `studio_assist`'s system prompt via Studio itself, run it, observe the new behavior. This verifies the loop closes.

**Browser tests (Playwright).** Limited to four golden paths, one per mode:
1. *Compose:* clone champion → edit prompt → save draft → assert version row exists with new content.
2. *Validate:* select draft → run preview against ground-truth set → assert results render.
3. *Deploy:* select candidate with passing batch → promote with rationale → assert state transition + approval_record.
4. *Govern:* open approvals inbox → approve pending request → assert state transition.

We deliberately do NOT write Playwright tests for every form. The four golden paths are the regression suite; finer-grained UI behavior is covered by API tests against the same routes.

### 4.3 Test data

- Ground-truth fixtures live under `verity/tests/fixtures/studio/`. Each fixture is a YAML bundle that can be re-imported via the YAML import endpoint. This means our test fixtures double as documentation of valid bundles.
- The `pytest_template_db` machinery (introduced in commit `ebf9389`) gives every test a clean, fast clone of the schema. Studio tests use this; no test mutates a shared DB.

### 4.4 Coverage targets

- New backend code (routes, models, serializers): 90% line coverage.
- Schema migrations: 100% — every column added has at least one test that exercises it.
- Frontend templates: not measured directly; covered transitively by API tests and Playwright golden paths.

### 4.5 Continuous validation

- Every PR runs pytest + a smoke Playwright test (the Compose golden path only — full Playwright is nightly).
- Every merge to main runs the full test suite.
- A nightly job runs the YAML round-trip property test for 1000 iterations against random bundles. Failures page engineering.

---

## 5. Work plan

Phases are sequenced for governance safety and parallelizable surface area. Each phase has explicit exit criteria that gate the next.

### S0 — Foundations (Studio shell + YAML + where-used)
**Size:** ~2-3 weeks. **Parallelizable with UW facelift.**

**Scope:**
- New top-level `/studio` route with the four-mode shell (left rail, header, breadcrumb, mode roots as placeholder pages).
- `POST /api/v1/yaml/export`, `POST /api/v1/yaml/import`, `GET /api/v1/where-used/...`.
- `verity` CLI: `export`, `import`, `diff` subcommands.
- `governance.entity_consumers` view.
- Optimistic-concurrency contract (§2.14): `updated_at` columns added where missing; PATCH endpoints accept `expected_updated_at`; uniform `409 stale_write` shape on conflict.

**Exit criteria:**
- Round-trip property test green at 1000 iterations.
- A YAML bundle exported from one DB imports cleanly into another, producing identical row content.
- CLI subcommands documented in `docs/api/`.
- Studio shell renders all four modes with placeholder content; left rail navigation works.

**Why first:** YAML in git is an immediate value unlock for governance auditing — engineers can see what changed in a PR. Where-used is a prerequisite for safe editing in S1.

### S1 — Compose: single-entity editors
**Size:** ~3-4 weeks. **Depends on S0.**

**Scope:**
- Edit forms for prompt, inference_config, tool. Each form: lifecycle badge, where-used panel, save-as-draft, clone-to-draft action on non-draft versions.
- "Used by N versions" warning when editing a global asset; block in-place save for champion/challenger consumers.
- Order to build: prompts first (highest edit volume, smallest blast radius), then configs, then tools.

**Exit criteria:**
- An SME can edit a draft prompt's content and template variables via the UI; resulting `prompt_version` row matches what the API would have produced.
- Editing a global prompt with a champion consumer is blocked with a clear message and a clone-to-draft CTA.
- All forms keyboard-navigable.

### S2 — Compose: package editor (four-pane)
**Size:** ~4-6 weeks. **Depends on S1.**

**Scope:**
- Tree pane for agent_version / task_version (root → prompts → tools → configs → bindings → targets).
- Editor pane (tabs per concern), driven by current tree selection.
- Mini-canvas wiring view for source/target bindings (read-only visualization first; edit via form).
- Add/remove/reorder prompts in `entity_prompt_assignment`.
- Authorize tools.
- Reference grammar autocomplete in source-binding and target-payload editors.
- Embed-vs-share UX: scope selector on prompt creation, "Fork to Private" and "Promote to Library" gestures.
- Schema migrations: `prompt.scope`, `prompt.owner_entity_*`, `entity_prompt_assignment.is_local_copy`, `*_version.editor_state`.

**Exit criteria:**
- An SME can clone a champion agent_version, add a private prompt, wire a new source binding, and save — all without code.
- Reference-grammar autocomplete validates references against the current draft's available context.
- Existing global prompts continue to work unchanged (backwards compat).

### S3 — Validate
**Size:** ~3-4 weeks. **Depends on S2.**

**Scope:**
- Preview pane in Compose: schema-aware input form, run button, mock vs. live toggle, ephemeral LLM override.
- Output rendering: envelope, tool calls, prompt assembly, token + cost summary.
- Validation batch runner UI: pick ground-truth dataset → run → progress → per-case drill-down.
- New endpoint: `POST /api/v1/runs/preview` with `inference_config_override`.

**Exit criteria:**
- An SME can run a draft agent against a ground-truth set, see results, and identify which cases regressed against champion.
- Preview runs are tagged `experimental` in `decision_log` and excluded from production telemetry queries.

### S4 — Deploy
**Size:** ~2-3 weeks. **Depends on S3.**

**Scope:**
- Deploy view: list of pending candidates with state, owner, last-modified, gate status, ground-truth coverage.
- Promote-with-batch-evidence gesture. Schema migration: `approval_record.evidence_run_id`.
- Diff-against-champion view (prompt-by-prompt, tool-by-tool, config diff).
- Multi-select bulk promote (NOT to champion). Endpoint: `POST /api/v1/lifecycle/promote-batch`.
- Approval modal: rationale required, approver name from auth, evidence link if attached.

**Exit criteria:**
- An SME can take a draft from candidate to challenger via UI, attaching a validation_run as evidence at each gate.
- Multi-select promotion to champion is structurally impossible (covered by §4.2 champion-safety test).
- Diff view renders for all six pre-champion transitions.

### S5 — Govern
**Size:** ~2-3 weeks. **Depends on S4.**

**Scope:**
- Approvals inbox (queue of pending transitions assigned to current user).
- Audit trail viewer (filter by entity, date, approver; uses existing `approval_record`).
- Redundancy review: clusters of similar prompts above a configurable threshold, surfaced for human review. New endpoint: `GET /api/v1/redundancy/prompts`. Nightly job populates similarity scores.
- Promotion policy CRUD (auto-promote rules, narrow scope: candidate→staging, shadow→challenger only). New table: `governance.promotion_policy`.
- AI-assist endpoint: `POST /api/v1/studio/assist` with intents `improve_prompt`, `explain_agent`, `review_for_redundancy`. New table: `governance.studio_assist_run` for audit.

**Exit criteria:**
- Governance officer can review the approvals inbox and approve/reject from a single screen.
- Auto-promote policies are enforced for candidate→staging only; attempt to create a policy targeting champion is rejected.
- Redundancy view surfaces at least one true positive on the seeded UW data.
- AI-assist's own prompts are governed Verity assets, editable through Studio.

### S6 — Knowledge ontology
**Deferred** per stakeholder direction. No timeline. Listed here only to signal that the four-mode IA leaves room for a fifth mode if/when this lands.

### Total estimate
S0–S5: roughly 5–6 months of focused work. Some parallelization is possible (S0 in parallel with the in-flight UW facelift; S5's redundancy nightly job in parallel with S5 UI). The critical path is S1 → S2 → S3 → S4 → S5.

### Non-blocking dependencies
- The OIDC auth layer (`docs/enhancements/rest-api-auth.md`) should land before S5 in production, since approver identity is a governance requirement. Until then, S5 runs in `single_user_mode=true` for development and demos.
- The I/O re-arch (`docs/architecture/execution.md`) is locked as of 2026-04-25; Studio builds on top of it without modification.
- The UW facelift (`uw_demo/facelift-plan.md`) and Studio S0 share no surface area and can run concurrently. S1+ should defer until UW facelift ships its current phase, since both teams will edit the templates directory.

---

## 6. Open questions

These are deliberate gaps to resolve before S0 starts:

1. **Single-process vs. mounted sub-app.** Does Studio mount at `/studio/*` on the existing FastAPI process, or under a sub-app for isolation? Recommend the former (one process, simpler ops) but flag for review.
ANS: Agree with recommendation.

2. **Sub-agent delegation graph.** The 2026-04-25 stub mentioned visualizing parent → child agent relationships. Is this in S2 scope or deferred? Recommend deferred — it's a cross-package view that belongs in a future visualization layer, not the per-package editor.
ANS: The scope of composition is one agent at time. We will show dependencies, and it is up to the user to start from the right agent and work upwards. The child agent changes first, tested and promoted up to stage. Then the parent is edited, wired to the right sub-agent,  tested and promoted. 

3. **Real-time collaboration.** Two SMEs editing the same draft simultaneously: optimistic locking with last-write-wins, or pessimistic with explicit lock-acquire? Recommend optimistic + visible "another user is editing" banner; explicit lock is overkill for our user count.
ANS: Pessimistic.

4. **Pricing tier.** Studio is plausibly a paid-tier feature (since it unlocks non-engineering seats). This is a product decision, not engineering — flag for the eventual SKU conversation.
ANS: Okay.

5. **DS workbench integration.** Notebooks can already import the Verity SDK. Should Studio surface a "Open this draft in workbench" link? Recommend yes, deferred to post-S5; the link is a one-line addition once everything else works.
ANS: Good idea. I want to detail out the workbench integration as we get close to the stage.
---

## 7. Out of scope

To be explicit about what this plan does **not** cover:

- A node-and-edge visual canvas (LangFlow-style). Reconsider only if the four-pane editor proves insufficient.
- A VS Code extension. The CLI is the developer surface; a thin extension wrapping the CLI is a small future project.
- Real-time multi-user editing with operational transforms or live cursors. Concurrency is handled by the conflict-at-save model in §2.14.
- A mobile interface. Studio is a desktop-class tool.
- Compliance mappings, gap analyses, evidence packages — these are the future Compliance plane, separate work.
- Knowledge ontology / semantic search across all assets — S6, deferred.

---

## 8. Approval

Sign-offs needed before S0 starts:
- [x] Engineering: this build plan is implementable as written.
- [x] Product: four-mode IA matches user intent; phase sequencing matches business priorities.
- [x] Governance: champion-safety guarantees in §2.4 and §4.2 meet our governance bar.
- [x] Stakeholder (you): vision and scope match what you asked for.

Once approved, S0 work can begin. Each subsequent phase requires its predecessor's exit criteria to be green, but does not require an additional sign-off — this doc is the contract.
