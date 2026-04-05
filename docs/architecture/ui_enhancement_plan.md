# UI Enhancement Plan — Future

Captured 2026-04-05. To be implemented after version management / date pinning.

---

## Navigation Restructure

### Left Sidebar Sections

```
Home (renamed from Dashboard)

REGISTRY
  Applications
  Pipelines
  Agents
  Tasks
  Prompts
  Configs (renamed from Inference Configs)
  Tools
  MCPs (coming soon)
  AI Models (coming soon)

OBSERVABILITY (renamed from Execution)
  Usage (new — dashboard of asset usage patterns)
  Pipeline Runs
  Decision Logs
  HITL Overrides (renamed from Overrides)
  Spend Analysis (coming soon)

GOVERNANCE
  Inventory (renamed from Model Inventory)
  Lifecycle
  Ground Truth (new)
  Test Status (renamed from Test Results)
  Incidents (coming soon)
```

---

## Home / Dashboard Redesign

### Three sections:

**[1] Top-line overview cards — 3 groups:**
- Registry: Applications, Pipelines, Agents, Tasks, Prompts, Configs, Tools
- Observability: Decisions, Pipeline Runs, Overrides
- Governance: Open Incidents, Pending Approvals, Entities in Staging/Shadow

**[2] Observability charts (interactive):**
- Decision count over time stacked by status (complete/failed/overridden)
- Options: Chart.js via CDN (lightweight, no npm), or Plotly.js, or ECharts
- Interactive filtering by application, entity type, date range
- Small font sizes acceptable — maximize chart real estate

**[3] Governance dashboard:**
- Asset additions over time (new versions created)
- Testing activity (test runs, pass/fail rates)
- Change stats: versions promoted, rollbacks, overrides trend
- Research: compliance heat map, drift detection indicators

---

## Page-Level Enhancements

### Applications
- Table at top with selection
- Selected application shows detail card: description, mapped entities (by type), decision count, override count, flags

### Pipelines
- Table with Applications column (display name)
- Selected pipeline shows steps with entity display names
- Step display name: use step_name (human-readable already, e.g., "classify_documents")

### Agents
- Applications column on table (display name)
- Tools and prompts used shown in table row
- Agent can only use one inference config per version (answer: yes, one config per version)

### Tasks
- Applications column on table
- Prompts used shown in table row

### Prompts
- Add `display_name` column to `prompt` table (currently only has `name`)
- "Used by" shows entity display name
- Detail page must be added
- Version numbering: change from single integer to 3-part (major.minor.patch) — requires schema change to `prompt_version`
- Add `valid_from` and `valid_to` to `prompt_version` (part of version management work)
- Applications column on table

### Configs (Inference Configs)
- Add `display_name` column to `inference_config` table
- "Used by" shows entity display name
- Detail page must be added
- Applications column on table

### Tools
- Tool detail page must be added
- Tool versioning: currently no `tool_version` table — impedes version-pinned execution
- This is a schema addition for a future phase

### Pipeline Runs
- Add Pipeline display name as second column
- Rename "Entities" to "Assets", show as badge list matching registry page style

### Decision Log
- Entity and step display names (requires join or denormalization)

---

## "Coming Soon" Items (Deferred)

| Item | Section | Notes |
|---|---|---|
| MCPs | Registry | MCP server governance — tables exist in PRD but not implemented |
| AI Models | Registry | Managing models via Bedrock/Foundry/Vertex — needs design discussion |
| Spend Analysis | Observability | Cost tracking per agent/task/pipeline — needs token cost mapping |
| Incidents | Governance | Incident table exists in schema but no UI — needs workflow design |

---

## Schema Changes Needed for UI Enhancements

| Change | Table | Notes |
|---|---|---|
| Add `display_name` | `prompt` | Currently only has `name` |
| Add `display_name` | `inference_config` | Currently only has `name` |
| Add `valid_from`, `valid_to` | `prompt_version` | Part of version management work |
| 3-part versioning | `prompt_version` | Change from single integer to major.minor.patch |
| `tool_version` table | new table | Enables tool versioning and version-pinned execution |

---

## Implementation Order

1. **Version management + date pinning** (in progress — separate plan)
2. Navigation restructure (sidebar sections, renamed pages)
3. Schema additions (display_name on prompt/config, prompt 3-part versioning)
4. Table enhancements (applications column, tools/prompts in agent rows)
5. Detail pages (prompt detail, config detail, tool detail)
6. Dashboard redesign (3-section layout with charts)
7. Coming soon placeholders
