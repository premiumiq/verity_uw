# Phase 4: Seed Data Inventory & Loading Strategy

## Overview

This document lists every record that must be loaded into `verity_db` to populate the Verity admin UI with demo-ready content. Loading follows foreign key dependency order — parent records before children.

---

## Loading Order (FK Dependencies)

```
Step 1: inference_config         (no dependencies)
Step 2: tool                     (no dependencies)
Step 3: agent + task + prompt    (no dependencies between them)
Step 4: agent_version + task_version  (depends on: agent/task + inference_config)
Step 5: prompt_version           (depends on: prompt)
Step 6: entity_prompt_assignment (depends on: agent_version/task_version + prompt_version)
Step 7: agent_version_tool + task_version_tool  (depends on: agent_version/task_version + tool)
Step 8: pipeline + pipeline_version  (no FK to agent/task, but references them by name in JSON)
Step 9: test_suite               (depends on: agent/task by entity_id)
Step 10: test_case               (depends on: test_suite)
Step 11: approval_record         (depends on: agent_version/task_version)
Step 12: Set champion pointers   (UPDATE agent.current_champion_version_id, task.current_champion_version_id)
Step 13: ground_truth_dataset    (depends on: agent/task)
Step 14: validation_run          (depends on: ground_truth_dataset + agent_version/task_version)
Step 15: model_card              (depends on: agent_version/task_version + validation_run)
Step 16: metric_threshold        (depends on: agent/task)
Step 17: test_execution_log      (depends on: test_suite + test_case + agent_version/task_version)
Step 18: agent_decision_log      (pre-seeded demo decisions)
Step 19: override_log            (depends on: agent_decision_log)
```

---

## Step 1: Inference Configs (5 records)

Source: PRD Section 15.1. These are exact.

| Name | Model | Temp | Max Tokens | Intended Use |
|---|---|---|---|---|
| `classification_strict` | claude-sonnet-4-20250514 | 0.0 | 512 | Doc classification, appetite, routing |
| `extraction_deterministic` | claude-sonnet-4-20250514 | 0.0 | 2048 | ACORD extraction, loss run parsing |
| `triage_balanced` | claude-sonnet-4-20250514 | 0.2 | 4096 | Triage agent, appetite agent |
| `generation_narrative` | claude-sonnet-4-20250514 | 0.4 | 8192 | Quote letters, referral memos |
| `renewal_analytical` | claude-sonnet-4-20250514 | 0.1 | 4096 | Renewal analysis |

**Strategy:** Hardcoded in seed script. Values from PRD.

---

## Step 2: Tools (8 records)

Tools are Python functions that agents can call. Registered with descriptions, schemas, and implementation paths.

| Name | Display Name | Description | Write Op | Mock |
|---|---|---|---|---|
| `get_submission_context` | Get Submission Context | Retrieves full submission data including account, coverage details, and loss history | No | Yes |
| `get_underwriting_guidelines` | Get UW Guidelines | Retrieves the underwriting guidelines document for a given line of business | No | Yes |
| `get_documents_for_submission` | Get Documents | Lists all documents uploaded for a submission from MinIO | No | Yes |
| `update_submission_event` | Update Event Log | Logs a workflow event for a submission | Yes | Yes |
| `store_triage_result` | Store Triage Result | Stores the triage agent's risk assessment output | Yes | Yes |
| `update_appetite_status` | Update Appetite | Stores appetite determination result | Yes | Yes |
| `get_loss_history` | Get Loss History | Retrieves loss history records for the submission's account | No | Yes |
| `get_enrichment_data` | Get Enrichment | Retrieves mock enrichment data (LexisNexis, D&B, Pitchbook simulation) | No | Yes |

**Strategy:** Hardcoded in seed script. Input/output schemas defined as JSON objects. Implementation paths point to `uw_demo.app.tools.*` (to be implemented in Phase 5). All start with `mock_mode_enabled=True`.

---

## Step 3: Agents (2 records) + Tasks (2 records) + Prompts (8 records)

### Agents

| Name | Display Name | Materiality | Domain | Description (from PRD) |
|---|---|---|---|---|
| `triage_agent` | Submission Risk Triage Agent | high | underwriting | Synthesises submission data, enrichment, and loss history into risk assessment. Produces risk score (Green/Amber/Red), routing recommendation, and narrative. |
| `appetite_agent` | Underwriting Appetite Assessment Agent | high | underwriting | Assesses whether a submission is within underwriting appetite by reasoning across submission characteristics and guidelines document. Cites specific guideline sections. |

### Tasks

| Name | Display Name | Capability | Materiality | Description (from PRD) |
|---|---|---|---|---|
| `document_classifier` | Insurance Document Classification Task | classification | medium | Classifies a single insurance document into one of the defined document types. Returns type + confidence. |
| `field_extractor` | D&O ACORD 855 Field Extraction Task | extraction | medium | Extracts structured data fields from a D&O ACORD 855 application form. Returns fields with per-field confidence. |

### Prompts (8 prompt entities — versions are separate records)

Prompts are named WITHOUT version numbers. Versioning is handled by `prompt_version` records under each prompt. This is Verity's core design: the prompt entity is the container, versions are the content.

| Prompt Name | For Entity | API Role | Governance Tier |
|---|---|---|---|
| `triage_agent_system` | triage_agent | system | behavioural |
| `triage_agent_context` | triage_agent | user | contextual |
| `appetite_agent_system` | appetite_agent | system | behavioural |
| `appetite_agent_context` | appetite_agent | user | contextual |
| `doc_classifier_instruction` | document_classifier | system | behavioural |
| `doc_classifier_input` | document_classifier | user | formatting |
| `field_extractor_instruction` | field_extractor | system | behavioural |
| `field_extractor_input` | field_extractor | user | formatting |

**Strategy:** Prompt content from PRD Section 15.2 and 15.3 — the exact system prompt text is specified there. User templates are short format strings.

---

## Step 4: Agent Versions + Task Versions

Each entity gets 2 versions to demonstrate version history in the UI.

| Entity | Version | State | Config | Change Summary |
|---|---|---|---|---|
| triage_agent | 0.9.0 | deprecated | triage_balanced | Initial prototype with basic risk scoring |
| triage_agent | 1.0.0 | champion | triage_balanced | Added multi-factor risk assessment and guideline citations |
| appetite_agent | 1.0.0 | champion | triage_balanced | Initial release with guidelines-based assessment |
| document_classifier | 0.9.0 | deprecated | classification_strict | Initial classifier with 6 document types |
| document_classifier | 1.0.0 | champion | classification_strict | Added board_resolution and other types, improved accuracy |
| field_extractor | 1.0.0 | champion | extraction_deterministic | Initial release with 20-field extraction |

**Strategy:** Create deprecated versions first (v0.9.0), then champion versions (v1.0.0). This gives the version history page content.

---

## Steps 5-7: Prompt Versions → Assignments → Tool Authorizations

### Prompt Versions (10 records)

Version numbers are integers on the `prompt_version` table. Each prompt gets at least 1 version; triage and classifier get 2 versions (older deprecated + current champion) to show version history/diff in the UI.

| Prompt Entity | Version # | State | Content |
|---|---|---|---|
| `triage_agent_system` | 1 | deprecated | Shorter initial system prompt |
| `triage_agent_system` | 2 | champion | Full system prompt from PRD |
| `triage_agent_context` | 1 | champion | Context template with {{variables}} |
| `appetite_agent_system` | 1 | champion | Full system prompt |
| `appetite_agent_context` | 1 | champion | Submission + guidelines template |
| `doc_classifier_instruction` | 1 | deprecated | Simpler classification instruction |
| `doc_classifier_instruction` | 2 | champion | Full instruction from PRD |
| `doc_classifier_input` | 1 | champion | "Document text:\n{{document_text}}" |
| `field_extractor_instruction` | 1 | champion | Full extraction instruction from PRD |
| `field_extractor_input` | 1 | champion | "ACORD 855 document text:\n{{document_text}}" |

### Entity-Prompt Assignments (8 records)

Link current prompt versions to champion entity versions. Each entity gets exactly 2 assignments: system prompt + user template.

### Tool Authorizations

| Agent/Task Version | Authorized Tools |
|---|---|
| triage_agent v1.0.0 | get_submission_context, get_underwriting_guidelines, get_loss_history, get_enrichment_data, store_triage_result |
| appetite_agent v1.0.0 | get_submission_context, get_underwriting_guidelines, update_appetite_status |
| document_classifier v1.0.0 | (none — task, no tools) |
| field_extractor v1.0.0 | (none — task, no tools) |

---

## Step 8: Pipeline (1 pipeline, 1 version)

| Pipeline | Steps |
|---|---|
| `uw_submission_pipeline` | 4 steps in dependency order |

Pipeline steps:
```
Step 1: classify_documents   → task: document_classifier   (order 1)
Step 2: extract_fields       → task: field_extractor        (order 2, depends on classify)
Step 3: triage_submission    → agent: triage_agent          (order 3, depends on extract)
Step 4: assess_appetite      → agent: appetite_agent        (order 4, depends on triage)
```

---

## Steps 9-10: Test Suites + Cases (4 suites, ~12 cases)

| Suite | Entity | Suite Type | Cases |
|---|---|---|---|
| document_classifier_unit | document_classifier | unit | 3 cases: ACORD 855, loss run, supplemental |
| field_extractor_unit | field_extractor | unit | 3 cases: complete form, partial form, empty form |
| triage_agent_unit | triage_agent | unit | 3 cases: green risk, amber risk, red risk |
| appetite_agent_unit | appetite_agent | unit | 3 cases: within appetite, borderline, outside appetite |

**Strategy:** Each test case has `input_data` (sample input JSON) and `expected_output` (expected result). Metric types match capability: `classification_f1` for classifier, `field_accuracy` for extractor, `classification_f1` for agents.

---

## Step 11: Approval Records (6+ records)

Simulate the lifecycle promotion history for all champion versions.

| Entity Version | Gate | From → To | Approver |
|---|---|---|---|
| triage_agent v1.0.0 | draft → candidate | draft → candidate | Dev Team |
| triage_agent v1.0.0 | candidate → champion | candidate → champion | Sarah Chen, Chief Actuary |
| appetite_agent v1.0.0 | candidate → champion | candidate → champion | Sarah Chen |
| document_classifier v1.0.0 | candidate → champion | candidate → champion | James Okafor, Model Risk |
| field_extractor v1.0.0 | candidate → champion | candidate → champion | James Okafor |
| uw_submission_pipeline v1 | candidate → champion | candidate → champion | Sarah Chen |

---

## Step 12: Set Champion Pointers

UPDATE statements to set `current_champion_version_id` on each agent, task, and pipeline.

---

## Steps 13-16: Validation, Model Cards, Thresholds

### Ground Truth Datasets (2 records — metadata only)

| Dataset | Entity | Records | Labeled By |
|---|---|---|---|
| classifier_ground_truth_v1 | document_classifier | 200 | Maria Santos, Senior UW |
| triage_ground_truth_v1 | triage_agent | 20 | James Okafor, Model Risk |

### Validation Runs (2 records)

| Entity | Passed | Precision | Recall | F1 | Kappa |
|---|---|---|---|---|---|
| document_classifier v1.0.0 | Yes | 0.9600 | 0.9400 | 0.9500 | — |
| triage_agent v1.0.0 | Yes | 0.8800 | 0.8500 | 0.8600 | 0.7800 |

### Model Cards (2 records — high materiality agents)

| Entity | Purpose | Design Rationale | Known Limitations | Status |
|---|---|---|---|---|
| triage_agent v1.0.0 | First-pass risk assessment | LLM-based multi-factor synthesis | Sensitivity to prompt phrasing, limited to D&O and GL | approved |
| appetite_agent v1.0.0 | Guidelines compliance check | LLM retrieval + reasoning | Dependent on guidelines document completeness | approved |

### Metric Thresholds (4 records)

| Entity | Metric | Min Acceptable | Target |
|---|---|---|---|
| triage_agent | f1_score | 0.8300 | 0.8800 |
| appetite_agent | f1_score | 0.8600 | 0.9000 |
| document_classifier | f1_score | 0.9200 | 0.9600 |
| field_extractor | field_accuracy | 0.9000 | 0.9500 |

---

## Steps 17-19: Pre-Seeded Demo Activity

### Test Execution Logs (~12 records)

Pre-seed passing test results for all test cases against champion versions. This populates the Test Results page.

### Decision Logs (15-20 records)

Pre-seeded decisions simulating past pipeline runs. These give the Decision Log page and Audit Trail content to browse without needing to run live AI.

| Decision | Entity | Submission | Status | Step Name |
|---|---|---|---|---|
| 1-4 | All 4 entities | SUB-001 | complete | classify → extract → triage → appetite |
| 5-8 | All 4 entities | SUB-002 | complete | classify → extract → triage → appetite |
| 9-12 | All 4 entities | SUB-003 | complete | classify → extract → triage → appetite |
| 13-16 | All 4 entities | SUB-004 | complete | classify → extract → triage → appetite |

Each decision includes:
- `pipeline_run_id` (shared per submission — groups the 4 steps)
- `step_name` (classify_documents, extract_fields, triage_submission, assess_appetite)
- `inference_config_snapshot` (actual config used)
- `output_json` (realistic mock output appropriate to the entity)
- `input_tokens` / `output_tokens` / `duration_ms` (realistic values)

**Strategy for mock outputs:** Create realistic JSON outputs for each entity:
- Classifier: `{"document_type": "acord_855", "confidence": 0.97, "classification_notes": "..."}`
- Extractor: `{"fields": {"named_insured": "Acme Dynamics LLC", ...}, "low_confidence_fields": [...], "extraction_complete": true}`
- Triage: `{"risk_score": "Green", "routing": "assign_to_uw", "reasoning": "...", "risk_factors": [...]}`
- Appetite: `{"determination": "within_appetite", "confidence": 0.88, "guideline_citations": [...]}`

### Override Logs (2-3 records)

| Override | Decision | Reason Code | Overrider |
|---|---|---|---|
| 1 | Triage for SUB-002 | risk_assessment_disagree | David Park, Senior UW |
| 2 | Appetite for SUB-003 | client_relationship | Lisa Wong, VP Underwriting |

---

## Loading Strategy

### Single Python Script — Uses Verity SDK Functions

All seed data lives in one script: `uw_demo/app/setup/register_all.py`

This script uses the Verity SDK's own registry and lifecycle functions — NOT raw SQL inserts. This proves the SDK works end-to-end and exercises the exact code path the demo relies on.

```python
# Example of how the seed script works (conceptual):

verity = Verity(database_url=DB_URL)
await verity.connect()

# Step 1: Register inference config using SDK
config_result = await verity.registry.register_inference_config(
    name="classification_strict",
    description="Fully deterministic for classification tasks",
    intended_use="Document classification, appetite classification",
    model_name="claude-sonnet-4-20250514",
    temperature=0.0,
    max_tokens=512,
)
config_id = config_result["id"]  # UUID returned, used in later steps

# Step 3: Register agent using SDK
agent_result = await verity.registry.register_agent(
    name="triage_agent",
    display_name="Submission Risk Triage Agent",
    ...
)
agent_id = agent_result["id"]

# Step 4: Register version using SDK
version_result = await verity.registry.register_agent_version(
    agent_id=agent_id,
    inference_config_id=config_id,
    ...
)
version_id = version_result["id"]

# Step 11: Promote using lifecycle SDK (proves lifecycle works)
await verity.promote(
    entity_type="agent",
    entity_version_id=version_id,
    target_state="candidate",
    approver_name="Dev Team",
    rationale="Development complete",
)
await verity.promote(
    entity_type="agent",
    entity_version_id=version_id,
    target_state="champion",
    approver_name="Sarah Chen, Chief Actuary",
    rationale="Ground truth validation passed, model card approved",
)
```

### Idempotency

The script is **idempotent** — safe to run multiple times. On each run it:
1. Drops all tables and recreates the schema (`verity init --drop-existing`)
2. Seeds all data from scratch

This means `python -m uw_demo.app.setup.register_all` always produces the same clean state regardless of what was in the database before.

### Why One Script (Not Separate Files Per Entity)

- Foreign key dependencies require strict ordering
- UUIDs from earlier inserts are needed for later inserts (e.g., agent_id → agent_version → tool authorization)
- One file = one place to read, one place to debug
- Using SDK functions means the script also serves as integration test

### Running the Seed Script

```bash
cd ~/verity_uw
source .venv/bin/activate
python -m uw_demo.app.setup.register_all
```

This drops, recreates, and seeds — clean state every time.

---

## PDF Documents (Separate Phase)

Synthetic ACORD 855, ACORD 125, and loss run PDFs are NOT created in this seed phase. They are part of Phase 5 (business app) when we build document upload, classification, and extraction workflows. The seed data here creates the governance metadata (agents, tasks, prompts, configs) so the Verity admin UI has content to display.

---

## Total Record Count

| Table | Count | Notes |
|---|---|---|
| inference_config | 5 | |
| tool | 8 | |
| agent | 2 | |
| task | 2 | |
| prompt | 8 | |
| agent_version | 3 | 2 champion + 1 deprecated |
| task_version | 3 | 2 champion + 1 deprecated |
| prompt_version | 10 | 8 current + 2 deprecated |
| entity_prompt_assignment | 8 | 2 per champion entity version |
| agent_version_tool | 8 | Tools for triage + appetite |
| task_version_tool | 0 | Tasks don't use tools in App 1 |
| pipeline | 1 | |
| pipeline_version | 1 | |
| test_suite | 4 | |
| test_case | 12 | 3 per suite |
| approval_record | 6 | |
| ground_truth_dataset | 2 | |
| validation_run | 2 | |
| model_card | 2 | |
| metric_threshold | 4 | |
| test_execution_log | 12 | |
| agent_decision_log | 16 | 4 per submission × 4 submissions |
| override_log | 2 | |
| **Total** | **~109** | |
