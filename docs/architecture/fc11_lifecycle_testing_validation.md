# FC-11: Lifecycle Management, Testing, Validation & Source Data

## Context

Verity's database schema has 9 testing/validation tables, a 7-state lifecycle with HITL gates, and metric thresholds - but critical gaps exist in the data model for real-world ground truth workflows. No execution logic or UI exists for the three governance sidebar links. Prompts are placeholder quality. No actual insurance document content exists in the system. This plan addresses all three layers: data model fixes, source data quality, and the lifecycle/testing UI.

---

## PART 1: DATA MODEL - GROUND TRUTH REDESIGN

### Problem

The existing `ground_truth_dataset` table treats the entire dataset as a
pre-packaged artifact pointed to by a single MinIO key. Verity has no visibility
into individual labeled records, no labeling lineage, no multi-annotator support,
no LLM-as-judge tracking, and no disagreement resolution. For a governance
platform that must answer "how do we know this validation data is trustworthy?",
this is the same gap as having no audit trail for agent decisions.

### Design: Three Tables

The existing `ground_truth_dataset` table is **replaced** by three tables
that separate concerns: dataset metadata, input records, and annotations (labels).

**Storage Abstraction:** All document references use `storage_provider`,
`storage_container`, and `storage_key` instead of MinIO-specific fields.
Works identically for MinIO, S3, Azure Blob, or local storage.

#### Table 1: `ground_truth_dataset` (REPLACED)

Dataset header. One row per dataset. Tracks target entity, purpose, quality
tier, labeling status, and computed IAA metrics.

```sql
CREATE TYPE gt_dataset_status AS ENUM (
    'collecting',    -- records being gathered, not yet ready for labeling
    'labeling',      -- annotations in progress
    'adjudicating',  -- disagreements being resolved
    'ready',         -- all records have an authoritative annotation
    'deprecated'     -- superseded by a newer dataset version
);

CREATE TYPE gt_quality_tier AS ENUM (
    'silver',   -- single annotator, no independent review
    'gold'      -- multi-annotator with IAA check, adjudication where needed
);

CREATE TABLE ground_truth_dataset (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type             entity_type NOT NULL,
    entity_id               UUID NOT NULL,
    designed_for_version_id UUID,

    name                    VARCHAR(300) NOT NULL,
    version                 VARCHAR(50)  NOT NULL DEFAULT '1.0',
    description             TEXT,
    purpose                 TEXT NOT NULL,

    quality_tier            gt_quality_tier NOT NULL DEFAULT 'silver',
    status                  gt_dataset_status NOT NULL DEFAULT 'collecting',

    -- Labeling guidance document (storage-abstracted)
    labeling_guide_provider  VARCHAR(50),
    labeling_guide_container VARCHAR(200),
    labeling_guide_key       VARCHAR(500),

    owner_name              VARCHAR(200) NOT NULL,
    created_by              VARCHAR(200) NOT NULL,

    -- Computed quality metrics (updated when annotations change)
    record_count            INTEGER NOT NULL DEFAULT 0,
    annotated_count         INTEGER NOT NULL DEFAULT 0,
    authoritative_count     INTEGER NOT NULL DEFAULT 0,
    iaa_score               NUMERIC(5,4),
    iaa_computed_at         TIMESTAMP,
    iaa_method              VARCHAR(50),
    coverage_notes          TEXT,

    applies_to_versions     UUID[] DEFAULT '{}',
    superseded_by           UUID REFERENCES ground_truth_dataset(id),

    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_gt_dataset UNIQUE (entity_type, entity_id, name, version)
);

CREATE INDEX idx_gtd_entity ON ground_truth_dataset(entity_type, entity_id);
CREATE INDEX idx_gtd_status ON ground_truth_dataset(status);
```

#### Table 2: `ground_truth_record` (NEW)

One input item within a dataset. This is the "question" - the document or
context fed to the entity during validation. Carries NO label. Labels live
in the annotation table.

```sql
CREATE TYPE gt_source_type AS ENUM (
    'document',     -- a real insurance document
    'submission',   -- a full submission context (for agent testing)
    'synthetic'     -- generated test case
);

CREATE TABLE ground_truth_record (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id              UUID NOT NULL REFERENCES ground_truth_dataset(id)
                            ON DELETE CASCADE,
    record_index            INTEGER NOT NULL,

    -- Source document reference (storage-abstracted)
    source_type             gt_source_type NOT NULL,
    source_provider         VARCHAR(50),
    source_container        VARCHAR(200),
    source_key              VARCHAR(500),
    source_description      VARCHAR(500),

    -- What gets fed to the entity during validation
    input_data              JSONB NOT NULL,

    -- Per-record tool mock overrides for agent testing
    tool_mock_overrides     JSONB,

    -- Slice tags for analysis
    tags                    TEXT[] DEFAULT '{}',
    difficulty              VARCHAR(20),
    record_notes            TEXT,

    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_gt_record UNIQUE (dataset_id, record_index)
);

CREATE INDEX idx_gtr_dataset ON ground_truth_record(dataset_id);
CREATE INDEX idx_gtr_tags    ON ground_truth_record USING GIN(tags);
```

#### Table 3: `ground_truth_annotation` (NEW)

One annotator's answer for one record. Multiple annotations per record
allowed. Exactly one per record has `is_authoritative = true` - this is
what the validation runner uses as the correct answer.

Adjudication is not a separate table. When a senior SME resolves disagreement,
they create a new annotation with `annotator_type = 'adjudicator'` and
`is_authoritative = true`. Prior annotations preserved for lineage.

LLM-as-judge is a first-class annotator type, tracked with model name and
prompt version for full reproducibility.

```sql
CREATE TYPE gt_annotator_type AS ENUM (
    'human_sme',
    'llm_judge',
    'adjudicator'
);

CREATE TABLE ground_truth_annotation (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id               UUID NOT NULL REFERENCES ground_truth_record(id)
                            ON DELETE CASCADE,
    dataset_id              UUID NOT NULL REFERENCES ground_truth_dataset(id),

    annotator_type          gt_annotator_type NOT NULL,

    -- Human SME / adjudicator fields
    labeled_by              VARCHAR(200),
    label_confidence        NUMERIC(5,4),
    label_notes             TEXT,

    -- LLM judge fields
    judge_model             VARCHAR(100),
    judge_prompt_version_id UUID REFERENCES prompt_version(id),
    judge_reasoning         TEXT,

    -- The label itself
    expected_output         JSONB NOT NULL,

    -- Authoritative flag (enforced by application logic, not DB constraint,
    -- because the transition must be atomic in a single transaction)
    is_authoritative        BOOLEAN NOT NULL DEFAULT FALSE,

    -- Correction tracking
    is_corrected            BOOLEAN DEFAULT FALSE,
    original_output         JSONB,
    corrected_at            TIMESTAMP,
    correction_reason       TEXT,

    labeled_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_human_fields CHECK (
        annotator_type NOT IN ('human_sme', 'adjudicator')
        OR labeled_by IS NOT NULL
    ),
    CONSTRAINT chk_llm_fields CHECK (
        annotator_type != 'llm_judge'
        OR judge_model IS NOT NULL
    )
);

CREATE INDEX idx_gta_record     ON ground_truth_annotation(record_id);
CREATE INDEX idx_gta_dataset    ON ground_truth_annotation(dataset_id);
CREATE INDEX idx_gta_auth       ON ground_truth_annotation(record_id)
                                WHERE is_authoritative = TRUE;
CREATE INDEX idx_gta_type       ON ground_truth_annotation(annotator_type);
```

### Validation Runner Query Pattern

```sql
-- Get all authoritative answers for a dataset
SELECT r.id AS record_id, r.record_index, r.input_data,
       r.tool_mock_overrides, r.tags,
       a.expected_output, a.annotator_type,
       a.labeled_by, a.judge_model
FROM ground_truth_record r
JOIN ground_truth_annotation a ON a.record_id = r.id AND a.is_authoritative = TRUE
WHERE r.dataset_id = :dataset_id
ORDER BY r.record_index;
```

### Workflow Scenarios

**Silver tier (single annotator):**
1. Dataset created, status = 'labeling'
2. SME creates one annotation per record, `is_authoritative = true`
3. Status set to 'ready'. Validation runner uses authoritative annotations.

**Gold tier (multi-annotator + adjudication):**
1. Annotator A labels all records, `is_authoritative = true`
2. Annotator B labels same records, `is_authoritative = false`
3. IAA computed, disagreements flagged
4. Senior SME adjudicates: `annotator_type = 'adjudicator'`, `is_authoritative = true`. Prior authoritative set to false in same transaction.
5. Status = 'ready', IAA stored on dataset.

**LLM-as-judge co-annotator:**
1. Human SME annotates as authoritative
2. LLM judge annotates as non-authoritative
3. Human-judge IAA computed as quality check on judge calibration

---

### Per-Record Validation Results (NEW TABLE)

`validation_run` stores aggregate metrics but no per-record predictions.
When F1=0.95, you need to see which documents were misclassified.

```sql
CREATE TABLE validation_record_result (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    validation_run_id       UUID NOT NULL REFERENCES validation_run(id),
    ground_truth_record_id  UUID NOT NULL REFERENCES ground_truth_record(id),
    record_index            INTEGER NOT NULL,

    expected_output         JSONB NOT NULL,
    actual_output           JSONB NOT NULL,
    confidence              NUMERIC(5,4),

    correct                 BOOLEAN NOT NULL,
    match_type              VARCHAR(50),
    match_score             NUMERIC(7,6),

    -- Per-field breakdown for extraction tasks
    field_results           JSONB,

    -- Links to decision log for full audit trail
    decision_log_id         UUID,

    duration_ms             INTEGER,
    created_at              TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_vrr UNIQUE (validation_run_id, record_index)
);

CREATE INDEX idx_vrr_run ON validation_record_result(validation_run_id);
CREATE INDEX idx_vrr_correct ON validation_record_result(validation_run_id, correct);
```

---

### Critical Gap 3: metric_threshold Needs Per-Field Support

Current `metric_threshold` table cannot express "named_insured accuracy >= 0.95 AND revenue accuracy >= 0.90". All thresholds are entity-level only.

**Fix: Add `field_name` column**

```sql
ALTER TABLE metric_threshold ADD COLUMN field_name VARCHAR(100);

-- Drop and recreate unique constraint to include field_name
ALTER TABLE metric_threshold DROP CONSTRAINT uq_threshold;
ALTER TABLE metric_threshold ADD CONSTRAINT uq_threshold 
    UNIQUE (entity_id, entity_type, materiality_tier, metric_name, field_name);
```

When `field_name` is NULL, the threshold applies to the aggregate metric. When set, it applies to that specific field. This supports both:
- `metric_name='f1_score', field_name=NULL, minimum=0.92` (aggregate F1)
- `metric_name='field_accuracy', field_name='named_insured', minimum=0.95` (per-field)

---

### Critical Gap 4: validation_run Needs Dataset Version Reference

`validation_run.dataset_id` points to a dataset but doesn't specify which version was used.

**Fix: Add column**

```sql
ALTER TABLE validation_run ADD COLUMN dataset_version INTEGER;
```

---

### Gap 5: Field Tolerance Configuration

Numeric extraction fields need tolerance-based comparison (is $49,500,000 close enough to $50,000,000?). No schema exists for this.

**Fix: New table `field_extraction_config`**

```sql
CREATE TABLE field_extraction_config (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type             entity_type NOT NULL,
    entity_id               UUID NOT NULL,
    field_name              VARCHAR(100) NOT NULL,
    field_type              VARCHAR(50) NOT NULL,   -- 'string', 'numeric', 'date', 'boolean', 'enum'
    match_type              VARCHAR(50) NOT NULL,   -- 'exact', 'numeric_tolerance', 'case_insensitive', 'contains'
    tolerance_value         NUMERIC(10,4),          -- For numeric: 0.05 = 5%
    tolerance_unit          VARCHAR(20),            -- 'percent' or 'absolute'
    is_required             BOOLEAN DEFAULT TRUE,   -- Must this field be extracted for "pass"?
    created_at              TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_field_config UNIQUE (entity_id, entity_type, field_name)
);
```

---

### Gap 6: Confusion Matrix and Field Accuracy Schema Definition

`validation_run.confusion_matrix` and `field_accuracy` are untyped JSONB. Define canonical schemas.

**Confusion matrix canonical format:**
```json
{
  "labels": ["acord_855", "acord_125", "loss_runs", "other"],
  "matrix": [[48, 1, 0, 1], [0, 49, 1, 0], [0, 2, 47, 1], [1, 0, 0, 49]],
  "per_class": {
    "acord_855": {"tp": 48, "fp": 1, "fn": 2, "precision": 0.96, "recall": 0.96, "f1": 0.96},
    ...
  }
}
```

**Field accuracy canonical format:**
```json
{
  "per_field": {
    "named_insured": {"correct": 48, "total": 50, "accuracy": 0.96},
    "annual_revenue": {"correct": 43, "total": 50, "accuracy": 0.86, "avg_error_pct": 0.03}
  },
  "overall_accuracy": 0.91,
  "fields_evaluated": 10,
  "records_evaluated": 50
}
```

These schemas will be documented in a comment block in schema.sql and enforced by the validation runner code.

---

### Gap 7: Governance Execution Identity

Every execution today flows through `agent_decision_log` with an `application`
(who triggered it), `execution_context_id` (business grouping), `channel`
(deployment stage), and `mock_mode` (was mocking used). But none of these
answer *why* the execution happened - was it a production run, a test, a
validation, or an audit reproduction?

When the test runner calls `run_agent()`, what application does it claim?
Today it would inherit "uw_demo" from the execution engine, polluting
production decision logs with test executions.

**Fix: run_purpose enum + governance applications**

```sql
CREATE TYPE run_purpose AS ENUM (
    'production',       -- normal business execution
    'test',             -- test suite run
    'validation',       -- ground truth validation
    'audit_rerun'       -- historical reproduction
);

ALTER TABLE agent_decision_log ADD COLUMN run_purpose run_purpose NOT NULL DEFAULT 'production';
ALTER TABLE agent_decision_log ADD COLUMN reproduced_from_decision_id UUID REFERENCES agent_decision_log(id);
```

`run_purpose` answers WHY. `application` answers WHO. `channel` answers
WHAT STAGE. These are three independent axes:

| Axis | Field | Example |
|------|-------|---------|
| Who triggered it | `application` | "ai_ops", "model_validation", "uw_demo" |
| Why it happened | `run_purpose` | "test", "validation", "production" |
| What deployment stage | `channel` | "staging", "production" |
| Was it mocked | `mock_mode` | true / false |

**Three governance applications (registered by Verity platform setup, not by business apps):**

| Machine Name | Display Name | Stakeholders | Primary Purpose |
|---|---|---|---|
| `ai_ops` | AI Operations | AI/ML engineers, developers | Test suite runs, regression testing, development experimentation |
| `model_validation` | Model Validation | Model Risk Management (MRM) team | Ground truth validation for promotion gates, independent model assessment |
| `compliance_audit` | Compliance & Audit | Compliance officers, internal audit, regulators | Audit reruns, regulatory reproduction, adverse action verification |

**Why separate applications, not one "verity_governance":**

1. **SR 11-7 separation of duties** - The team that builds the model (AI Ops)
   must NOT be the same team that validates it (MRM). Separate applications
   enforce and demonstrate this separation in the audit trail.

2. **Dashboard filtering** - "Show me all model_validation decisions this
   quarter" and "Show me all ai_ops test runs" are natural queries.
   Production business apps are never polluted.

3. **Applications are independent of run_purpose** - The model_validation
   team could run a test suite (`run_purpose=test`) to reproduce a testing
   team's finding. Compliance could trigger a validation run
   (`run_purpose=validation`) during a regulatory exam. The axes are orthogonal.

**Execution context patterns for governance runs:**

```
-- Test suite run
application = "ai_ops"
execution_context.context_type = "test_suite_run"
execution_context.context_ref  = "suite:document_classifier_unit:run_20260405_001"

-- Ground truth validation
application = "model_validation"
execution_context.context_type = "validation_run"
execution_context.context_ref  = "validation:classifier_gt_v1:run_20260405_001"

-- Audit rerun (links to original decision)
application = "compliance_audit"
execution_context.context_type = "audit_rerun"
execution_context.context_ref  = "rerun:decision_abc123"
execution_context.metadata     = {"original_decision_id": "abc123",
                                   "original_application": "uw_demo",
                                   "reason": "regulatory_exam_2026Q2"}
reproduced_from_decision_id    = <original decision UUID>
```

**Audit rerun linkage:** `reproduced_from_decision_id` on `agent_decision_log`
gives a direct FK to the original decision being reproduced. No need to dig
through JSONB metadata. The original decision's application, context, and
full audit trail remain untouched.

**Seeding:** These three applications are registered during Verity platform
initialization (`verity/src/verity/db/migrate.py` or a dedicated platform
setup script), NOT in `uw_demo/app/setup/register_all.py`. They are Verity
infrastructure, not business app registrations.

---

### Summary of Schema Changes

| Change | Type | Impact |
|--------|------|--------|
| `ground_truth_dataset` | REPLACE | New design with quality_tier, status lifecycle, IAA metrics, storage abstraction |
| `ground_truth_record` | NEW TABLE | Per-record input items with storage-abstracted document refs, tags, difficulty |
| `ground_truth_annotation` | NEW TABLE | Multi-annotator labels with lineage, LLM-as-judge, adjudication, is_authoritative |
| `validation_record_result` | NEW TABLE | Per-record validation predictions for drill-down |
| `field_extraction_config` | NEW TABLE | Per-field tolerance and type config |
| `metric_threshold.field_name` | ALTER | Per-field thresholds for extraction |
| `validation_run.dataset_version` | ALTER | Dataset version disambiguation |
| `agent_decision_log.run_purpose` | ALTER | New enum column: production/test/validation/audit_rerun |
| `agent_decision_log.reproduced_from_decision_id` | ALTER | FK to original decision for audit reruns |
| `run_purpose` | CREATE TYPE | New enum for execution intent |
| 4 `gt_*` ENUMs | CREATE TYPE | `gt_dataset_status`, `gt_quality_tier`, `gt_source_type`, `gt_annotator_type` |
| 3 governance applications | SEED DATA | ai_ops, model_validation, compliance_audit registered in application table |
| `insert_ground_truth_dataset` SQL | REWRITE | Match new table structure |

**Also needed:** Update registration.sql query `insert_ground_truth_dataset` and any seed script references to the old table structure. Update execution engine to accept `run_purpose` and `reproduced_from_decision_id` parameters.

**Deferred (not needed for demo):**
- Protected class tables for fairness segmentation
- Threshold violation severity tracking
- Regression test generation from production decisions

---

## PART 2: SOURCE DATA - PROMPTS, DOCUMENTS, AND GROUND TRUTH

### Current State (Critical Gaps)

**Prompts are placeholder quality:**
- Triage agent system prompt v1: 1 sentence ("You are a risk assessment assistant...")
- Triage agent system prompt v2: Basic structure but no scoring criteria, no examples, no chain-of-thought
- Document classifier: No document type descriptions, no recognition guidance, no examples
- Field extractor: Lists 20 fields but no field definitions, no format specs, no examples
- Context templates: 3 template variables only, no structured context

**No document content exists:**
- 12 document references in document_tools.py (filenames, sizes) but ZERO actual text
- Document classifier and field extractor tasks have nothing to classify or extract
- Test cases use truncated placeholders ("ACORD 855 DIRECTORS AND OFFICERS... ")
- MinIO buckets exist but are empty

**Mock outputs are unrealistically simple:**
- 1 risk factor per triage assessment (real assessments have 3-5)
- Reasoning is 1 sentence (prompts request 2-3 paragraphs)
- Missing mitigating_factors field in most outputs

### What Needs to Be Built

#### A. Production-Grade Prompts

Each prompt needs to be rewritten from scratch with:
- Clear decision criteria with specific thresholds
- Worked examples (2-3 per prompt) showing expected reasoning
- Chain-of-thought structure
- Edge case handling
- Confidence calibration guidance
- Domain terminology and definitions
- Complete output JSON schema with examples

**Prompts to rewrite (8 total):**

1. **Triage Agent System (behavioural)** - Complete decision framework with Green/Amber/Red criteria tied to specific metrics. Include scoring guidance with threshold ranges. Chain-of-thought instruction. 3 worked examples.

2. **Triage Agent Context (contextual)** - Rich template with all available submission fields, not just 3. Instruction on tool call order and what constitutes "full context".

3. **Appetite Agent System (behavioural)** - Systematic guideline comparison framework. Weighting rules for contradictions. Exception criteria. 2 worked examples (within and outside appetite).

4. **Appetite Agent Context (contextual)** - LOB-specific instruction, all submission fields, guideline reference.

5. **Document Classifier System (behavioural)** - Description of each document type with recognition signatures. Header patterns, keyword sets, structural markers. Confidence calibration. 2-3 example excerpts per type.

6. **Document Classifier Input (formatting)** - Include document metadata (source, submission_id) alongside text.

7. **Field Extractor System (behavioural)** - Field-by-field definitions with data types, format specs, and example values. Confidence calibration rules. Output schema with example. Handling of missing, ambiguous, and multi-value fields.

8. **Field Extractor Input (formatting)** - Include document type context and extraction expectations.

#### B. Sample Insurance Document Content

Need realistic text representations of insurance documents. NOT actual ACORD PDFs (copyrighted), but text content that mirrors what OCR or PDF extraction would produce from these forms.

**Documents to generate (per submission, ~44 total across 4 submissions + extras for ground truth):**

| Document Type | Count | Content |
|---------------|-------|---------|
| ACORD 855 (D&O Application) | 8-10 | Sections: Applicant Info, Corporate Structure, Board of Directors, Prior Insurance, Claims History, Securities History, Regulatory Questions |
| ACORD 125 (GL Application) | 8-10 | Sections: Applicant Info, Operations Description, Location Schedule, Products/Completed Ops, Prior Insurance, Claims |
| Loss Run Reports | 8-10 | Policy periods, claim line items (date, claimant, type, status, paid, reserved, incurred) |
| Financial Statements | 5-6 | Balance sheet summary, income statement highlights, auditor opinion, going concern notes |
| Board Resolutions | 3-4 | Board composition, committee structure, D&O authorization |
| Supplemental questionnaires | 4-5 | D&O supplementals (regulatory history), GL supplementals (product liability) |

**Generation approach:** Python script using string templates with randomized company data pools. Each document is 500-2000 words of realistic insurance text. Stored as .txt files in `uw_demo/seed_docs/` and uploaded to MinIO during setup.

**Company data pools needed:**
- 20+ company names with addresses, FEINs, SIC codes
- Revenue ranges ($5M-$500M)
- Employee counts (50-5000)
- Board compositions (3-12 members)
- Loss histories (0-20 claims over 3 years, varied severity)
- Industry sectors (manufacturing, technology, professional services, financial)
- Regulatory scenarios (clean, inquiry, enforcement, investigation)

#### C. Ground Truth Datasets

With documents generated, build labeled ground truth datasets:

**1. Document Classification Ground Truth (200 records)**
- 50 ACORD 855 texts + label "acord_855"
- 50 ACORD 125 texts + label "acord_125"
- 50 loss run texts + label "loss_runs"
- 25 financial statement texts + label "financial_statements"
- 15 board resolution texts + label "board_resolution"
- 10 supplemental texts + label "supplemental_do" or "supplemental_gl"
- Each record: input_data = {document_text}, expected_output = {document_type, confidence}
- Stored in ground_truth_record table AND exported to MinIO JSON for portability

**2. Field Extraction Ground Truth (50 records)**
- 50 ACORD 855 texts with all 20 fields hand-verified
- Each record: input_data = {document_text}, expected_output = {fields: {field_name: {value, confidence}}}
- field_extraction_config defines tolerance per field

**3. Triage Agent Ground Truth (30 records)**
- 10 Green (clean, well-capitalized companies)
- 10 Amber (borderline: some positives, some negatives, competing signals)
- 10 Red (clear disqualifiers: going concern, excluded SIC, excessive claims)
- Each record includes tool_mock_overrides so tools return record-specific submission data
- Expected output: {risk_score, routing, confidence, reasoning, risk_factors}

**4. Appetite Agent Ground Truth (30 records)**
- 10 within_appetite (all criteria met)
- 10 borderline (1-2 criteria unmet but not disqualifying)
- 10 outside_appetite (disqualifying criteria violated)
- Includes guideline citations in expected output

#### D. Mock Output Improvements

Update pipeline.py mock outputs to match production-grade prompt expectations:
- 3-5 risk factors per triage (not 1)
- 2-3 paragraph reasoning (not 1 sentence)
- Include mitigating_factors array
- Include decision_rationale chain-of-thought
- Guideline citations for appetite with section references

---

## PART 3: METRICS ENGINE AND TEST/VALIDATION RUNNER

### 3A. Metrics Engine
**New file:** `verity/src/verity/core/metrics.py`

Pure computation module (no DB, no I/O). Implements from scratch for regulatory auditability - no sklearn dependency.

```
MetricsEngine:
  classification_metrics(actual: list[str], expected: list[str]) -> dict
    Returns: precision, recall, f1 (macro-averaged), cohens_kappa,
             confusion_matrix (canonical format), per_class breakdown

  field_accuracy(actual_fields: dict, expected_fields: dict,
                 field_configs: list[FieldExtractionConfig]) -> dict
    Returns: per_field_accuracy, overall_accuracy, missing_fields, extra_fields
    Respects tolerance config per field

  exact_match(actual: Any, expected: Any) -> dict
    Returns: matched (bool), differences (list)

  schema_valid(output: dict, schema: dict) -> dict
    Returns: valid (bool), errors (list)
```

### 3B. Test Runner
**New file:** `verity/src/verity/core/test_runner.py`

```
TestRunner(registry, execution_engine, testing, metrics):
  run_suite(entity_type, entity_version_id, suite_id, mock_llm=True) -> SuiteResult
  run_single_case(entity_type, entity_version_id, test_case_id, mock_llm=True) -> CaseResult
```

Uses the SAME execution path as production. MockContext controls what's mocked.

### 3C. Validation Runner
**New file:** `verity/src/verity/core/validation_runner.py`

```
ValidationRunner(registry, execution_engine, testing, metrics, db):
  run_validation(entity_type, entity_version_id, dataset_id, run_by) -> ValidationResult
    1. Load ground truth records from ground_truth_record table
    2. For each record: build MockContext from tool_mock_overrides, run entity, collect prediction
    3. Store per-record results in validation_record_result
    4. Compute aggregate metrics via MetricsEngine
    5. Check against metric_thresholds (including per-field)
    6. Store validation_run record
    7. Update version flag (staging_tests_passed or ground_truth_passed)
```

### 3D. New SQL Queries

Add to `verity/src/verity/db/queries/testing.sql`:
- `list_all_test_suites` - All suites with case counts and last-run stats
- `get_test_suite` - Single suite by ID
- `list_ground_truth_datasets` - All datasets with entity info and record counts
- `get_ground_truth_dataset` - Single dataset by ID
- `list_ground_truth_records` - Records for a dataset
- `create_ground_truth_record` - Insert individual record
- `create_validation_run` - Insert validation_run
- `create_validation_record_result` - Insert per-record result
- `list_validation_record_results` - Results for a run (with correct/incorrect filter)
- `update_agent_version_staging_flag` - Set staging_tests_passed
- `update_task_version_staging_flag`
- `update_agent_version_ground_truth_flag` - Set ground_truth_passed
- `update_task_version_ground_truth_flag`
- `list_metric_thresholds` - Thresholds for an entity (including per-field)
- `list_field_extraction_configs` - Tolerance configs for extraction entity
- `list_all_entity_versions_with_state` - UNION ALL across all version tables for lifecycle overview

### 3E. Client and Model Changes

**Modify `client.py`:** Add test_runner, validation_runner initialization and facade methods.

**Modify `models/testing.py`:** Add SuiteResult, CaseResult, ValidationResult, GroundTruthRecord models.

---

## PART 4: LIFECYCLE MANAGEMENT UI

### 4A. Lifecycle Overview Page
**New template:** `lifecycle.html`

All entity versions across all types in one filterable table:
| Entity | Type | Version | State | Tests Passed | Validation Passed | Actions |

Filter tabs: All | Agents | Tasks | Prompts | Pipelines
State filter: All | Draft | Candidate | ... | Champion

### 4B. Version Lifecycle Detail Page
**New template:** `lifecycle_detail.html`

1. **7-state progression bar** - Visual nodes with current state highlighted
2. **Version metadata** - Entity name, version, state, channel, created_at
3. **Gate requirements checklist** - For the next possible transition, show each requirement with pass/fail
4. **Evidence links** - Test results, validation results, model card, approval history
5. **Promotion form** (HTMX POST) - Approver name, role, rationale, evidence checkboxes, "Promote" button

### 4C. Routes

Replace 3 placeholder routes in `routes.py` (lines 498-535):
- `GET /admin/lifecycle` - Overview with all versions
- `GET /admin/lifecycle/{entity_type}/{version_id}` - Detail with gates
- `POST /admin/lifecycle/{entity_type}/{version_id}/promote` - HTMX promotion action

---

## PART 5: TEST STATUS UI

### 5A. Test Suites Overview
**New template:** `test_results.html`

| Suite | Entity | Type | Cases | Last Run | Pass Rate | Run |

### 5B. Test Suite Detail
**New template:** `test_suite_detail.html`

Suite metadata, test cases with expected outputs, latest results per case, aggregate metrics, "Run All Tests" button.

### 5C. Routes
- `GET /admin/test-results` - All suites overview
- `GET /admin/test-results/{suite_id}` - Suite detail with results
- `POST /admin/test-results/{suite_id}/run` - HTMX test execution

---

## PART 6: GROUND TRUTH & VALIDATION UI

### 6A. Ground Truth Datasets Page
**New template:** `ground_truth.html`

| Dataset | Entity | Records | Labeled By | Last Validation | Status | Validate |

### 6B. Validation Results Detail
**New template:** `validation_detail.html`

- Metric cards (precision, recall, F1, kappa)
- Confusion matrix (color-coded HTML table)
- Field accuracy breakdown (for extraction)
- Threshold comparison table (metric | required | achieved | pass/fail)
- Misclassified records drill-down (from validation_record_result where correct=false)

### 6C. Routes
- `GET /admin/ground-truth` - All datasets
- `GET /admin/ground-truth/{dataset_id}` - Dataset detail with records
- `GET /admin/ground-truth/{dataset_id}/validation` - Latest validation results
- `POST /admin/ground-truth/{dataset_id}/validate` - HTMX validation trigger

---

## IMPLEMENTATION ORDER

| Phase | What | Files |
|-------|------|-------|
| **1. Schema** | New tables + ALTER statements | `db/schema.sql`, new migration SQL |
| **2. Source data** | Document generation script, prompt rewrites | `scripts/generate_documents.py`, `register_all.py` |
| **3. Ground truth** | Ground truth record population | `scripts/generate_ground_truth.py`, `register_all.py` |
| **4. Metrics** | Metrics engine | `core/metrics.py` |
| **5. Test runner** | Test execution orchestrator | `core/test_runner.py`, SQL queries |
| **6. Validation runner** | Ground truth validation | `core/validation_runner.py`, SQL queries |
| **7. Lifecycle UI** | Overview + detail + promote | Templates, routes |
| **8. Test status UI** | Suites + results + run | Templates, routes |
| **9. Ground truth UI** | Datasets + validation + drill-down | Templates, routes |
| **10. Mock output upgrade** | Richer pipeline mock outputs | `pipeline.py` |

Phase 1-3 are foundational. Phases 4-6 are backend. Phases 7-9 are UI. Phase 10 is polish.

---

## VERIFICATION

1. **Schema**: Run migration, verify new tables created with correct columns and constraints
2. **Documents**: Generate documents, verify 40+ text files in seed_docs/, upload to MinIO
3. **Ground truth**: Populate ground_truth_record table, verify 200+ records queryable by dataset
4. **Metrics**: Unit test with known inputs (e.g., [A,A,B] vs [A,B,B] yields known F1)
5. **Test runner**: Run 3 existing suites against champion versions with mock_llm=True, all should pass
6. **Validation**: Run classifier validation against 200-record dataset, verify per-record results stored and aggregate metrics computed
7. **Lifecycle UI**: Navigate /admin/lifecycle, see all versions, click detail, see gate checklist, promote a draft to candidate
8. **End-to-end**: New version -> run tests -> pass gates -> promote through lifecycle -> all visible in UI
