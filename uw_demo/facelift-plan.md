# UW Demo — Strategic Facelift Plan (v4)

## Context

Started with a 7-item UI facelift. Strategic review surfaced three issues the original facelift would paper over: blocking POST handlers (UX trust), freeform `submission.status` (no state machine on UW side), and a hastily cobbled data model. Phase 6 (triage rendering) is already resolved.

Per user direction: **pragmatic, not ocean-boiling**. Adopt the part of the ontology we need now, with column shapes that map cleanly onto the eventual full structure. UW maintains submission state authoritatively; Verity tracks runs and receives override notifications via API. Easy UI lifts come first; deeper foundation work follows.

**Architectural calls in this revision:**
- Override delivery to Verity is **API-mediated** (`POST /api/v1/runs/{run_id}/overrides`). UW does not touch `verity_db` schema directly. Verity owns the schema and integrity checks.
- The override table is named `hitl_override` (not `agent_output_override`). Tasks get overridden too — classification, field extraction — not only agents. Naming the table by the *event* (a HITL correction) rather than the *producer* keeps it unbiased.
- `output_path` uses **JSONPath** (e.g. `$.fields.annual_revenue`, `$.risk_factors[0].factor`). Rationale: Verity outputs are nested JSON; flat keys can't address arrays or sub-objects. JSONPath is the right level of generality; locking it in early avoids string-rewriting later. Implementation detail can use a small library (`jsonpath-ng`) on the Verity side for resolution + integrity check.
- Document discovery is split from extraction. Discovery persists references in a uw_db `document` table. UW then tracks per-document extraction status. If a needed doc isn't there, UW can't proceed — it waits for upload.
- Override schema captures **both** technical anchor (`run_id` + `output_path`) and business identification (`application` / `entity_type` / `entity_reference` / `fact_type`). The two are parallel; the technical pair pinpoints the field within an AI run, the business quartet pinpoints the same fact in business terms.
- `submission_extraction` carries the Verity traceability needed to call the override API: the Verity **execution run id** (the runtime ID, distinct from the UW-side `workflow_run_id`) plus the **`output_path`** within that run's output. Without these on the row we can't make a clean override call when the human edits.
- HITL queue is **polymorphic**, not a single flat table. Different problem types (classification, extraction, discrepancy) have genuinely different shapes; one wide table with mostly-null columns is a smell. A generic `hitl_queue` row points to a per-type detail table; a `hitl_log` records actions (viewed, reassigned, resolved, waived).

The intended outcome: a UW demo with persisted document references, a real submission state machine, async runs that survive page navigation, structured per-field provenance powering the sparkle/pen UX, AI corrections propagating to Verity as governance signal, and a HITL queue surface.

---

## What This Plan Covers vs. Defers

**In scope:**
- `document` reference table in uw_db (links to EDMS / Vault)
- Discovery step that persists doc references; per-document extraction status
- Submissions list facelift (with `# Docs` column)
- Documents panel on detail page (classification pills)
- `submission_status_enum` + `submission_event` (append-only audit log covering state changes, user actions, and pipeline events — replaces the originally planned narrower `submission_status_history`)
- Async run wiring + idempotency guard + run-status polling endpoint
- `submission_extraction` extended with provenance fields (incl. `ai_found` flag, `hitl_value`)
- `submission_extraction_audit` append-only log
- Form layout for Details tab
- Sparkle + pen edit affordance with provenance tooltip
- Verity REST endpoint `POST /api/v1/runs/{run_id}/overrides`
- HITL queue table in uw_db + minimal queue UI
- 10 demo submissions across DO/GL with varied stages

**Deferred — eventual full ontology trajectory:**
- Cluster 1: separate `account` / `account_term` / `location` / `account_financials` / `entity_hierarchy`
- Cluster 2 (full): `extracted_fact` (per-source) + `fact_node` (resolved) split; `gl_coverage_intent` / `do_coverage_intent`
- Cluster 3: `gl_operation_class`, `gl_exposure_base`
- Cluster 4: `loss_run`, `claim_event`, `claim_development`
- Cluster 5: `gl_policy`, `gl_coverage_form`, `gl_endorsement`
- Cluster 6: `uw_action`, `decision`, `gl_pricing_factor`
- Cluster 7: `external_data_record`
- Cluster 8: `participant` w/ authority limits
- Conflict-detection engine + `diff_threshold_rule`
- SSE streaming for live progress
- Mid-run cancel
- Renewal diff engine

---

## Phase Order (revised)

The user wants easy UI lifts ahead of deeper foundation work. Phase 1 is reduced to "the smallest foundation needed to unlock the easy UI"; Phase 4 carries the heavier data work.

| Phase | What | Approx |
|---|---|---|
| **1. Document references** | `document` table in uw_db; discovery persistence; split discovery from extraction | ~1 day |
| **2. Submissions list facelift** | `# Docs` column (from uw_db), status pill, risk badge | ~½ day |
| **3. Documents panel** | New tab/section on detail page rendering uw_db `document` rows with classification pills | ~½ day |
| **4. Data foundation + state + async** | Refactor `submission_extraction` to clean `ai_*` / `hitl_*` channels (incl. `ai_found`, `verity_execution_run_id`, `output_path`); audit table; status enum + history; `pending_run_id`; async submit + polling endpoint | ~2 days |
| **5. Form layout** | 2-column form grid in Details tab | ~½ day |
| **6. Sparkle + pen + override API** | `ai_field` macro; edit endpoint; Verity `POST /api/v1/runs/{run_id}/overrides`; audit row + override id linkage | ~1.5 days |
| **7. HITL queue** | `hitl_review_queue` table in uw_db; minimal queue page listing items needing UW resolution | ~1 day |

Phases are sized for one developer; total ~6.5–7 days of focused work.

---

## Phase 1 — Document references + discovery split

Goal: every doc UW cares about is a row in uw_db, linked to its EDMS/Vault original. Today docs live only in EDMS and are pulled fresh on every pipeline run.

### 1a. New table `document` in uw_db

In [uw_demo/app/db/schema.sql](uw_demo/app/db/schema.sql):

```sql
CREATE TABLE IF NOT EXISTS document (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id       UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
  edms_document_id    UUID NOT NULL,           -- the id in edms_db / Vault
  filename            TEXT NOT NULL,
  content_type        TEXT,
  document_type       TEXT,                    -- classification (e.g. 'acord_125', 'loss_run', 'supplemental')
  classification_confidence  REAL,
  page_count          INTEGER,
  source              TEXT NOT NULL DEFAULT 'broker',  -- 'broker' | 'external_data' | 'internal'
  discovery_status    TEXT NOT NULL DEFAULT 'received', -- 'pending' | 'received' | 'failed'
  extraction_status   TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'in_progress' | 'complete' | 'not_applicable'
  received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(submission_id, edms_document_id)
);

CREATE INDEX idx_document_submission ON document(submission_id);
CREATE INDEX idx_document_extraction_status ON document(extraction_status);
```

The `edms_document_id` is a value, not a foreign key (cross-database). It's authoritative for retrieving content; uw_db only stores the reference + metadata.

### 1b. Discovery step

Today's `/process-documents` does discovery + classification + extraction in one go. Split it:

- New endpoint `POST /submissions/{id}/discover-documents` — calls EDMS via existing `_fetch_document_index(submission_id)` ([routes.py:220](uw_demo/app/ui/routes.py#L220)), upserts rows into uw_db `document` table, transitions submission status `intake → documents_received`.
- The existing `/process-documents` becomes "extract from received documents" — reads `document` rows from uw_db (not EDMS), runs classify + extract per-document, updates each row's `document_type` and `extraction_status`.
- UI shows **Discover Documents** button when `status = intake`. After discovery, UI shows the Documents panel (Phase 3) and a **Process Documents** button that's only enabled when at least one classifiable doc is present.
- If a needed doc type is missing, UI shows a "waiting for: ACORD 125, Loss Run" hint. UW cannot trigger extraction. (The "needed types" check can be a small static map per LOB; defer dynamic config.)

### 1c. Re-seed: 10 submissions

Rewrite [uw_demo/app/setup/seed_uw.py](uw_demo/app/setup/seed_uw.py) submission list from 4 → 10. Mix:
- **5** in `intake` (no docs yet)
- 2 in `review` (extraction flagged for HITL)
- 2 in `approved` (extraction OK; awaiting risk assessment)
- 1 in `assessed` (full pipeline complete)

Across DO and GL, varied revenue bands, varied SIC codes. For non-`intake` rows, seed `document` rows referencing existing PDFs in [uw_demo/seed_docs/filled/](uw_demo/seed_docs/filled/) (re-upload to EDMS via [seed_edms.py](uw_demo/app/setup/seed_edms.py) if needed). Seed `submission_extraction` for `review`/`approved`/`assessed` so Phase 6 has data to render with realistic provenance.

---

## Phase 2 — Submissions list facelift

Edit [uw_demo/app/ui/templates/submissions.html](uw_demo/app/ui/templates/submissions.html) and `_get_submissions` in [routes.py:75](uw_demo/app/ui/routes.py#L75):

- Add `# Docs` column. Source: `SELECT count(*) FROM document WHERE submission_id = ...` joined onto the submissions query (single SQL with `LEFT JOIN ... GROUP BY`). No EDMS round-trip per row.
- Status pill — driven by the new ENUM after Phase 4. For Phase 2, render the existing TEXT status with a stylized pill.
- Risk badge already shown; keep.
- Optional: column for "needs review" count (from `submission_extraction.needs_review`).

---

## Phase 3 — Documents panel on detail page (DONE)

New tab partial `uw_demo/app/ui/templates/partials/_tab_documents.html` + route `GET /submissions/{id}/tab/documents` in [routes.py](uw_demo/app/ui/routes.py).

- Reads `document` rows from uw_db (not Vault).
- One card per doc: filename, file size, page count, received_at, **classification pill** (driven by `document.document_type` with a color map), `extraction_status` chip, "Open in Vault" link.
- Add the tab to [submission_detail.html](uw_demo/app/ui/templates/submission_detail.html) tab list.

## Phase 3.1 — Documents tab refinements

### 3.1.a Doc count badge on the tab

Mirror the existing `review_count` badge on the Extracted Fields tab. The Documents tab heading shows `<span class="verity-tab-badge">{{ doc_count }}</span>` next to the label. Neutral color (use the existing draft / muted variant — not red/amber, this is informational). When `doc_count = 0`, render the badge with a `0` so the visual flag is unmistakable.

### 3.1.b Empty-state CTA

When the Documents tab loads with zero rows, the existing empty message also renders a "Discover Documents" button and an "Upload Document" button. The Discover button stays accessible inside the tab even when the action bar above has moved past `intake` (e.g., a submission stuck in `documents_received` with zero docs in Vault).

### 3.1.c Seed: row 11 — submission with no Vault documents

Add a row 11 to [seed_uw.py](uw_demo/app/setup/seed_uw.py) `SUBMISSIONS` and seed it with `status='documents_received'` but **no** entry in [seed_edms.py](uw_demo/app/setup/seed_edms.py) `SUBMISSION_DOCS`. This produces a submission where Vault has zero docs, exercising the empty-state UX path.

### 3.1.d Upload to Vault from the UW UI

UI surface: an **"Upload Document"** button in the Documents tab opens a native HTML `<dialog>` modal. The modal contains:
- File picker (`input type=file`).
- Document type dropdown: `do_application`, `gl_application`, `loss_run`, `financial_statement`, `board_resolution`, `supplemental`, `other`.
- **Sensitivity** dropdown (Vault `sensitivity` tag): `public`, `internal`, `confidential`, `pii`, `phi`.
- **Category** dropdown (Vault `category` tag): `application`, `loss_report`, `financial`, `governance`, `supplemental`, `correspondence`, `regulatory`, `other`.
- Cancel + Submit buttons. Submit posts to the upload endpoint; cancel closes the modal.

The modal uses the native `<dialog>` element with `.showModal()` / `.close()` — no JS framework. Backdrop dimming and focus trapping come for free.

The dropdown values are hardcoded in the template to match Vault's current `tag_allowed_value` vocabulary. If Vault's vocabulary changes, the template needs an update — acceptable for demo. (Future: a Vault `GET /tag-definitions` API would let UW populate the dropdowns dynamically.)

New endpoint `POST /submissions/{id}/upload-document` in [routes.py](uw_demo/app/ui/routes.py):
1. Receive multipart `file` + form fields: `document_type`, `sensitivity`, `category`.
2. Look up the `underwriting` collection's UUID from Vault (`GET {EDMS_URL}/collections`) — cache the result module-side.
3. Build the `tags` JSON: `{"sensitivity": ..., "category": ..., "lob": <derived>}`. The `lob` value is derived from `submission.lob` (`DO`→`do`, `GL`→`gl`); the user does not pick it.
4. Forward to Vault `POST {EDMS_URL}/upload` (multipart) with: `file`, `collection_id`, `context_ref="submission:{id}"`, `context_type="submission"`, `document_type`, `tags=<json>`, `uploaded_by="uw_user"`.
5. On success, call `_persist_documents` to mirror the new doc into uw_db's `document` table.
6. Redirect back to the detail page; the Documents tab re-renders with the new card.

Auto-populated (NOT user-picked):
- Collection: always `underwriting`.
- Context ref: `submission:{submission_id}`.
- Context type: `submission`.
- LOB tag: derived from `submission.lob`.
- Uploaded by: `uw_user` (placeholder until auth).

User-picked: file, document type, sensitivity, category.

The user-picked `document_type` is **authoritative** — no AI re-classification needed for uploaded docs. The upload endpoint stores `document.document_type = <user-picked>` and `classification_confidence = 1.0`. The workflow optimization to actually *skip* the classifier step for already-classified docs (saving an LLM call) is deferred to Phase 4 where workflows.py is being touched for the state machine; for now the value is preserved but the classifier may still run wastefully.

Out of scope: folder selection; freeform `source` tag editing.

## Phase 3.2 — Stepper visual redesign

The current stepper is a vertical 4-column table that consumes too much vertical space. Replace with a compact horizontal pipeline visual:

- One row of step circles connected by short lines (or chevron segments — pick whichever is simpler in pure CSS).
- Step label below each circle.
- Color encodes status: completed=green, current=amber/blue, pending=grey, failed=red, skipped=muted.
- Hover tooltip (HTML `title=`) shows status + completion timestamp.
- Use the freed vertical space for workflow-context info next to the stepper:
  - "Received: {created_at}"
  - "In current stage: {age}" (e.g., "2 days")
  - "Last update: {updated_at}"

Pure HTML+CSS; no JS dependency. The data is already on `sub` and `workflow_steps`.

---

## Phase 4 — Data foundation: extraction provenance + state machine + async runs

### 4a. Extend `submission_extraction`

The schema needs a real cleanup. Today the table mixes "what AI produced" with "what was overridden" with "what's flagged for review" using six override-related columns. Collapse to a clean two-channel model: an immutable `ai_*` channel (what the AI produced on this row's most recent AI run) and an `hitl_*` channel (what a human corrected, if anything). The current value displayed is the HITL value if present, else the AI value.

Drop these existing columns: `extracted_value`, `confidence`, `extraction_notes`, `overridden`, `override_value`, `overridden_by`, `override_reason`, `override_at`. They are all subsumed below.

Add these columns (consistent `ai_*` / `hitl_*` naming throughout):

| Column | Type | Notes |
|---|---|---|
| `ai_value` | TEXT | What the AI produced. NULL when AI hasn't run yet, or when AI ran and didn't find anything (disambiguated by `ai_found`). |
| `ai_confidence` | REAL | AI's confidence (0–1). NULL until AI has run. |
| `ai_found` | BOOLEAN NOT NULL DEFAULT FALSE | TRUE = AI looked and produced a value (or a deliberate not-found). FALSE = AI hasn't run for this field. Distinguishes "AI ran but couldn't find this field" (`ai_value IS NULL AND ai_found=TRUE`) from "AI hasn't tried yet" (`ai_found=FALSE`). |
| `source_document_id` | UUID REFERENCES document(id) | Which doc the AI extracted from. |
| `source_page` | INTEGER | Page number in source doc. |
| `source_snippet` | TEXT | Verbatim quote. Powers sparkle tooltip. |
| `verity_execution_run_id` | UUID | Verity's runtime execution id for the run that produced `ai_value`. Distinct from `workflow_run_id` (UW-side correlation). Required for the HITL override API call. |
| `output_path` | TEXT | JSONPath of this field within the Verity run's output (e.g. `$.fields.annual_revenue`). Stored at extraction time so the override endpoint can resolve and integrity-check. |
| `extractor_id` | TEXT | Identifier of who/what extracted (e.g. `claude-sonnet-4-6` or agent version label). |
| `hitl_value` | TEXT | Human-corrected value. NULL until a human edits. |
| `hitl_at` | TIMESTAMPTZ | When the human edit happened. |
| `hitl_by` | TEXT | Actor of the human edit. |

A read-side helper `current_value(row)` returns `hitl_value` if present, else `ai_value`. A read-side flag `is_ai_authoritative(row)` is `hitl_value IS NULL` — used by the macro to decide whether to render the sparkle.

`needs_review` and `review_reason` stay (they're queue-population signals, not value-channel signals). `workflow_run_id` stays as the UW-side correlation id.

### 4b. Audit log

New table `submission_extraction_audit`:

```sql
CREATE TABLE IF NOT EXISTS submission_extraction_audit (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id            UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
  field_name               TEXT NOT NULL,
  old_value                TEXT,
  new_value                TEXT,
  was_ai_authoritative     BOOLEAN,        -- TRUE when the prior value was the AI's (i.e. this change is an AI→HITL flip)
  actor                    TEXT NOT NULL,
  changed_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  hitl_override_id         UUID,           -- value of verity_db.hitl_override.id when this was an AI→HITL flip
  workflow_run_id          UUID            -- denormalized for easy filtering
);
```

### 4c. UW-side state machine

- New PostgreSQL ENUM `submission_status_enum`: `intake`, `documents_received`, `documents_processed`, `review`, `approved`, `assessed`, `declined`. `triaged` is dropped — the existing intermediate isn't load-bearing.
- New append-only table `submission_event` — the canonical UW-side audit log. Covers state changes, user actions, pipeline lifecycle events, and system events in one stream so the Audit Trail tab can render a unified timeline (merged with Verity's decision log at the UI layer). The originally planned narrower `submission_status_history` is subsumed by this; status changes are just the `event_category='state_change'` rows.

  ```sql
  CREATE TABLE submission_event (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id   UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
    event_category  TEXT NOT NULL,    -- 'state_change' | 'user_action' | 'pipeline' | 'system'
    event_type      TEXT NOT NULL,    -- 'status_changed', 'document_uploaded',
                                      -- 'discovery_started', 'extraction_review_approved', etc.
    actor           TEXT NOT NULL,    -- 'uw_user', 'system', specific username when auth lands
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Loose-shape payload — varies by event_type. Examples:
    --   status_changed:       {"from": "intake", "to": "documents_received", "reason": null}
    --   document_uploaded:    {"document_id": "...", "filename": "...", "document_type": "loss_run"}
    --   pipeline_started:     {"kind": "doc_processing", "run_id": "..."}
    --   pipeline_completed:   {"kind": "risk_assessment", "run_id": "...", "outcome": "complete"}
    payload         JSONB NOT NULL DEFAULT '{}',
    -- Optional cross-refs for drill-down (denormalized for fast filtering)
    workflow_run_id UUID,
    document_id     UUID,
    field_name      TEXT
  );

  CREATE INDEX idx_submission_event_sub_time
      ON submission_event(submission_id, occurred_at DESC);
  ```

- Field-level edits keep their own structured table (`submission_extraction_audit`) because that table has columns specific to before/after value diffs — no point cramming those into JSONB. The unified Audit Trail tab merges three sources: `submission_event` (uw_db) + `submission_extraction_audit` (uw_db) + Verity's decision log (federated query).
- Instrumentation pass: every handler in [routes.py](uw_demo/app/ui/routes.py) and [workflows.py](uw_demo/app/workflows.py) that mutates state or takes a user action calls a small helper `record_event(submission_id, category, type, actor, payload, ...)`. Status transitions through `transition_status` automatically emit a `state_change` event.
- New helper `transition_status(submission_id, to_status, changed_by, run_id=None, reason=None)` in `uw_demo/app/db/state.py`. Validates against an `ALLOWED_TRANSITIONS: dict[str, set[str]]` table; writes the history row; updates `submission.status`. All status writes in [routes.py](uw_demo/app/ui/routes.py) and [workflows.py](uw_demo/app/workflows.py) route through it.
- `workflow_step` stays as a UI cache — but stops being authority for submission progress.

### 4d. Async run wiring + idempotency

Extend `submission` with `pending_run_id UUID` and `pending_run_kind TEXT`.

Replace blocking handlers in [routes.py:386](uw_demo/app/ui/routes.py#L386) (`/process-documents`) and [:563](uw_demo/app/ui/routes.py#L563) (`/assess-risk`):

```
1. Idempotency: if pending_run_id is set and verity.get_run(...) is non-terminal, return existing running panel.
2. verity.submit_run(entity_kind, entity_name, input_data, workflow_run_id, execution_context_id) → run_id immediately.
3. UPDATE submission SET pending_run_id = run_id, pending_run_kind = ...
4. transition_status(...).
5. Return HTMX partial: a "Running…" panel polling /submissions/{id}/run-status every 2s.
```

New endpoint `GET /submissions/{id}/run-status` (HTMX partial):
- Reads `pending_run_id`; calls `verity.get_run(run_id)`.
- Terminal: clear `pending_run_id`; fetch `verity.get_run_result(run_id)`; persist extracted-fact rows or assessment rows; transition status; return post-completion action bar.
- Running: re-render running panel (re-arms hx-trigger).

Survives navigation: when the user returns to the page, the panel re-renders from `pending_run_id` and resumes polling.

Reuses [verity/src/verity/client/inprocess.py:338](verity/src/verity/client/inprocess.py#L338) `submit_run` and [:381](verity/src/verity/client/inprocess.py#L381) `get_run`. No Verity-side changes for async itself.

---

## Phase 5 — Form layout for Details tab

Edit [uw_demo/app/ui/templates/partials/_tab_details.html](uw_demo/app/ui/templates/partials/_tab_details.html):

- Replace the 3 stacked cards with a 2-column form grid grouped by section: **Company**, **Policy**, **Prior Coverage**.
- **No tooltip on label** (dropped per user). Plain `<label>` text only.
- Add `.verity-form-grid` class to [verity.css](uw_demo/app/ui/static/verity.css) if needed.

---

## Phase 6 — Sparkle + pen + override API

### 6a. Reusable Jinja macro

New file `uw_demo/app/ui/templates/partials/_ai_field.html`:

```jinja
{% macro ai_field(extraction) %}
  ...renders label, current_value(extraction), sparkle if is_ai_authoritative, pen icon...
{% endmacro %}
```

- Sparkle visible only when `is_ai_authoritative(extraction)` is true (i.e. `hitl_value IS NULL`).
- Sparkle color: green when `confidence >= 0.85`, amber when `< 0.85`. Inline SVG.
- Sparkle hover (HTML `title=` attribute, no JS dep): "Source: {filename}, page {source_page}\n\"{source_snippet}\"\nConfidence: {confidence*100}%\nExtractor: {extractor_id_or_agent_label}".
- When `ai_found = FALSE`: render an explicit empty-state pill ("AI did not find this field") instead of a blank value — avoids confusing "blank because AI couldn't find it" with "blank because not yet extracted".
- Pen icon always visible. Click → `hx-get` swaps to inline editor.

### 6b. Edit endpoint

`POST /submissions/{id}/extraction/{field_name}/edit`:

```
1. Read current submission_extraction row.
2. INSERT into submission_extraction_audit (always).
   was_ai_authoritative = (row.hitl_value IS NULL)
3. If was_ai_authoritative (AI→HITL flip):
     POST /api/v1/runs/{row.verity_execution_run_id}/overrides on Verity.
     Body: { application, entity_type, entity_reference, fact_type,
              output_path, ai_value, ai_found, hitl_value, actor, reason }
     Stash returned hitl_override_id on the audit row.
4. UPDATE submission_extraction:
     hitl_value = new_value,
     hitl_at = NOW(),
     hitl_by = actor
   (ai_value, ai_confidence, ai_found stay untouched — immutable for this AI run.)
5. Return the macro re-rendered (sparkle now gone since hitl_value is populated).
```

Application = `"uw_demo"`. Entity type = `"submission"`. Entity reference = the submission's UUID *as a value* (not a URL/link — just the key). Fact type = `field_name`. Output path = the JSONPath stored on `submission_extraction.output_path` (set at extraction time). All four come straight off the row; UW does not have to compute or look them up at edit time.

### 6c. Verity REST: `POST /api/v1/runs/{run_id}/overrides`

New endpoint in [verity/src/verity/web/api/](verity/src/verity/web/api/) — new file `overrides.py` mounted at `/api/v1/runs/{run_id}/overrides`. Naming the resource `overrides` (not `agent_overrides` or `output_overrides`) keeps it producer-agnostic — agents and tasks both produce outputs that get HITL-corrected.

Schema for the table backing it (Verity owns; UW does not write directly):

```sql
CREATE TABLE hitl_override (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  execution_run_id    UUID NOT NULL REFERENCES execution_run(id),
  -- Technical anchor (which Verity output, which field within it):
  output_path         TEXT NOT NULL,           -- JSONPath, e.g. '$.fields.annual_revenue'
  ai_value            JSONB,                   -- nullable: AI may have returned no value
  ai_found            BOOLEAN NOT NULL,        -- FALSE = AI looked but did not find
  hitl_value          JSONB NOT NULL,
  -- Business identification (parallel to technical, lets us roll up overrides
  -- by business meaning regardless of which run produced them):
  application         TEXT NOT NULL,           -- e.g. 'uw_demo'
  entity_type         TEXT NOT NULL,           -- e.g. 'submission', 'claim_event'
  entity_reference    TEXT NOT NULL,           -- the entity's key value (string), not a FK link
  fact_type           TEXT NOT NULL,           -- e.g. 'annual_revenue'
  -- Audit:
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by          TEXT NOT NULL,
  reason              TEXT
);

CREATE INDEX idx_hitl_override_run ON hitl_override(execution_run_id);
CREATE INDEX idx_hitl_override_fact ON hitl_override(application, entity_type, fact_type);
```

**API behavior:**
- Verify `run_id` exists and is terminal.
- Resolve `output_path` against the run's output (from the decision log / envelope) using `jsonpath-ng`. Get the value at that path.
- **Integrity check:** if the request's `ai_value` does not match the resolved value AND `ai_found=TRUE`, reject with 409 (UW is operating on stale data). Skip the check when `ai_found=FALSE`.
- Persist the override row. Return `{ override_id }`.
- The full output payload stays where it is (decision log / `execution_run.output`); we do not duplicate it in the override row. The override is a *delta* signal, not a copy.

Library wrapper: `verity.record_override(run_id, body, ...)` in [verity/src/verity/client/inprocess.py](verity/src/verity/client/inprocess.py) so co-located UW code can call directly without HTTP.

---

## Phase 7 — HITL queue (polymorphic)

Today flagged extractions are surfaced inside the submission's Extraction tab. A queue surface lets a UW see *all* items needing attention across submissions and across problem types.

Different HITL problem types have different shapes. A flat one-table model would have wide swaths of nulls and string-typed reason codes hiding real schema differences. Instead: a generic queue row that points to a per-type detail row (polymorphic), plus a log of actions taken on each queue item.

### 7a. Generic queue table

```sql
CREATE TYPE hitl_problem_type AS ENUM (
  'classification',     -- Which doc type is this PDF?
  'extraction',         -- What's the value of this field?
  'discrepancy',        -- Multiple sources disagree on the same fact
  'risk_review'         -- Submission-level: triage flagged Red / low confidence
);

CREATE TYPE hitl_status AS ENUM ('open', 'in_progress', 'resolved', 'waived');

CREATE TABLE IF NOT EXISTS hitl_queue (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  problem_type        hitl_problem_type NOT NULL,
  problem_ref         UUID NOT NULL,           -- FK-by-value to the per-type detail row
  submission_id       UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
  priority            TEXT NOT NULL DEFAULT 'medium',  -- 'high' | 'medium' | 'low'
  status              hitl_status NOT NULL DEFAULT 'open',
  assigned_to         TEXT,
  llm_recommendation  TEXT,
  llm_confidence      REAL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at         TIMESTAMPTZ,
  resolved_by         TEXT,
  resolution_action   TEXT
);

CREATE INDEX idx_hitl_queue_open
  ON hitl_queue(status, priority, created_at)
  WHERE status IN ('open', 'in_progress');
CREATE INDEX idx_hitl_queue_submission ON hitl_queue(submission_id);
```

`problem_ref` is intentionally a value (not a real FK) because it points polymorphically into one of the detail tables below. Application-layer joins decide which detail table to read based on `problem_type`.

### 7b. Per-problem-type detail tables

```sql
-- Classification HITL: AI's predicted doc type is uncertain
CREATE TABLE IF NOT EXISTS hitl_classification_problem (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id              UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  ai_predicted_type        TEXT,
  ai_confidence            REAL,
  candidate_types          JSONB,           -- e.g. [{"type":"acord_125","conf":0.55}, {"type":"supplemental","conf":0.40}]
  verity_execution_run_id  UUID,
  output_path              TEXT
);

-- Extraction HITL: AI's field value is uncertain or missing
CREATE TABLE IF NOT EXISTS hitl_extraction_problem (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_extraction_id UUID NOT NULL REFERENCES submission_extraction(id) ON DELETE CASCADE,
  reason                   TEXT NOT NULL,           -- 'low_confidence' | 'ai_not_found' | 'flagged_by_rule'
  ai_value                 TEXT,
  ai_confidence            REAL
);

-- Discrepancy HITL: same fact, different values from different sources
CREATE TABLE IF NOT EXISTS hitl_discrepancy_problem (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id            UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
  fact_type                TEXT NOT NULL,
  source_a_origin          TEXT NOT NULL,          -- e.g. 'acord_125'
  source_a_value           TEXT,
  source_a_confidence      REAL,
  source_b_origin          TEXT NOT NULL,          -- e.g. 'dnb'
  source_b_value           TEXT,
  source_b_confidence      REAL,
  delta_pct                REAL                    -- magnitude of disagreement
);

-- Risk review HITL: submission-level flag from triage / appetite
CREATE TABLE IF NOT EXISTS hitl_risk_review_problem (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id            UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
  flag_reason              TEXT NOT NULL,          -- 'risk_red' | 'low_triage_confidence' | 'outside_appetite'
  risk_score               TEXT,
  appetite_determination   TEXT,
  triage_confidence        REAL,
  appetite_confidence      REAL
);
```

### 7c. HITL log — actions on queue items

```sql
CREATE TYPE hitl_log_action AS ENUM (
  'created', 'viewed', 'assigned', 'reassigned',
  'commented', 'resolved', 'waived', 'reopened'
);

CREATE TABLE IF NOT EXISTS hitl_log (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  queue_id     UUID NOT NULL REFERENCES hitl_queue(id) ON DELETE CASCADE,
  action       hitl_log_action NOT NULL,
  actor        TEXT NOT NULL,
  occurred_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  payload      JSONB                          -- action-specific: comment text, prior assignee, resolution_action, etc.
);

CREATE INDEX idx_hitl_log_queue ON hitl_log(queue_id, occurred_at);
```

The log captures the lifecycle of every queue item. A `created` row is written when the queue row is first inserted; `viewed` when a UW opens the deep link; `resolved` / `waived` when they take final action.

### 7d. Population

- After extraction completes: for each `submission_extraction` with `needs_review=TRUE`, insert a `hitl_extraction_problem` + `hitl_queue` row pair.
- After classification: for documents with `classification_confidence < 0.7`, insert `hitl_classification_problem` + `hitl_queue`.
- Discrepancy population is deferred (requires the conflict-detection engine, which is out of scope) — schema is in so we can plug it in later.
- After triage: if `risk_score='Red'` or triage confidence below threshold, insert `hitl_risk_review_problem` + `hitl_queue`.

### 7e. Minimal UI

New page `/queue` listing all open items grouped by problem type, with priority chips and filter pills. Clicking a row deep-links to the submission detail page anchored at the relevant field/document. Resolution happens on the detail page; on save, the queue item is marked `resolved` and a `hitl_log` row is appended.

---

## Critical Files

**To edit:**
- [uw_demo/app/db/schema.sql](uw_demo/app/db/schema.sql) — `document`, extension of `submission_extraction`, `submission_extraction_audit`, `submission_status_enum`, `submission_event`, `pending_run_id`/`pending_run_kind` on `submission`, `output_path` on `submission_extraction`, `hitl_review_queue`. Clean up duplicate section-header blocks.
- [uw_demo/app/setup/seed_uw.py](uw_demo/app/setup/seed_uw.py) — 10 submissions (5/2/2/1 mix); seed `document` and `submission_extraction` rows with provenance.
- [uw_demo/app/ui/routes.py](uw_demo/app/ui/routes.py) — split discover from extract; async submit + polling endpoint; idempotency; new run-status, fact-edit, queue, document-tab endpoints; route status writes through `transition_status`.
- [uw_demo/app/workflows.py](uw_demo/app/workflows.py) — write the `ai_*` channel when persisting extracted facts: `ai_value`, `ai_confidence`, `ai_found`, `source_document_id`, `source_page`, `source_snippet`, `verity_execution_run_id`, `output_path`, `extractor_id`. Never touch the `hitl_*` channel from a workflow — that's edit-endpoint only.
- [uw_demo/app/ui/templates/submissions.html](uw_demo/app/ui/templates/submissions.html) — Phase 2 `# Docs` column.
- [uw_demo/app/ui/templates/submission_detail.html](uw_demo/app/ui/templates/submission_detail.html) — Documents tab; running-panel slot.
- [uw_demo/app/ui/templates/partials/_tab_details.html](uw_demo/app/ui/templates/partials/_tab_details.html) — Phase 5 form layout.
- [uw_demo/app/ui/templates/partials/_tab_extraction.html](uw_demo/app/ui/templates/partials/_tab_extraction.html) — adopt `ai_field` macro.
- Verity: new file `verity/src/verity/web/api/overrides.py`; new table DDL in `verity/src/verity/db/schema/` (verify path); extend [verity/src/verity/client/inprocess.py](verity/src/verity/client/inprocess.py) with `record_override`.

**To create:**
- `uw_demo/app/db/state.py` — `transition_status`, `ALLOWED_TRANSITIONS`.
- `uw_demo/app/ui/templates/partials/_ai_field.html` — sparkle + pen macro.
- `uw_demo/app/ui/templates/partials/_tab_documents.html` — Documents panel.
- `uw_demo/app/ui/templates/partials/_run_status.html` — HTMX polling panel.
- `uw_demo/app/ui/templates/queue.html` — HITL queue page.

**To reuse (do not re-implement):**
- [verity/src/verity/client/inprocess.py:338](verity/src/verity/client/inprocess.py#L338) `submit_run`
- [verity/src/verity/client/inprocess.py:381](verity/src/verity/client/inprocess.py#L381) `get_run`
- [verity/src/verity/runtime/worker.py](verity/src/verity/runtime/worker.py) — worker loop
- [verity/src/verity/contracts/envelope.py:106](verity/src/verity/contracts/envelope.py#L106) `ExecutionEnvelope`
- [uw_demo/app/ui/routes.py:220](uw_demo/app/ui/routes.py#L220) `_fetch_document_index` (used during discovery)

---

## Verification

After **Phase 1**:
- `\dt` shows `document` table; `SELECT count(*) FROM document` matches the seed mix; submissions in `intake` have zero docs, others have realistic counts.
- Discovery flow: open an `intake` submission → click "Discover Documents" → status transitions to `documents_received` → `document` rows appear → "Process Documents" button enables.

After **Phase 2**: list shows `# Docs` correctly without per-row EDMS round-trips.

After **Phase 3**: Documents tab on detail page shows the new doc cards with classification pills.

After **Phase 4**:
- Async submit: clicking "Process Documents" returns the running panel *immediately*. Navigate away and back — panel resumes. While running, a second click does not create a second `execution_run`.
- State machine: `submission_event` rows with `event_category='state_change'` on every transition. Trying to trigger "Assess Risk" while extraction is pending is refused.
- Audit Trail tab: merged timeline of `submission_event` + `submission_extraction_audit` + Verity decision log, ordered by timestamp, with category filter chips (Workflow / User / AI). Each row shows actor, event type, summary, and optional drill-down link.
- Provenance fields populated on `submission_extraction` after extraction.

After **Phase 5**: Details tab renders as a 2-column form grouped by section.

After **Phase 6**:
- Sparkle hover shows source filename + page + snippet + confidence.
- Confidence color: 0.92 → green; 0.65 → amber.
- Edit AI field: sparkle disappears; `hitl_value` populated, `ai_value` / `ai_confidence` / `ai_found` retained unchanged. New `submission_extraction_audit` row with `was_ai_authoritative=TRUE`. Verity returns `hitl_override_id`; row in `verity_db.hitl_override`. JSONPath integrity check verified.
- Re-edit (HITL→HITL): audit row gains; Verity does not.

After **Phase 7**: `/queue` lists open items across all submissions; clicking deep-links to the detail page; resolving on detail page marks the queue item resolved.

---

## Out of Plan / Open Questions

- Confirm exact path for the `verity_db` schema files in the new runtime split (commit history shows recent reorganization).
- Whether to use `jsonpath-ng` (most common) or `jsonpath-rw` for the integrity check on the Verity side. Lean: `jsonpath-ng` — actively maintained, simple syntax.
- Whether the discovery step should also accept doc uploads (vs being read-only against EDMS). Lean: read-only for now; uploads remain a separate EDMS UI.
- Whether the queue page should support waiver/no-action ("waive" status) in v1 or just resolve. Lean: support both (queue UX is cheap once the table exists).
