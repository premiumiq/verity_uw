# Governance UI Enhancement — Design

## Overview

The Verity admin has three governance pages (Lifecycle, Test Status, Ground Truth) that currently show list views with no drill-down. This enhancement adds detail pages, navigation linking, page descriptions, and restructures the navigation.

---

## Navigation Changes

### Current sidebar (Governance section):
```
Governance
  Inventory
  Lifecycle
  Ground Truth
  Test Status
  Incidents (soon)
```

### New sidebar:
```
Governance
  Inventory
  Lifecycle
  Testing              ← renamed from "Test Status"
  Ground Truth
  Validation Runs      ← new, separated from Ground Truth
  Incidents (soon)
```

---

## Page Descriptions

Every governance page gets a brief explanation block at the top (inside a `verity-card`) explaining what the concept is and what the page contains. This helps CIO/CTO audiences who may not understand the terminology.

---

## 1. Lifecycle Management

### List page (`/admin/lifecycle`)

**Page description:**
> Lifecycle Management tracks every version of every agent and task through Verity's 7-state promotion sequence: draft → candidate → staging → shadow → challenger → champion → deprecated. Each transition requires evidence (tests passed, validation passed, model card reviewed) and an approver. This page shows all versions across all entities.

**Changes:**
- Group rows by entity (entity name as a row header spanning all columns, versions indented below)
- Version rows link to `/admin/agents/{name}` or `/admin/tasks/{name}` (existing detail pages)
- Valid To: show full timestamp (`YYYY-MM-DD HH:MM`), not truncated to date
- Add a "Pre-champion" filter tab (show only draft/candidate/staging versions)

### Asset detail pages (`/admin/agents/{name}`, `/admin/tasks/{name}`)

**Changes:**
- Version history: "Champion" text in the champion column → show actual version number (e.g., `v1.0.0`)
- Version history: valid_to shows full `YYYY-MM-DD HH:MM` (not truncated)
- Version history: each row links to a version-specific view
- Version-specific view: shows prompts, tools, config for THAT version (not just champion)

### Version detail page (`/admin/agents/{name}/versions/{version_id}`) — NEW

Shows details for a specific version (not necessarily champion):
- Version metadata (state, channel, log level, valid dates, developer, change summary)
- Prompts assigned to THIS version
- Tools authorized for THIS version
- Test results for THIS version
- Validation results for THIS version

**Route:** `GET /admin/agents/{agent_name}/versions/{version_id}`
**Data:** `get_agent_version_by_id`, `get_entity_prompts`, `get_entity_tools`, `list_test_results_for_entity`

### Pre-champion versions for testing

Seed data change: register a v2.0.0 for triage_agent in `draft` state (not promoted). This gives a version in the lifecycle pipeline that hasn't been promoted yet, demonstrating the governance gate.

---

## 2. Testing (renamed from "Test Status")

### Sidebar: rename "Test Status" → "Testing"

### Test suites list page (`/admin/testing`)

**Page description:**
> Testing validates that AI entities meet accuracy requirements before promotion. Test suites contain test cases — small, focused inputs with expected outputs. Running a suite executes each case against an entity version and compares outputs. Tests are fast, cheap, and run frequently — they gate candidate → staging promotion.

**Changes:**
- Rename route from `/admin/test-results` to `/admin/testing`
- Each suite row links to suite detail page
- Add "Entity Type" filter tabs (All | Agents | Tasks)

### Test suite detail page (`/admin/testing/{suite_id}`) — NEW

**Page description:**
> This test suite contains {N} test cases for {entity_name}. Each case defines an input and expected output. When the suite runs, each case is executed against an entity version and the output is compared using the specified metric (classification F1, field accuracy, exact match, or schema validation).

Shows:
- Suite metadata (name, description, entity, type, created by)
- Test cases table: name, description, metric type, expected output (truncated), last result (pass/fail)
- Test run history: run timestamp, version tested, pass rate, duration
- "Run Suite" button (future — triggers test_runner via POST)

**Route:** `GET /admin/testing/{suite_id}`
**Data:** `get_test_suite`, `list_test_cases_for_suite`, `list_test_results_for_suite`

### Relationship to ground truth

Test suites and ground truth are different:

| | Test Suites | Ground Truth |
|---|---|---|
| **Purpose** | Unit tests — specific behaviors | Validation — production-representative accuracy |
| **Data** | Hand-written cases (3-10 per suite) | SME-labeled records (50-200 per dataset) |
| **Runner** | Test Runner | Validation Runner |
| **Metrics** | Per-case pass/fail | Aggregate F1, precision, recall, kappa |
| **Gates** | candidate → staging | staging → champion |
| **Cost** | Free (mock LLM) | Expensive (can use real LLM) |

---

## 3. Ground Truth

### Ground truth datasets page (`/admin/ground-truth`)

**Page description:**
> Ground truth datasets contain production-representative data labeled by subject matter experts (SMEs). Each record has an input (a document, a submission) and an authoritative annotation (the correct answer). Validation runs execute an entity version against every record and compare outputs to annotations. Ground truth validation gates staging → champion promotion.

**Changes:**
- Remove validation runs from this page (moved to separate Validation Runs page)
- Add link to dataset detail page
- Show display name (not just name)
- Add "# Validation Runs" column with count
- Add "Latest Run" column linking to the most recent validation run detail
- Add quality tier explanation in page description

### Quality tiers explained (in page description):

| Tier | What it means |
|---|---|
| **Silver** | Single annotator. One SME labels each record. No independent review. Suitable for medium-materiality tasks. |
| **Gold** | Multi-annotator with inter-annotator agreement (IAA) check. Disagreements adjudicated by senior SME. Required for high-materiality agents. |

### Ground truth dataset detail page (`/admin/ground-truth/{dataset_id}`) — NEW

**Page description:**
> This dataset contains {N} records for validating {entity_name}. Each record has an input and one or more annotations. The authoritative annotation (marked with a checkmark) is what the validation runner compares against. Quality tier: {silver|gold}.

Shows:
- Dataset metadata (name, version, entity, quality tier, status, owner, coverage notes)
- Annotation summary: {annotated}/{total} records, annotator names, IAA score (if gold)
- Records table: index, source description, tags, difficulty, authoritative annotation (truncated expected output)
- Each record row: if source_provider is "local" or storage-based, show link to EDMS document
- Validation runs for THIS dataset (count + link to latest)

**Route:** `GET /admin/ground-truth/{dataset_id}`
**Data:** `get_ground_truth_dataset`, `list_ground_truth_records`, `list_authoritative_annotations`

### EDMS navigation from records

For records where `source_provider` is set and `source_key` contains a path, show an "Open in EDMS" link:
- URL: `http://localhost:8002/ui/documents/{document_id}` (if we have the EDMS document ID)
- Or: `http://localhost:8002/ui/` with a search parameter (if we only have the filename)

Since ground truth records reference seed docs by `source_key` (e.g., `filled/do_app_acme_dynamics.pdf`) but don't store EDMS document IDs, the link would go to the EDMS document browser filtered by filename. This is a best-effort navigation — not a guaranteed deep link.

---

## 4. Validation Runs — NEW navigation item

### Validation runs list page (`/admin/validation-runs`)

**Page description:**
> Validation runs test an entity version against a ground truth dataset. The runner executes the entity for every record, compares outputs to authoritative annotations, and computes aggregate metrics (precision, recall, F1, Cohen's kappa for classification; per-field accuracy for extraction). Results are checked against metric thresholds — all thresholds must be met for the version to pass validation.

Shows:
- All validation runs across all entities
- Columns: entity, dataset, F1, precision, recall, kappa, thresholds met, result (passed/failed), run by, when
- Each row links to validation run detail

**Route:** `GET /admin/validation-runs`
**Data:** `list_validation_runs`

### Validation run detail page (`/admin/validation-runs/{run_id}`) — NEW

**Page description:**
> This validation run tested {entity_name} v{version} against {dataset_name} ({record_count} records) on {date}. Below are the aggregate metrics, threshold check results, and per-record outcomes.

Shows:

**Metrics summary cards** (same pattern as dashboard):
- Precision, Recall, F1, Cohen's Kappa (classification)
- Overall Accuracy, Fields Evaluated (extraction)
- Total Records, Correct, Incorrect

**Metric definitions** (reference table in a collapsible section):

| Metric | What it measures |
|---|---|
| Precision | Of all items the model labeled as class X, what fraction actually were class X? High precision = few false positives. |
| Recall | Of all items that actually were class X, what fraction did the model correctly identify? High recall = few false negatives. |
| F1 Score | Harmonic mean of precision and recall. Balances both. Range 0-1, higher is better. |
| Cohen's Kappa | Agreement between model and SME, adjusted for chance. 0 = random agreement, 1 = perfect agreement. >0.8 is strong. |
| Field Accuracy | For extraction: fraction of fields where the extracted value matches the expected value (within tolerance). |

**Threshold check table:**
- Metric name, field (if per-field), required minimum, target, achieved, pass/fail badge

**Confusion matrix** (for classification — HTML table with color-coded cells)

**Per-record results table:**
- Record index, expected output (truncated), actual output (truncated), correct (pass/fail badge), confidence, match score
- Filter: All | Correct | Incorrect
- Failed records highlighted

**Route:** `GET /admin/validation-runs/{run_id}`
**Data:** `get_validation_run_by_id` (new query), `list_validation_record_results`, `list_validation_record_failures`

**New SQL query needed:**
```sql
-- name: get_validation_run_by_id
SELECT
    vr.*,
    gtd.name AS dataset_name, gtd.record_count AS dataset_record_count,
    COALESCE(a.display_name, t.display_name) AS entity_display_name,
    COALESCE(av.version_label, tv.version_label) AS version_label
FROM validation_run vr
JOIN ground_truth_dataset gtd ON gtd.id = vr.dataset_id
LEFT JOIN agent_version av ON av.id = vr.entity_version_id AND vr.entity_type = 'agent'
LEFT JOIN agent a ON a.id = av.agent_id
LEFT JOIN task_version tv ON tv.id = vr.entity_version_id AND vr.entity_type = 'task'
LEFT JOIN task t ON t.id = tv.task_id
WHERE vr.id = %(run_id)s;
```

---

## 5. Seed Data Changes

### Pre-champion version for testing

Add to `register_all.py` in `seed_agent_versions()`:

```python
# Triage agent v2.0.0 — draft, not promoted (demonstrates lifecycle pipeline)
r = await verity.registry.register_agent_version(
    agent_id=agents["triage_agent"]["id"],
    major_version=2, minor_version=0, patch_version=0,
    lifecycle_state="draft", channel="development",
    inference_config_id=configs["triage_balanced"],
    decision_log_detail="full",
    developer_name="Dev Team",
    change_summary="Experimental: enhanced risk factor weighting with industry-specific adjustments",
    change_type="new_capability",
)
versions[("triage_agent", "2.0.0")] = r["id"]
```

This gives the lifecycle page a version that hasn't been promoted — showing the governance gate in action.

---

## Files to Change

### New templates (5)
| Template | Route | Purpose |
|---|---|---|
| `testing.html` | `/admin/testing` | Replaces `test_results.html` (renamed) |
| `test_suite_detail.html` | `/admin/testing/{suite_id}` | Suite cases + results |
| `ground_truth_detail.html` | `/admin/ground-truth/{dataset_id}` | Dataset records + annotations |
| `validation_runs.html` | `/admin/validation-runs` | All validation runs |
| `validation_run_detail.html` | `/admin/validation-runs/{run_id}` | Run metrics + per-record results |

### Modified templates (3)
| Template | Change |
|---|---|
| `base.html` | Sidebar: rename Test Status → Testing, add Validation Runs link |
| `lifecycle.html` | Group by entity, link rows to detail, fix valid_to format |
| `agent_detail.html` / implicit | Version rows link to version detail, champion shows version number |

### New/modified routes (5 new, 3 modified)
| Route | Method | Purpose |
|---|---|---|
| `GET /admin/testing` | Modified | Renamed from `/admin/test-results` |
| `GET /admin/testing/{suite_id}` | New | Suite detail |
| `GET /admin/ground-truth/{dataset_id}` | New | Dataset detail |
| `GET /admin/validation-runs` | New | Validation runs list |
| `GET /admin/validation-runs/{run_id}` | New | Validation run detail |

### New SQL queries (2)
| Query | File | Purpose |
|---|---|---|
| `get_validation_run_by_id` | testing.sql | Validation run with entity/dataset names |
| `get_test_suite` | testing.sql | Already exists |

### Seed data (1 change)
| Change | File |
|---|---|
| Add triage_agent v2.0.0 (draft) | register_all.py |

---

## Implementation Order

1. Navigation: update sidebar + rename routes
2. Page descriptions: add to all 5 governance pages
3. Lifecycle: group by entity, fix formatting, link rows
4. Testing: rename, add suite detail page
5. Ground Truth: add dataset detail page, remove validation runs
6. Validation Runs: new list page + detail page with metrics/records
7. Seed data: add pre-champion version
8. Agent/task detail: version links, champion version number fix
