# EDMS + Ground Truth Integration — Design

## Problem

Ground truth records currently reference local file paths (`source_key = "filled/do_app_acme_dynamics.pdf"`). They should reference EDMS documents. The EDMS collection/folder structure doesn't support the ground truth workflow. Validation runs and test suites can't be executed from the demo UI.

## EDMS Collection and Folder Structure

### Collection: `underwriting` (new)

For submission documents organized by submission:

```
underwriting/
  submissions/
    00000001-0001-0001-0001-000000000001/    ← Acme D&O
      do_app_acme_dynamics.pdf
      loss_run_acme_dynamics.txt
      board_resolution_acme_dynamics.txt
    00000002-0002-0002-0002-000000000002/    ← TechFlow D&O
      do_app_techflow_industries.pdf
      loss_run_techflow_industries.txt
      financial_stmt_techflow_industries.txt
    ...
```

This replaces the current `general` collection. Documents are organized by submission ID, not dumped flat.

### Collection: `ground_truth` (new)

For ground truth validation assets organized by entity:

```
ground_truth/
  task-document_classifier/
    input/
      classifier_ground_truth_v1/
        do_app_acme_dynamics.pdf          ← copy or reference to underwriting doc
        do_app_techflow_industries.pdf
        gl_app_meridian_holdings.pdf
        loss_run_acme_dynamics.txt
        financial_stmt_techflow_industries.txt
        ...
  task-field_extractor/
    input/
      extractor_ground_truth_v1/
        do_app_acme_dynamics.pdf
        do_app_techflow_industries.pdf
        ...
  agent-triage_agent/
    input/
      triage_ground_truth_v1/
        (no documents — triage uses submission context from tools)
  agent-appetite_agent/
    input/
      appetite_ground_truth_v1/
        (no documents — appetite uses submission context from tools)
```

### Key Decision: Copy vs Reference

For the classifier and extractor ground truth, the input documents are the same PDFs that live in the `underwriting` collection. Two options:

**Option A: Copy documents into ground_truth collection.**
Each ground truth dataset has its own copies. Independent — changing submission docs doesn't affect ground truth. But duplicates storage.

**Option B: Reference documents from underwriting collection.**
Ground truth records point to document IDs in the `underwriting` collection. No duplication. But if someone deletes or modifies a submission document, the ground truth is broken.

**Recommendation: Option B (reference) for the demo.** Ground truth records store EDMS document IDs. The source_provider/container/key fields point to the EDMS document. The ground truth folder structure still exists for organizational purposes (metadata) but the actual documents are referenced, not copied.

## Ground Truth Records — EDMS Document References

### Current (broken)
```python
source_provider="local", source_container="seed_docs", source_key="filled/do_app_acme_dynamics.pdf"
```

### New (EDMS-backed)
```python
source_provider="edms", source_container="underwriting",
source_key=str(edms_document_id),  # UUID of the EDMS document
source_description="do_application: do_app_acme_dynamics.pdf"
```

The `source_key` stores the EDMS document UUID. The ground truth record detail page can then link directly:
```
http://localhost:8002/ui/documents/{source_key}
```

## Seed Order Change

Current order:
1. Register Verity entities (steps 1-19)
2. Seed Verity platform settings (step 20)
3. Seed UW database (step 21)
4. Upload documents to EDMS (step 22)

New order:
1. Register Verity entities (steps 1-12)
2. Seed governance artifacts — datasets only, no records yet (step 13)
3. Upload documents to EDMS (step 14) — returns document ID mapping
4. Populate ground truth records with EDMS document IDs (step 15)
5. Remaining governance (validation runs, model cards, thresholds) (step 16)
6. Test execution logs, decision logs, overrides (steps 17-19)
7. Platform settings, UW database (steps 20-21)

The key change: EDMS upload happens BEFORE ground truth population, so we have the document IDs.

## Document ID Mapping

The `seed_edms.py` script uploads documents and returns metadata including IDs. It needs to return a mapping:

```python
{
    "do_app_acme_dynamics.pdf": "a5a3917a-a44e-41be-9250-efe43b69f845",
    "loss_run_acme_dynamics.txt": "61f1bba5-8a80-41a9-b0fe-627637f0eaaf",
    ...
}
```

This mapping is passed to `seed_ground_truth_records()` which uses it to set `source_key` to the EDMS document UUID.

## EDMS Collection/Folder Setup

The EDMS seed script (`edms/src/edms/seed.py`) currently creates a `general` collection with a `Miscellaneous` folder. It needs to also create:

1. Collection: `underwriting` (storage_container: `submissions`)
   - Folder: `submissions`
     - Sub-folders: one per submission UUID

2. Collection: `ground_truth` (storage_container: `ground-truth-datasets`)
   - Folder: `task-document_classifier`
     - Sub-folder: `input`
       - Sub-folder: `classifier_ground_truth_v1`
   - Folder: `task-field_extractor`
     - Sub-folder: `input`
       - Sub-folder: `extractor_ground_truth_v1`
   - Folder: `agent-triage_agent`
     - Sub-folder: `input`
       - Sub-folder: `triage_ground_truth_v1`
   - Folder: `agent-appetite_agent`
     - Sub-folder: `input`
       - Sub-folder: `appetite_ground_truth_v1`

## Demo Capabilities

### Running Ground Truth Validation
- "Validate" button on ground truth dataset detail page
- POST triggers `validation_runner.run_validation()`
- Validation runner:
  1. Loads records from ground_truth_record table
  2. For classifier: fetches document content from EDMS via `source_key` (document ID)
  3. Runs entity against each record
  4. Compares to authoritative annotation
  5. Computes aggregate metrics
  6. Stores validation_run + per-record results
- Results page shows metrics, confusion matrix, per-record pass/fail

### Running Test Suites
- "Run Suite" button on test suite detail page
- POST triggers `test_runner.run_suite()`
- Test runner:
  1. Loads test cases from test_case table
  2. For each case: builds MockContext with expected output, runs entity
  3. Compares actual to expected using metric_type
  4. Stores results in test_execution_log
- Results show per-case pass/fail

## Files to Change

| File | Change |
|---|---|
| `edms/src/edms/seed.py` | Add `underwriting` and `ground_truth` collections with folder structure |
| `uw_demo/app/setup/seed_edms.py` | Upload docs to `underwriting` collection with submission folders. Return filename→ID mapping |
| `uw_demo/app/setup/register_all.py` | Reorder steps. Pass EDMS doc IDs to GT population. |
| `uw_demo/app/setup/register_all.py` (seed_ground_truth_records) | Use EDMS doc IDs for `source_key`, `source_provider="edms"` |
| `verity/src/verity/web/templates/ground_truth_record.html` | Link to `/ui/documents/{source_key}` when source_provider is "edms" |
| `verity/src/verity/web/templates/ground_truth_detail.html` | Same fix for record list EDMS links |
| `verity/src/verity/web/routes.py` | Add POST routes for running validation and test suites from UI |
| `verity/src/verity/web/templates/test_suite_detail.html` | Add "Run Suite" button |
| `verity/src/verity/web/templates/ground_truth_detail.html` | Add "Run Validation" button |

## Implementation Order

1. Update EDMS seed with new collections/folders
2. Update seed_edms.py to upload to `underwriting` collection with proper folders, return ID mapping
3. Reorder register_all.py steps
4. Update seed_ground_truth_records to use EDMS document IDs
5. Fix templates to link to EDMS document detail pages
6. Add "Run Validation" and "Run Suite" POST routes + buttons
