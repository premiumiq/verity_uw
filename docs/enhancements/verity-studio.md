# Verity Studio — UI-Driven Authoring & Management

> **Status:** future, not yet designed
> **Source:** new (introduced 2026-04-25); will become a fourth Verity plane alongside Governance, Runtime, and Agents
> **Priority:** medium-high — significant productivity unlock for non-developer users; the bottleneck on engineering for any composition work

## What's missing today

Composing AI assets in Verity is currently a developer-only activity. Registering an Agent, wiring its source bindings, authorizing tools, building test cases, uploading ground-truth data, and driving the lifecycle all require Python scripts (see `uw_demo/app/setup/seed_uw.py` for the canonical pattern).

The people accountable for the resulting AI behavior — underwriters, compliance officers, governance reviewers, SMEs — cannot author or modify the assets directly. Every change funnels through engineering, which:

- Slows iteration. A prompt tweak or threshold change is a code commit.
- Decouples accountability from authorship. The SME signs off on AI behavior they did not (and could not) shape.
- Limits adoption. Demos are impressive; day-2 use stalls because the audience that should drive the next change can't.

The Admin UI already shows read-only views of everything (registry browse, decision-log viewer, validation results). What's missing is the **write surface**: a UI to create, modify, and govern the assets.

## Proposed approach

A new fourth plane: **Verity Studio**. A thick frontend over the existing Verity REST API (`/api/v1/*`), oriented around the four authoring jobs the current scripts cover.

### Capabilities (initial scope)

- **Compose AI** — visual authoring for Agents, Tasks, Prompts, Inference Configs, Tools, Data Connectors, MCP Servers
  - Prompt template editor with template-variable validation, live preview, conditional-section preview by `governance_tier`
  - Source-binding wiring panel with reference-grammar autocomplete (`input.*`, `const:*`, `fetch:C/M(input.X)`)
  - Write-target editor with payload-field reference assistance
  - Tool authorization picker (agent → tools, with `data_classification_max` filtering)
  - Sub-agent delegation graph (visual parent → child relationships)
- **Lifecycle Management** — extend the existing partial UI
  - Promotion workflow with evidence checklists per gate
  - Approval routing with HITL sign-off (uses `approval_record`)
  - Clone-and-edit authoring with composition diff viewer
  - Rollback workflow with diff against prior champion
- **Ground Truth Management** — dataset and annotation UX
  - Dataset upload (CSV / JSON / Vault link)
  - Annotator assignment + IAA dashboard
  - Authoritative-label resolution UI (multi-annotator → gold)
  - Coverage and quality reporting
- **Test Management** — test-suite authoring
  - Suite builder with case templates per `capability_type`
  - Expected-output editor (JSON Schema-aware)
  - Mock fixture builder for `tool` / `source` / `target` / `step`
  - Run-test-suite + result drill-through

### Architecture position

Studio is a **UI plane** — no new backend capabilities required initially. It calls the same REST API that the SDK uses; everything Studio writes goes through the existing governance writes (so audit, lifecycle, and validation gates apply uniformly to UI-driven and SDK-driven changes).

```
┌────────────────────────────────────────────────────┐
│  Verity Studio (port 8003 — future)                │
│  Visual composition · Lifecycle UX · GT mgmt · Tests│
└──────────┬─────────────────────────────────────────┘
           │ REST API calls — same /api/v1/* the SDK uses
           ▼
┌────────────────────────────────────────────────────┐
│  Verity Governance (port 8000)                     │
│  Asset Registry · Lifecycle · Decisions · etc.     │
└────────────────────────────────────────────────────┘
```

Studio-specific backend endpoints come later, only when needed (e.g. real-time collaboration for multi-author prompt editing, prompt template autocomplete with embedding search).

### Tech direction (open for design)

- Likely a single-page app: React or HTMX + Alpine to stay in the existing Jinja+HTMX+Tailwind family
- Shares the DaisyUI theme already used by the Admin UI for visual consistency
- Authentication tied to the same OIDC layer planned in [rest-api-auth.md](rest-api-auth.md) — Studio is unusable without per-user identity

### Relationship to existing surfaces

| Surface | Today | After Studio |
|---|---|---|
| Python SDK | Primary authoring + invocation surface | Stays primary for batch / scripted setup; Studio for iterative work |
| REST API | Read + runtime + (limited) authoring | Same scope — Studio is a consumer |
| Admin UI | Read-only browse, dashboards, partial lifecycle UI | Read views remain; write workflows move to Studio |
| Verity Agents (future) | Drives drift detection, lifecycle init, validation routing | Studio surfaces the agents' outputs (incidents, drafted candidates, validation routing queues) for human action |

## Acceptance criteria

Per capability area, this is what "done" looks like for an MVP:

- **Compose AI** — a non-developer SME can author a new prompt version, wire it into an existing draft Task version, save, and validate the composition without writing code. The resulting `task_version` row is byte-identical to what a `seed_*.py` script would have produced.
- **Lifecycle** — the same SME can drive a candidate version through `staging → shadow → challenger → champion`, supplying evidence and rationale at each gate. Approval records land in `approval_record` with the SME's identity (post-auth).
- **Ground Truth** — an SME uploads a CSV of labeled records, assigns two annotators, monitors IAA in real time, and resolves the gold label via the UI. Three rows in `ground_truth_dataset` / `_record` / `_annotation` per labeled item.
- **Tests** — the same SME builds a 20-case suite for `document_classifier`, runs it against the current champion, and sees per-case pass/fail in the UI.

Post-MVP: real-time collaboration; embedding-based prompt similarity for de-duplication suggestions; validation-failure → candidate-draft handoff to Verity Agents.

## Notes

The product story matters: **Verity Studio is what makes Verity usable beyond the engineering team.** Without it, Verity is a metamodel + governance backend that requires a developer to operate. With it, Verity is a governance platform that the people accountable for AI behavior can actually use.

Design isn't started. Open questions:

- Do we ship Studio as a separate Docker service (`port 8003`) or fold it into `verity` at `/studio/*`?
- Single-page app vs HTMX + Alpine — pick before any code goes in
- How much of the Admin UI's existing read views stay vs. get re-implemented in Studio's design language
- Pricing implications (Studio likely a paid-tier feature for non-engineering seats)

These are the next conversations.
