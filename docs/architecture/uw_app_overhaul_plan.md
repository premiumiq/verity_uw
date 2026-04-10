# UW Demo App — Complete UI Overhaul

## Implementation Status

| Phase | Status | Notes |
|---|---|---|
| Phase 1: Database (workflow_step table + seed) | DONE | Added to schema.sql, seed_uw.py seeds 5 steps per submission |
| Phase 2: CSS (stepper, tabs, action-bar, spinner, KPI) | DONE | All use verity- prefix. CSS synced to all 3 apps. |
| Phase 3: submissions.html (KPI cards + enhanced table) | DONE | 6 KPI cards, 8-column table with status/risk/appetite |
| Phase 4: submission_detail.html (stepper, cards, tabs) | DONE | Full rewrite with HTMX tab loading |
| Phase 5: Tab partials (5 tabs + stepper + action bar) | DONE | 7 partial templates in partials/ dir |
| Phase 6: routes.py (tab endpoints, HTMX, workflow helpers) | DONE | 5 tab routes, 3 action routes, 8 db helpers |
| Phase 7: Cleanup (delete old, sync CSS) | DONE | Removed pipeline_runner.html, extraction_review.html |

### New files created
- `uw_demo/app/ui/templates/partials/_stepper.html`
- `uw_demo/app/ui/templates/partials/_action_bar.html`
- `uw_demo/app/ui/templates/partials/_tab_details.html`
- `uw_demo/app/ui/templates/partials/_tab_extraction.html`
- `uw_demo/app/ui/templates/partials/_tab_assessment.html`
- `uw_demo/app/ui/templates/partials/_tab_loss_history.html`
- `uw_demo/app/ui/templates/partials/_tab_audit_trail.html`

### Files deleted
- `uw_demo/app/ui/templates/pipeline_runner.html` (merged into detail page)
- `uw_demo/app/ui/templates/extraction_review.html` (merged into extraction tab)

### Design decisions during implementation
- **APP_ENV controls mock vs live**: `settings.APP_ENV != "live"` uses mock context. No UI toggle.
- **OOB swaps**: Stepper and action bar update via HTMX out-of-band swaps after pipeline actions. The extraction tab partial includes OOB blocks when `workflow_steps` and `next_action` are in the template context.
- **extraction_review auto-skip**: If no flagged fields, extraction_review step is set to "skipped" and submission advances directly to "approved" status.
- **One CSS file**: verity.css copied to all 3 apps (UW, EDMS, Verity admin). All new components use `verity-` prefix.

---

## Context

The current UW Demo app has basic templates that don't look like a real underwriting workbench. The user shared screenshots of a production UW workbench (ServiceNow-style) showing: KPI summary cards, workflow steppers with numbered circles, tabbed detail pages with company/broker/policy cards, data completeness metrics, and inline analytics.

Key requirements from the user:
- **No mock mode from UW app** — live pipeline runs only (mock stays for dev/testing via APP_ENV)
- **Submissions seeded as intake only** — no pre-processed data, users run each step live
- **HITL integrated into detail page** — not a separate redirect, happens inline in the Extracted Fields tab
- **Workflow progression visible** — numbered stepper shows where each submission is in the flow
- **ServiceNow-style UI** — summary cards, tabs, status badges, action buttons

---

## Pages (2 pages + 5 HTMX tab partials)

### Page 1: Submissions List (`/`)

```
+----------------------------------------------------------+
|            |  H1: Submissions                             |
|            |                                              |
|  Sidebar   |  KPI CARDS (6 in a row)                     |
|            |  [Intake:2] [Processing:0] [Review:1] ...    |
|            |                                              |
|            |  TABLE                                       |
|            |  Company | LOB | Eff.Date | Industry |       |
|            |  Status | Risk Score | Appetite | Action     |
+----------------------------------------------------------+
```

**KPI cards**: Count submissions by status (intake, processing, review, ready, assessed, total). Computed in route from `GROUP BY status`.

**Table columns**: Named Insured (bold, primary) | LOB (badge) | Effective Date | Industry (SIC description, truncated) | Status (workflow badge) | Risk Score (RAG badge, empty until assessed) | Appetite (badge, empty until assessed) | View button.

### Page 2: Submission Detail (`/submissions/{id}`)

```
+----------------------------------------------------------+
|            |  H1: {Named Insured}    [Status] [LOB]      |
|            |                                              |
|  Sidebar   |  WORKFLOW STEPPER (horizontal, 5 circles)   |
|            |  (1)----(2)----(3)----(4)----(5)            |
|            |  Intake  Docs  Review Triage Appetite        |
|            |                                              |
|            |  SUMMARY CARDS (4 in a row)                  |
|            |  [Revenue] [Employees] [Limits] [Prior Prem] |
|            |                                              |
|            |  ACTION BAR (contextual next step only)      |
|            |  [Process Documents]                         |
|            |                                              |
|            |  TABS (HTMX, no full page reload)            |
|            |  Details | Extraction | Assessment |         |
|            |  Loss History | Audit Trail                  |
|            |                                              |
|            |  TAB CONTENT (swapped via hx-get)            |
+----------------------------------------------------------+
```

**Workflow stepper**: 5 circles connected by lines. States: complete (green checkmark), active/running (blue, pulsing), pending (gray hollow). Timestamps shown under completed steps.

**Action bar**: Shows ONE button for the next action based on status:
- `intake` → "Process Documents"
- `review` → switches to Extraction tab (button scrolls to HITL form)
- `approved` / `documents_processed` → "Assess Risk"
- `assessed` → "Workflow Complete" badge

**No mock/live toggle** in the UI. The route handler uses `APP_ENV` internally.

### Tab Partials (HTMX fragments, no base template)

| Partial | Route | Content |
|---|---|---|
| `_tab_details.html` | `GET /submissions/{id}/tab/details` | Company Details, Policy Details, Prior Coverage cards (3-col grid) |
| `_tab_extraction.html` | `GET /submissions/{id}/tab/extraction` | Completeness metric + extraction table. In review mode: editable form with override inputs. In read-only mode: table with overrides shown |
| `_tab_assessment.html` | `GET /submissions/{id}/tab/assessment` | Triage card (RAG badge, reasoning) + Appetite card (determination, citations). Empty state if not yet assessed |
| `_tab_loss_history.html` | `GET /submissions/{id}/tab/loss-history` | Loss history table with totals row |
| `_tab_audit_trail.html` | `GET /submissions/{id}/tab/audit-trail` | Verity decision log entries with links to Verity admin |

### Pages Removed

- `pipeline_runner.html` — pipeline runs inline from detail page, results show in tabs
- `extraction_review.html` — merged into `_tab_extraction.html` with inline HITL form

---

## Database Addition

Add `workflow_step` table to `uw_demo/app/db/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS workflow_step (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id   UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
    step_name       TEXT NOT NULL,
    step_order      INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    completed_by    TEXT,
    pipeline_run_id UUID,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(submission_id, step_name)
);
```

| step_order | step_name | Trigger |
|---|---|---|
| 1 | intake | Auto-complete on seed |
| 2 | document_processing | User clicks "Process Documents" |
| 3 | extraction_review | Auto if flags exist, skipped if clean |
| 4 | triage | User clicks "Assess Risk" (Pipeline 2 step 1) |
| 5 | appetite | Auto after triage (Pipeline 2 step 2) |

Update `seed_uw.py`: insert 5 workflow_step rows per submission (step 1 complete, steps 2-5 pending).

---

## HTMX Patterns

| Pattern | Where | How |
|---|---|---|
| Tab switching | Detail page tabs | `hx-get="/submissions/{id}/tab/details"` `hx-target="#tab-content"` `hx-swap="innerHTML"` |
| HITL form submit | Extraction tab | `hx-post="/submissions/{id}/approve-extraction"` `hx-target="#tab-content"` |
| Stepper update after action | Pipeline complete / HITL approve | OOB swap: `<div id="workflow-stepper" hx-swap-oob="true">` in response |
| Action bar update | After any state change | OOB swap: `<div id="action-bar" hx-swap-oob="true">` |
| Pipeline spinner | Process Docs / Assess Risk buttons | `hx-indicator="#spinner"` `hx-disabled-elt="this"` |
| Default tab on page load | Detail page initial render | Server-side `{% include 'partials/_tab_details.html' %}` (no HTMX needed) |

**Long-running pipelines (15-30s)**: HTMX request stays open. Spinner shows. Button disabled. Response replaces tab content + OOB updates stepper/action bar. Simple and sufficient for demo.

---

## New CSS Components

Add to shared `verity.css` (one CSS file used by all apps — UW, EDMS, Verity admin). All classes use `verity-` prefix:

- **`.verity-stepper`** — flex row of step circles with connectors
- **`.verity-step-circle`** — 36px circle, 3 color states (green/blue/gray)
- **`.verity-step-connector`** — horizontal line between circles (green when complete)
- **`.verity-tabs`** — tab bar with bottom border
- **`.verity-tab`** — individual tab button with active state underline
- **`.verity-tab-badge`** — red notification dot (e.g., count of flagged fields)
- **`.verity-action-bar`** — gray action button container
- **`.verity-spinner`** — CSS-only loading spinner
- **`@keyframes verity-pulse`** — active step breathing animation
- **`@keyframes verity-spin`** — spinner rotation

After adding to `verity.css`, copy the file to EDMS (`edms/src/edms/service/static/verity.css`). One CSS for all apps.

---

## Route Changes

### Modified Routes

| Route | Change |
|---|---|
| `GET /` | Add `status_counts` dict for KPI cards. Enrich submissions with assessments. |
| `GET /submissions/{id}` | Add `workflow_steps`, `next_action`, `review_count`. Serve default tab inline. |
| `POST /submissions/{id}/process-documents` | Remove `mode` param. Use `APP_ENV`. Return HTMX partial + OOB swaps (not redirect). |
| `POST /submissions/{id}/approve-extraction` | Return HTMX partial (updated extraction tab + OOB stepper + OOB action bar). |
| `POST /submissions/{id}/assess-risk` | Remove `mode` param. Return HTMX partial + OOB swaps. |

### New Routes (HTMX tab partials)

| Route | Returns |
|---|---|
| `GET /submissions/{id}/tab/details` | `_tab_details.html` partial |
| `GET /submissions/{id}/tab/extraction` | `_tab_extraction.html` partial |
| `GET /submissions/{id}/tab/assessment` | `_tab_assessment.html` partial |
| `GET /submissions/{id}/tab/loss-history` | `_tab_loss_history.html` partial |
| `GET /submissions/{id}/tab/audit-trail` | `_tab_audit_trail.html` partial |

### Removed Routes

| Route | Reason |
|---|---|
| `GET /submissions/{id}/review-extraction` | Merged into extraction tab |

---

## Files Changed

| File | Action | What |
|---|---|---|
| `uw_demo/app/db/schema.sql` | Add | `workflow_step` table |
| `uw_demo/app/setup/seed_uw.py` | Modify | Seed workflow_step rows (step 1 complete, rest pending) |
| `uw_demo/app/ui/static/verity.css` | Add | `verity-stepper`, `verity-tabs`, `verity-action-bar`, `verity-spinner` CSS |
| `uw_demo/app/ui/templates/submissions.html` | Rewrite | KPI cards + enhanced table |
| `uw_demo/app/ui/templates/submission_detail.html` | Rewrite | Stepper + cards + tabs + action bar |
| `uw_demo/app/ui/templates/partials/_tab_details.html` | New | Company/Policy/Prior Coverage cards |
| `uw_demo/app/ui/templates/partials/_tab_extraction.html` | New | Completeness metrics + HITL form / read-only table |
| `uw_demo/app/ui/templates/partials/_tab_assessment.html` | New | Triage + Appetite result cards |
| `uw_demo/app/ui/templates/partials/_tab_loss_history.html` | New | Loss history table with totals |
| `uw_demo/app/ui/templates/partials/_tab_audit_trail.html` | New | Verity decision log entries |
| `uw_demo/app/ui/routes.py` | Rewrite | Tab partial routes, HTMX responses, workflow_step helpers, remove mock param |
| `uw_demo/app/ui/templates/pipeline_runner.html` | Delete | Merged into detail page |
| `uw_demo/app/ui/templates/extraction_review.html` | Delete | Merged into extraction tab |

## Reuse

- All `verity-card`, `verity-table`, `verity-badge`, `verity-btn`, `verity-detail-grid` CSS classes
- `_get_submission()`, `_get_extractions()`, `_get_assessments()` helpers already in routes.py
- `_fetch_documents_from_edms()` helper already in routes.py
- Existing sidebar and base template (`uw_base.html`) — unchanged
- HTMX 2.0.4 already loaded in base template

## Verification

1. Load `http://localhost:8001/` — see KPI cards, 4 submissions all in "intake" status
2. Click a submission — see stepper (step 1 green, 2-5 gray), summary cards, Details tab
3. Click "Process Documents" — spinner shows, 15-30s wait, stepper updates (step 2 green), Extraction tab loads
4. If flags exist — Extraction tab shows HITL form with yellow-highlighted fields. Override, click Approve.
5. Click "Assess Risk" — spinner, triage + appetite run, stepper fully green, Assessment tab shows results
6. Check Verity admin — audit trail shows all pipeline steps with full decision logs
