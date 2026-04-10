# Steps 6-10: Verity-EDMS Integration — Implementation Plan

## Context

The UW pipeline was a single 4-step pipeline where steps 1-2 were broken and steps 3-4 used hardcoded data. After architectural review, we're rebuilding it as a **fully connected, two-pipeline flow** with real data, real documents, and a human checkpoint.

### Key Architecture Decisions

1. **Two pipelines, not one.** Document processing (classify + extract) and risk assessment (triage + appetite) are separate pipelines with a HITL checkpoint between them.
2. **Classifier and extractor stay as tasks.** They receive input, produce output. No tool calling. Reliable and deterministic.
3. **PDF for classification, extracted text for field extraction.** Claude sees the actual PDF form layout for classification. Extracted text is sufficient and cheaper for field extraction.
4. **No edms package coupling.** UW Demo calls EDMS via REST API (httpx). In production these run on separate servers.
5. **Extraction results write to uw_db.** Real database persistence, not Python dicts. Flags for HITL review. Override tracking.
6. **UW App orchestrates pipeline handoff.** Pipeline 1 returns → UW app checks quality → auto-advances or holds for HITL → triggers Pipeline 2.
7. **Rename pas_db to uw_db.** PAS is post-bind. Submissions are pre-bind. The underwriting database holds submissions, extracted fields, triage results, and overrides.

### System Boundaries

| System | Role | Database | What it holds |
|---|---|---|---|
| UW App (8001) | Business application | uw_db | Submissions, extracted fields, triage results, HITL overrides |
| EDMS (8002) | Document management | edms_db | Documents, text extractions, metadata, classifications |
| Verity (8000) | AI governance | verity_db | Agents, tasks, prompts, tools, decision audit trail |

### Task vs Agent

| | Task | Agent |
|---|---|---|
| Turns | Single-turn: input → output | Multi-turn: reason, call tools, iterate |
| Tools | None — receives all input upfront | Calls tools to gather information |
| Reliability | Deterministic, no LLM decision points for data | Tool calls add LLM decisions that can fail |
| Examples | Classify a document, extract fields | Triage risk across multiple sources, assess appetite |

---

## The Complete Flow

### Before any pipeline runs (after seeding):

**EDMS:** 11 documents uploaded and text-extracted for 4 submissions.
**UW App (uw_db):** 4 submission records with basic intake data (insured name, LOB, limits, etc.). No extracted fields yet.
**Verity:** 2 pipelines, 2 agents, 2 tasks, 10 tools registered. All promoted to champion.

### Pipeline 1: Document Processing

**User opens SUB-001 (Acme D&O) in UW app, clicks "Process Documents"**

#### Pre-step: UW app fetches documents from EDMS

```
UW App → GET /documents?context_ref=submission:00000001-... → EDMS
EDMS returns: [{id, filename, content_type, ...}, ...]

For each document:
  UW App → GET /documents/{id}/content → EDMS (PDF bytes)
  UW App → GET /documents/{id}/text → EDMS (extracted text)
```

UW app builds pipeline context with documents attached.

#### Step 1: classify_documents (task)

- **Input:** PDF content blocks (Claude sees actual form layout, checkboxes, headers)
- **Claude returns:** `{"documents_classified": [{document_id, document_type, confidence}, ...]}`
- **Data written:** UW app calls `PUT /documents/{id}/type` on EDMS to tag each document with its classified type
- **Verity logs:** Decision with full audit trail

#### Step 2: extract_fields (task)

- **Input:** Extracted text of the document classified as `do_application` (identified in step 1)
- **Claude returns:** `{"fields": {"named_insured": {value, confidence}, "annual_revenue": {value, confidence}, ...}, "low_confidence_fields": [...], "unextractable_fields": [...]}`
- **Data written:** UW app writes extracted fields to `uw_db.submission_extraction` table:
  - Each field: value, confidence_score, extraction_notes
  - Low-confidence fields flagged: `needs_review = true`
  - Missing fields flagged: `needs_review = true, value = null`
  - Overall status: `extraction_status = 'needs_review'` or `'clean'`
- **Verity logs:** Decision with full audit trail

#### Pipeline 1 returns to UW app

UW app inspects extraction result:

**If `extraction_status = 'clean'` (all fields extracted with high confidence):**
→ Auto-trigger Pipeline 2. User sees "All fields extracted cleanly — proceeding to risk assessment."

**If `extraction_status = 'needs_review'` (flags exist):**
→ Show HITL review screen:
  - All extracted fields displayed in a form
  - Flagged fields highlighted (yellow for low-confidence, red for missing)
  - Underwriter can edit/override any field
  - Each override recorded: `overridden_by`, `override_reason`, `original_value`, `original_confidence`
  - Underwriter clicks "Approve & Continue" → triggers Pipeline 2

### Pipeline 2: Risk Assessment

**Triggered by UW app after extraction is finalized (auto or after HITL)**

#### Pre-step: UW app reads finalized fields from uw_db

The pipeline context includes the **finalized** fields (post-HITL if any overrides happened), not raw extraction output. The triage agent sees what the underwriter approved.

#### Step 3: triage_submission (agent)

- **Input context:** Finalized extracted fields from uw_db
- **Claude calls tools:**
  - `get_submission_context(submission_id)` → reads from uw_db (finalized fields + submission metadata)
  - `get_loss_history(account_id)` → loss data
  - `get_enrichment_data(named_insured)` → LexisNexis, D&B, Pitchbook
  - `store_triage_result(submission_id, risk_score, routing, reasoning)` → writes to uw_db
- **Claude returns:** `{"risk_score": "Green", "routing": "assign_to_uw", "confidence": 0.89, ...}`
- **Data written:** Triage result stored in uw_db
- **Verity logs:** Decision with full audit trail, tool call history

#### Step 4: assess_appetite (agent)

- **Input context:** Everything from steps 1-3 + finalized fields
- **Claude calls tools:**
  - `get_underwriting_guidelines("DO")` → full guideline text
  - `get_submission_context(submission_id)` → finalized submission data
  - `update_appetite_status(submission_id, determination, citations)` → writes to uw_db
- **Claude returns:** `{"determination": "within_appetite", "guideline_citations": [...]}`
- **Data written:** Appetite result stored in uw_db
- **Verity logs:** Decision with full audit trail

---

## What's Real vs Hardcoded (After Implementation)

| Data Source | Status | System |
|---|---|---|
| Documents (PDFs, text files) | **Real** — stored in EDMS, fetched via API | EDMS |
| Document classification | **Real** — Claude classifies actual PDFs | Verity (task) |
| Extracted fields | **Real** — Claude extracts from actual form text | Verity (task) → uw_db |
| HITL overrides | **Real** — stored in uw_db with audit trail | UW App |
| Loss history | Hardcoded (would be from a loss run system) | UW App |
| Enrichment (LexisNexis, D&B) | Hardcoded (would be external APIs) | UW App |
| UW Guidelines | Hardcoded (would be from a guidelines DB) | UW App |
| Decision audit trail | **Real** — every step logged | Verity |
| Document type tags in EDMS | **Real** — classifier writes back | EDMS |

---

## Implementation Steps

### Step 6: Register EDMS Tools + Rename pas_db

**6a. Rename pas_db to uw_db**

Files to change:
- `docker-compose.yml` — env vars: `UW_DB_URL` replaces `PAS_DB_URL`
- `scripts/init-multiple-dbs.sh` — database list: `verity_db,uw_db,edms_db`
- `uw_demo/app/config.py` — setting name: `UW_DB_URL`

**6b. Create uw_db schema**

New file: `uw_demo/app/db/schema.sql`

```sql
-- Submission intake record (basic data from broker/insured)
CREATE TABLE submission (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    named_insured TEXT NOT NULL,
    lob TEXT NOT NULL,  -- DO, GL
    annual_revenue BIGINT,
    employee_count INTEGER,
    effective_date DATE,
    expiration_date DATE,
    limits_requested BIGINT,
    retention_requested BIGINT,
    prior_carrier TEXT,
    prior_premium BIGINT,
    status TEXT DEFAULT 'intake',  -- intake, documents_processed, review, triaged, assessed, quoted
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Extracted fields from document processing pipeline
CREATE TABLE submission_extraction (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id UUID REFERENCES submission(id),
    field_name TEXT NOT NULL,
    extracted_value TEXT,
    confidence REAL,
    extraction_notes TEXT,
    needs_review BOOLEAN DEFAULT FALSE,
    -- HITL override tracking
    overridden BOOLEAN DEFAULT FALSE,
    override_value TEXT,
    overridden_by TEXT,
    override_reason TEXT,
    override_at TIMESTAMPTZ,
    -- Audit
    pipeline_run_id UUID,  -- links to Verity decision log
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(submission_id, field_name)
);

-- Triage and appetite results
CREATE TABLE submission_assessment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id UUID REFERENCES submission(id),
    assessment_type TEXT NOT NULL,  -- 'triage' or 'appetite'
    result JSONB NOT NULL,  -- full structured output
    pipeline_run_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**6c. Register EDMS tools in Verity**

File: `uw_demo/app/setup/register_all.py` — `seed_tools()`

Add 2 tools to the `tools_data` list:

- **`list_documents`** — input: `{context_ref, document_type (optional), context_type (optional)}`
- **`get_document_text`** — input: `{document_id}`

Also add:
- **`store_extraction_result`** — new tool for writing extracted fields to uw_db

### Step 7: Wire EDMS via httpx + EDMS API additions

**7a. UW app EDMS helper:** `uw_demo/app/tools/edms_tools.py` (new file)

Async functions calling EDMS REST API via httpx. No edms package import.
- `list_documents(context_ref, document_type=None, context_type=None)`
- `get_document_text(document_id)`
- `get_document_content(document_id)` — returns PDF bytes for Claude

**7b. Config:** Add `EDMS_URL` to `uw_demo/app/config.py`

**7c. Main:** Register tool implementations in `uw_demo/app/main.py`

**7d. EDMS API additions:**

- Add `GET /documents/{id}/content` — returns original file bytes from MinIO
- Add `document_type` and `context_type` query filters to `GET /documents`
- Remove `POST /upload-local` endpoint

**7e. EdmsClient updates:** `edms/src/edms/client.py`

- Add `upload()` — standard multipart upload (replaces `upload_local()`)
- Add `list_collections()` — find collection UUID
- Remove `upload_local()`

### Step 8: Seed Documents to EDMS

**8a. Create seed script:** `uw_demo/app/setup/seed_edms.py` (new file)

Uses httpx directly (no EdmsClient). Uploads 11 documents, triggers text extraction.

**8b. Seed uw_db submissions:** `uw_demo/app/setup/seed_uw.py` (new file)

Creates 4 submission records in uw_db with basic intake data.

**8c. Integrate into register_all.py** — call both at end of `main()`

### Step 9: Two-Pipeline Architecture + HITL Flow

**9a. Register two pipelines in Verity**

Pipeline 1: `uw_document_processing`
```
Step 1: classify_documents (task) — no dependencies
Step 2: extract_fields (task) — depends_on: [classify_documents]
```

Pipeline 2: `uw_risk_assessment`
```
Step 1: triage_submission (agent) — no dependencies
Step 2: assess_appetite (agent) — depends_on: [triage_submission]
```

**9b. Prompt updates:** `uw_demo/app/prompts.py`

- `CLASSIFIER_INPUT_V2` — documents arrive as content blocks, no `{{document_text}}`
- `EXTRACTOR_INPUT_V2` — keeps `{{document_text}}` (extracted text of identified application)
- Triage/appetite prompts — update to reference finalized fields from uw_db

**9c. Execution engine:** `verity/src/verity/core/execution.py`

Modify `_assemble_prompts()` to support `_documents` content blocks (PDF for Claude).

**9d. Pipeline runner:** `uw_demo/app/ui/routes.py`

- Pre-fetch documents from EDMS before Pipeline 1
- After Pipeline 1: inspect extraction, write to uw_db, decide auto-advance vs HITL
- HITL review screen (new template)
- After HITL approval: trigger Pipeline 2 with finalized fields from uw_db

**9e. Submission tools refactor:** `uw_demo/app/tools/submission_tools.py`

- `get_submission_context()` reads from uw_db (finalized fields, not hardcoded)
- `store_extraction_result()` writes to uw_db
- `store_triage_result()` writes to uw_db
- `update_appetite_status()` writes to uw_db

**9f. Mock context:** `uw_demo/app/pipeline.py`

Update for two separate pipelines. Each has its own mock context.

### Step 10: End-to-End Test

```bash
docker compose down -v
docker compose up -d --build
docker compose exec uw-demo python -m uw_demo.app.setup.register_all
```

Verify:
1. EDMS: 11 documents uploaded, text extracted
2. uw_db: 4 submissions seeded
3. Verity: 2 pipelines, 2 agents, 2 tasks, 11 tools
4. UW Demo: Run document processing → see extraction results → HITL screen → approve → auto-triggers risk assessment

---

## Files Changed (Summary)

| File | Action | What |
|---|---|---|
| `docker-compose.yml` | Modify | Rename pas_db → uw_db |
| `scripts/init-multiple-dbs.sh` | Modify | Rename pas_db → uw_db |
| `uw_demo/app/config.py` | Modify | PAS_DB_URL → UW_DB_URL, add EDMS_URL |
| `uw_demo/app/db/schema.sql` | New | submission, submission_extraction, submission_assessment tables |
| `uw_demo/app/tools/edms_tools.py` | New | httpx wrappers for EDMS REST API |
| `uw_demo/app/tools/submission_tools.py` | Rewrite | Read/write uw_db instead of hardcoded dicts |
| `uw_demo/app/main.py` | Modify | Register EDMS tool implementations |
| `uw_demo/app/prompts.py` | Add | CLASSIFIER_INPUT_V2, EXTRACTOR_INPUT_V2 |
| `uw_demo/app/setup/register_all.py` | Modify | 2 pipelines, new tools, call seed scripts |
| `uw_demo/app/setup/seed_edms.py` | New | Upload 11 documents to EDMS |
| `uw_demo/app/setup/seed_uw.py` | New | Create 4 submissions in uw_db |
| `uw_demo/app/pipeline.py` | Rewrite | Two separate mock contexts |
| `uw_demo/app/ui/routes.py` | Modify | Two pipeline triggers, HITL review flow |
| `uw_demo/app/ui/templates/` | New | HITL extraction review template |
| `edms/src/edms/service/routes.py` | Add + Remove | GET /content, query filters, remove upload-local |
| `edms/src/edms/client.py` | Modify | Add upload(), list_collections(); remove upload_local() |
| `verity/src/verity/core/execution.py` | Modify | _assemble_prompts() supports document content blocks |
