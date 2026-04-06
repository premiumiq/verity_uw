cat > /home/avenugopal/.claude/plans/harmonic-chasing-ocean-agent-acd4964ac514d4d92.md << 'PLANEOF'
# Verity Lifecycle Management UI & Testing/Validation Framework
## Comprehensive Implementation Plan

---

## 1. EXECUTIVE SUMMARY

This plan covers five interconnected workstreams that transform Verity from a
registry-with-seeded-data into an end-to-end AI governance platform with:

- **Test Runner Module** — execute test suites, compute real metrics, store results
- **Validation Execution Module** — run entities against ground truth datasets
- **Metric Computation Library** — F1, precision, recall, kappa, field accuracy
- **Lifecycle Management UI** — pages for asset composition, testing, promotion
- **Document Generation** — synthetic PDFs/JSON for MinIO ground truth

**Phasing**: Three phases. Phase 1 (demo-ready in ~5 days) delivers the test runner,
metric computation, lifecycle UI, and synthetic ground truth. Phase 2 adds the full
validation runner and document upload. Phase 3 adds shadow/challenger evaluation.

---

## 2. MODULE ARCHITECTURE

### 2.1 New Files to Create

```
verity/src/verity/
├── core/
│   ├── test_runner.py         # NEW: Execute test suites using MockContext
│   ├── validation_runner.py   # NEW: Execute ground truth validation
│   ├── metrics.py             # NEW: Classification & extraction metrics
│   └── documents.py           # NEW: MinIO ground truth operations
├── db/queries/
│   └── testing.sql            # MODIFY: Add new queries
│   └── lifecycle.sql          # MODIFY: Add gate-check queries
│   └── composition.sql        # NEW: Queries for asset composition UI
├── models/
│   └── testing.py             # MODIFY: Add GroundTruthDataset model, RunRequest models
│   └── composition.py         # NEW: Form models for asset composition
├── web/
│   ├── routes.py              # MODIFY: Add lifecycle, testing, composition routes
│   ├── routes_lifecycle.py    # NEW: Lifecycle management page routes
│   ├── routes_testing.py      # NEW: Testing & validation page routes
│   ├── routes_composition.py  # NEW: Asset composition page routes
│   └── templates/
│       ├── lifecycle.html           # NEW: Lifecycle overview page
│       ├── lifecycle_version.html   # NEW: Per-version lifecycle detail + promote
│       ├── test_suites.html         # NEW: Test suite browser & runner
│       ├── test_results.html        # REPLACE: Real test results page
│       ├── test_run_detail.html     # NEW: Single test run detail
│       ├── ground_truth.html        # REPLACE: Ground truth dataset manager
│       ├── ground_truth_upload.html # NEW: Upload ground truth dataset
│       ├── validation_run.html      # NEW: Run validation + view results
│       ├── compose_prompt.html      # NEW: Create/edit prompt versions
│       ├── compose_task.html        # NEW: Compose task versions
│       ├── compose_agent.html       # NEW: Compose agent versions
│       ├── compose_pipeline.html    # NEW: Compose pipeline versions
│       ├── partials/                # NEW: HTMX partial fragments
│       │   ├── _test_progress.html  # NEW: Live test execution progress
│       │   ├── _gate_status.html    # NEW: Gate requirements checklist
│       │   ├── _promote_form.html   # NEW: Promotion approval form
│       │   └── _metric_card.html    # NEW: Metric result display card
│       └── (existing templates unchanged)

scripts/
├── generate_ground_truth.py   # NEW: Generate synthetic ground truth datasets
└── seed_minio_documents.py    # NEW: Upload sample documents to MinIO
```

### 2.2 Files to Modify

| File | Changes |
|------|---------|
| `verity/src/verity/core/client.py` | Add test_runner, validation_runner properties; add run_test_suite(), run_validation(), compose_*() facade methods |
| `verity/src/verity/core/testing.py` | Add update_version_flags(), get_metric_thresholds(), list_ground_truth_datasets() |
| `verity/src/verity/core/lifecycle.py` | Add get_gate_status() (returns structured gate info for UI), get_version_timeline() |
| `verity/src/verity/core/registry.py` | Add list_ground_truth_datasets(), get_ground_truth_dataset() |
| `verity/src/verity/web/app.py` | Mount new route modules |
| `verity/src/verity/web/routes.py` | Replace lifecycle/test-results/ground-truth placeholders with real route groups |
| `verity/src/verity/web/templates/base.html` | No changes needed — nav links already point to /lifecycle, /test-results, /ground-truth |
| `verity/src/verity/db/queries/testing.sql` | Add 8+ new queries |
| `verity/src/verity/db/queries/lifecycle.sql` | Add 4+ new queries |
| `verity/src/verity/models/testing.py` | Add GroundTruthDataset, TestRunRequest, ValidationRequest models |
| `verity/src/verity/models/lifecycle.py` | Add GateStatus model |

---

## 3. TEST RUNNER MODULE DESIGN

### 3.1 Architecture: `verity/src/verity/core/test_runner.py`

The test runner sits between the Testing module (which reads/writes DB) and the
Execution Engine (which runs agents/tasks). It:

1. Loads test cases from a suite
2. For each test case, builds a MockContext from the case's `input_data` and `expected_output`
3. Calls the Execution Engine (run_agent or run_task) with the MockContext
4. Compares actual output vs expected output using the Metrics module
5. Logs results via Testing.log_test_result()
6. Optionally updates the version flag (staging_tests_passed)

```python
class TestRunner:
    """Execute test suites against entity versions using MockContext."""

    def __init__(self, testing: Testing, execution: ExecutionEngine, registry: Registry, metrics: MetricsEngine):
        self.testing = testing
        self.execution = execution
        self.registry = registry
        self.metrics = metrics

    async def run_suite(
        self,
        suite_id: UUID,
        entity_version_id: UUID,
        channel: str = "staging",
        mock_llm: bool = True,
    ) -> TestSuiteResult:
        """Run all active test cases in a suite against a specific version."""
        # 1. Load suite + cases
        # 2. For each case: build MockContext, execute, compute metric, log result
        # 3. Aggregate: all_passed, summary metrics
        # 4. If all_passed and flag_update requested: update version.staging_tests_passed

    async def run_single_case(
        self,
        test_case_id: UUID,
        entity_version_id: UUID,
        channel: str = "staging",
        mock_llm: bool = True,
    ) -> TestCaseResult:
        """Run a single test case."""

    def _build_mock_for_case(
        self,
        test_case: dict,
        entity_type: str,
    ) -> MockContext:
        """Build a MockContext from test case data.

        For classification tasks: mock LLM to return expected_output directly
        For extraction tasks: mock LLM to return expected field values
        For agents: mock both LLM (return expected output) and tools (mock_all_tools)
        """
```

**Key Design Decision**: Test cases define `input_data` (what to feed the entity) and
`expected_output` (what the correct answer is). The test runner uses `input_data` as the
execution input and `expected_output` for metric comparison. When `mock_llm=True` (default
for unit tests), the LLM is mocked to return the entity's expected output structure with
intentional variations (so metrics are realistic, not always 100%). When `mock_llm=False`,
the real LLM runs against the input, and the output is compared against expected.

**MockContext construction for test cases**:
- **Classification tasks** (mock_llm=True): `MockContext(llm_responses=[expected_output])`
  The LLM returns the expected classification. Metric = exact_match on the class label.
- **Classification tasks** (mock_llm=False): `MockContext()` (no mocking). Real LLM
  classifies, metric compares actual vs expected class.
- **Extraction tasks**: Same pattern but metric = field_accuracy.
- **Agents**: `MockContext(llm_responses=[expected_output], mock_all_tools=True)` since
  agents use tools. The LLM is mocked to return the final expected output directly
  (simple mock mode), and all tools use DB-registered mock responses.

### 3.2 Result Models

```python
@dataclass
class TestCaseResult:
    test_case_id: UUID
    test_case_name: str
    passed: bool
    metric_type: str
    metric_result: dict  # e.g., {"f1": 0.95, "precision": 0.96, "recall": 0.94}
    actual_output: dict
    expected_output: dict
    duration_ms: int
    failure_reason: Optional[str] = None

@dataclass
class TestSuiteResult:
    suite_id: UUID
    suite_name: str
    entity_version_id: UUID
    total_cases: int
    passed_cases: int
    failed_cases: int
    all_passed: bool
    case_results: list[TestCaseResult]
    aggregate_metrics: dict  # {"mean_f1": 0.94, "min_f1": 0.88, ...}
    duration_ms: int
```

---

## 4. METRIC COMPUTATION MODULE

### 4.1 Architecture: `verity/src/verity/core/metrics.py`

A pure-function module with no DB dependencies. All inputs/outputs are dicts.
No external ML libraries (no sklearn) -- implements metrics from scratch for
transparency and auditability.

```python
class MetricsEngine:
    """Compute classification and extraction metrics.

    All methods are static/classmethod -- no state.
    Implements from scratch for auditability (no sklearn dependency).
    """

    @staticmethod
    def classification_metrics(
        actual_labels: list[str],
        expected_labels: list[str],
        classes: list[str] | None = None,
    ) -> dict:
        """Compute precision, recall, F1 (macro-averaged), and confusion matrix.

        Returns:
            {
                "precision": float,
                "recall": float,
                "f1": float,
                "per_class": {
                    "acord_855": {"precision": 0.96, "recall": 0.94, "f1": 0.95, "support": 50},
                    ...
                },
                "confusion_matrix": {"acord_855": {"acord_855": 48, "other": 2}, ...},
                "support": 200,
            }
        """

    @staticmethod
    def cohens_kappa(
        actual_labels: list[str],
        expected_labels: list[str],
    ) -> float:
        """Compute Cohen's kappa inter-rater reliability coefficient.

        kappa = (p_o - p_e) / (1 - p_e)
        where p_o = observed agreement, p_e = expected agreement by chance.
        """

    @staticmethod
    def field_accuracy(
        actual_fields: dict[str, Any],
        expected_fields: dict[str, Any],
        required_fields: list[str] | None = None,
        tolerance: float = 0.0,
    ) -> dict:
        """Compute per-field accuracy for extraction tasks.

        Returns:
            {
                "overall_accuracy": 0.92,
                "per_field": {
                    "named_insured": {"correct": True, "actual": "Acme Corp", "expected": "Acme Corp"},
                    "annual_revenue": {"correct": True, "actual": 50000000, "expected": 50000000},
                    "fein": {"correct": False, "actual": "12-345678", "expected": "12-3456789"},
                },
                "fields_correct": 18,
                "fields_total": 20,
                "missing_fields": ["board_size"],
            }
        """

    @staticmethod
    def exact_match(actual: Any, expected: Any) -> dict:
        """Simple exact match comparison.

        Returns: {"matched": True/False, "actual": ..., "expected": ...}
        """

    @staticmethod
    def schema_valid(output: dict, schema: dict) -> dict:
        """Validate output against a JSON schema.

        Returns: {"valid": True/False, "errors": [...]}
        """

    @staticmethod
    def aggregate_suite_metrics(case_results: list[dict]) -> dict:
        """Aggregate per-case metrics into suite-level summary.

        Computes: mean/min/max F1, overall pass rate, etc.
        """
```

### 4.2 Classification Metric Implementation Detail

For a single test case with metric_type=classification_f1:
- `actual_output` = `{"document_type": "acord_855", "confidence": 0.97}`
- `expected_output` = `{"document_type": "acord_855", "confidence": 0.95}`
- Metric compares `actual_output["document_type"]` vs `expected_output["document_type"]`
- Returns `{"matched": True, "actual_class": "acord_855", "expected_class": "acord_855"}`

For a full suite (3 cases), aggregate into confusion matrix and compute F1.

For validation runs (200 records), the full classification_metrics() function runs
with 200 actual/expected pairs, producing the complete confusion matrix, per-class
F1, and macro-averaged scores.

### 4.3 Field Accuracy Implementation Detail

For extraction tasks:
- `actual_output` = `{"fields": {"named_insured": "Acme Corp", "fein": "12-345678", ...}}`
- `expected_output` = `{"fields": {"named_insured": "Acme Corp", "fein": "12-3456789", ...}}`
- Compare each field: string equality (with optional normalization: strip, lowercase)
- Numeric fields: compare with tolerance (e.g., 50000000 vs 50000000.0)
- Missing fields: count as incorrect
- Returns per-field accuracy + overall accuracy rate

---

## 5. GROUND TRUTH & VALIDATION DESIGN

### 5.1 Ground Truth Dataset Format

Ground truth datasets are JSON files stored in MinIO. The format supports both
classification and extraction validation:

**Classification Ground Truth** (document_classifier):
```json
{
    "metadata": {
        "entity_type": "task",
        "entity_name": "document_classifier",
        "version": 1,
        "record_count": 200,
        "labeled_by": "Maria Santos, Senior UW",
        "created_at": "2026-04-01T00:00:00Z",
        "label_classes": ["acord_855", "acord_125", "loss_runs", "supplemental_do", "other"]
    },
    "records": [
        {
            "id": "gt-001",
            "input": {
                "document_text": "ACORD 855 DIRECTORS AND OFFICERS LIABILITY APPLICATION...",
                "document_filename": "acord_855_sample_001.pdf"
            },
            "expected_output": {
                "document_type": "acord_855",
                "confidence_min": 0.85
            },
            "label_notes": "Clear ACORD 855 header, standard form layout",
            "difficulty": "easy"
        },
        ...
    ]
}
```

**Extraction Ground Truth** (field_extractor):
```json
{
    "metadata": {
        "entity_type": "task",
        "entity_name": "field_extractor",
        "version": 1,
        "record_count": 50,
        "labeled_by": "Maria Santos, Senior UW",
        "required_fields": ["named_insured", "fein", "annual_revenue", ...]
    },
    "records": [
        {
            "id": "gt-ext-001",
            "input": {
                "document_text": "Named Insured: Acme Dynamics LLC FEIN: 12-3456789...",
                "submission_id": "gt-sub-001"
            },
            "expected_output": {
                "fields": {
                    "named_insured": "Acme Dynamics LLC",
                    "fein": "12-3456789",
                    "annual_revenue": 50000000,
                    "employee_count": 500,
                    ...
                }
            },
            "label_notes": "Complete form, all fields present"
        },
        ...
    ]
}
```

**Agent Ground Truth** (triage_agent):
```json
{
    "metadata": {
        "entity_type": "agent",
        "entity_name": "triage_agent",
        "version": 1,
        "record_count": 20,
        "labeled_by": "James Okafor, Model Risk",
        "label_classes": ["Green", "Amber", "Red"]
    },
    "records": [
        {
            "id": "gt-triage-001",
            "input": {
                "submission_id": "gt-sub-001",
                "lob": "DO",
                "named_insured": "SafeCorp LLC"
            },
            "expected_output": {
                "risk_score": "Green",
                "routing": "assign_to_uw"
            },
            "tool_mock_overrides": {
                "get_submission_context": {"account_name": "SafeCorp LLC", ...},
                "get_loss_history": {"total_claims": 0, ...}
            }
        },
        ...
    ]
}
```

### 5.2 Validation Runner: `verity/src/verity/core/validation_runner.py`

```python
class ValidationRunner:
    """Execute entity versions against ground truth datasets and compute metrics."""

    def __init__(self, testing: Testing, execution: ExecutionEngine,
                 registry: Registry, metrics: MetricsEngine, minio_client):
        self.testing = testing
        self.execution = execution
        self.registry = registry
        self.metrics = metrics
        self.minio = minio_client

    async def run_validation(
        self,
        entity_type: str,
        entity_version_id: UUID,
        dataset_id: UUID,
        run_by: str,
        mock_llm: bool = True,
        mock_tools: bool = True,
    ) -> ValidationRunResult:
        """Run a full validation against a ground truth dataset.

        Steps:
        1. Load ground truth dataset from MinIO
        2. For each record: build MockContext, execute entity, collect output
        3. Compute aggregate metrics (F1, field_accuracy, confusion matrix)
        4. Compare against metric_thresholds
        5. Store validation_run record
        6. Update version flag (ground_truth_passed)
        """

    async def _load_ground_truth(self, dataset_id: UUID) -> dict:
        """Load ground truth JSON from MinIO."""

    async def _execute_single_record(
        self, record: dict, entity_type: str, entity_name: str,
        entity_version_id: UUID, mock_llm: bool, mock_tools: bool,
    ) -> dict:
        """Execute entity against one ground truth record."""

    async def _check_thresholds(
        self, entity_type: str, entity_id: UUID,
        materiality_tier: str, metrics: dict,
    ) -> dict:
        """Compare computed metrics against metric_threshold records."""
```

### 5.3 MinIO Document Operations: `verity/src/verity/core/documents.py`

```python
class Documents:
    """MinIO operations for ground truth datasets and sample documents."""

    def __init__(self, minio_endpoint: str, access_key: str, secret_key: str):
        self.client = Minio(minio_endpoint, access_key, secret_key, secure=False)

    async def upload_ground_truth(self, dataset_json: dict, bucket: str, key: str) -> str:
        """Upload a ground truth JSON file to MinIO."""

    async def download_ground_truth(self, bucket: str, key: str) -> dict:
        """Download and parse a ground truth JSON file from MinIO."""

    async def list_ground_truth_files(self, bucket: str, prefix: str = "") -> list[str]:
        """List ground truth files in a bucket."""

    async def upload_document(self, file_bytes: bytes, bucket: str, key: str,
                              content_type: str = "application/pdf") -> str:
        """Upload a sample document to MinIO."""
```

---

## 6. UI PAGE STRUCTURE & NAVIGATION FLOW

### 6.1 New Pages Overview

The existing sidebar already has nav links for Lifecycle, Ground Truth, and Test Status.
These currently point to placeholder routes. The plan replaces them with real pages.

**Governance Section** (sidebar):
- **Lifecycle** `/admin/lifecycle` -- Overview of all entities with lifecycle state
  - `/admin/lifecycle/{entity_type}/{entity_name}` -- Per-entity version timeline
  - `/admin/lifecycle/{entity_type}/{version_id}/promote` -- Promotion form (HTMX)
- **Ground Truth** `/admin/ground-truth` -- List all ground truth datasets
  - `/admin/ground-truth/upload` -- Upload new dataset
  - `/admin/ground-truth/{dataset_id}` -- View dataset detail + run validation
- **Test Status** `/admin/test-results` -- Test suites, results, run tests
  - `/admin/test-results/{suite_id}` -- View suite detail + run
  - `/admin/test-results/run/{execution_id}` -- View run detail

**Registry Section** (new "Compose" sub-routes on existing detail pages):
- `/admin/prompts/new` -- Create new prompt + version
- `/admin/prompts/{name}/new-version` -- Create new version of existing prompt
- `/admin/agents/{name}/compose` -- Compose new agent version (pick prompts, config, tools)
- `/admin/tasks/{name}/compose` -- Compose new task version
- `/admin/pipelines/{name}/compose` -- Compose new pipeline version

### 6.2 Lifecycle Overview Page (`lifecycle.html`)

**Layout**: Two-column page. Left: entity type filter tabs (All | Agents | Tasks | Prompts | Pipelines). Right: main content.

**Main Content**: Table showing all entity versions across all types, with:
- Entity name, type, version label, current lifecycle state (badge)
- Materiality tier (badge)
- Gate status indicators (checkmarks/crosses for: staging_tests_passed, ground_truth_passed, fairness_passed, shadow_period_complete, challenger_period_complete)
- Available actions: "View" link, "Promote" button (only if next transition is valid)
- Filter by lifecycle state (dropdown): Draft, Candidate, Staging, etc.

**HTMX pattern**: The entity type tabs and state filter use `hx-get` to load filtered
table body without full page reload. Each filter hits an endpoint like
`/admin/lifecycle?entity_type=agent&state=candidate` which returns the table partial.

### 6.3 Version Lifecycle Detail Page (`lifecycle_version.html`)

**Reached via**: Clicking a version row in the lifecycle overview.

**Layout**:
1. **Version Header**: Entity name, version label, current state (large badge),
   materiality tier, inference config name.

2. **State Progression Visual**: Horizontal 7-step bar showing:
   `draft → candidate → staging → shadow → challenger → champion → deprecated`
   Current state highlighted. Completed states checked. Future states grayed.
   This is pure CSS/HTML, no JavaScript needed.

3. **Gate Requirements Panel**: For the NEXT valid transition, shows a checklist:
   - [ ] Staging tests passed (link to test results)
   - [ ] Ground truth validation passed (link to validation run)
   - [ ] Fairness analysis passed
   - [ ] Shadow period complete (N/A for early transitions)
   - [ ] Challenger period complete
   Each item shows pass/fail status and links to the relevant evidence page.

4. **Promote Action** (HTMX form):
   - Target state dropdown (only valid next states)
   - Approver name, role, rationale (text inputs)
   - Evidence checkboxes (dynamically shown based on target state)
   - "Promote" button -> POST to `/admin/lifecycle/promote` -> returns updated page

5. **Approval History**: Table of all approval_record rows for this version.

6. **Test Results Summary**: Latest test execution results (aggregated).

7. **Validation Summary**: Latest validation_run metrics.

### 6.4 Test Suites Page (`test_suites.html`)

**Layout**:
1. **Suite List**: All test suites grouped by entity. Each suite shows:
   - Suite name, entity type, entity name, suite_type (unit/integration)
   - Number of test cases
   - Last run date, pass/fail count
   - "Run Suite" button

2. **Suite Detail** (clicked row expands via HTMX, or navigates to detail page):
   - List of test cases with name, metric_type, tags
   - For each case: last result (passed/failed), last run date
   - "Run Case" button per case, "Run All" button for suite

3. **Run Suite Form** (HTMX modal or inline):
   - Select entity version to test against (dropdown of non-deprecated versions)
   - Mock mode toggle (mock_llm: yes/no)
   - Channel: staging (default)
   - "Execute" button -> POST -> returns progress partial

4. **Progress Partial** (`_test_progress.html`):
   - HTMX polls `/admin/test-results/status/{run_id}` every 2 seconds
   - Shows: "Running case 3 of 9..." with progress bar
   - On completion: shows summary table with pass/fail badges and metrics

### 6.5 Ground Truth Page (`ground_truth.html`)

**Layout**:
1. **Dataset List**: All ground_truth_dataset records with:
   - Name, entity type, entity name, version, record count
   - Labeled by, reviewed by
   - MinIO key (clickable to view/download)
   - "Run Validation" button

2. **Upload New Dataset**: Link to `/admin/ground-truth/upload`
   - Form with: entity type, entity name, dataset name, file upload (JSON)
   - Validates JSON structure before upload
   - Uploads to MinIO and creates ground_truth_dataset record

3. **Dataset Detail**: Click a dataset to see:
   - Metadata (record count, labeler, etc.)
   - Sample records (first 5, rendered as JSON)
   - Validation history (all validation_runs against this dataset)
   - "Run Validation" form: select entity version, run_by name, execute

### 6.6 Asset Composition Pages

**Compose Prompt** (`compose_prompt.html`):
- For new prompts: name, display_name, description fields
- For new versions of existing prompts: version number auto-incremented
- Content editor: `<textarea>` with monospace font (no rich editor needed)
- API role selector: system / user / assistant_prefill
- Governance tier selector: behavioural / contextual / formatting
- Change summary, author name fields
- "Save as Draft" button -> creates prompt + prompt_version via registry

**Compose Task** (`compose_task.html`):
- Select existing task (or create new)
- Version number auto-incremented from latest version
- Select inference config (dropdown of all configs)
- Select prompt versions to assign:
  - Multi-select with role assignments (system prompt, user template)
  - Execution order drag/sort or number inputs
- Output schema: JSON textarea
- "Save as Draft" button -> creates task_version, entity_prompt_assignments

**Compose Agent** (`compose_agent.html`):
- Same as task, plus:
- Tool authorization checkboxes (list all registered tools)
- Authority thresholds: JSON editor
- Output schema: JSON editor

**Compose Pipeline** (`compose_pipeline.html`):
- Pipeline step builder: ordered list of steps
- Each step: step_name, entity_type (agent/task), entity_name (dropdown),
  depends_on (multi-select), parallel_group, error_policy
- Add/remove steps with HTMX
- "Save as Draft" button -> creates pipeline_version

### 6.7 HTMX Interaction Patterns

Following the existing pattern in the codebase (HTMX via CDN, no custom JS):

1. **Tab switching**: `hx-get="/admin/lifecycle?type=agent" hx-target="#entity-table-body" hx-swap="innerHTML"`
2. **Run test**: `hx-post="/admin/test-results/run" hx-target="#run-results" hx-swap="innerHTML"`
3. **Promote version**: `hx-post="/admin/lifecycle/promote" hx-target="#promote-result" hx-swap="innerHTML"`
4. **Progress polling**: `hx-get="/admin/test-results/status/123" hx-trigger="every 2s" hx-target="#progress"`
5. **Dynamic form fields**: `hx-get="/admin/lifecycle/gate-fields?target=shadow" hx-target="#evidence-fields"`

---

## 7. SQL QUERIES NEEDED

### 7.1 New Queries for `testing.sql`

```sql
-- name: list_all_test_suites
-- For the test suites overview page
SELECT ts.*, 
       COUNT(tc.id) AS case_count,
       COALESCE(a.name, t.name, '') AS entity_name,
       COALESCE(a.display_name, t.display_name, '') AS entity_display_name
FROM test_suite ts
LEFT JOIN agent a ON ts.entity_type = 'agent' AND a.id = ts.entity_id
LEFT JOIN task t ON ts.entity_type = 'task' AND t.id = ts.entity_id
LEFT JOIN test_case tc ON tc.suite_id = ts.id AND tc.active = TRUE
WHERE ts.active = TRUE
GROUP BY ts.id, a.name, a.display_name, t.name, t.display_name
ORDER BY ts.entity_type, entity_name, ts.suite_type;

-- name: get_test_suite_with_stats
-- Suite detail with last run stats
SELECT ts.*,
       COUNT(tc.id) AS case_count,
       (SELECT COUNT(*) FROM test_execution_log tel 
        WHERE tel.suite_id = ts.id AND tel.passed = TRUE
        AND tel.run_at = (SELECT MAX(run_at) FROM test_execution_log WHERE suite_id = ts.id)
       ) AS last_run_passed,
       (SELECT MAX(run_at) FROM test_execution_log WHERE suite_id = ts.id) AS last_run_at
FROM test_suite ts
LEFT JOIN test_case tc ON tc.suite_id = ts.id AND tc.active = TRUE
WHERE ts.id = %(suite_id)s::uuid
GROUP BY ts.id;

-- name: get_test_case_by_id
SELECT tc.* FROM test_case tc WHERE tc.id = %(test_case_id)s::uuid;

-- name: list_ground_truth_datasets
SELECT gtd.*,
       COALESCE(a.name, t.name) AS entity_name,
       COALESCE(a.display_name, t.display_name) AS entity_display_name,
       (SELECT COUNT(*) FROM validation_run vr WHERE vr.dataset_id = gtd.id) AS validation_count,
       (SELECT MAX(vr.run_at) FROM validation_run vr WHERE vr.dataset_id = gtd.id) AS last_validation_at
FROM ground_truth_dataset gtd
LEFT JOIN agent a ON gtd.entity_type = 'agent' AND a.id = gtd.entity_id
LEFT JOIN task t ON gtd.entity_type = 'task' AND t.id = gtd.entity_id
ORDER BY gtd.created_at DESC;

-- name: get_ground_truth_dataset
SELECT gtd.* FROM ground_truth_dataset gtd WHERE gtd.id = %(dataset_id)s::uuid;

-- name: list_validation_runs_for_dataset
SELECT vr.*,
       av.version_label AS agent_version_label,
       tv.version_label AS task_version_label
FROM validation_run vr
LEFT JOIN agent_version av ON vr.entity_type = 'agent' AND av.id = vr.entity_version_id
LEFT JOIN task_version tv ON vr.entity_type = 'task' AND tv.id = vr.entity_version_id
WHERE vr.dataset_id = %(dataset_id)s::uuid
ORDER BY vr.run_at DESC;

-- name: list_metric_thresholds_for_entity
SELECT mt.* FROM metric_threshold mt
WHERE mt.entity_type = %(entity_type)s::entity_type
  AND mt.entity_id = %(entity_id)s::uuid
ORDER BY mt.metric_name;

-- name: update_agent_version_staging_flag
UPDATE agent_version SET staging_tests_passed = %(passed)s, updated_at = NOW()
WHERE id = %(version_id)s::uuid RETURNING id;

-- name: update_task_version_staging_flag
UPDATE task_version SET staging_tests_passed = %(passed)s, updated_at = NOW()
WHERE id = %(version_id)s::uuid RETURNING id;

-- name: update_agent_version_ground_truth_flag
UPDATE agent_version SET ground_truth_passed = %(passed)s, updated_at = NOW()
WHERE id = %(version_id)s::uuid RETURNING id;

-- name: update_task_version_ground_truth_flag
UPDATE task_version SET ground_truth_passed = %(passed)s, updated_at = NOW()
WHERE id = %(version_id)s::uuid RETURNING id;
```

### 7.2 New Queries for `lifecycle.sql`

```sql
-- name: list_all_entity_versions_with_state
-- For lifecycle overview page: all versions across all entity types
SELECT 'agent' AS entity_type, a.name, a.display_name, a.materiality_tier,
       av.id AS version_id, av.version_label, av.lifecycle_state, av.channel,
       av.staging_tests_passed, av.ground_truth_passed, av.fairness_passed,
       av.shadow_period_complete, av.challenger_period_complete,
       av.created_at, av.developer_name, av.change_summary
FROM agent a JOIN agent_version av ON av.agent_id = a.id
WHERE av.lifecycle_state != 'deprecated'
UNION ALL
SELECT 'task', t.name, t.display_name, t.materiality_tier,
       tv.id, tv.version_label, tv.lifecycle_state, tv.channel,
       tv.staging_tests_passed, tv.ground_truth_passed, tv.fairness_passed,
       NULL, NULL,
       tv.created_at, tv.developer_name, tv.change_summary
FROM task t JOIN task_version tv ON tv.task_id = t.id
WHERE tv.lifecycle_state != 'deprecated'
UNION ALL
SELECT 'prompt', p.name, p.display_name, NULL,
       pv.id, pv.version_label, pv.lifecycle_state, NULL,
       pv.staging_tests_passed, NULL, NULL, NULL, NULL,
       pv.created_at, pv.author_name, pv.change_summary
FROM prompt p JOIN prompt_version pv ON pv.prompt_id = p.id
WHERE pv.lifecycle_state != 'deprecated'
UNION ALL
SELECT 'pipeline', pl.name, pl.display_name, NULL,
       plv.id, plv.version_number::text, plv.lifecycle_state, NULL,
       NULL, NULL, NULL, NULL, NULL,
       plv.created_at, plv.developer_name, plv.change_summary
FROM pipeline pl JOIN pipeline_version plv ON plv.pipeline_id = pl.id
WHERE plv.lifecycle_state != 'deprecated'
ORDER BY entity_type, name, created_at DESC;

-- name: get_version_gate_status
-- For a specific version: returns all gate flags + related evidence counts
-- (This will be entity-type specific; shown here for agents)
SELECT av.id, av.lifecycle_state, av.staging_tests_passed, av.ground_truth_passed,
       av.fairness_passed, av.shadow_period_complete, av.challenger_period_complete,
       (SELECT COUNT(*) FROM test_execution_log tel WHERE tel.entity_version_id = av.id) AS test_count,
       (SELECT COUNT(*) FROM test_execution_log tel WHERE tel.entity_version_id = av.id AND tel.passed = TRUE) AS tests_passed,
       (SELECT COUNT(*) FROM validation_run vr WHERE vr.entity_version_id = av.id) AS validation_count,
       (SELECT COUNT(*) FROM model_card mc WHERE mc.entity_version_id = av.id) AS model_card_count,
       (SELECT COUNT(*) FROM approval_record ar WHERE ar.entity_version_id = av.id) AS approval_count
FROM agent_version av WHERE av.id = %(version_id)s::uuid;
```

### 7.3 New Queries for `composition.sql`

```sql
-- name: list_available_prompts_for_entity
-- For composition UI: show all non-deprecated prompt versions
SELECT p.name, p.display_name, pv.id AS version_id, pv.version_label,
       pv.api_role, pv.governance_tier, pv.lifecycle_state,
       LEFT(pv.content, 100) AS content_preview
FROM prompt p JOIN prompt_version pv ON pv.prompt_id = p.id
WHERE pv.lifecycle_state != 'deprecated'
ORDER BY p.name, pv.major_version DESC, pv.minor_version DESC;

-- name: list_available_configs
SELECT id, name, display_name, model_name, temperature, max_tokens
FROM inference_config WHERE active = TRUE ORDER BY name;

-- name: list_available_tools
SELECT id, name, display_name, description, is_write_operation
FROM tool WHERE active = TRUE ORDER BY name;

-- name: get_next_version_number
-- For auto-incrementing version numbers
SELECT COALESCE(MAX(major_version), 0) + 1 AS next_major,
       MAX(minor_version) AS current_minor,
       MAX(patch_version) AS current_patch
FROM agent_version WHERE agent_id = %(entity_id)s::uuid;
```

---

## 8. DOCUMENT GENERATION STRATEGY

### 8.1 Approach: Synthetic Text-Based JSON Documents

Instead of generating actual PDF files (which would require external libraries
and complex rendering), the strategy is:

1. **Create JSON ground truth datasets** with realistic insurance document text
   embedded as `document_text` fields. This matches how the existing test cases
   already work (they pass `document_text` as input).

2. **Generate 200 classification records** with text that mimics real form content:
   - 50x ACORD 855 (D&O application) texts
   - 50x ACORD 125 (GL application) texts
   - 40x Loss run report texts
   - 30x Supplemental application texts
   - 30x Financial statement / board resolution / other texts

3. **Generate 50 extraction records** with ACORD 855-style text containing
   labeled field values that the extractor should find.

4. **Generate 20 triage records** with submission context data and labeled
   risk scores (Green/Amber/Red) plus routing decisions.

### 8.2 Script: `scripts/generate_ground_truth.py`

This script creates the JSON dataset files and uploads them to MinIO.
It uses Python string templates with randomized but realistic insurance data
(company names, FEINs, revenue figures, etc.).

The text content does NOT need to be a real PDF rendering. The existing pipeline
already processes `document_text` as a string input. The ground truth dataset
format matches this exactly.

**Template example for ACORD 855**:
```python
ACORD_855_TEMPLATE = """
ACORD 855 - DIRECTORS AND OFFICERS LIABILITY APPLICATION
APPLICANT INFORMATION
Named Insured: {named_insured}
FEIN: {fein}
State of Incorporation: {state}
Entity Type: {entity_type}
Date of Incorporation: {incorporation_date}

FINANCIAL INFORMATION
Annual Revenue: ${annual_revenue:,.0f}
Total Assets: ${total_assets:,.0f}
Number of Employees: {employee_count}

BOARD OF DIRECTORS
Total Board Members: {board_size}
Independent Directors: {independent_directors}

REQUESTED COVERAGE
Effective Date: {effective_date}
Expiration Date: {expiration_date}
Limits Requested: ${limits:,.0f}
Retention: ${retention:,.0f}

PRIOR INSURANCE
Prior Carrier: {prior_carrier}
Prior Premium: ${prior_premium:,.0f}
...
"""
```

The script generates N instances with randomized values drawn from realistic
distributions, creates the JSON dataset, uploads to MinIO at the path referenced
in the existing `ground_truth_dataset` records.

### 8.3 MinIO Configuration

The existing docker-compose.yml already configures MinIO. The buckets referenced
in the seeded data are `ground-truth-datasets`. The script needs to:
1. Create the bucket if it does not exist
2. Upload `document_classifier/v1/dataset.json`
3. Upload `triage_agent/v1/dataset.json`
4. Upload `field_extractor/v1/dataset.json` (new dataset to register)

---

## 9. PHASE BREAKDOWN

### PHASE 1: Minimum Viable Demo (5 days)
**Goal**: Demonstrate end-to-end: compose version -> run tests -> see results -> promote

| Day | Deliverable |
|-----|------------|
| 1 | `metrics.py` (classification + extraction metrics, tested standalone) |
| 1 | `test_runner.py` (run suite, run case, using MockContext + metrics) |
| 2 | SQL queries: `list_all_test_suites`, `get_test_case_by_id`, version flag updates |
| 2 | Add `run_test_suite()` and `run_single_case()` to `client.py` |
| 2 | `test_suites.html` + `test_run_detail.html` + `_test_progress.html` partial |
| 3 | `routes_testing.py` (all test suite + test run routes) |
| 3 | Replace `test-results` placeholder route with real implementation |
| 3 | `lifecycle.html` + `lifecycle_version.html` + `_gate_status.html` + `_promote_form.html` |
| 4 | `routes_lifecycle.py` (lifecycle overview, version detail, promote POST) |
| 4 | Replace `lifecycle` placeholder route with real implementation |
| 4 | SQL queries for lifecycle overview + gate status |
| 5 | `generate_ground_truth.py` script (generate + upload to MinIO) |
| 5 | Wire up: run tests -> update flag -> show in lifecycle -> promote |
| 5 | End-to-end manual testing and CSS polish |

**Phase 1 Demo Flow**:
1. Navigate to `/admin/lifecycle` -- see all entities with lifecycle states
2. Click a `candidate` version -- see gate requirements (staging_tests_passed: no)
3. Navigate to `/admin/test-results` -- see test suites for this entity
4. Click "Run Suite" -- see tests execute with progress, results appear
5. Return to lifecycle -- staging_tests_passed now shows checkmark
6. Click "Promote" -- fill in approver info, check evidence boxes, promote to staging
7. Version moves to `staging` state, approval record visible

### PHASE 2: Ground Truth & Validation (3 days)
**Goal**: Upload ground truth, run validation, see metrics, compare thresholds

| Day | Deliverable |
|-----|------------|
| 6 | `documents.py` (MinIO operations), `validation_runner.py` |
| 6 | `ground_truth.html` (list + detail + upload) |
| 7 | `routes_testing.py` additions (ground truth routes, validation trigger) |
| 7 | `validation_run.html` (run validation + results display) |
| 7 | Confusion matrix rendering (HTML table with color coding) |
| 8 | Wire up validation -> ground_truth_passed flag -> lifecycle gate check |
| 8 | `compose_prompt.html` + `routes_composition.py` (prompt creation) |

**Phase 2 Demo Flow**:
1. Navigate to `/admin/ground-truth` -- see existing datasets
2. Upload a new ground truth JSON file
3. Click "Run Validation" on a dataset, select entity version
4. See validation progress, then results: F1=0.95, confusion matrix, field accuracy
5. Thresholds checked automatically (F1 >= 0.92: PASS)
6. Ground truth flag updated on version
7. Create a new prompt version via compose page

### PHASE 3: Full Composition + Shadow/Challenger (4 days)
**Goal**: Compose new assets bottom-up, shadow/challenger evaluation stubs

| Day | Deliverable |
|-----|------------|
| 9 | `compose_task.html`, `compose_agent.html` -- full composition forms |
| 10 | `compose_pipeline.html` -- pipeline step builder |
| 10 | `routes_composition.py` additions for task/agent/pipeline composition |
| 11 | Shadow/challenger stubs: mark shadow_period_complete, challenger_period_complete |
| 11 | Evaluation run display (seeded data, not real computation) |
| 12 | Integration testing, CSS refinement, documentation |

---

## 10. CRITICAL DEPENDENCIES AND RISKS

### Dependencies
1. **MinIO must be running** for ground truth upload/download. The existing
   docker-compose.yml starts MinIO. Ensure the `ground-truth-datasets` bucket exists.

2. **psycopg v3 async** is already installed and working. No new DB dependencies.

3. **No external ML libraries needed**. Metrics are implemented from scratch.
   This avoids sklearn/numpy as dependencies and keeps the package lightweight.

4. **Anthropic API key** is needed only for `mock_llm=False` mode (live LLM testing).
   Phase 1 works entirely with `mock_llm=True`.

### Risks
1. **HTMX form handling**: POST routes need careful parameter parsing since we are
   not using Pydantic request models for form data. Use `request.form()` in FastAPI.

2. **File upload for ground truth**: FastAPI file upload with `UploadFile` needs
   `python-multipart` dependency (likely already installed via FastAPI).

3. **Test execution timing**: Running 200 ground truth records with mock LLM is fast
   (~seconds). Running with live LLM would take 15-30 minutes. The UI needs to handle
   async execution for live mode (Phase 3 consideration).

---

## 11. ARCHITECTURAL DECISIONS

### Decision 1: Separate route modules vs single routes.py
**Choice**: Create separate `routes_lifecycle.py`, `routes_testing.py`,
`routes_composition.py` files and mount them via `app.py`.
**Rationale**: The existing `routes.py` is already 560 lines. Adding ~400 more lines
for lifecycle + testing + composition would make it unwieldy. Separate files follow
the existing pattern of modular code.
**Alternative considered**: Adding to existing `routes.py`. Rejected for maintainability.

### Decision 2: Metrics from scratch vs sklearn
**Choice**: Implement F1, precision, recall, kappa, field_accuracy from scratch.
**Rationale**: The user explicitly wants simple, heavily-commented code. The metrics
are straightforward (confusion matrix + arithmetic). No need for a 50MB ML library
dependency. Full auditability of the metric computation (important for insurance governance).

### Decision 3: Ground truth as JSON in MinIO vs DB rows
**Choice**: JSON files in MinIO, with metadata in `ground_truth_dataset` table.
**Rationale**: Matches the existing schema design (minio_bucket, minio_key columns
already exist). Ground truth datasets can be large (200+ records with full document
text). JSON files are easily versioned and shareable.

### Decision 4: Test runner uses MockContext vs direct function calls
**Choice**: Test runner creates MockContext and calls the full execution engine.
**Rationale**: This tests the actual execution path (gateway -> LLM/mock -> tools/mock
-> decision logging -> output). A test that bypasses the execution engine would not
catch integration issues. The MockContext pattern is already designed for exactly this.

### Decision 5: HTMX partials vs full page reloads
**Choice**: Use HTMX partials for actions (run test, promote, filter) but full page
loads for navigation between pages.
**Rationale**: HTMX partials provide responsive UX for actions without any JavaScript.
Full page loads for navigation are simpler and work with the existing template
inheritance pattern. This matches the existing codebase approach.

---

## 12. ROUTE MODULE STRUCTURE

### `routes_lifecycle.py` Routes:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/lifecycle` | Lifecycle overview (all entity versions) |
| GET | `/admin/lifecycle/{entity_type}/{version_id}` | Version detail + gate status |
| GET | `/admin/lifecycle/gate-fields` | HTMX partial: gate evidence fields for target state |
| POST | `/admin/lifecycle/promote` | Execute promotion |
| GET | `/admin/lifecycle/approvals/{version_id}` | List approvals for version |

### `routes_testing.py` Routes:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/test-results` | All test suites overview |
| GET | `/admin/test-results/{suite_id}` | Suite detail with cases |
| POST | `/admin/test-results/run-suite` | Run a full test suite |
| POST | `/admin/test-results/run-case` | Run a single test case |
| GET | `/admin/test-results/run/{execution_id}` | View run results |
| GET | `/admin/ground-truth` | Ground truth datasets list |
| GET | `/admin/ground-truth/{dataset_id}` | Dataset detail |
| POST | `/admin/ground-truth/upload` | Upload new dataset |
| POST | `/admin/ground-truth/validate` | Run validation against dataset |
| GET | `/admin/ground-truth/validation/{run_id}` | View validation results |

### `routes_composition.py` Routes:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/prompts/new` | New prompt form |
| POST | `/admin/prompts/new` | Create prompt + version |
| GET | `/admin/prompts/{name}/new-version` | New version of existing prompt |
| POST | `/admin/prompts/{name}/new-version` | Create new prompt version |
| GET | `/admin/agents/{name}/compose` | Compose agent version form |
| POST | `/admin/agents/{name}/compose` | Create agent version |
| GET | `/admin/tasks/{name}/compose` | Compose task version form |
| POST | `/admin/tasks/{name}/compose` | Create task version |
| GET | `/admin/pipelines/{name}/compose` | Compose pipeline version form |
| POST | `/admin/pipelines/{name}/compose` | Create pipeline version |

---

## 13. CSS ADDITIONS

Add to `verity.css`:

```css
/* Lifecycle state progression bar */
.verity-lifecycle-bar { display: flex; align-items: center; gap: 0; margin: 20px 0; }
.verity-lifecycle-step { flex: 1; text-align: center; padding: 8px 4px; font-size: 0.75rem;
    border-bottom: 3px solid var(--verity-gray-light); color: var(--verity-text-light); }
.verity-lifecycle-step.completed { border-bottom-color: var(--verity-green);
    color: var(--verity-green); font-weight: 600; }
.verity-lifecycle-step.current { border-bottom-color: var(--verity-blue);
    color: var(--verity-blue-deep); font-weight: 700; background: var(--verity-blue-pale); }

/* Gate checklist */
.verity-gate-list { list-style: none; padding: 0; }
.verity-gate-item { display: flex; align-items: center; gap: 8px; padding: 6px 0;
    border-bottom: 1px solid var(--verity-border-light); }
.verity-gate-icon-pass { color: var(--verity-green); font-size: 1.1rem; }
.verity-gate-icon-fail { color: var(--verity-red); font-size: 1.1rem; }
.verity-gate-icon-na { color: var(--verity-gray-light); font-size: 1.1rem; }

/* Confusion matrix table */
.verity-confusion-matrix { border-collapse: collapse; font-size: 0.8rem; }
.verity-confusion-matrix th, .verity-confusion-matrix td { padding: 6px 10px;
    border: 1px solid var(--verity-border); text-align: center; }
.verity-confusion-matrix .diagonal { background: var(--verity-green-light);
    font-weight: 600; }
.verity-confusion-matrix .off-diagonal { background: var(--verity-red-light); }

/* Metric cards */
.verity-metric-card { display: inline-block; padding: 12px 20px; margin: 4px;
    border: 1px solid var(--verity-border); border-radius: 8px; text-align: center; }
.verity-metric-value { font-size: 1.8rem; font-weight: 700; color: var(--verity-blue-deep); }
.verity-metric-label { font-size: 0.75rem; color: var(--verity-text-light); margin-top: 2px; }
.verity-metric-card.pass { border-color: var(--verity-green); }
.verity-metric-card.fail { border-color: var(--verity-red); }

/* Progress bar for test execution */
.verity-progress { width: 100%; height: 6px; background: var(--verity-gray-pale);
    border-radius: 3px; overflow: hidden; }
.verity-progress-bar { height: 100%; background: var(--verity-blue);
    transition: width 0.3s ease; }

/* Form styles for composition pages */
.verity-form-group { margin-bottom: 16px; }
.verity-form-label { display: block; font-size: 0.85rem; font-weight: 600;
    margin-bottom: 4px; color: var(--verity-text); }
.verity-form-input { width: 100%; padding: 8px 12px; border: 1px solid var(--verity-border);
    border-radius: 6px; font-size: 0.9rem; font-family: var(--verity-font); }
.verity-form-textarea { width: 100%; min-height: 120px; padding: 8px 12px;
    border: 1px solid var(--verity-border); border-radius: 6px; font-size: 0.85rem;
    font-family: 'Courier New', monospace; }
.verity-form-select { padding: 8px 12px; border: 1px solid var(--verity-border);
    border-radius: 6px; font-size: 0.9rem; }
.verity-btn { display: inline-block; padding: 8px 20px; border: none; border-radius: 6px;
    font-size: 0.9rem; font-weight: 600; cursor: pointer; }
.verity-btn-primary { background: var(--verity-blue-deep); color: white; }
.verity-btn-primary:hover { background: var(--verity-blue-dark); }
.verity-btn-secondary { background: var(--verity-gray-pale); color: var(--verity-text); }
```

---

## 14. COMPLETE FILE MANIFEST

### New Files (20)
1. `verity/src/verity/core/metrics.py`
2. `verity/src/verity/core/test_runner.py`
3. `verity/src/verity/core/validation_runner.py`
4. `verity/src/verity/core/documents.py`
5. `verity/src/verity/models/composition.py`
6. `verity/src/verity/db/queries/composition.sql`
7. `verity/src/verity/web/routes_lifecycle.py`
8. `verity/src/verity/web/routes_testing.py`
9. `verity/src/verity/web/routes_composition.py`
10. `verity/src/verity/web/templates/lifecycle.html`
11. `verity/src/verity/web/templates/lifecycle_version.html`
12. `verity/src/verity/web/templates/test_suites.html`
13. `verity/src/verity/web/templates/test_run_detail.html`
14. `verity/src/verity/web/templates/ground_truth_upload.html`
15. `verity/src/verity/web/templates/validation_run.html`
16. `verity/src/verity/web/templates/compose_prompt.html`
17. `verity/src/verity/web/templates/compose_task.html`
18. `verity/src/verity/web/templates/compose_agent.html`
19. `verity/src/verity/web/templates/compose_pipeline.html`
20. `scripts/generate_ground_truth.py`

### New HTMX Partials (4)
21. `verity/src/verity/web/templates/partials/_test_progress.html`
22. `verity/src/verity/web/templates/partials/_gate_status.html`
23. `verity/src/verity/web/templates/partials/_promote_form.html`
24. `verity/src/verity/web/templates/partials/_metric_card.html`

### Modified Files (10)
25. `verity/src/verity/core/client.py` — add facade methods
26. `verity/src/verity/core/testing.py` — add flag update + threshold methods
27. `verity/src/verity/core/lifecycle.py` — add get_gate_status()
28. `verity/src/verity/core/registry.py` — add ground truth listing
29. `verity/src/verity/web/app.py` — mount new route modules
30. `verity/src/verity/web/routes.py` — replace 3 placeholder routes
31. `verity/src/verity/db/queries/testing.sql` — add 8+ queries
32. `verity/src/verity/db/queries/lifecycle.sql` — add 4+ queries
33. `verity/src/verity/models/testing.py` — add new models
34. `verity/src/verity/web/static/verity.css` — add lifecycle, metric, form styles
PLANEOF
echo "Plan written successfully"