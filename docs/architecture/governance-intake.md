# Governance Intake — Intakes, Risk Tiering, Requirements, Approvals

**Status:** v3 — **Phase A SHIPPED** · Phase B in design
**Author:** Anil + Claude
**Date:** 2026-05-06
**Revision history:**
- **v3 (2026-05-06)** — records what actually shipped in Phase A (incl. profile page, role-help modal, redundancy threshold tune, schema auto-application via container startup). Expands Phase B from one paragraph into an actionable plan. Resolves the v2 open questions.
- **v2 (2026-05-06)** — incorporated review feedback: "use case" → "intake"; `artifact_link` → `entity_link` (reusing `entity_type` enum); embeddings on `intake_requirement`; personas + role-actions matrix; artifact plan from intake.
- **v1 (2026-05-06)** — initial design.

This document is the design contract for the "process" layer that sits *upstream* of the registry: how a business idea becomes an approved AI **intake**, gets risk-classified, traces through to agents/tasks, and clears an approval chain before promotion to champion.

Four named capabilities the user asked for on 2026-05-06:

1. **Intake** — durable record of business problem, expected benefit, affected populations, in/out-of-scope decisions, requesting business owner.
2. **AI impact / risk classification** — tier the intake (EU AI Act language: minimal / limited / high / unacceptable, plus NAIC materiality), trigger heavier review at higher tiers.
3. **Requirements traceability** — business requirement → functional requirement → agent/task → eval/test → production monitor.
4. **Approval chain** — legal, compliance, model risk, business owner sign-offs captured as durable artifacts before promote-to-champion.

Plus three v2 additions surfaced in review:

5. **Personas / role-actions** — explicit role × action matrix; persona switcher in Studio nav; writes record `acting_as_role`.
6. **Artifact plan** — intake produces a draft plan of registry artifacts (agents/tasks/prompts/tools) needed; engineers "realize" plan rows into actual registry drafts.
7. **Embedded requirements** — `intake_requirement` carries a 384-dim BGE-small vector for semantic search and redundancy detection.

This is **not** a redo of the compliance stack ([compliance-stack.md](compliance-stack.md)). The compliance stack covers regulatory frameworks, canonical requirements, Verity features, and reports. This doc covers business intake, requirements, approvals, and registry traceability. The two layers connect via a single bridge table (§ 8 "Compliance bridge").

---

## 1. Why this layer is missing today

Today the registry starts at "agent exists." The pre-build process — *who asked for this, what problem is it solving, what risk tier is it, who approved it* — is not represented anywhere. That's a regulatory gap under:

- **NAIC Model Bulletin on Use of AI Systems by Insurers (Dec 2023)** — adopted by 20+ states; expects a documented AI Systems program covering full lifecycle from design intent.
- **NYDFS Circular Letter No. 7 (July 2024)** — explicit on use-case-level governance for AI/ECDIS in insurance underwriting and pricing.
- **EU AI Act Article 11** — technical documentation must link *intended purpose → risk assessment → design → testing → monitoring*.
- **ISO/IEC 42001** — AI management system standard.
- **SR 11-7 (Fed model risk management)** — applied across regulated insurance.

All five expect a use-case-level inventory with documented purpose, risk classification, approvals, and traceability. Currently Verity can't answer "show me every AI intake with its approver, risk tier, and the agents that implement it" — and that is the first question an examiner asks.

---

## 2. Vocabulary

| Concept | Meaning | Where it lives |
|---|---|---|
| **Intake** *(new)* | A business-approved purpose for AI within the company. E.g. "BOP submission eligibility classification." Owned by a business sponsor, risk-classified, approved. | `governance.intake` |
| **Agent / Task / Prompt / Tool** | A Verity registry artifact that *implements* part of an intake. | `governance.agent`, etc. |
| **Materiality tier** *(existing)* | Influence of an individual agent on underwriting decisions. high/medium/low. | `governance.agent.materiality_tier` |
| **AI risk tier** *(new)* | Risk classification of the **intake** under EU AI Act / NAIC framing. minimal/limited/high/unacceptable. | `governance.intake.ai_risk_tier` |
| **Canonical requirement** *(existing, compliance stack)* | A rationalized regulatory obligation. E.g. "Model inventory & registration." | `compliance.canonical_requirement` |
| **Intake requirement** *(new)* | A business / functional / non-functional / compliance requirement raised under a specific intake. | `governance.intake_requirement` |
| **Artifact plan** *(new)* | The list of registry entities the intake intends to produce, drafted on Studio, eventually realized as actual registry rows. | `governance.intake_artifact_plan` |
| **Persona** *(new)* | The role a Studio user is currently acting as. Drives nav and authorization. | session cookie + `acting_as_role` on writes |

The two requirement concepts are deliberately separate: regulatory obligations describe rules the world imposes on us; intake requirements describe what the business asked us to build. Both trace to agents/tasks, but for different reasons.

---

## 3. Data model

All tables live in the **`governance`** schema next to existing registry tables. No changes to existing tables; integration is via a polymorphic link table (§ 3.4).

### 3.1 Enumerations

```sql
CREATE TYPE governance.intake_status AS ENUM (
    'proposed',         -- intake submitted, not yet triaged
    'in_review',        -- governance team reviewing
    'impact_assessment',-- risk-tier-driven assessment in progress
    'approved',         -- all required sign-offs collected; build may begin
    'in_build',         -- agents/tasks being authored against this intake
    'live',             -- linked artifacts have at least one champion version
    'rejected',         -- governance team rejected at intake or review
    'retired'           -- no longer in production; linked artifacts deprecated
);

CREATE TYPE governance.ai_risk_tier AS ENUM (
    'minimal',          -- e.g. spell-check; no decision influence
    'limited',          -- supports humans; transparency obligations apply
    'high',             -- direct material impact (UW eligibility, pricing, claims)
    'unacceptable'      -- prohibited (social scoring, etc.); flagged at intake
);

CREATE TYPE governance.naic_materiality AS ENUM (
    'material',         -- NAIC AI Bulletin "Material" — governance program applies
    'non_material'      -- not material under bulletin
);

CREATE TYPE governance.requirement_kind AS ENUM (
    'business',         -- "Underwriters need 50% faster submission triage"
    'functional',       -- "System classifies BOP eligibility against appetite rules"
    'non_functional',   -- "P95 latency < 5 s; availability ≥ 99.5%"
    'compliance'        -- "All decisions retain decision log per NAIC §3.1"
);

CREATE TYPE governance.requirement_status AS ENUM (
    'draft', 'approved', 'implemented', 'verified', 'deprecated'
);

CREATE TYPE governance.requirement_relationship AS ENUM (
    'implements', 'tests', 'monitors', 'informs'
);

CREATE TYPE governance.studio_role AS ENUM (
    'business_owner',
    'compliance',
    'legal',
    'model_risk',
    'ai_governance',
    'security',
    'privacy',
    'engineer',
    'auditor',
    'viewer'
);

-- approval_role is the subset of studio_role that can be required on an
-- approval_request. Kept separate so non-approval roles (engineer, viewer)
-- never appear in required_roles by accident.
CREATE TYPE governance.approval_role AS ENUM (
    'business_owner', 'compliance', 'legal', 'model_risk',
    'ai_governance', 'security', 'privacy'
);

CREATE TYPE governance.approval_decision AS ENUM (
    'approved', 'rejected', 'requested_changes', 'abstained'
);

CREATE TYPE governance.approval_request_kind AS ENUM (
    'intake',                   -- initial intake approval
    'risk_reclassification',    -- tier changed mid-flight
    'promote_candidate',        -- linked artifact promoted to candidate
    'promote_champion',         -- linked artifact promoted to champion
    'retire'                    -- intake being retired
);

CREATE TYPE governance.artifact_plan_status AS ENUM (
    'proposed',         -- auto-drafted or manually added; no registry row yet
    'in_progress',      -- engineer is building; draft registry row exists
    'realized',         -- registry row created and linked
    'cancelled'         -- plan row dropped
);

-- Reuse of the existing entity_type enum, extended with the kinds
-- intakes need to link. ALTER TYPE … ADD VALUE is non-breaking.
ALTER TYPE governance.entity_type ADD VALUE IF NOT EXISTS 'test_suite';
ALTER TYPE governance.entity_type ADD VALUE IF NOT EXISTS 'ground_truth_dataset';
```

### 3.2 `intake` — the header

```sql
CREATE TABLE governance.intake (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code                        VARCHAR(120) NOT NULL UNIQUE,        -- e.g. 'uw-bop-eligibility'
    title                       TEXT NOT NULL,
    problem_statement           TEXT NOT NULL,                       -- the business problem
    expected_benefit            TEXT NOT NULL,                       -- why we are building this
    in_scope_decisions          TEXT,                                -- what the AI WILL decide / influence
    out_of_scope_decisions      TEXT,                                -- explicit non-goals
    affected_populations        JSONB NOT NULL DEFAULT '[]',         -- ["applicants","brokers","underwriters",...]
    business_owner_name         VARCHAR(200) NOT NULL,
    business_owner_email        VARCHAR(200),
    requesting_team             VARCHAR(200),
    ai_risk_tier                ai_risk_tier NOT NULL,
    risk_classification_rationale TEXT NOT NULL,
    naic_materiality            naic_materiality NOT NULL,
    status                      intake_status NOT NULL DEFAULT 'proposed',
    intake_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at                 TIMESTAMPTZ,
    retired_at                  TIMESTAMPTZ,
    effective_date              DATE,
    next_recertification_due    DATE,                                -- phase B: scheduled recertification
    created_by                  VARCHAR(200) NOT NULL,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes                       TEXT
);

CREATE INDEX idx_intake_status     ON governance.intake(status);
CREATE INDEX idx_intake_risk_tier  ON governance.intake(ai_risk_tier);
CREATE INDEX idx_intake_owner      ON governance.intake(business_owner_email);
```

`created_by VARCHAR(200)` follows existing convention (`prompt_version.author_name`, etc.). Free-text strings remain the user identity for the demo; persona switching (§ 5) records `acting_as_role` on writes.

### 3.3 `intake_impact_assessment` — required for limited / high tier

```sql
CREATE TABLE governance.intake_impact_assessment (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id                   UUID NOT NULL REFERENCES governance.intake(id) ON DELETE CASCADE,
    version                     INT NOT NULL DEFAULT 1,
    data_sources                JSONB NOT NULL DEFAULT '[]',         -- [{source,owner,classification},...]
    potential_harms             JSONB NOT NULL DEFAULT '[]',         -- [{population,harm,severity,likelihood},...]
    mitigations                 JSONB NOT NULL DEFAULT '[]',         -- [{mitigation,owner,evidence},...]
    fairness_considerations     TEXT,
    privacy_considerations      TEXT,
    human_oversight_plan        TEXT NOT NULL,                       -- required when tier ≥ limited
    completed_at                TIMESTAMPTZ,
    completed_by                VARCHAR(200),
    notes                       TEXT,
    UNIQUE (intake_id, version)
);
```

Triggered by status `in_review` for any intake with `ai_risk_tier IN ('limited','high')`. Approval cannot proceed without `completed_at IS NOT NULL`.

### 3.4 `intake_entity_link` — bridge to the registry

```sql
CREATE TABLE governance.intake_entity_link (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id                   UUID NOT NULL REFERENCES governance.intake(id) ON DELETE CASCADE,
    requirement_id              UUID REFERENCES governance.intake_requirement(id) ON DELETE SET NULL,
    entity_type                 governance.entity_type NOT NULL,     -- agent|task|prompt|tool|test_suite|ground_truth_dataset
    entity_id                   UUID NOT NULL,                       -- FK validated in application layer per kind
    relationship                requirement_relationship NOT NULL DEFAULT 'implements',
    created_by                  VARCHAR(200) NOT NULL,
    acting_as_role              governance.studio_role,              -- persona that created the link
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (intake_id, requirement_id, entity_type, entity_id, relationship)
);

CREATE INDEX idx_link_intake     ON governance.intake_entity_link(intake_id);
CREATE INDEX idx_link_entity     ON governance.intake_entity_link(entity_type, entity_id);
```

Polymorphic FK validated at the application layer — same convention as `entity_prompt_assignment.entity_type` and `application_entity.entity_type`. Reusing `governance.entity_type` keeps the enum count bounded.

### 3.5 `intake_requirement` — BR / FR / NFR / compliance, with embedding

```sql
CREATE TABLE governance.intake_requirement (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id                   UUID NOT NULL REFERENCES governance.intake(id) ON DELETE CASCADE,
    code                        VARCHAR(40) NOT NULL,                -- 'BR-1','FR-3','NFR-2','CR-1'
    kind                        requirement_kind NOT NULL,
    statement                   TEXT NOT NULL,
    acceptance_criteria         TEXT,
    source                      TEXT,                                -- 'PRD §4.2','NYDFS Circular 7'
    status                      requirement_status NOT NULL DEFAULT 'draft',
    parent_requirement_id       UUID REFERENCES governance.intake_requirement(id) ON DELETE SET NULL,

    -- Vector embedding for semantic search and redundancy detection
    embedding                   vector(384),
    embedding_model_id          UUID REFERENCES compliance.embedding_config(id),
    embedding_input_hash        BYTEA,                               -- SHA-256 of (statement || acceptance_criteria) at embed time

    created_by                  VARCHAR(200) NOT NULL,
    acting_as_role              governance.studio_role,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (intake_id, code)
);

CREATE INDEX idx_req_intake      ON governance.intake_requirement(intake_id);
CREATE INDEX idx_req_status      ON governance.intake_requirement(status);

-- IVFFlat index on the embedding for cosine-similarity queries.
-- lists=100 is appropriate for small/medium corpora; tune later.
CREATE INDEX idx_req_embedding
    ON governance.intake_requirement
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

**Embedding model:** `BAAI/bge-small-en-v1.5` (384 dim) via `fastembed`, matching the compliance stack ([AD-CS-007](compliance-stack.md#ad-cs-007)). Embeddings recompute when `(statement || acceptance_criteria)` changes — `embedding_input_hash` is the staleness sentinel. The existing `verity compliance reembed` CLI grows a new selector to cover this table.

**Redundancy check UX:** when a user types a new requirement, a Studio HTMX endpoint embeds the draft text and returns the top-N nearest existing requirements (across all intakes) above a similarity threshold. The UI surfaces these as "similar requirements found — consider linking instead of duplicating." Soft warning, not a block.

### 3.6 `intake_artifact_plan` — what we plan to build

```sql
CREATE TABLE governance.intake_artifact_plan (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id                   UUID NOT NULL REFERENCES governance.intake(id) ON DELETE CASCADE,
    requirement_id              UUID REFERENCES governance.intake_requirement(id) ON DELETE SET NULL,
    proposed_kind               governance.entity_type NOT NULL,     -- agent|task|prompt|tool
    proposed_name               VARCHAR(120) NOT NULL,
    proposed_display_name       TEXT NOT NULL,
    proposed_description        TEXT,
    proposed_purpose            TEXT,
    proposed_inputs             JSONB DEFAULT '{}',
    proposed_outputs            JSONB DEFAULT '{}',
    proposed_capability_type    governance.capability_type,          -- only when proposed_kind = 'task'
    proposed_materiality_tier   governance.materiality_tier NOT NULL,
    realized_entity_id          UUID,                                -- set when registry entity is created from this plan
    status                      artifact_plan_status NOT NULL DEFAULT 'proposed',
    auto_generated              BOOLEAN NOT NULL DEFAULT false,      -- true if produced by the auto-draft step
    created_by                  VARCHAR(200) NOT NULL,
    acting_as_role              governance.studio_role,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (intake_id, proposed_kind, proposed_name)
);

CREATE INDEX idx_plan_intake     ON governance.intake_artifact_plan(intake_id);
CREATE INDEX idx_plan_status     ON governance.intake_artifact_plan(status);
```

**Auto-generation on intake approval (§ 6):** the intake service scans approved requirements and proposes plan rows by kind. Functional requirements with action verbs ("classify", "extract", "generate") propose tasks. Multi-step requirements that imply tool use propose agents. All auto-generated rows have `auto_generated=true` and are fully editable — engineers add, remove, rename, or replace them.

**Realization:** clicking "Realize" on a plan row opens the existing registry create form (`/studio/govern/agents/new`, etc.) pre-populated from the plan. On successful create, the plan row's `realized_entity_id` is set, `status → realized`, and an `intake_entity_link` row is auto-created. Cancelling realization leaves the plan row at `in_progress` — never creates orphan registry rows.

**Unacceptable tier:** no plan rows are auto-generated; the intake is rejected at triage. The plan tab on the detail page shows a single banner — "this intake is in `unacceptable` risk tier under EU AI Act; no artifacts may be planned" — for demo visibility.

### 3.7 `approval_request` and `approval_signoff`

```sql
CREATE TABLE governance.approval_request (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id                   UUID NOT NULL REFERENCES governance.intake(id) ON DELETE CASCADE,
    kind                        approval_request_kind NOT NULL,
    target_entity_type          governance.entity_type,              -- nullable: only set for promote_* kinds
    target_entity_id            UUID,                                -- nullable: only set for promote_* kinds
    required_roles              JSONB NOT NULL,                      -- ['business_owner','compliance','legal','model_risk']
    status                      VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|withdrawn
    opened_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    opened_by                   VARCHAR(200) NOT NULL,
    opened_by_role              governance.studio_role,
    decided_at                  TIMESTAMPTZ,
    summary                     TEXT NOT NULL,
    notes                       TEXT
);

CREATE INDEX idx_approval_req_intake ON governance.approval_request(intake_id);
CREATE INDEX idx_approval_req_status ON governance.approval_request(status);

CREATE TABLE governance.approval_signoff (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_request_id         UUID NOT NULL REFERENCES governance.approval_request(id) ON DELETE CASCADE,
    role                        approval_role NOT NULL,
    approver_name               VARCHAR(200) NOT NULL,
    approver_email              VARCHAR(200),
    decision                    approval_decision NOT NULL,
    comment                     TEXT,
    evidence_url                TEXT,                                -- link to retained doc/email
    signed_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (approval_request_id, role, approver_email)
);

CREATE INDEX idx_signoff_request ON governance.approval_signoff(approval_request_id);
```

`required_roles` is JSONB because it's set per-request based on risk tier and request kind (§ 4.3). `approval_request.status` rolls up: `approved` when every role in `required_roles` has at least one `approved` signoff and no `rejected` signoff exists.

---

## 4. Processes

### 4.1 Intake creation

A user with persona `business_owner` or `ai_governance` creates an `intake` row via the Studio intake form. Required fields enforced. Status starts `proposed`. An `approval_request` of kind `intake` is opened automatically with `required_roles` defaulted to `['business_owner','ai_governance']`.

### 4.2 Risk classification & impact assessment

When a user with persona `ai_governance` triages (`status → in_review`), they set `ai_risk_tier` and `naic_materiality` with a written `risk_classification_rationale`. If `ai_risk_tier IN ('limited','high')`, an `intake_impact_assessment` row becomes required and `required_roles` on the open approval request expand:

| Risk tier | Required roles |
|---|---|
| `unacceptable` | rejected at triage; status → `rejected`; no plan rows generated |
| `high` | business_owner, compliance, legal, model_risk, ai_governance |
| `limited` | business_owner, compliance, ai_governance |
| `minimal` | business_owner |

### 4.3 Approval

Each role in `required_roles` provides an `approval_signoff`. Request transitions to `approved` when every role has at least one `approved` signoff and no `rejected` signoff exists. A `rejected` signoff transitions immediately. On approval:

1. Intake status → `approved`.
2. `intake.approved_at` set.
3. **Artifact plan auto-generation runs** (§ 3.6 / § 6).

### 4.4 Build

Engineers (persona `engineer`) realize plan rows via the Studio "Realize" button → pre-filled registry create form → plan row `status → realized`, `intake_entity_link` auto-created. Engineers may also create entities outside the plan and link them manually.

### 4.5 Promotion gates

The lifecycle service gains a hook before any candidate→staging→shadow→champion promotion of a *linked* entity:

```
For each agent_version / task_version / prompt_version being promoted:
    1. Find every intake_entity_link pointing at this entity.
    2. For each linked intake:
         - assert status IN ('approved','in_build','live')
         - assert there is no open approval_request of kind 'intake' or 'risk_reclassification'
    3. If risk tier is 'high' AND target state is 'champion':
         require an approval_request of kind 'promote_champion' in 'approved' status,
         opened against this specific (entity_type, entity_id).
    4. All linked intake_requirements with kind ∈ ('functional','compliance') must be
       in status ∈ ('verified','approved').  Soft warning if 'approved' but not 'verified'.
```

Promotion failures return 409 with the failing condition, same shape as today's draft-edit conflicts.

**Unlinked entities skip the gate.** This preserves backward compat for existing seed data and lets internal/utility agents operate without an intake. A dashboard counter for "unlinked entities" is shown to keep this visible.

### 4.6 Retirement

`status → retired` lists all linked `intake_entity_link` rows. The system proposes deprecation of any entity *only* linked to this intake. Confirmation finalizes deprecation. Phase B feature.

---

## 5. Personas and role-actions matrix

A persona is the role a Studio user is currently acting as. For the demo there is no real auth — the persona is a session-scoped value the user selects from a switcher in the nav. Every write captures `acting_as_role` so the audit trail records *who acted in what capacity*, even though the underlying identity is free text.

### 5.1 Persona switcher

A pill in the top nav showing the current persona. Click → dropdown of all 10 `studio_role` values. Selection updates a session cookie `verity_studio_persona`. The current persona is also rendered as an avatar/initials icon next to the pill.

When a user signs off on an approval, the system enforces `acting_as_role == signoff.role` — i.e. you must *be* model_risk to sign off as model_risk. SoD enforcement (§ 5.3) further restricts who can do what.

### 5.2 Role × action matrix

✓ = allowed; — = not allowed; ◯ = allowed but with a warning badge (SoD violation).

| Action | business_owner | compliance | legal | model_risk | ai_governance | security | privacy | engineer | auditor | viewer |
|---|---|---|---|---|---|---|---|---|---|---|
| **Create intake** | ✓ | — | — | — | ✓ | — | — | — | — | — |
| **Edit intake (own)** | ✓ | — | — | — | ✓ | — | — | — | — | — |
| **Triage intake (set risk tier)** | — | — | — | — | ✓ | — | — | — | — | — |
| **Reclassify risk tier** | — | suggest | suggest | suggest | ✓ | — | — | — | — | — |
| **Create / edit requirements** | ✓ | suggest | — | — | ✓ | — | — | ✓ (linked) | — | — |
| **Edit impact assessment** | — | ✓ | — | ✓ | ✓ | ✓ | ✓ | — | — | — |
| **Sign off as own role** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | — | — |
| **Withdraw approval request** | opener | opener | opener | opener | ✓ | — | — | — | — | — |
| **Auto-generate artifact plan** | — | — | — | — | ✓ | — | — | — | — | — |
| **Edit artifact plan rows** | — | — | — | — | ✓ | — | — | ✓ | — | — |
| **Realize plan → registry draft** | — | — | — | — | — | — | — | ✓ | — | — |
| **Author / edit agent / task / prompt** | — | — | — | — | — | — | — | ✓ | — | — |
| **Promote registry artifact** | — | review | — | review | ✓ | — | — | — | — | — |
| **View intakes / requirements / plans** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Export YAML** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| **Import YAML** | — | — | — | — | ✓ | — | — | ✓ | — | — |
| **View compliance reports** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ | — |

`engineer (linked)` — engineers may edit only requirements that are linked to entities they are authoring.

### 5.3 Segregation of duties (SoD) warnings

The matrix above defines what each persona *can* do. SoD adds soft warnings (◯) on top:

- **Same person, multiple personas:** if user X creates an intake as `business_owner` then switches to `compliance` to sign off, the signoff is allowed but a warning badge "Signed off by intake creator" appears on the approvals tab.
- **Author = approver:** if the engineer who authored an entity is the same person as the approver of the related intake, a warning badge appears on the entity detail page.
- **Single-role coverage:** if a single user account has signed off in three or more required roles within 30 days, a SoD risk indicator surfaces in the governance dashboard.

For demo, warnings are visible but never block. Phase C (real auth) tightens these into hard blocks where appropriate.

### 5.4 Navigation tailoring

Studio nav adapts to current persona:

| Persona | Default landing page | Nav highlights |
|---|---|---|
| business_owner | "My Intakes" — list filtered to intakes where user is the owner | Intake list, my approvals to review |
| ai_governance | Governance dashboard — tier rollups, pending triage queue | All intakes, triage queue, plans, reports |
| compliance | Pending approvals queue + compliance reports | Approvals, reports, regulatory mapping |
| legal | Pending approvals queue (high-risk only) | Approvals, regulatory mapping |
| model_risk | Pending approvals queue + validation runs | Approvals, validation runs, model cards |
| engineer | Govern → registry list (existing studio default) | Registry, my plans to realize |
| auditor | Compliance dashboard, read-only | Reports, audit log |
| viewer | Intake list, read-only | Intake list |

Implementation: a small middleware reads the persona cookie, attaches `request.state.persona`, and templates use `{% if persona == 'engineer' %}` etc. for the nav block. No plumbing changes outside of the nav partial and the route guards.

### 5.5 Demo roleplay flow

For the CIO/CTO demo, a single laptop walks through:

1. **Sarah the underwriting director** (business_owner) submits an intake for "BOP eligibility classification." Risk tier draft = high.
2. Switch persona → **Marcus from AI Governance** (ai_governance) triages, confirms tier = high, opens impact assessment.
3. Switch → **Priya from Compliance** completes the impact assessment, signs off as compliance.
4. Switch → **David from Legal** signs off as legal. SoD warning fires because David is also the underwriting business contact (deliberate demo moment).
5. Switch → **Elena from Model Risk** signs off; intake → approved; artifact plan auto-generates 3 rows (1 agent, 2 tasks).
6. Switch → **Anil the engineer** realizes each plan row, building agents in the existing registry flow. Each draft is linked to the intake automatically.
7. Promotion attempt from candidate → champion fires the gate; the approval audit trail is shown.

The persona switcher makes this single-device demo credible without needing seven actual user accounts.

---

## 6. Artifact plan auto-generation (the "build a plan from intake" feature)

When an intake is approved, the system runs a deterministic plan-generation pass:

```
For each requirement R where kind = 'functional':
    Examine R.statement for action verbs and structural patterns:

    IF R contains "classify", "categorize", "label", "score" AND single-step:
        propose 1 task with capability_type='classification'

    ELIF R contains "extract", "parse", "pull fields":
        propose 1 task with capability_type='extraction'

    ELIF R contains "summarize", "summarise":
        propose 1 task with capability_type='summarisation'

    ELIF R contains "generate", "draft", "write" AND output is a document:
        propose 1 task with capability_type='generation'

    ELIF R contains multiple steps, tool calls, or "decide", "orchestrate":
        propose 1 agent (no capability_type — agents are goal-directed)

    ELIF R contains "match", "resolve", "deduplicate":
        propose 1 task with capability_type='matching'

    ELIF R contains "validate", "check", "verify":
        propose 1 task with capability_type='validation'

    ELSE:
        propose nothing — flag for human review

For each high-risk intake:
    propose 1 ground_truth_dataset for production validation
    propose 1 test_suite of integration tests
```

Plan rows are inserted with `auto_generated=true`, `status='proposed'`. The Studio plan tab shows them as a checklist; the engineer can edit, add, or remove freely before realizing any.

**Naming heuristic:** `{intake.code}-{slug-of-requirement-statement}` truncated to 60 chars. Engineers rename freely.

**Materiality default:** copied from intake risk tier — `high → high`, `limited → medium`, `minimal → low`. Engineer overrides as needed.

This is intentionally **rule-based**, not LLM-generated. The demo emphasis is "the platform reasons about your requirements deterministically and proposes a build skeleton." LLM-driven plan generation is a Phase C upgrade.

---

## 7. UI — Studio additions

A new top-level nav section: **Intake** (sits between "Govern" and "Validate"). All views server-rendered Jinja + HTMX.

| Route | Template | Purpose |
|---|---|---|
| `GET /studio/intake` | `studio/intake_list.html` | Table: code, title, owner, risk tier, status, # linked entities, # outstanding reqs |
| `GET /studio/intake/new` | `studio/intake_new.html` | Intake form |
| `GET /studio/intake/{code}` | `studio/intake_detail.html` | Tabs: Overview · Requirements · Plan · Linked Entities · Impact Assessment · Approvals · History |
| `GET /studio/intake/{code}/requirements` | `studio/intake_requirements.html` | Requirement tree + add/edit (with redundancy-check HTMX) |
| `GET /studio/intake/{code}/plan` | `studio/intake_plan.html` | Plan rows with Realize buttons |
| `GET /studio/intake/{code}/coverage` | `studio/intake_coverage.html` | Matrix: requirements × entities |
| `GET /studio/intake/{code}/impact` | `studio/intake_impact.html` | Impact assessment form |
| `GET /studio/intake/{code}/approvals` | `studio/intake_approvals.html` | Open requests + sign-off button per role |
| `GET /studio/governance/dashboard` | `studio/governance_dashboard.html` | Inventory by tier, status, gates, unlinked entities |
| `POST /studio/persona` | (HTMX fragment) | Persona switcher endpoint — sets cookie, returns updated nav |

The intake form is one screen (not a wizard) because intake users are business people — cognitive load matters more than form-validation purity. Required fields are marked, optional fields collapsed by default.

Partial `_partials/intake_badge.html` renders `{code, tier, status}` as a colored pill — reused on agent/task detail pages so any registry artifact viewer sees its parent intake at a glance.

Partial `_partials/persona_switcher.html` renders the nav pill; included in `_base.html`.

Partial `_partials/redundancy_hint.html` renders the top-N nearest existing requirements as the user types; fired by HTMX `hx-trigger="keyup changed delay:500ms"` against `POST /studio/intake/{code}/requirements/redundancy-check`.

---

## 8. JSON API surface (`/api/v1/governance/...`)

```
POST   /api/v1/governance/intake                  create intake
GET    /api/v1/governance/intake                  list (filter by status, tier, owner)
GET    /api/v1/governance/intake/{code}           full detail
PATCH  /api/v1/governance/intake/{code}           update mutable fields
POST   /api/v1/governance/intake/{code}/triage    risk classification + status transition
POST   /api/v1/governance/intake/{code}/retire    retirement workflow

POST   /api/v1/governance/intake/{code}/requirements
GET    /api/v1/governance/intake/{code}/requirements
PATCH  /api/v1/governance/intake/{code}/requirements/{req_code}
POST   /api/v1/governance/intake/{code}/requirements/redundancy-check  -- semantic search

POST   /api/v1/governance/intake/{code}/links     create entity link
DELETE /api/v1/governance/intake/{code}/links/{link_id}
GET    /api/v1/governance/intake/{code}/coverage  coverage matrix as JSON

POST   /api/v1/governance/intake/{code}/impact    create/update impact assessment
GET    /api/v1/governance/intake/{code}/impact

POST   /api/v1/governance/intake/{code}/plan/generate     trigger auto-generation
GET    /api/v1/governance/intake/{code}/plan
PATCH  /api/v1/governance/intake/{code}/plan/{plan_id}
POST   /api/v1/governance/intake/{code}/plan/{plan_id}/realize  -- creates registry draft

POST   /api/v1/governance/intake/{code}/approvals open approval request
GET    /api/v1/governance/intake/{code}/approvals
POST   /api/v1/governance/approvals/{request_id}/signoff  add a sign-off

GET    /api/v1/governance/dashboard               tier/status rollups
```

YAML import/export under `verity/src/verity/governance/yaml_io/intake.py` — each intake + children round-trips as a YAML document.

---

## 9. Compliance bridge

```sql
CREATE TABLE governance.intake_canonical_link (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id                   UUID NOT NULL REFERENCES governance.intake(id) ON DELETE CASCADE,
    canonical_requirement_id    UUID NOT NULL,                       -- FK to compliance.canonical_requirement
    relevance                   VARCHAR(20) NOT NULL DEFAULT 'applies',   -- 'applies' | 'informs' | 'satisfies'
    rationale                   TEXT,
    created_by                  VARCHAR(200) NOT NULL,
    acting_as_role              governance.studio_role,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (intake_id, canonical_requirement_id)
);
```

A regulator's question "show every place NAIC §3.1 applies" is answered by joining `regulatory_provision → provision_requirement_map → canonical_requirement → intake_canonical_link → intake`.

### How intake reports compose (Phase B revised — 2026-05-06)

After auditing the existing reporting framework before starting Phase B, two facts changed the plan:

1. **The compliance metamodel is already comprehensively seeded.** 5 frameworks (NAIC AI Bulletin, NAIC Eval Tool, SR 11-7, CO SB21-169, ORSA/ASOP/CAS), 48 regulatory provisions, 15 themes, **37 canonical_requirements**, 51 provision↔requirement mappings, 126 requirement↔feature links, 5 working `report_definition` rows. Intake doesn't need a new framework slice — it links into the existing graph via `intake_canonical_link`.
2. **The 5 existing reports compose directly from L1 via `analytics.v_*` views, not from `fact_*` tables.** The `analytics.fact_*` / `analytics.dim_*` mart layer is *architecturally specified* in [compliance-stack.md](compliance-stack.md) but is not built yet. Phase B follows the same composer-from-views pattern as the existing reports — building L2 fact tables is a separate, broader phase that touches all reports at once.

**So Phase B does NOT add `fact_intake` / `fact_approval` / `dim_intake` / `dim_risk_tier`.** Those move out of Phase B and into the future "L2 mart build-out" phase that will give every report point-in-time history. For now, intake reports read from L1 the same way Decision Audit Trail reads from `v_decision`.

**What Phase B does add to the compliance/reporting layer:**

- Three new views (or table) views over governance.intake* tables: `analytics.v_intake`, `analytics.v_intake_requirement`, `analytics.v_intake_approval`. Same shape contract as the existing `v_decision`, `v_lifecycle_event`, etc.
- mart_field rows registering each new column (in `compliance_seed_reports.yaml`).
- Three new `report_definition` rows (in same YAML), three new `compose_*` functions (in `composers.py`), three new `.docx` template authors (in `_template_authoring.py`) — **`.docx` Word output via the existing rendering engine. Do not introduce a separate PDF renderer.**

The bridge to canonical_requirements:

- `intake_canonical_link` is the only new governance table.
- Joining `regulatory_provision → provision_requirement_map → canonical_requirement → intake_canonical_link → intake` answers the regulator's "show every intake subject to SR 11-7 §I" question without any new SQL — the existing graph queries extend naturally.
- For each new intake, the system embeds `(title || problem_statement || risk_classification_rationale)` and surfaces the top-5 nearest `canonical_requirement.embedding` rows above a threshold as **suggested** links on the intake's Compliance tab. AI Governance accepts/rejects manually. Same threshold and BGE-small embedding model as `intake_requirement` (§ 3.5).

---

## 10. Phasing

### Phase A — SHIPPED (2026-05-06)

All Phase A items below landed and were verified end-to-end against the running container with the seeded `uw-bop-eligibility` intake. File paths point at the actual implementation.

- [x] **Schema** — 11 enums + 7 tables ([schema_intake.sql](../../verity/src/verity/db/schema_intake.sql)), wired into [migrate.py](../../verity/src/verity/db/migrate.py). `entity_type` enum extended with `test_suite`, `ground_truth_dataset`. `intake_requirement` carries `embedding vector(384)` + `embedding_model_id` FK to `compliance.embedding_config` + `embedding_input_hash` (SHA-256 staleness sentinel) + IVFFlat cosine index.
- [x] **Pydantic models** — [models/intake.py](../../verity/src/verity/models/intake.py) — every enum mirrored as Python `Enum`; `REQUIRED_ROLES_BY_RISK_TIER` policy table centralised here so service + API agree without copy-paste.
- [x] **SQL queries** — [db/queries/intake.sql](../../verity/src/verity/db/queries/intake.sql) — 46 named queries.
- [x] **`IntakeService`** — [governance/intake.py](../../verity/src/verity/governance/intake.py) — full CRUD; embedding via `fastembed` (BGE-small, 384 dim; lazy-imported); redundancy search; signoff workflow with auto plan-trigger on `kind=intake` approval; `check_promotion_gate(entity_type, entity_id, target_state) → PromotionGateResult`. Wired onto the SDK as `verity.intake`.
- [x] **Plan generator** — [governance/plan_generator.py](../../verity/src/verity/governance/plan_generator.py) — deterministic action-verb regex rules; auto-runs *after* the intake-approval transaction commits; high-risk intakes also seed a `ground_truth_dataset` + `test_suite` plan row.
- [x] **Promotion gate hook** — [governance/lifecycle.py:240](../../verity/src/verity/governance/lifecycle.py) — `_check_intake_gate` runs between the existing gate-requirement check and the state update. Unlinked entities pass through (backward compat).
- [x] **Persona middleware** — [web/middleware/persona.py](../../verity/src/verity/web/middleware/persona.py) — `vty_persona` cookie, full action × role matrix (17 actions × 10 roles), `is_action_allowed`, `actions_allowed_for`, `role_action_matrix`, plus `ACTION_LABELS` and `ROLE_DESCRIPTIONS` for the profile page. Mounted on **both** Admin and Studio sub-apps so `request.state.persona` is consistent across the whole product.
- [x] **JSON API** — [web/api/intake.py](../../verity/src/verity/web/api/intake.py) — 23 routes under `/api/v1/governance/...` (intake CRUD, requirements + redundancy-check, links, impact, plan + generate + realize, approvals + signoff, dashboard). Wired into `build_api_router`.
- [x] **Studio routes** — [web/studio_intake_routes.py](../../verity/src/verity/web/studio_intake_routes.py) — 12 routes including the persona switcher and the governance dashboard.
- [x] **Studio templates** — `templates/studio/intake_list.html`, `intake_new.html`, `intake_detail.html` (six tabs: overview, requirements, plan, linked, impact, approvals), `governance_dashboard.html`. Three partials: `_partials/intake_badge.html`, `_partials/redundancy_hint.html`, and the shared (Admin + Studio) `_partials/persona_indicator.html`.
- [x] **Studio nav update** — Intake added as the **first** mode in `studio/_base.html`'s rail (`⊕` icon).
- [x] **Admin nav update** — Intake link added at the top of the Admin sidebar's STUDIO section ([base.html](../../verity/src/verity/web/templates/base.html)). The placeholder 👤 emoji (which rendered purple due to platform emoji rendering and ignored CSS color) replaced with `@` glyph linking to `/admin/profile`.
- [x] **Profile page** — [/admin/profile](../../verity/src/verity/web/routes.py:285) + [profile.html](../../verity/src/verity/web/templates/profile.html). Identity card; active-role card with role pill, description, and an `(i)` info button; capability list (✓ Allowed / — Not allowed) for the current role; persona switcher dropdown. The single source of truth for changing role — sidebar pills are display-only.
- [x] **Role-help modal** — native `<dialog>` opened by the `(i)` button on the profile page; renders the role definitions and the full action × role matrix from `role_action_matrix()` (single source of truth).
- [x] **YAML I/O** — [governance/yaml_io/intake.py](../../verity/src/verity/governance/yaml_io/intake.py) — `apiVersion: verity.intake/v1` round-trip including requirements, impact assessment, plan rows, links, and approval history.
- [x] **Seed** — [setup/seed_intake_example.py](../../verity/src/verity/setup/seed_intake_example.py) — `uw-bop-eligibility` (high-risk, 5 requirements with embeddings, completed impact assessment, 5 signoffs across all required roles → status `approved`, 4 plan rows auto-generated). Idempotent.
- [x] **End-to-end smoke tests** — verified: seed runs clean, JSON API list/detail/dashboard, Studio list/detail/governance-dashboard render, persona cookie set + redirect picks it up, redundancy hint surfaces near-duplicates, YAML export round-trips, promotion gate fires on linked + high-risk + target-champion (with clear reason) and passes on linked + target-staging.

**Bugs found and fixed during smoke testing** (recorded for the post-mortem and as a guardrail for similar work in Phase B):

1. `tx.execute(raw_sql, params)` doesn't dispatch raw SQL — it requires a named query. Fixed by adding the `update_approval_request_required_roles` named query.
2. Postgres parameter type ambiguity in `update_approval_request_status`: the same `%(status)s` appeared in both an assignment (where it's `varchar`) and a CASE WHEN comparison (where it's `text`). Fixed with explicit `::varchar` casts on each occurrence.
3. Same class of ambiguity in `search_similar_requirements`: `%(exclude_id)s::uuid IS NULL` is needed because Postgres can't deduce the type of a parameter that only appears alongside literals. Fixed with explicit `::uuid` casts.
4. The default redundancy-check cosine threshold of 0.85 was empirically too tight for BGE-small in this domain — a genuine paraphrase scored 0.844. Lowered to 0.78 (recorded with rationale comment in `IntakeService.search_similar_requirements`).
5. The placeholder 👤 emoji in the Admin sidebar rendered as colour-emoji (purple/blue) on most platforms regardless of CSS `color`. Replaced with `@` (plain ASCII; consistent monochrome rendering) and made it an active link to `/admin/profile`.
6. Migration auto-applied via the running container's startup hook on first volume-mount detection — schema landed before I asked the migrator to run it. Worth knowing for Phase B; the same will happen with new schema files.

**Deviations from the v2 design contract** (all aligned with explicit user requests during Phase A):

- v2 said the persona switcher would live in the sidebar as a dropdown; the as-built design has the switcher only on the profile page, with sidebar showing a display-only "Acting as · ROLE" indicator. This collapses the two switching surfaces into one source of truth. Same partial (`_partials/persona_indicator.html`) is used in both Admin and Studio sidebars.
- v2 mentioned an SoD warning badge on the approvals tab when `created_by == approver_email`; that visualisation is not yet implemented (low priority for Phase A; tracked as an item in Phase C alongside real auth + hard-block SoD).
- v2 listed "Integration tests" as the final Phase A item (item 13). The smoke tests landed (script + curl-based end-to-end verification) but the formal `pytest` integration test files are deferred to early Phase B so we can land them once with both the intake and compliance-bridge fixtures.

### Phase B — compliance reporting & metamodel bridge

The goal of Phase B: turn the intake registry into auditor-ready evidence by hooking into the **already-seeded compliance metamodel** (5 frameworks, 37 canonical_requirements, 15 themes, 5 working `.docx` reports). The principle: **don't reinvent the wheel** — extend the existing reporting framework rather than building a parallel one.

Confirmed in 2026-05-06 review:
- **Comprehensive coverage** — link intakes into the existing 37 canonical_requirements; do not seed a new "intake-specific" slice.
- **Reporting format** — `.docx` Word documents, via the existing rendering engine ([reporting/engine.py](../../verity/src/verity/reporting/engine.py), [composers.py](../../verity/src/verity/reporting/composers.py), [_template_authoring.py](../../verity/src/verity/reporting/_template_authoring.py)). No PDF library, no WeasyPrint.
- **Generate-from-entity pattern** — same as Decision Audit Trail's button on `decision_detail.html`: a simple POST form on `intake_detail.html` to the existing `/admin/compliance/reports/{code}/generate` endpoint, with `intake_code` as a scope param.
- **No fact_/dim_ tables in Phase B** — the existing 5 reports already compose directly from `analytics.v_*` views over L1. Building the L2 mart is a separate, broader phase that touches every report at once. Out of scope here.

#### B.1 Schema (minimal — one new table + three views)

- [ ] **`governance.intake_canonical_link`** — the bridge to `compliance.canonical_requirement` (column shape in § 9).
- [ ] **`analytics.v_intake`** — view over `governance.intake` exposing the columns reports need (code, title, ai_risk_tier, naic_materiality, business_owner_name, status, intake_at, approved_at, retired_at). Same shape contract as `v_decision`, `v_lifecycle_event`.
- [ ] **`analytics.v_intake_requirement`** — view over `governance.intake_requirement` joined to `governance.intake` for `intake_code`.
- [ ] **`analytics.v_intake_approval`** — view joining `governance.approval_request` × `governance.approval_signoff` with intake context. **One row per signoff** (per the resolved B-Q-1).
- [ ] **mart_field rows** registering each new view column — added to [compliance_seed_reports.yaml](../../verity/src/verity/setup/compliance_seed_reports.yaml). The integrity contract from [AD-CS-004](compliance-stack.md#ad-cs-004) requires every report-reachable column to be registered.

DDL lives in `schema_intake.sql` (the bridge table) and `schema_compliance_views.sql` (the views) so the existing migrator order applies them in the right place.

#### B.2 Canonical-requirement mapping

Reuses the existing 37 canonical_requirements. No new framework or provision seeding needed.

- [ ] **Seed `intake_canonical_link` for `uw-bop-eligibility`** — link the demo intake to the canonical_requirements it actually satisfies. Spot candidates: `model_inventory`, `governance_program`, `fairness`, `consumer_protection`, `data_inputs_governance`, `transparency_explainability`, `monitoring_drift`, `examination_readiness`. Final list confirmed by AI Governance during the demo authoring. Added to [seed_intake_example.py](../../verity/src/verity/setup/seed_intake_example.py).
- [ ] **Auto-suggest module** — `verity.governance.intake.IntakeService.suggest_canonical_links(intake_id)` embeds `(title || problem_statement || risk_classification_rationale)` and returns the top-5 nearest `canonical_requirement.embedding` rows ≥ 0.78. Mirrors the existing `search_similar_requirements` API.
- [ ] **Studio "Compliance" tab on intake detail** — shows linked canonical_requirements; below them, auto-suggested matches with "Accept" / "Reject" buttons. AI Governance owns this action; persona gate via a new `accept_canonical_suggestion` action.

#### B.3 Reports — three new `report_definition` rows in the existing module

Each report is **bake into the existing compliance module**: the YAML, composer, and `.docx` template all extend the existing files.

| Report code | Name | What it covers | Scope params |
|---|---|---|---|
| `intake_inventory` | Intake Inventory | Every approved/live intake. Maps to `model_inventory`, `governance_program` canonical_requirements. | optional date range, optional risk_tier filter |
| `approval_audit_log` | Approval Audit Log | Every signoff, intake-scoped or program-wide. Maps to `governance_program`, `examination_readiness`. | optional date range, optional intake_code |
| `intake_impact_assessment_register` | Impact Assessment Register | Every high-risk intake with full impact assessment. Maps to `consumer_protection`, `fairness`, `privacy_security`, `data_inputs_governance`. | optional date range, optional risk_tier filter (default `high`) |

For each report:
- [ ] Add the `report_definition` and its `report_requirement` mappings to [compliance_seed_reports.yaml](../../verity/src/verity/setup/compliance_seed_reports.yaml).
- [ ] Add a `compose_<code>(verity, scope)` function in [composers.py](../../verity/src/verity/reporting/composers.py) and register it in the `COMPOSERS` dict.
- [ ] Add an `author_<code>()` function in [_template_authoring.py](../../verity/src/verity/reporting/_template_authoring.py) and register it in the authors registry. Generates the `.docx` template programmatically — no manual Word editing.
- [ ] Run `verity compliance author-templates && verity compliance seed-reports` to land the new templates and DB rows.

Output formats inherited from existing convention

#### B.4 Studio UI

- [ ] **Per-intake "Generate report" buttons** — same pattern as [decision_detail.html](../../verity/src/verity/web/templates/decision_detail.html)'s in-context generate buttons. Add a button row to `intake_detail.html` overview tab that POSTs to `/admin/compliance/reports/{report_code}/generate` with `intake_code` as a hidden field. One button per applicable report (Inventory + Audit Log + Impact Register for high-risk; Inventory + Audit Log only for limited/minimal).
- [ ] **Auto-listing on `/admin/compliance/reports`** — the existing landing page reads `compliance.report_definition` and renders cards. Adding the new rows makes them appear automatically; no template change needed.
- [ ] **Studio governance dashboard tile** — small "Compliance reports" card linking to `/admin/compliance/reports`.

#### B.5 Tests

- [ ] **Pytest suite** for IntakeService — promotion gate, signoff rollup, plan generator, embedding round-trip, YAML round-trip, suggest_canonical_links. `verity/tests/integration/governance/test_intake.py`.
- [ ] **API endpoint tests** — happy path + 404/400/409 paths. `verity/tests/integration/api/test_intake_endpoints.py`.
- [ ] **Persona-gate tests** — restricted endpoints return 403 under wrong persona. `verity/tests/integration/web/test_persona_gate.py`.
- [ ] **Composer tests** — render each new composer against the seeded intake; assert the dataset shape conforms to `report_field_manifest`. `verity/tests/integration/reporting/test_intake_reports.py`.
- [ ] **End-to-end report-from-intake test** — POST to `/admin/compliance/reports/intake_inventory/generate` with `intake_code=uw-bop-eligibility`, assert the `.docx` blob in `report_run_log` is non-empty.

### Phase B exit criteria

1. The seeded `uw-bop-eligibility` intake is linked to ≥ 5 canonical_requirements across the existing 5 frameworks.
2. All three new reports render to `.docx` from the `/admin/compliance/reports` landing page with the seeded intake visible.
3. Clicking "Generate Intake Inventory" from the intake detail page produces a `.docx` for that intake (same generator path; same `report_run_log`).
4. The Compliance tab on the intake detail page surfaces auto-suggested canonical_requirement matches with accept/reject controls.
5. All pytest suites listed in B.5 pass — including the deferred Phase A integration tests landing alongside the Phase B ones.

Items deliberately deferred from Phase B (move to a future "L2 mart build-out" phase that touches all reports together):

- `analytics.fact_intake` / `fact_approval` / `dim_intake` / `dim_risk_tier` and the periodic publish job. Today's reports compose from L1 via views — adding fact tables for intake alone would create an inconsistency where some reports use L2 and others use L1. Better to do it once for everything.

### Phase C — full process closure (after Phase B)

Roughly unchanged from the v2 plan, but resequenced now that Phase A has shaped the priorities:

- [ ] **Real auth + RBAC** — replace the persona cookie with SSO (OIDC / SAML); bind roles to identities; promote SoD warnings to hard blocks (author = approver, single user across multiple required roles).
- [ ] **Recertification scheduling** — `next_recertification_due` already exists on `intake`; add a small task that flags due-soon intakes on the governance dashboard, plus an email/notification hook.
- [ ] **Vendor model risk** — `vendor_model` table for Anthropic and any other model providers; FK from `inference_config`; SR 11-7 §V evidence rows.
- [ ] **Incident & override → intake linkage** — close the loop from production runtime (HITL overrides, drift incidents) back to the intake that owns the affected agent.
- [ ] **Training & qualification records** — who is qualified to author/approve which class of intake; soft-blocks until met.
- [ ] **LLM-driven plan generation** — replace rule-based heuristics in `plan_generator.py` with a Claude call behind the same `generate_plan(intake_id)` interface. Cache + audit prompt input/output per the Verity execution engine contract.
- [ ] **SoD enforcement** — when real auth lands, promote § 5.3 warnings into hard blocks where appropriate.

---

## 11. Backward compatibility and risk

- **No existing tables modified.** Every change is additive.
- **`entity_type` enum extension is non-breaking** — adding values doesn't affect existing rows.
- **No existing entity requires an intake.** Promotion gate only activates when `intake_entity_link` rows exist.
- **Migration is forward-only.** New `schema_intake.sql` applied after main schema.
- **Studio nav.** One new top-level item; no existing route or template modified.

The only place this design touches existing code is the lifecycle promotion service (§ 4.5) — a single function call `IntakeService.check_promotion_gate(entity_type, entity_id, target_state)` returning `(allowed, reasons)`, with existing behavior preserved when no intakes are linked.

---

## 12. Open questions — Phase A resolutions

| Question (v2) | Resolution (v3) |
|---|---|
| **Plan auto-generation heuristics** — rule-based vs LLM-driven | Rule-based shipped in Phase A. Deterministic, no demo-day latency surprise. LLM-driven is a Phase C upgrade behind the same `generate_plan(intake_id)` interface. |
| **Persona scope** — keep all 10 roles or trim? | **Kept all 10.** Reduced breadth would make the role × action matrix less interesting in the help popup, and `security` / `privacy` already differ from `compliance` in the action matrix (e.g. they don't have `withdraw_approval`). |
| **Redundancy threshold** — `0.85` hint, `0.95` strong warning | **Lowered hint threshold to `0.78`.** Empirically tested with the seeded data: a genuine paraphrase of FR-1 scored 0.844 — just below the original 0.85 cutoff. 0.78 still rejects unrelated pairs (which sit < 0.7). The strong-warning band at 0.95 was not implemented in Phase A; surfacing it is a small UI follow-up. |
| **Plan realization audit** — capture engineer on plan or registry or both? | **Both.** The registry artifact's `developer_name` already records the engineer per existing convention; the plan row's `realized_entity_id` provides the back-link. |

---

## 13. Phase B kickoff — resolved decisions and execution order

All B-Q-* questions resolved by the user on 2026-05-06. Resolutions are baked into § 9 and § 10.B above; capturing them here for the historical record:

| ID | Decision (final) |
|---|---|
| **B-Q-1 — fact_approval granularity** | One row per **signoff**. Lets reports answer "every signoff by this approver" without aggregation. Reflected in `analytics.v_intake_approval` (B.1). |
| **B-Q-2 — framework scope** | **Comprehensive** — link into the existing 5 frameworks already seeded (NAIC AI Bulletin, NAIC Eval Tool, SR 11-7, CO SB21-169, ORSA/ASOP/CAS) and the existing 37 canonical_requirements covering 15 themes. **No new framework seeding** — the bridge connects intake to what's already there. |
| **B-Q-3 — auto-suggest canonical links** | Yes — embed intake text, search `canonical_requirement.embedding`, surface top-5 ≥ 0.78 as **suggestions**, never auto-link. Mirrors `search_similar_requirements`. |
| **B-Q-4 — mart population timing** | Confirmed — but **moot for Phase B**: no fact tables added. Future L2 build-out will use a CLI + dashboard "Refresh now" button per the resolved pattern. |
| **B-Q-5 — report rendering** | **`.docx` Word documents via the existing reporting framework.** No PDF library. Uses `_template_authoring.py` + `composers.py` + the `docx_template` column already on `report_definition`. |
| **B-Q-6 — sidebar placement** | Reports auto-listed under the existing **Compliance > Reports** page (no new top-level nav). PLUS: each intake detail page gets a "Generate compliance report" button row, mirroring the pattern on `decision_detail.html`. |

### Execution order (concrete, no ambiguity)

The order is structured so each step is independently testable and the demo's evidence path is buildable end-to-end early:

1. **Schema** — add `governance.intake_canonical_link` to `schema_intake.sql`. Add `analytics.v_intake`, `v_intake_requirement`, `v_intake_approval` to `schema_compliance_views.sql`. Restart container; verify migrations apply.
2. **mart_field registrations** — extend `compliance_seed_reports.yaml`'s `mart_fields` block with the new view columns. Re-run `verity compliance seed-reports`.
3. **Bridge model + service** — Pydantic model `IntakeCanonicalLink`, named queries (`insert_intake_canonical_link`, `list_canonical_links_for_intake`, `delete_intake_canonical_link`, `suggest_canonical_links_for_intake`), and `IntakeService` methods. New persona action `accept_canonical_suggestion` (allowed: `ai_governance`).
4. **Auto-suggest endpoint** — JSON API `POST /api/v1/governance/intake/{code}/canonical-suggestions` and Studio HTMX endpoint for the Compliance tab.
5. **Studio Compliance tab on intake_detail.html** — render linked + suggested canonical_requirements with accept/reject controls.
6. **Seed wiring** — extend `seed_intake_example.py` to add ≥ 5 `intake_canonical_link` rows for `uw-bop-eligibility`. Includes spot picks like `model_inventory`, `governance_program`, `fairness`, `consumer_protection`, `data_inputs_governance`, `transparency_explainability`.
7. **Report `intake_inventory`** — composer + `.docx` author + YAML entry. End-to-end test: render to `.docx` from `/admin/compliance/reports/intake_inventory/generate`.
8. **Report `approval_audit_log`** — composer + `.docx` author + YAML entry. Same end-to-end test.
9. **Report `intake_impact_assessment_register`** — composer + `.docx` author + YAML entry. Same end-to-end test.
10. **Generate-from-intake buttons** — add the button row to `intake_detail.html` overview tab; one button per applicable report; POSTs to existing generate endpoint with `intake_code` scope param.
11. **Pytest suites** — land all four (B.5).
12. **Smoke verification** — full demo path: intake → linked canonicals → "Generate Intake Inventory" → downloaded `.docx` opens in Word with the seeded intake's data populating the template.

### What I'd like a green light on before I start step 1

- The four-table-name additions (`intake_canonical_link`, `v_intake`, `v_intake_requirement`, `v_intake_approval`) — naming consistent with existing `v_decision`, `v_lifecycle_event`.
- The new persona action `accept_canonical_suggestion` (allowed: `ai_governance` only).
- The three new report codes: `intake_inventory`, `approval_audit_log`, `intake_impact_assessment_register`.
- The 5+ canonical_requirement codes to link from `uw-bop-eligibility` — I'll propose the exact list when I get to step 6 (depends on which canonicals are best-fit; happy to surface that for confirmation then).

---

## 14. Pointers (where things live)

For the next session: a single place to start reading.

| What | Where |
|---|---|
| Live design contract (this doc) | `docs/architecture/governance-intake.md` |
| Compliance-stack architecture (Phase B inputs) | `docs/architecture/compliance-stack.md` |
| Schema | `verity/src/verity/db/schema_intake.sql` |
| SQL queries | `verity/src/verity/db/queries/intake.sql` |
| Service | `verity/src/verity/governance/intake.py` |
| Plan generator | `verity/src/verity/governance/plan_generator.py` |
| YAML I/O | `verity/src/verity/governance/yaml_io/intake.py` |
| Pydantic models | `verity/src/verity/models/intake.py` |
| Persona middleware + matrix | `verity/src/verity/web/middleware/persona.py` |
| Studio routes | `verity/src/verity/web/studio_intake_routes.py` |
| Admin profile route | `verity/src/verity/web/routes.py` (search `# ── PROFILE`) |
| JSON API | `verity/src/verity/web/api/intake.py` |
| Studio templates | `verity/src/verity/web/templates/studio/intake_*.html` |
| Profile template | `verity/src/verity/web/templates/profile.html` |
| Persona indicator (shared) | `verity/src/verity/web/templates/_partials/persona_indicator.html` |
| Seed | `verity/src/verity/setup/seed_intake_example.py` |
| Existing compliance seed (frameworks, canonicals, reports) | `verity/src/verity/setup/compliance_seed_*.yaml`, `verity/src/verity/setup/seed_compliance.py` |
| Reporting engine (composers, .docx authors, runner) | `verity/src/verity/reporting/{engine,composers,_template_authoring,render}.py` |
| Existing report templates | `verity/src/verity/reporting/templates/*.docx` |
| Existing reports landing | `/admin/compliance/reports` (route in `web/routes.py`, template `templates/compliance_reports.html`) |
| Pattern to copy for "generate from entity" | `templates/decision_detail.html` (search `compliance/reports/decision_audit_trail/generate`) |
