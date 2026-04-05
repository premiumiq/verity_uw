# Phase 5: UW Business Application

## Context

The Verity admin UI shows the governance side — agents, tasks, prompts, decisions, model inventory. But the demo narrative is "Application X powered by Verity." We need the "Application X" — a simple underwriting workflow UI where a business user sees submissions, runs the AI pipeline, and views results. Then switches to Verity admin to see the governance trail.

## Decisions Made
- **Mock by default, live Claude optional** — Pipeline runs use pre-computed mock results instantly. A "Run Live" button calls Claude for real (costs ~$0.05, takes ~15-30 seconds).
- **Separate sidebar** — UW app has its own navigation, distinct from Verity admin. A link in each sidebar lets you jump to the other.
- **Multi-app tracking deferred to Phase 5b** — Future: `application` table in Verity, map registry assets to applications. For now, assume one app.

---

## What Gets Built

### UW Business App UI (at `/uw/`)

| Page | URL | What It Shows |
|---|---|---|
| **Submissions** | `/uw/` | List of 4 pre-seeded submissions with status badges (Green/Amber/Red), LOB, named insured |
| **Submission Detail** | `/uw/submissions/{id}` | Account info + AI results panel showing classifier, extractor, triage, appetite outputs |
| **Pipeline Runner** | `/uw/submissions/{id}/pipeline` | "Run Pipeline" button → step-by-step progress → results. Mock by default, live optional |

### UW Base Template
- Same PremiumIQ branding (logo, Poppins font, color palette)
- Own sidebar with: Submissions, (future: Quotes, Policies)
- Link to Verity Admin in sidebar footer
- Breadcrumbs: UW Demo > Submissions > Acme Dynamics

### Mock Pipeline Execution
- When "Run Pipeline (Mock)" is clicked: creates decision log entries using pre-built outputs (same data as seed script), instant completion
- When "Run Pipeline (Live)" is clicked: calls `verity.execute_pipeline()` which calls Claude for real
- Both paths log decisions in Verity — the governance trail is identical

### Link Between UIs
- UW submission detail has "View in Verity" links that jump to:
  - `/admin/audit-trail/{submission_id}` — full decision chain
  - `/admin/decisions/{decision_id}` — individual decision detail
- Verity admin sidebar footer has "UW Demo →" link

---

## Files to Create/Modify

### New Files

| File | Purpose |
|---|---|
| `uw_demo/app/ui/routes.py` | FastAPI routes for /uw/ pages |
| `uw_demo/app/ui/templates/uw_base.html` | Base template with UW sidebar |
| `uw_demo/app/ui/templates/submissions.html` | Submission list page |
| `uw_demo/app/ui/templates/submission_detail.html` | Single submission with AI results |
| `uw_demo/app/ui/templates/pipeline_runner.html` | Pipeline execution page with step progress |
| `uw_demo/app/tools/submission_tools.py` | Tool implementations (mock data returns) |
| `uw_demo/app/tools/guidelines_tools.py` | Guidelines tool (returns mock guidelines text) |
| `uw_demo/app/tools/mock_enrichment.py` | Mock enrichment data |
| `uw_demo/app/pipeline.py` | Mock pipeline runner (creates decision logs from pre-built outputs) |

### Modified Files

| File | Change |
|---|---|
| `uw_demo/app/main.py` | Mount UW routes at `/uw/`, register tool implementations with Verity |
| `verity/src/verity/web/templates/base.html` | Add "UW Demo →" link in sidebar footer |

### NOT Creating (deferred)

| Item | Reason |
|---|---|
| `pas_db` schema / business database | Submissions data comes from seed decision logs — no separate business DB needed for App 1 |
| `application` table in Verity | Phase 5b — multi-app tracking |
| MinIO document upload | Phase 5 upgrade — synthetic PDFs |

---

## Architecture: How Submissions Work Without pas_db

The 4 pre-seeded submissions exist as decision log entries in `verity_db.agent_decision_log` with fixed submission IDs. The UW app queries these decisions to show submission data:

```python
# Get all decisions for a submission → shows what AI produced
trail = await verity.get_audit_trail(submission_id)

# The submission metadata (name, LOB, status) comes from a static dict
# in the UW app — not a database table. This keeps Phase 5 simple.
SUBMISSIONS = {
    "00000001-...": {"name": "Acme Dynamics LLC", "lob": "D&O", "status": "Green", ...},
    "00000002-...": {"name": "TechFlow Industries Inc", "lob": "D&O", "status": "Amber", ...},
    ...
}
```

This avoids building a second database schema. The demo story is about Verity governance, not about a policy admin system.

---

## Page Designs

### Submissions List (`/uw/`)

```
UW Demo > Submissions

┌──────────────────────────────────────────────────────────────┐
│ Submissions                                          4 total │
├──────┬─────────────────────┬──────┬────────┬─────────┬──────┤
│ ID   │ Named Insured       │ LOB  │ Status │ Steps   │      │
├──────┼─────────────────────┼──────┼────────┼─────────┼──────┤
│ 001  │ Acme Dynamics LLC   │ D&O  │ Green  │ 4/4     │ View │
│ 002  │ TechFlow Industries │ D&O  │ Amber  │ 4/4 ⚠   │ View │
│ 003  │ Meridian Holdings   │ GL   │ Red    │ 4/4     │ View │
│ 004  │ Acme Dynamics LLC   │ GL   │ Amber  │ 4/4     │ View │
└──────┴─────────────────────┴──────┴────────┴─────────┴──────┘
```

### Submission Detail (`/uw/submissions/{id}`)

```
UW Demo > Submissions > Acme Dynamics LLC

┌─ Submission Info ────────────────────────────────────────────┐
│ Named Insured: Acme Dynamics LLC                             │
│ LOB: D&O    Revenue: $50,000,000    Employees: 250           │
│ Status: [Green]   Pipeline: 4/4 steps complete               │
│                                                              │
│ [Run Pipeline (Mock)]  [Run Pipeline (Live)]                 │
│ [View in Verity ↗]                                           │
└──────────────────────────────────────────────────────────────┘

┌─ AI Results ─────────────────────────────────────────────────┐
│                                                              │
│ ┌─ [TASK] Document Classification ─── 0.97 confidence ─────┐│
│ │ Type: acord_855                                           ││
│ │ Notes: Clear ACORD 855 D&O application header             ││
│ └───────────────────────────────────────────────────────────┘│
│                                                              │
│ ┌─ [TASK] Field Extraction ─── complete ────────────────────┐│
│ │ named_insured: Acme Dynamics LLC                          ││
│ │ annual_revenue: $50,000,000                               ││
│ │ employee_count: 250                                       ││
│ │ board_size: 7                                             ││
│ └───────────────────────────────────────────────────────────┘│
│                                                              │
│ ┌─ [AGENT] Risk Triage ─── Green ─── 0.89 confidence ──────┐│
│ │ Routing: assign_to_uw                                     ││
│ │ Reasoning: Strong financials, clean loss history...        ││
│ │ Risk factors: Revenue concentration (low)                  ││
│ └───────────────────────────────────────────────────────────┘│
│                                                              │
│ ┌─ [AGENT] Appetite Assessment ─── within_appetite ─────────┐│
│ │ Confidence: 0.92                                          ││
│ │ Reasoning: Meets all D&O guidelines criteria per §2.1-2.4 ││
│ │ Citations: §2.1 Revenue > $10M ✓                          ││
│ └───────────────────────────────────────────────────────────┘│
│                                                              │
│ ┌─ Override (if exists) ────────────────────────────────────┐│
│ │ Overrider: David Park, Senior UW                          ││
│ │ Reason: risk_assessment_disagree                          ││
│ │ AI said: Amber → Human said: Green                        ││
│ └───────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

### Pipeline Runner (`/uw/submissions/{id}/pipeline`)

For mock mode: instant results displayed as step cards.
For live mode: HTMX polling shows steps completing one by one.

```
UW Demo > Submissions > TechFlow Industries > Pipeline

Pipeline: uw_submission_pipeline v1
Status: Running...

Step 1: [TASK] classify_documents    ✓ complete  (1.2s)
Step 2: [TASK] extract_fields        ✓ complete  (2.4s)
Step 3: [AGENT] triage_submission    ⏳ running...
Step 4: [AGENT] assess_appetite      ○ pending

Total: 3.6s elapsed
```

---

## Tool Implementations (Mock)

All tools return realistic hardcoded data matching the seed submissions. They don't hit a real database — they return pre-built dicts keyed by submission_id.

```python
# uw_demo/app/tools/submission_tools.py
def get_submission_context(submission_id: str) -> dict:
    """Returns mock submission data for the given ID."""
    return MOCK_SUBMISSIONS.get(submission_id, {"error": "not found"})
```

These tool implementations are registered with Verity at startup:
```python
# In main.py
verity.register_tool_implementation("get_submission_context", get_submission_context)
```

When `execute_pipeline()` runs live, Claude calls these tools, gets mock data back, and reasons about it. The AI output is real — the input data is mock.

---

## Build Steps

1. Create `uw_base.html` (own sidebar, PremiumIQ branding, link to Verity)
2. Create `submissions.html` (list with status badges)
3. Create `submission_detail.html` (info card + AI results from decision logs)
4. Create `pipeline_runner.html` (step progress cards)
5. Create `uw_demo/app/ui/routes.py` (3 page routes + mock pipeline endpoint)
6. Create tool implementations (mock data returns)
7. Create `uw_demo/app/pipeline.py` (mock pipeline: creates decision logs from pre-built outputs)
8. Update `main.py` (mount UW routes, register tool implementations)
9. Add "UW Demo →" link in Verity admin sidebar
10. Create validation guide

---

## Phase 5b: Multi-App Tracking (Deferred)

Add to Verity schema:
```sql
CREATE TABLE application (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    description TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE application_entity (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id  UUID NOT NULL REFERENCES application(id),
    entity_type     entity_type NOT NULL,
    entity_id       UUID NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_app_entity UNIQUE (application_id, entity_type, entity_id)
);
```

This enables:
- Filtering Verity admin by application
- Model inventory per application
- Decision log filtered by application
- Multiple business apps sharing agents/tasks

---

## Verification

1. `/uw/` shows 4 submissions with status badges (Green, Amber, Red, Amber)
2. `/uw/submissions/{id}` shows submission info + 4 AI result cards from decision logs
3. Submission detail for SUB-002 shows the override (David Park, Amber → Green)
4. "Run Pipeline (Mock)" creates new decision log entries → visible in Verity admin decision log
5. "View in Verity" link opens audit trail page for that submission
6. Verity admin sidebar has "UW Demo →" link that navigates to `/uw/`
7. "Run Pipeline (Live)" calls Claude API → real AI output → decisions logged
