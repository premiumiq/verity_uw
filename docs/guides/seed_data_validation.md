# Seed Data Validation Guide

After running the seed script, follow this guide to verify all data loaded correctly.

---

## Step 1: Run the Seed Script

```bash
cd ~/verity_uw
source .venv/bin/activate
python -m uw_demo.app.setup.register_all
```

You should see output ending with:
```
✓ Seed complete. All demo data loaded.
  Open http://localhost:8000/verity/admin/ to see the data.
```

If you see errors, the script drops and re-creates the schema each time, so you can just run it again.

---

## Step 2: Verify via Database (Optional)

Check record counts directly in PostgreSQL:

```bash
docker exec verity_postgres psql -U verityuser -d verity_db -c "
  SELECT 'inference_config' AS tbl, COUNT(*) FROM inference_config
  UNION ALL SELECT 'agent', COUNT(*) FROM agent
  UNION ALL SELECT 'task', COUNT(*) FROM task
  UNION ALL SELECT 'agent_version', COUNT(*) FROM agent_version
  UNION ALL SELECT 'task_version', COUNT(*) FROM task_version
  UNION ALL SELECT 'prompt', COUNT(*) FROM prompt
  UNION ALL SELECT 'prompt_version', COUNT(*) FROM prompt_version
  UNION ALL SELECT 'tool', COUNT(*) FROM tool
  UNION ALL SELECT 'pipeline', COUNT(*) FROM pipeline
  UNION ALL SELECT 'test_suite', COUNT(*) FROM test_suite
  UNION ALL SELECT 'test_case', COUNT(*) FROM test_case
  UNION ALL SELECT 'approval_record', COUNT(*) FROM approval_record
  UNION ALL SELECT 'agent_decision_log', COUNT(*) FROM agent_decision_log
  UNION ALL SELECT 'override_log', COUNT(*) FROM override_log
  UNION ALL SELECT 'model_card', COUNT(*) FROM model_card
  ORDER BY tbl;
"
```

Expected counts:

| Table | Count |
|---|---|
| inference_config | 5 |
| agent | 2 |
| task | 2 |
| agent_version | 3 |
| task_version | 3 |
| prompt | 8 |
| prompt_version | 10 |
| tool | 8 |
| pipeline | 1 |
| test_suite | 4 |
| test_case | 12 |
| approval_record | 8 |
| agent_decision_log | 16 |
| override_log | 2 |
| model_card | 2 |

---

## Step 3: Start the App and Verify in Browser

```bash
uvicorn uw_demo.app.main:app --port 8000 --reload
```

Open http://localhost:8000/verity/admin/ and verify each page:

### Dashboard (`/verity/admin/`)
- 8 stat cards showing: Agents=2, Tasks=2, Prompts=8, Configs=5, Tools=8, Decisions=16, Overrides=2, Incidents=0
- Recent Decisions table with 10 rows showing entity names, types (agent/task badges), step names, and status

### Agents (`/verity/admin/agents`)
- Table with 2 rows: triage_agent and appetite_agent
- Both show "high" materiality badge (red/orange)
- Both show "1.0.0" champion version badge (green)
- Inference config column shows "triage_balanced"

### Agent Detail (`/verity/admin/agents/triage_agent`)
- Agent Details card: name, materiality=high, champion=1.0.0, owner=Sarah Chen
- Description and purpose text from the PRD
- Version History table with 2 rows: v0.9.0 (deprecated) and v1.0.0 (champion)
- Prompts section: 2 prompts — system (behavioural) and user (contextual)
  - System prompt shows the full multi-paragraph triage instruction
- Authorized Tools: 5 tools listed (get_submission_context, get_underwriting_guidelines, etc.)
- Model Card section: purpose, design rationale, known limitations, status=approved

### Tasks (`/verity/admin/tasks`)
- Table with 2 rows: document_classifier (classification) and field_extractor (extraction)
- Both show "medium" materiality badge
- Both show champion version badge

### Prompts (`/verity/admin/prompts`)
- Table with 8 rows
- Shows governance tier badges: behavioural (red), contextual (amber), formatting (green)
- Shows API role badges: system, user

### Inference Configs (`/verity/admin/configs`)
- Table with 5 rows showing name, model, temperature, max_tokens, intended use
- classification_strict: temp=0.0, max_tokens=512
- triage_balanced: temp=0.2, max_tokens=4096

### Tools (`/verity/admin/tools`)
- Table with 8 tools
- Write operation column: 3 tools marked ✓ (update_submission_event, store_triage_result, update_appetite_status)
- Mock mode: all ✓

### Pipelines (`/verity/admin/pipelines`)
- 1 pipeline: "Underwriting Submission Processing Pipeline" with champion v1 badge
- Steps table with 4 rows showing dependency chain:
  1. classify_documents → task: document_classifier
  2. extract_fields → task: field_extractor (depends on classify)
  3. triage_submission → agent: triage_agent (depends on extract)
  4. assess_appetite → agent: appetite_agent (depends on triage)

### Decision Log (`/verity/admin/decisions`)
- "16 total decisions logged" header
- Table with 16 rows showing entity names, type badges (agent/task), step names, submission IDs
- Rows are clickable — clicking opens decision detail

### Decision Detail (click any decision row)
- Execution Summary: entity type, version, step name, status, duration, tokens, model
- Inference Config Snapshot: shows the exact parameters used (temperature, max_tokens)
- Output section: full JSON output
- For agent decisions: reasoning text visible

### Model Inventory (`/verity/admin/model-inventory`)
- Agents section (2 rows):
  - triage_agent: materiality=high, F1=0.860, Kappa=0.780, model card=approved
  - appetite_agent: materiality=high, model card=approved
- Tasks section (2 rows):
  - document_classifier: capability=classification, F1=0.950
  - field_extractor: capability=extraction

---

## Re-Seeding

To start over with fresh data:

```bash
python -m uw_demo.app.setup.register_all
```

The script drops all tables and re-creates everything. No need to manually clean up.
