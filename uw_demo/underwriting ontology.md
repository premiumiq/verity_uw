# General Liability Underwriting — A Complete Guide
## From Business Flow to Ontology to Data Model

> **Who this is for:** Someone building or working with an insurance underwriting platform who wants to understand *why* the system is designed the way it is, not just *what* it does. No insurance background assumed.

---

# CHAPTER I — The General Liability Business Flow (Pre-Policy)

## What Is General Liability Insurance?

Before diving into the process, let's understand what we're insuring.

**General Liability (GL) insurance** protects a business against claims that its operations, products, or employees caused **bodily injury or property damage to a third party** — someone who is not an employee of the business.

**Real-world examples:**
- A customer slips on a wet floor at a retail store and breaks their wrist → **Bodily Injury (BI)**
- A contractor accidentally breaks a water pipe while renovating an office, flooding the floor below → **Property Damage (PD)**
- A manufacturer sells a faulty product that injures a consumer → **Products Liability**
- A completed construction project has a roof that collapses a year later → **Completed Operations**

The **insurer** (AIG in our case) agrees to pay damages and legal costs if such claims arise — in exchange for a **premium** paid by the insured business.

---

## The Seven Stages of GL Pre-Policy

The journey from "a business wants insurance" to "a policy is issued" has seven stages. Each stage has a clear purpose, involves specific people and documents, and produces specific outputs.

```
BROKER                        UNDERWRITER                      SYSTEMS
  |                               |                               |
  |  1. SUBMISSION                |                               |
  |---[ACORD 125]---------------->|                               |
  |---[Loss Runs]---------------->|                               |
  |---[Supp Apps]---------------->|          [Ingestion + OCR]---->|
  |---[Risk Narrative]----------->|          [Fact Extraction]---->|
  |                               |                               |
  |  2. TRIAGE & APPETITE CHECK   |                               |
  |                               |--[Check SIC code]------------>|
  |                               |--[Check revenue band]-------->|
  |                               |--[Check geography]----------->|
  |                               |                               |
  |<--[Declination Letter]--------|  (if declined)                |
  |                               |  (if accepted → continue)     |
  |                               |                               |
  |  3. RISK EVALUATION           |                               |
  |<--[Request more info?]--------|                               |
  |---[Additional docs]---------->|                               |
  |                               |--[Analyze operations]-------->|
  |                               |--[Review loss history]------->|
  |                               |--[Identify hazards]---------->|
  |                               |--[Check subsidiaries]-------->|
  |                               |                               |
  |  4. PRICING & STRUCTURING     |                               |
  |                               |--[Apply base rates]---------->|
  |                               |--[Apply credits/debits]------>|
  |                               |--[Set limits/retentions]----->|
  |                               |--[Structure sublimits]------->|
  |                               |                               |
  |  5. QUOTE                     |                               |
  |<--[Formal Quote Letter]-------|                               |
  |                               |                               |
  |  6. BIND / ISSUE              |                               |
  |---[Bind Order]--------------->|                               |
  |                               |--[Issue Policy]-------------->|
  |<--[Policy Documents]----------|                               |
  |                               |                               |
  |  7. RENEWAL (next year)       |                               |
  |---[Updated info]------------->|          [Diff analysis]------>|
  |<--[Renewal Quote]-------------|                               |
```

---

## Stage 1 — Submission

### Who is involved?
- **Broker:** An intermediary who represents the insured business. They do not work for the insurance company. Their job is to find the best coverage at the best price for their client.
- **Insured:** The business seeking coverage (e.g., "Acme Construction LLC")
- **Underwriter (UW):** The insurance professional who evaluates and prices the risk

### What arrives?

A submission is a **package of documents** the broker sends to the insurer. Think of it as a job application — the insured is applying for insurance coverage.

| Document | What It Is | Why It Matters |
|---|---|---|
| **ACORD 125** | Standard insurance application form. Captures legal name, FEIN, address, operations, revenue, payroll, number of employees, prior coverage. | The primary structured data source. Every insurer uses the same form. |
| **ACORD 126 GL** | GL-specific supplement. Requested limits, deductible, prior GL coverage, specific GL exposures. | Captures what coverage the insured is asking for. |
| **Loss Runs** | 5-year claims history from prior carriers. Shows every claim: date, type, amount paid, amount reserved, open/closed status. | The most critical underwriting document. Past losses predict future losses. |
| **Supplemental Applications** | Additional questionnaires for specific industries or hazards. A contractor may fill out a separate form about subcontractor practices. | Fills gaps in the ACORD form for complex risks. |
| **Risk Narrative** | A letter from the broker explaining the account, its history, any unusual circumstances, and why it's a good risk. | Broker advocacy — provides context that forms cannot capture. |
| **Financial Statements** | Revenue, payroll, asset data. May be audited or broker-stated. | Used to verify exposure (what's being insured) and financial stability. |

### What does "submission" mean technically?
The submission creates a **container** in the system. Every document, every extracted fact, every decision that follows is linked to this submission ID. Nothing exists in isolation.

---

## Stage 2 — Triage & Appetite Check

### The Appetite Question

Before a UW spends hours evaluating a risk, someone must first answer: **"Do we even want to insure this type of business?"**

Every insurance company has an **underwriting appetite** — a defined set of business types, sizes, geographies, and risk characteristics they are willing to insure. This is not arbitrary. It reflects:
- The insurer's actuarial data and loss experience
- Reinsurance treaty constraints (what the reinsurer will accept)
- Regulatory requirements
- Competitive positioning

**Examples of appetite decisions:**
```
PREFERRED (we want this business):
  ✓ Office buildings, professional services, retail stores
  ✓ Established businesses (5+ years)
  ✓ Clean loss history

ACCEPTABLE (we'll consider it):
  ✓ Residential contractors with documented safety programs
  ✓ Restaurants (but not bars)
  ✓ Light manufacturing

RESTRICTED (refer to senior UW):
  ⚠ Roofing contractors
  ⚠ Bars and nightclubs
  ⚠ Businesses with significant prior losses

DECLINE (we will not insure this):
  ✗ Asbestos abatement
  ✗ Fireworks manufacturers
  ✗ Businesses with criminal convictions
```

### Triage checks

| Check | Question | Decision |
|---|---|---|
| **SIC/NAICS Code** | Is this industry class in our appetite? | Accept / Restrict / Decline |
| **Revenue Band** | Is the revenue within our size limits? | Accept / Refer |
| **Geography** | Do we write business in this state? | Accept / Decline |
| **Prior Carrier** | Did a reputable carrier insure this before? Non-renewal is a red flag. | Accept / Flag |
| **Years in Business** | Startups have no loss history — higher risk. | Accept with conditions / Decline |
| **Prior Losses** | Quick scan: did the loss runs arrive? Do they look catastrophic? | Accept / Refer |

### What happens at triage?

**If declined:** The broker receives a declination letter — often with no explanation (insurers are not required to explain declinations in most jurisdictions).

**If accepted:** The submission moves to Risk Evaluation. The clock starts — brokers and insureds often have a deadline for coverage.

---

## Stage 3 — Risk Evaluation

This is the core of underwriting. The UW's job is to **understand the risk deeply enough to price it accurately**.

### The Four Questions

#### 1. What does the insured DO?

"Operations" in insurance means the actual activities of the business — not just its legal description. Two companies can both say "general contractor" but have very different risk profiles:

```
Company A — "General Contractor"          Company B — "General Contractor"
  → Residential kitchen remodels             → Commercial high-rise construction
  → Avg project: $50K                        → Avg project: $5M
  → No subcontractors                        → 80% subcontracted labor
  → Work completed before occupancy          → Work on occupied buildings
  
VERY DIFFERENT RISK PROFILE
```

The UW maps operations to **ISO class codes** — standardized descriptions used across the industry for rating purposes. Each ISO code has a default exposure base (payroll, revenue, square footage) and a default hazard grade (A through E, with E being most hazardous).

#### 2. What could go wrong? (Hazard Identification)

The UW systematically identifies **exposures** — circumstances that could lead to a covered loss.

| Hazard Type | Example | GL Coverage Part Triggered |
|---|---|---|
| **Premises hazard** | Wet floors, uneven pavement, inadequate lighting | Bodily Injury |
| **Operations hazard** | Workers causing damage at a client site | Property Damage |
| **Products hazard** | A defective product injures a user | Products Liability |
| **Completed Operations hazard** | A completed building has a structural defect | Completed Operations |
| **Contractual hazard** | A contract requires the insured to cover the other party's liability | Contractual Liability |
| **Personal Injury hazard** | A business falsely advertises, defames a competitor | Personal & Advertising Injury |

#### 3. What HAS gone wrong? (Loss History)

Loss runs are studied in detail. The UW looks for:

```
5-Year Loss Run Analysis:

Year    Carrier    Claims    Paid        Reserved    Open?    Coverage Part
2019    Hartford   1         $8,200      $0          No       Property Damage
2020    Hartford   0         —           —           —        —
2021    Hartford   3         $142,000    $0          No       Bodily Injury (x2), PD
2022    Hartford   1         $0          $380,000    YES      Bodily Injury — OPEN CLAIM
2023    Travelers  2         $22,000     $45,000     1 open   Bodily Injury, PD
                   ----      ---------   ---------
TOTALS             7         $172,200    $425,000
                             ^^^^^^^^^^^ ^^^^^^^^^^^
                             Paid is real  Reserved is an ESTIMATE
                             money gone    could go up or down

KEY FLAGS:
⚠ 2022 open claim: $380,000 reserved — the actual cost is unknown
⚠ Frequency: 7 claims in 5 years for a small contractor is elevated
⚠ Severity trend: increasing ($8K → $142K → $380K open)
```

#### 4. Who else is on the risk?

Modern businesses have complex structures. The UW must identify:

- **Named Insured:** The legal entity on the policy
- **Additional Insureds:** Other parties who also receive coverage (landlords, general contractors requiring their subs to name them)
- **Subsidiaries:** Owned companies that may be included in or excluded from coverage
- **Employees vs. Subcontractors:** Subcontractors who are uninsured become the insured's liability

---

## Stage 4 — Pricing & Structuring

### Rating: How Premium is Calculated

GL premium is not pulled from a table. It is **calculated** from the ground up.

```
PREMIUM CALCULATION FLOW

Step 1: Exposure Base
        (What is being measured?)
        
        Payroll:  $2,400,000
        Revenue:  $8,500,000
        
Step 2: Base Rate
        (Rate per $1,000 of exposure, from ISO class code)
        
        ISO Class 91111 (Residential Contractor):
        Rate per $1,000 payroll = $4.85
        
        Base Premium = ($2,400,000 / 1,000) × $4.85 = $11,640

Step 3: Schedule Modifications
        (UW judgment adjustments — credits reduce premium, debits increase it)
        
        Safety program in place:          -10%  (-$1,164)
        Prior losses above average:       +15%  (+$1,746)
        Years in business (15 yrs):        -5%  (-$582)
        Single primary location:           -5%  (-$582)
        
        Modified Premium = $11,640 + $1,746 - $1,164 - $582 - $582 = $11,058

Step 4: Coverage Loads
        (Additional premium for specific coverages)
        
        Products & Completed Ops:         +$2,200
        Contractual Liability (blanket):  +$850
        
        Total Premium = $11,058 + $2,200 + $850 = $14,108

Step 5: Minimum Premium Check
        Minimum for this class: $5,000 ✓ (we're above minimum)
        
        FINAL PREMIUM: $14,108
```

### Coverage Structuring

The UW also decides the **shape** of the policy:

| Component | What It Means | Example |
|---|---|---|
| **Each Occurrence Limit** | Max payout for any single incident | $1,000,000 |
| **General Aggregate** | Max payout for all incidents in the policy year | $2,000,000 |
| **Products/Completed Ops Aggregate** | Separate aggregate for Products and Completed Ops claims | $2,000,000 |
| **Deductible** | Amount the insured pays before insurance kicks in | $2,500 per claim |
| **Self-Insured Retention (SIR)** | Like a deductible but insured also handles defense costs | $10,000 |

---

## Stage 5 — Quote

The formal quote is a **written indication** sent to the broker. It is not yet a binding commitment. The broker may:
- Accept it → proceed to bind
- Negotiate → request changes (different limits, lower premium)
- Decline it → the insured goes to another carrier
- Let it expire → quotes have expiration dates (typically 30-60 days)

The quote letter specifies:
- Premium
- Coverage structure (limits, deductible)
- Conditions (required endorsements, loss control requirements)
- Expiration of the quote

---

## Stage 6 — Bind / Issue

When the broker sends a **bind order**, they are instructing the insurer to activate coverage. This is the moment the insurer is legally on the risk.

```
Bind Order received at 2:00 PM
         |
         ▼
Coverage begins at 12:01 AM on effective date
(or immediately if retroactive)
         |
         ▼
Policy Admin System (PAS) generates:
  - Policy number
  - Policy documents
  - Certificates of Insurance
  - Endorsements
         |
         ▼
Documents delivered to broker → insured
```

**Key distinction:** A **binder** is temporary proof of coverage issued immediately. The **policy** is the full legal document, typically issued within 30 days of binding.

---

## Stage 7 — Renewal

At the end of the policy period (typically 12 months), the policy expires. The renewal process is essentially a repeat of stages 1–6 — but with one critical difference: **the UW now has a year of data to compare against.**

The renewal analysis answers:
- Did the insured's operations change?
- Did new locations or subsidiaries appear?
- Did their revenue or payroll grow significantly?
- How was the loss experience this year?
- Did they make any claims?
- Did they implement the safety improvements the UW required?

This is why the **Renewal Diff Engine** in the ontology is so important — it automates the change analysis that UWs used to do manually by comparing last year's file to this year's.

---

# CHAPTER II — Introduction to Ontology Concepts

## What Is an Ontology?

The word "ontology" comes from philosophy — it means the study of what *exists* and how things relate to each other. In computer science and data modeling, an ontology is a **formal representation of knowledge about a domain** — what things there are, what properties they have, and how they connect.

**The simplest way to think about it:** An ontology is a map of concepts and their relationships.

```
Plain English:         "An Account submits a Submission which contains Documents"

Ontology:              Account ──[submits]──> Submission ──[contains]──> Document
                          |                        |
                      [has]                    [produces]
                          |                        |
                       Location              ExtractedFact
```

### Why not just use a regular database?

A regular database answers: "What are the values in this table?"

An ontology additionally answers: "What do these values *mean*, where did they *come from*, and how do they *relate* to everything else?"

**Without ontology:**
```sql
SELECT revenue FROM account WHERE account_id = '123';
-- Returns: 5000000
-- You know the number. You don't know if it came from the broker, D&B, or Pitchbook.
-- You don't know if it conflicts with another source.
-- You don't know how confident the system is in this number.
```

**With ontology (via FactNode):**
```sql
SELECT resolved_value, source_document_id, confidence, extractor_id, resolution_status
FROM fact_node
WHERE entity_id = '123' AND fact_type = 'annual_revenue';

-- Returns: 
--   resolved_value: 5000000
--   source_document_id: [points to ACORD 125]
--   confidence: 0.92
--   extractor_id: 'claude-sonnet-4-6'
--   resolution_status: 'hitl_resolved'  ← a human confirmed this value
-- You know the number AND its full history.
```

---

## What Are Clusters?

In our ontology, a **cluster** is a logical grouping of related entities that together represent one major concept in the insurance domain.

Think of clusters like chapters in a book. Each chapter covers a distinct topic, but all chapters are part of the same story.

```
CLUSTER = a group of tables/entities that:
  (a) represent the same business concept
  (b) are primarily related to each other
  (c) have a clear, single responsibility

Example:

LOSS HISTORY CLUSTER:
  ┌─────────────────────────────────────────────────────────┐
  │                   LOSS HISTORY                          │
  │                                                         │
  │  LossRun ──────> ClaimEvent ──────> ClaimDevelopment   │
  │      |               |                                  │
  │      └──> Occurrence  └──> (gl_coverage_part enum)      │
  │                                                         │
  │  Everything about claims lives here.                    │
  │  Nothing about policies or pricing lives here.          │
  └─────────────────────────────────────────────────────────┘
```

**Why cluster instead of one big model?**

Because it mirrors how insurance professionals think. A claims analyst thinks in "Loss History" terms. An underwriter thinks in "Risk Profile" terms. A billing system thinks in "Coverage" terms. Clusters map the data model to human mental models — which makes LLM queries more natural.

---

## The Three Governing Principles

These are not just design preferences. They are the philosophical foundation that every decision in the model traces back to.

### Principle 1 — Every Fact Has Provenance

**Provenance** means: *where did this fact come from, and how much do we trust it?*

In insurance, the same fact (say, annual revenue) can arrive from multiple sources with different values:

```
Source 1 — ACORD 125 (broker-stated):   $5,000,000
Source 2 — D&B (independently verified): $3,800,000
Source 3 — Pitchbook (financial data):   $4,100,000

Which one is right?  ← This is the provenance problem.
```

**The FactNode pattern** solves this by attaching metadata to every fact:

```
FactNode for "annual_revenue" of Account 'Acme Construction':

  raw_value:          "$5,000,000"
  normalized_value:   5000000.00
  source_document:    → [ACORD 125, Page 2, Field Q56]
  confidence:         0.89  ← LLM extracted this, 89% confident
  extractor_id:       "claude-sonnet-4-6"
  extracted_at:       2024-03-15 09:23:11
  resolution_status:  "hitl_resolved"  ← A UW reviewed the conflict
  resolved_by:        → [UW Sarah Johnson]
  resolved_at:        2024-03-15 14:45:00
```

**Why this matters:** In a regulatory audit, you can prove exactly what information was used to price a policy and who made every decision. In a dispute, you can show that the insured declared $5M revenue on their application.

### Principle 2 — The Ontology Is the Semantic Layer, Not the Data Store

This is a subtle but important distinction.

```
DATA STORE:    Where data physically lives
               (PostgreSQL tables, S3 files, the PAS system)

SEMANTIC LAYER: What the data MEANS and how concepts RELATE
                (The ontology)
```

**Analogy:** Think of a library. The books are the data store — the physical objects containing information. The card catalog (or Dewey Decimal System) is the semantic layer — it tells you what subjects exist, how they relate (Philosophy → Ethics → Applied Ethics), and where to find each one.

In our system:
- The raw PDF loss run lives in S3 → **data store**
- The extracted claim amounts with provenance → **ontology layer (FactNode)**
- The relationship "this claim belongs to this account which has this ISO class" → **ontology layer (graph relationships)**

The ontology doesn't replace the database — it **sits above it** and provides meaning.

### Principle 3 — Designed for LLM Traversal

A traditional database is queried with SQL. You must know exactly what tables to join and what columns to filter on. You write machine instructions.

An ontology-backed system can be queried in **natural language** — because the relationships between entities are explicit enough that an LLM can traverse them:

```
Natural language query:
"What GL claims does this insured have involving products liability
 in the last 5 years, and what were the outcomes?"

How the LLM traverses the ontology:
  1. Find the Account for this insured
  2. Find all LossRuns linked to this Account
  3. Filter ClaimEvents where gl_coverage_part = 'products_liability'
  4. Filter where date_of_loss > (today - 5 years)
  5. For each claim, get paid_amount, reserved_amount, claim_status
  6. Look up ClaimDevelopment to find if reserves changed significantly
  7. Compose a human-readable answer

The ontology makes step 3-6 possible because the relationships
are NAMED and TYPED — not just foreign keys.
```

**Why this matters for insurance:** UWs do not want to write SQL. They want to ask questions the way they think. An ontology-backed AI assistant can answer questions like:
- "Are there any open claims above $100K for accounts renewing in the next 30 days?"
- "Which accounts in our portfolio have new Products Liability claims since their last renewal?"
- "What is the loss ratio trend for restaurant accounts in California?"

---

## The Modeling Process — How We Got Here

### Step 1: Start with Business Process

Before modeling a single entity, you ask: *what does a human actually do?*

```
A UW opens a submission. They:
  1. Look at what kind of business this is  →  ACCOUNT cluster
  2. Check what documents arrived            →  SUBMISSION cluster
  3. Review what the business does           →  ACCOUNT (operations)
  4. Look at their loss history              →  LOSS HISTORY cluster
  5. Check appetite guidelines               →  RISK PROFILE cluster
  6. Price the risk                          →  COVERAGE + PRICING clusters
  7. Make a decision                         →  UW DECISION cluster
```

Each step the UW performs corresponds to a cluster in the ontology. The data model follows the workflow, not the other way around.

### Step 2: Identify Entities

Within each cluster, identify the **things** that exist:

```
In LOSS HISTORY:
  - A loss run (document from a carrier listing claims)  → LossRun entity
  - An individual claim                                  → ClaimEvent entity
  - Multiple claimants on one incident                   → Occurrence entity
  - How a claim's reserve changes over time              → ClaimDevelopment entity
  - Aggregate patterns across years                      → LossTrend entity
```

### Step 3: Define Relationships

Relationships are as important as entities. In an ontology, relationships have **names** (verbs):

```
Account    ──[has]──────────────> Location
Account    ──[submits]──────────> Submission
Submission ──[contains]─────────> Document
Document   ──[produces]─────────> ExtractedFact
ExtractedFact ──[resolves to]──> FactNode
LossRun    ──[has]──────────────> ClaimEvent
ClaimEvent ──[belongs to]───────> Occurrence
Occurrence ──[occurred at]──────> Location
Occurrence ──[attributed to]────> OperationClass
```

Notice that relationships are directional and named. This is what makes natural language queries possible.

### Step 4: Apply Governing Principles

For every entity, ask:
- Does this fact need provenance? (attach `source_fact_ids` and link to FactNode)
- Is this append-only or updatable? (determines whether an audit trigger is needed)
- Can an LLM traverse this relationship by name? (make sure relationship names are explicit)

### Design Patterns Used

| Pattern | What It Is | Where Used |
|---|---|---|
| **Append-Only** | Records are never updated; new versions create new rows | ExtractedFact, FactNode, ClaimDevelopment |
| **Effective Dating** | `effective_from` / `effective_to` columns track validity periods | EntityHierarchy, AccountTerm |
| **Polymorphic FK** | `entity_type` + `entity_id` to reference any table from one place | FactNode (universal provenance) |
| **Snapshot + Diff** | Full copy of state at a point in time, then compare two snapshots | AccountTermSnapshot + TermDiffReport |
| **Rule-Driven Config** | Thresholds and routing logic in data tables, not code | DiffThresholdRule, ConflictDetectionRule |
| **HITL Queue** | AI makes a recommendation; human makes the final call | HITLReviewQueue |

---

# CHAPTER III — The Nine Clusters

## Overview: How the Clusters Relate

The nine clusters are not independent — they form a **dependency graph** where some clusters provide the foundation that others build upon.

```
DEPENDENCY FLOW (read arrows as "depends on" or "feeds into")

                        ┌─────────────────┐
                        │   PARTICIPANTS  │ (8)
                        │  Brokers, UWs   │
                        └────────┬────────┘
                                 │ performs
                                 ▼
┌──────────────┐    contains   ┌─────────────────┐    yields    ┌──────────────────┐
│   ACCOUNT    │──────────────>│   SUBMISSION    │─────────────>│  RISK PROFILE    │
│ (1)          │               │ (2)             │              │  (3)             │
│ Who is the   │               │ What arrived    │              │  What's the risk │
│ insured?     │               │ from the broker │              │  level?          │
└──────┬───────┘               └────────┬────────┘              └────────┬─────────┘
       │                                │                                 │
       │ has                            │ extracts                        │ informs
       │                                ▼                                 │
       │                       ┌─────────────────┐                       │
       │                       │   PROVENANCE    │ (9)                   │
       │                       │  FactNode wraps │<──────────────────────┘
       │                       │  every fact     │
       │                       └─────────────────┘
       │
       │ has history
       ▼
┌──────────────┐              ┌─────────────────┐    shapes    ┌──────────────────┐
│ LOSS HISTORY │─────────────>│  UW DECISION    │────────────>│    COVERAGE      │
│ (4)          │  informs     │  (6)            │             │    (5)           │
│ Prior claims │              │  Triage, quote, │             │  Policy limits,  │
│ and trends   │              │  bind, decline  │             │  endorsements    │
└──────────────┘              └────────┬────────┘             └──────────────────┘
                                       │ enriched by
                                       ▼
                              ┌─────────────────┐
                              │  EXTERNAL DATA  │ (7)
                              │  D&B, OSHA,     │
                              │  Pitchbook      │
                              └─────────────────┘
```

The **Provenance cluster (9)** is special — it doesn't sit in the flow. It wraps **every other cluster** as a cross-cutting concern. Every fact in every cluster traces back to a FactNode.

---

## Cluster 1 — Account

*Refer to the Account + Operations Cluster diagram.*

### Business Concept

The **Account** is the insured business. It is the root of everything. Before you can evaluate a risk, price a policy, or process a claim, you need to know: **who is the insured?**

In insurance, "who is the insured" is more complicated than it sounds. A business is rarely a single clean entity:

```
EXAMPLE: Acme Group Holdings LLC (the named insured)

Corporate Structure:
  Acme Group Holdings LLC          ← Named Insured (on the policy)
    ├── Acme Construction LLC      ← Subsidiary (included in policy)
    ├── Acme Property Management   ← Subsidiary (included in policy)
    └── Acme Investments LLC       ← Subsidiary (EXCLUDED from policy)
    
The UW must decide: which entities are covered?
This drives the "Additional Insureds" list on the policy.
```

The Account cluster handles this complexity through the **EntityHierarchy** table — a self-referential tree where each node has an `include_in_policy` flag.

### Key Entities

| Entity | Business Meaning | Key Fields to Know |
|---|---|---|
| **account** | One legal entity. Root of everything. | `legal_name`, `fein` (Federal EIN), `primary_sic_code` |
| **entity_hierarchy** | The corporate tree — parent/child relationships between accounts | `relationship_type`, `include_in_policy`, `ownership_pct`, `effective_from/to` |
| **location** | Every physical address where the insured operates | `location_type` (headquarters/branch/jobsite), `premises_sqft`, `territory_code` |
| **account_financials** | Revenue, payroll, employees — versioned by fiscal year and source | `annual_revenue`, `total_payroll`, `source` (who reported this number) |
| **account_term** | One row per policy year per LOB — the versioned anchor | `effective_date`, `expiry_date`, `prior_term_id` (chain for renewals) |
| **account_term_snapshot** | Full copy of account state at term start — feeds renewal diff | `entity_hierarchy`, `locations`, `financials` — all as JSON snapshots |

### Why `account_financials` Has Multiple Rows Per Year

The same revenue figure is often reported by multiple sources with different values. The system stores all of them — each with its `source` — and uses the Provenance cluster to determine which is authoritative.

```
account_financials for Acme Construction, Fiscal Year 2023:

Row 1: annual_revenue = $8,500,000  source = 'broker_stated'  (from ACORD 125)
Row 2: annual_revenue = $6,200,000  source = 'DB'             (D&B verified)
Row 3: annual_revenue = $7,100,000  source = 'FactSet'        (FactSet data)

Conflict: $8.5M vs $6.2M vs $7.1M — 37% spread.
→ ConflictRecord created, priority = HIGH (revenue drives premium)
→ Routed to HITL queue for UW resolution
→ UW reviews and selects D&B figure ($6.2M) as most reliable
→ FactNode created: resolved_value = 6200000, resolution_status = 'hitl_resolved'
```

### The Renewal Diff Chain

The `prior_term_id` on `account_term` creates a linked list through time:

```
2022 Term ──[prior_term_id]──> 2021 Term ──[prior_term_id]──> 2020 Term

Each term has a snapshot. The diff engine compares adjacent snapshots:
  2023 Snapshot vs 2022 Snapshot → TermDiffReport → UWSignalQueue
```

---

## Cluster 2 — Submission

*Refer to the Submission + ExtractedFact diagram.*

### Business Concept

The Submission is the **entry point for all information**. Everything the insurer knows about an account during underwriting came through a submission. The submission cluster's job is to:

1. **Receive** documents of different types (ACORD 125, loss runs, broker email, supplementals)
2. **Parse** each document into structured facts with field-level provenance
3. **Detect conflicts** when the same fact appears in multiple sources with different values
4. **Route conflicts** to HITL review with enough context for the UW to resolve
5. **Stamp resolved facts** as authoritative, feeding downstream clusters (Risk Profile, Loss History, Coverage)
6. **Track GL-specific coverage structures** (Products/Completed Ops, Contractual Liability) from the moment they first appear in any document

### The Information Flow Within Submission

```
Documents arrive
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  DOCUMENT PROCESSING PIPELINE                               │
│                                                             │
│  Document (ACORD_125)                                       │
│       │                                                     │
│       ├──[OCR + Parse]──> Raw text extracted                │
│       │                                                     │
│       ├──[LLM Extract]──> ExtractedFact (named_insured)     │
│       │                   ExtractedFact (annual_revenue)    │
│       │                   ExtractedFact (sic_code)          │
│       │                   ExtractedFact (gl_occ_limit_req)  │
│       │                   ...                               │
│       │                                                     │
│  Document (D&B_record)                                      │
│       │                                                     │
│       └──[API normalize]─> ExtractedFact (annual_revenue)  │
│                                                             │
│  CONFLICT DETECTED: annual_revenue appears in both         │
│  with different values                                      │
│       │                                                     │
│       ▼                                                     │
│  ConflictRecord created                                     │
│       │                                                     │
│       ▼                                                     │
│  HITLReviewQueue entry created (with LLM recommendation)   │
│       │                                                     │
│       ▼ (UW resolves)                                       │
│  FactNode created with resolved_value + resolution_status  │
└─────────────────────────────────────────────────────────────┘
```

### Key Entities

#### Document

A Document represents one physical or digital file received in the submission.

| Field | Type | Business Meaning |
|---|---|---|
| `document_id` | UUID | Unique identifier for this file |
| `submission_id` | UUID | Which submission this belongs to |
| `doc_type` | enum | What kind of document it is |
| `source` | enum | Who sent it (broker, external data provider, internal) |
| `storage_ref` | text | Pointer to the file in S3/GDM — the binary never goes in the database |
| `ocr_status` | enum | Has this been processed? (pending / processing / done / failed) |
| `page_count` | integer | Number of pages — useful for knowing how much was extracted |

**Document types and what they contain:**

| `doc_type` | What It Is | Key Facts Extracted |
|---|---|---|
| `ACORD_125` | Standard insurance application | Named insured, FEIN, address, SIC code, revenue, payroll, employees |
| `ACORD_126_GL` | GL-specific supplement | Requested limits, deductible, prior GL history, specific GL coverages |
| `loss_run` | Claims history from prior carrier | Every claim: date, type, paid, reserved, open/closed |
| `broker_email` | Broker narrative and cover letter | Operations description, risk context, prior carrier explanation |
| `supplemental_app` | Industry-specific questionnaire | Contractor: subcontractor practices, safety program, largest job size |
| `financial_statement` | Audited or broker-stated financials | Revenue, payroll, total assets, net worth |
| `contract` | AI/indemnity agreement | Contractual liability type, additional insured requirements |

#### ExtractedFact

This is the **atomic unit of information** in the entire system. Every piece of data that enters the ontology begins as an ExtractedFact.

| Field | Type | Business Meaning |
|---|---|---|
| `fact_id` | UUID | Unique identifier for this specific extraction |
| `document_id` | UUID | Which document this came from |
| `fact_type` | text | What kind of fact this is (e.g., `annual_revenue`, `named_insured`, `gl_occ_limit_requested`) |
| `raw_value` | text | Exactly what was in the document, before any interpretation |
| `normalized_value` | JSONB | The typed, validated version (e.g., "5,000,000" becomes `5000000.00`) |
| `page_ref` | integer | Which page of the document this was found on |
| `field_ref` | text | Which specific field (e.g., ACORD field `Q56` for revenue) |
| `confidence` | float (0–1) | How confident the extractor is. 1.0 = rule-based certainty; 0.7 = LLM estimate |
| `extractor_id` | text | What extracted it (e.g., `acord-parser-v1`, `claude-sonnet-4-6`) |
| `llm_extracted` | boolean | TRUE if an AI model did the extraction (useful for audit filtering) |

**Why `raw_value` AND `normalized_value`?**

```
Document says:  "Five Million Dollars"   ← raw_value (verbatim)
Normalized:     5000000.00               ← normalized_value (typed, usable)

Document says:  "$5M"                    ← raw_value
Normalized:     5000000.00              ← normalized_value

Document says:  "5,000,000"             ← raw_value
Normalized:     5000000.00              ← normalized_value

All three normalize to the same number. But the raw_value is preserved
so you can always audit: "what exactly was in the document?"
```

**The `fact_type` enum covers both standard and GL-specific fields:**

| Category | Examples of `fact_type` values |
|---|---|
| Identity | `named_insured`, `fein`, `state_of_incorporation` |
| Financials | `annual_revenue`, `total_payroll`, `num_employees` |
| Classification | `sic_code`, `naics_code`, `operations_desc` |
| GL Coverage Requested | `gl_occ_limit_requested`, `gl_agg_limit_requested`, `gl_pco_limit_requested` |
| GL Flags | `contractual_liab_flag`, `prod_completed_ops_flag` |
| Loss Data | `loss_amount`, `claim_date`, `claim_status` |

#### ConflictRecord

Created **automatically** when the conflict detection engine finds the same `fact_type` for the same account in two or more documents with materially different values.

| Field | Type | Business Meaning |
|---|---|---|
| `conflict_id` | UUID | Unique identifier |
| `fact_type` | text | Which fact is in conflict |
| `conflicting_fact_ids` | UUID[] | Array of ExtractedFact IDs — all the disagreeing values |
| `conflict_type` | enum | What kind of conflict: `value_mismatch`, `missing_in_source`, `date_conflict`, `threshold_exceeded` |
| `delta_pct` | float | How big is the discrepancy in percentage terms |
| `priority` | enum | `high` / `medium` / `low` — auto-elevated to HIGH if the fact drives GL rating |
| `status` | enum | `open` / `resolved` / `waived` / `auto_resolved` |

**The delta_pct field is critical.** A 2% difference in revenue between sources is probably rounding. A 22% difference is a real discrepancy that changes the premium significantly.

```
ConflictRecord example:

fact_type:        annual_revenue
conflicting_facts:
  Fact A (ACORD 125):   $8,500,000
  Fact B (D&B):         $6,200,000
delta_pct:        37.1%    ← 37% gap — this is significant
priority:         HIGH     ← auto-elevated (revenue drives premium)
conflict_type:    value_mismatch
```

**The conflict detection is rule-driven, not hardcoded.** The `ConflictDetectionRule` (now `diff_threshold_rule` in the DDL) allows administrators to configure:
- Revenue: flag if delta > 15%
- Claim dates: flag if any difference (0% tolerance)
- Operations descriptions: use semantic similarity scoring (not a simple number comparison)

This means adding a new rule or changing a threshold is a **data change**, not a code deployment.

#### HITLReviewQueue (Human-in-the-Loop)

The HITL queue is the bridge between AI extraction and human judgment. It is **not** just a flag. It is a full work item with:

| Field | Type | Business Meaning |
|---|---|---|
| `queue_id` | UUID | Unique identifier |
| `conflict_id` | UUID | Which conflict triggered this review |
| `assigned_uw` | UUID | Which underwriter needs to resolve this |
| `context_snapshot` | JSONB | Everything the UW needs: all source values, document references, GL flags — in one place |
| `llm_recommendation` | text | What the AI thinks the right answer is, in plain English |
| `llm_confidence` | float | How confident the AI is in its recommendation |
| `uw_decision` | enum | `accept_source_a` / `accept_source_b` / `manual_override` / `waive` |
| `uw_override_value` | JSONB | If the UW enters a value not from any source |

**The key design insight:** The AI assists but never decides. The `context_snapshot` gives the UW everything they need without forcing them to navigate multiple screens. The `llm_recommendation` saves time — if the AI is 95% confident, the UW can quickly confirm rather than re-derive from scratch.

```
HITL Queue entry example:

Conflict: annual_revenue — 37% gap between ACORD and D&B

context_snapshot: {
  "ACORD_125": {
    "value": 8500000,
    "page": 2,
    "field": "Q56",
    "note": "Broker-stated, no supporting documentation"
  },
  "DB_record": {
    "value": 6200000,
    "duns": "12-345-6789",
    "fetched_at": "2024-03-15",
    "paydex_score": 78
  },
  "gl_flags": {
    "pco_applicable": true,
    "contractual_liab_applicable": true
  }
}

llm_recommendation: "D&B figure ($6.2M) is likely more accurate.
  The broker-stated figure may include revenue from subsidiaries not
  covered by this policy. The D&B data was verified 3 days ago.
  Recommend using $6.2M as the rated revenue."

llm_confidence: 0.83
```

#### GLCoverageIntent

This entity is populated purely from submission documents and records what the insured is **asking for** in coverage terms. It is the input to the eventual `gl_policy` record (what was actually bound).

| Field | Type | Business Meaning |
|---|---|---|
| `occ_limit_requested` | money | Each Occurrence limit requested |
| `agg_limit_requested` | money | General Aggregate limit requested |
| `pco_requested` | boolean | Is Products/Completed Ops coverage requested? |
| `pco_sublimit_requested` | money | Requested PCO aggregate (often same as general aggregate) |
| `contractual_liab_requested` | boolean | Is Contractual Liability coverage requested? |
| `contractual_liab_type` | enum | `incidental` (standard) / `blanket` / `specific` |
| `source_fact_ids` | UUID[] | Full provenance back to the ExtractedFacts that populated this |

**GL flags are first-class extracted facts** — not metadata. Products/Completed Ops and Contractual Liability coverage needs appear in submission documents and are extracted with the same provenance chain as revenue or payroll. This matters because:
- A PCO flag on the coverage intent triggers different rating (separate sublimit)
- A Contractual Liability flag triggers contract review in the HITL queue
- Both flags affect whether certain ISO class codes are appropriate

---

## Cluster 3 — Risk Profile

*Refer to the Risk Profile section of the entity model diagram.*

### Business Concept

The Risk Profile is the UW's **structured assessment** of what the insured does and how dangerous it is. It translates the raw operations description from the submission into rated, structured data that the pricing engine can use.

This cluster answers two key questions:
1. **What is this business's exposure?** (What is being insured, measured in what units?)
2. **How hazardous is it?** (What is the appropriate hazard grade?)

Note: In the DDL, Risk Profile entities live in the `gl` schema as `gl_operation_class` and `gl_exposure_base`, since risk classification is LOB-specific.

### ISO Class Codes — The Classification System

The insurance industry uses **ISO class codes** to standardize how similar businesses are grouped and rated. ISO (Insurance Services Office) maintains this catalog.

```
Every GL class code tells you:

  Code:     91111
  Desc:     Contractors — Residential Remodeling
  Default exposure:  payroll_subcontractors
  Default hazard:    C (moderate)
  PCO eligible:      YES  ← products/completed ops applies
  Contractual liab:  YES  ← contracts common in this trade
  Appetite:          acceptable

  vs.

  Code:     60010
  Desc:     Stores — Retail NOC (Not Otherwise Classified)
  Default exposure:  revenue
  Default hazard:    B (below average)
  PCO eligible:      NO   ← a retail store's products aren't really manufactured
  Contractual liab:  NO   ← leases are incidental
  Appetite:          preferred
```

The ISO class code is the **bridge** between the LLM's free-text operations extraction and the structured rating world. When the LLM reads "residential kitchen and bathroom remodeling contractor," it maps to ISO 91111.

### gl_operation_class — One Account, Many Classes

A single account can have multiple operation classes if it does more than one type of work. This is common:

```
Acme Construction LLC — Operation Classes:

Class 1: ISO 91111 — Residential Remodeling      70% of revenue
          hazard_grade: C
          pco_applicable: TRUE
          
Class 2: ISO 91580 — Commercial General           25% of revenue
          hazard_grade: D
          pco_applicable: TRUE
          
Class 3: ISO 41650 — Office operations            5% of revenue
          hazard_grade: A
          pco_applicable: FALSE
```

Premium is calculated for each class separately based on its revenue percentage, then combined. This is called **blended rating**.

### gl_exposure_base — The Rating Unit

For each operation class, an exposure base defines *how much of that activity there is*.

| `exposure_type` | Used For | Example |
|---|---|---|
| `payroll` | Most contractor classes | $2,400,000 annual payroll |
| `payroll_subcontractors` | Contractors using subs | $1,800,000 subcontractor cost |
| `revenue` | Retail, services | $8,500,000 annual revenue |
| `gross_sales` | Manufacturing, products | $12,000,000 gross sales |
| `sqft` | Real estate, warehouses | 45,000 square feet |
| `units` | Apartments, hotels | 120 units |

The `change_pct` field compares current exposure to prior year, and `change_flag` is set TRUE when the delta exceeds the configured threshold. A 30% payroll increase triggers a renewal flag because it likely means the business grew significantly and the premium may be underpriced.

---

## Cluster 4 — Loss History

*Refer to the Loss History + ClaimEvent + Renewal Diff diagram.*

### Business Concept

Loss history is the single most important underwriting signal. The saying in insurance is: **"The best predictor of future losses is past losses."**

But loss history is also the messiest data in a submission. Loss runs arrive as PDFs, Excels, or scanned images in carrier-proprietary formats. The system must parse them, normalize them, detect development (how reserves change over time), and compute trends.

### The Loss Run Document

A loss run is a report from the insured's prior carrier. It shows all claims during a policy period as of a specific valuation date.

```
SAMPLE LOSS RUN — Hartford Fire Insurance
Account: Acme Construction LLC
Policy: GL-2021-4892
Period: 01/01/2021 — 12/31/2021
Valued As Of: 12/31/2023                ← THIS DATE MATTERS

Claim#    Date    Claimant    Coverage    Paid       Reserved    Incurred    Status
2021-001  03/15   J. Smith    BI          $85,000    $0          $85,000     Closed
2021-002  07/22   Doe Corp.   PD          $32,000    $0          $32,000     Closed
2021-003  11/08   M. Jones    BI          $0         $380,000    $380,000    OPEN

TOTALS                                   $117,000   $380,000    $497,000
```

**Why "valued as of" matters:**

The open claim (#2021-003) has $380,000 reserved. That is the carrier's *estimate* of what will ultimately be paid. It is not real money yet. If this loss run were valued 12 months earlier, the reserve might have been $150,000. If valued in 6 months, it might be $500,000. The valuation date determines what you see.

### gl_loss_run — The Container

| Field | Business Meaning |
|---|---|
| `carrier_name` | Which insurer provided this loss run |
| `policy_period_start/end` | Which coverage year this covers |
| `as_of_date` | The valuation date — when were the reserves set? |
| `total_incurred` | Paid + Reserved = total cost estimate |
| `open_claim_count` | How many claims are still being developed |
| `parse_confidence` | How confident was the LLM in reading this document? |

### gl_claim_event — The Atomic Loss Unit

One row per claimant per occurrence. If a car crash on a client's premises injures three people, that's three `gl_claim_event` rows all sharing one `occurrence_id`.

**The `gl_coverage_part` enum — the GL claim taxonomy:**

| Coverage Part | What It Covers | When It Applies |
|---|---|---|
| `bodily_injury` | Physical injury to a third party | Customer falls in store, visitor injured at job site |
| `property_damage` | Damage to someone else's property | Contractor breaks client's equipment |
| `products_liability` | Injury from a product you made/sold | Defective component causes equipment failure |
| `completed_ops` | Injury after your work is done | Completed building has structural flaw |
| `personal_adv_injury` | Libel, slander, copyright infringement | False advertising, defamation |
| `contractual_liab` | Liability assumed via contract | Indemnification clause in a lease or construction contract |
| `medical_pay` | No-fault minor injury payments | Minor cut treated at urgent care |

**GL flags on ClaimEvent:**

| Flag | Business Meaning | Effect |
|---|---|---|
| `pco_trigger` | This claim involved Products or Completed Ops | Escalates to mandatory UW review; feeds PCO sublimit analysis |
| `contractual_liab_trigger` | This claim arose from a contractual liability assumption | Flags need for contract review |
| `litigation_flag` | This claim is or was in litigation | Increases severity estimate; debit in pricing |
| `catastrophe_flag` | This was a major event (tornado, flood, mass casualty) | Excluded from normal trend analysis |

### gl_occurrence — Grouping Claimants

An occurrence groups all claims from the same incident. The per-occurrence limit on the GL policy applies at the occurrence level — not the individual claim level.

```
One Incident (Scaffolding Collapse):

Occurrence #2022-047
  ClaimEvent: Worker A — Bodily Injury — $220,000 incurred
  ClaimEvent: Worker B — Bodily Injury — $185,000 incurred
  ClaimEvent: Property Owner — Property Damage — $45,000 incurred
  
  Total at occurrence level: $450,000
  
  Policy each-occurrence limit: $1,000,000
  → Limit not exhausted, all claims covered within one occurrence
  
  pco_trigger: FALSE (this was during active operations, not completed work)
```

### gl_claim_development — The Reserve Timeline

Every time a new loss run arrives for the same claim, a new `gl_claim_development` row is created. This builds a timeline:

```
Claim #2021-003 (M. Jones, Bodily Injury)
Development history:

as_of_date     paid       reserved    incurred    reserve_change
2021-12-31     $0         $150,000    $150,000    —
2022-06-30     $0         $220,000    $220,000    +$70,000  ← adverse development
2022-12-31     $0         $380,000    $380,000    +$160,000 ← more adverse development
2023-06-30     $0         $380,000    $380,000    $0         (stable)
2023-12-31     $45,000    $335,000    $380,000    $0         (partial payment)

PATTERN: Reserve doubled from initial estimate. Significant adverse development.
IMPLICATION: The carrier's initial $150K estimate was too low. This is now a
             $380K claim with partial payment but still open.
```

**Why this matters for underwriting:** A claim that started at $150K and grew to $380K shows the carrier underestimated severity. The UW must consider whether the reserve is now accurate — or still growing.

### gl_loss_trend — The Aggregated Signal

Computed per account per GL coverage part over 3 or 5 years. This is what feeds the renewal diff engine.

| Field | Business Meaning |
|---|---|
| `claim_frequency` | Claims per year — is the account accident-prone? |
| `avg_severity` | Average cost per claim — are claims getting bigger? |
| `loss_ratio` | Incurred / Premium — is this account profitable? |
| `large_loss_count` | Claims over $100K — high-severity events count differently |
| `frequency_trend` | `improving` / `stable` / `deteriorating` |

---

## Cluster 5 — Coverage

*Refer to the Coverage cluster in the entity model diagram.*

### Business Concept

Coverage is the **contractual agreement** — what the insurer promises to pay for, and under what conditions. If Account (Cluster 1) answers "who" and Risk Profile (Cluster 3) answers "what's the risk," then Coverage answers "what are we agreeing to cover?"

The Coverage cluster bridges the submission (what was requested) and the policy (what was bound). There are intentionally two separate entities for this:

```
gl_coverage_intent   ←  What the insured ASKED for  (Cluster 2: Submission)
      ↓ compared by UW
gl_policy + gl_coverage_form  ← What was actually OFFERED/BOUND
```

### gl_policy — The Policy Record

The policy is the legal contract. Key concepts:

| Field | Business Meaning |
|---|---|
| `policy_number` | Assigned by PAS when bound — NULL until then |
| `status` | Lifecycle: `quoted` → `bound` → `issued` → `expired` |
| `total_premium` | The amount the insured pays |
| `effective_date` | When coverage begins |
| `expiry_date` | When coverage ends (typically 12 months later) |

### gl_coverage_form — The Limits Structure

The coverage form holds the actual limit amounts. One GL policy typically has one coverage form (CG 00 01 is the standard), but complex policies can have multiple.

**Understanding GL limits:**

```
GL Coverage Form for Acme Construction:

Each Occurrence Limit:        $1,000,000
  └─ Max paid for any ONE incident

General Aggregate:            $2,000,000
  └─ Max paid for ALL incidents in the policy year
     (BI + PD + Personal Injury combined)

Products/Completed Ops Agg:  $2,000,000
  └─ Separate aggregate just for Products and Completed Ops claims
     (has its own "bucket" — doesn't eat into the General Aggregate)

Deductible:                   $2,500 per claim
  └─ Insured pays first $2,500 of each claim

Medical Payments:             $5,000 per person
  └─ No-fault payments for minor injuries — no liability determination needed

Fire Damage Legal Liability:  $50,000
  └─ Damage to rented premises caused by insured's negligence
```

**The PCO sublimit** is one of the most important GL-specific concepts:

```
Why Products/Completed Ops gets its own aggregate:

A contractor builds 50 homes per year. Each home is "completed operations"
once construction is done. A structural defect in one home could result in
a claim years later. Because there are 50 homes, this exposure accumulates.

If PCO shared the General Aggregate:
  One bad completed ops year could exhaust the entire policy aggregate,
  leaving BI and PD claims without coverage.

With its own PCO Aggregate:
  Completed ops claims draw from their own bucket ($2M),
  while BI and PD claims draw from the General Aggregate ($2M).
  The insured has $4M of effective protection.
```

### gl_endorsement — Modifications to the Policy

Endorsements are amendments that add, remove, or modify coverage. They are attached to the policy and change what the standard form provides.

**Common GL endorsements:**

| Form Number | Name | Business Effect |
|---|---|---|
| CG 20 10 | Additional Insured — Owners, Lessees or Contractors | Names a general contractor as additional insured for ongoing operations |
| CG 20 37 | Additional Insured — Completed Operations | Names GC as AI for completed work (PCO exposure) |
| CG 21 47 | Employment-Related Practices Exclusion | Removes coverage for discrimination, harassment claims |
| CG 24 04 | Waiver of Transfer of Rights | Prevents insurer from suing GC's client after paying a claim |
| IL 04 15 | Protective Safeguards | Requires specific fire suppression equipment; voids coverage if not maintained |

Endorsements marked `uw_required = TRUE` are conditions of coverage — the UW mandated them. If the insured doesn't comply, coverage may be void.

---

## Cluster 6 — UW Decision

*Refer to the UW Decision cluster in the entity model diagram.*

### Business Concept

Every action a UW takes during the underwriting process is recorded as a `UWAction`. This cluster is the **audit trail** of the entire decision-making process.

This is critical for several reasons:
- **Regulatory compliance:** In many jurisdictions, insurers must demonstrate that declinations are not discriminatory
- **Actuarial analysis:** Understanding which accounts were declined and why helps calibrate future pricing
- **Quality assurance:** Supervisors can review UW decisions for consistency
- **AI oversight:** When LLMs assist in decisions, every AI recommendation and every human override is recorded

### uw_action — The Decision Log

```
Action sequence for Acme Construction submission:

Action 1: triage      → performed_by: [Triage Bot]         → 2024-03-14 08:00
Action 2: review      → performed_by: [UW Sarah Johnson]   → 2024-03-14 09:30
Action 3: request_info → performed_by: [UW Sarah Johnson]  → 2024-03-14 10:15
  (requested updated loss run from Hartford)
Action 4: review      → performed_by: [UW Sarah Johnson]   → 2024-03-15 14:00
  (received and reviewed updated loss run)
Action 5: quote       → performed_by: [UW Sarah Johnson]   → 2024-03-15 16:30
Action 6: bind        → performed_by: [System/Broker]      → 2024-03-22 10:00
  (broker submitted bind order)
```

### decision — The Outcome

Each `uw_action` that results in a definitive decision creates a `decision` record:

| `outcome` | Business Meaning |
|---|---|
| `accept` | Risk is acceptable; proceed to quote |
| `decline` | Risk is outside appetite; no coverage offered |
| `refer` | Exceeds UW authority; escalate to senior UW or management |
| `pend` | Need more information before deciding |
| `bound` | Coverage is active |

`decline_reason_code` is LOB-specific (GL has different decline codes than WC) and is validated at the application layer — the database stores the code string, the application knows its meaning.

### gl_pricing_factor — The Premium Breakdown

Every component that contributes to the final premium is a separate `gl_pricing_factor` row. This is essential for:
- Actuarial audit trails (what drove pricing)
- UW override tracking (did the UW manually change a system-generated factor?)
- Regulatory filings (premium components must be documented)

```
Pricing factors for Acme Construction policy:

Type                    Basis                Value      $ Impact
base_rate               per $1,000 payroll   $4.85      $11,640
schedule_credit         safety program       -10%       -$1,164
schedule_debit          above-avg losses     +15%       +$1,746
schedule_credit         years in business    -5%        -$582
pco_load                flat load            flat       +$2,200
contractual_liab_load   flat load            flat       +$850
                                                        -------
                                             TOTAL:     $14,690

Note: pco_load has uw_override = TRUE
  UW Sarah Johnson changed PCO load from $3,100 to $2,200
  rationale: "Account has clean PCO history, 15+ years in business"
```

The `uw_override = TRUE` flag is how the system knows a human changed what the rating engine calculated. Every override is preserved with the UW's ID and their rationale.

---

## Cluster 7 — External Data

*Refer to the External Data cluster in the entity model diagram.*

### Business Concept

Insurers do not rely solely on what the broker and insured tell them. External data enriches and validates the information received in the submission.

**The fundamental problem external data solves:**

```
Broker submits on behalf of an insured:
  Named Insured: "Acme Construction LLC"
  Annual Revenue: $8,500,000 (broker-stated)
  Years in business: 15
  No OSHA violations
  Clean legal history

The insurer needs to VERIFY this independently.
```

External data sources provide independent verification:

| Source | What It Provides | Key Use |
|---|---|---|
| **D&B (Dun & Bradstreet)** | Revenue, employee count, PAYDEX credit score, payment history, derogatory marks | Revenue verification, financial stability check |
| **Pitchbook** | Private company financials, investors, funding rounds | Revenue/valuation for VC-backed companies |
| **FactSet** | Public company financials | Revenue verification for public companies |
| **OSHA** | Inspection records, violation history, penalties | Safety culture assessment, hazard confirmation |
| **LexisNexis** | Litigation history, court records | Legal exposure, principal background |
| **NewsAPI** | Recent news about the company | Adverse events (lawsuits, accidents, controversies) |
| **NPSIS** | National insurance registry | Prior insurance history, prior coverage cancellations |

### The External Data Record Structure

One row per source per account per fetch. Key design decisions:

**Why store the `raw_payload`?** Because API responses change. If D&B updates their schema, the raw_payload preserves what was actually received at the time of the decision.

**Why normalized fields separately?** Because downstream systems (conflict detection, LLM queries) need typed values, not JSON string parsing.

**The `staleness_flag`:** External data is fetched at submission time. If the same account submits a year later and the D&B data is still in the database from 14 months ago, `staleness_flag = TRUE` triggers a re-fetch. Revenue figures, employee counts, and OSHA records change over time.

### How External Data Feeds Conflict Detection

```
External data arrives and its values are mapped to ExtractedFacts:

D&B fetch for Acme Construction:
  revenue_db = $6,200,000
  → Creates ExtractedFact: fact_type='annual_revenue', value=6200000,
    extractor_id='DB-api-v2', confidence=0.99

ACORD 125 already has:
  ExtractedFact: fact_type='annual_revenue', value=8500000,
    extractor_id='acord-parser-v1', confidence=0.95

CONFLICT DETECTED:
  Same fact_type, same account, delta_pct = 37%
  → ConflictRecord created
  → HITLReviewQueue entry created
  → LLM generates recommendation using both context snapshots
  → UW resolves
  → FactNode created with winning value
```

---

## Cluster 8 — Participants

*Refer to the Participants cluster in the entity model diagram.*

### Business Concept

Every action in the underwriting workflow is performed by someone or something. The Participants cluster tracks all of them:

| Participant Type | Who They Are | Key System Role |
|---|---|---|
| `underwriter` | The AIG employee who evaluates and prices the risk | Assigned to submissions; has `authority_limit` and `referral_threshold` |
| `broker` | The intermediary representing the insured | Submits the account; receives quotes and policy documents |
| `insured` | The business seeking coverage | The named insured on the policy |
| `manager` | Senior UW who handles referrals | Approves when deal exceeds UW's authority |
| `system` | Automated processes (triage bot, extraction pipeline) | Performs automated actions; appears in action log |
| `tpa` | Third-Party Administrator | Handles claims on behalf of insurer in some arrangements |
| `actuary` | Pricing specialist | Reviews pricing factors, provides rate guidance |

### The Authority Limit System

The `authority_limit` and `referral_threshold` fields on UW participants drive automatic routing:

```
UW Sarah Johnson:
  authority_limit: $500,000   ← can bind policies up to $500K premium
  referral_threshold: $250,000  ← must get review for quotes above $250K

UW Director Tom Chen:
  authority_limit: $2,000,000
  referral_threshold: $1,000,000

When Acme Construction quote = $14,690:
  → Within Sarah's authority ($14,690 < $500,000)
  → No referral needed
  → Sarah can bind

If Acme Construction quote = $320,000:
  → Above Sarah's referral threshold ($320,000 > $250,000)
  → Referral to Tom Chen required before binding
  → UWAction of type 'refer' created
  → HITLReviewQueue entry created for Tom
```

---

## Cluster 9 — Provenance

*Refer to the FactNode provenance section in the entity model diagram.*

### Business Concept

Provenance is the answer to the question: **"How do we know what we know, and how much do we trust it?"**

This cluster is not about a business process. It is about **epistemics** — the system's theory of knowledge. Every other cluster contributes facts; the Provenance cluster keeps track of where every fact came from and how confident we are in it.

### fact_node — The Universal Provenance Record

The FactNode is the most important design element in the entire ontology. It wraps every authoritative fact across all clusters.

**The polymorphic FK pattern:**

Instead of having a separate `account_provenance` table, a `submission_provenance` table, a `claim_provenance` table... the FactNode uses `entity_type` + `entity_id` to point to any entity in any cluster:

```
FactNode records:

entity_type: 'account'          entity_id: [Acme Construction UUID]
fact_type:   'annual_revenue'   resolved_value: 6200000
source:      → [D&B Record]     confidence: 0.99
             resolved by:       [UW Sarah Johnson]

entity_type: 'gl_claim_event'   entity_id: [Claim #2021-003 UUID]
fact_type:   'incurred_amount'  resolved_value: 380000
source:      → [Loss Run PDF]   confidence: 0.87
             resolution_status: 'uncontested'  (only one source)

entity_type: 'gl_operation_class'  entity_id: [Op Class UUID]
fact_type:   'iso_class_code'      resolved_value: '91111'
source:      → [ACORD_126_GL]      confidence: 0.71
             extractor_id:         'claude-sonnet-4-6'
             llm_extracted:        TRUE
```

**The `resolution_status` enum tells you how confident to be:**

| Status | Meaning |
|---|---|
| `uncontested` | Only one source provided this fact; no conflict |
| `auto` | Multiple sources agreed; automatically resolved |
| `hitl_pending` | Conflict detected; waiting for UW resolution |
| `hitl_resolved` | A human UW reviewed and resolved the conflict |
| `overridden` | A UW manually entered a value not from any source |

### The Renewal Diff Engine (TermDiffReport + UWSignalQueue)

At renewal time, the system compares two `account_term_snapshot` records — this year's state vs last year's state.

**TermDiffReport** contains an array of DiffItem records:

```
DiffItem format:
{
  "field":          "annual_revenue",
  "prior_value":    6200000,
  "current_value":  8100000,
  "delta_pct":      30.6,
  "change_type":    "exposure_growth",
  "severity":       "escalate",
  "uw_action_required": true
}
```

**UWSignalQueue** is what the UW actually sees when they open a renewal. The LLM synthesizes the DiffItems into plain language:

```
Signal: Revenue spike + new PCO claim

priority: HIGH

llm_summary: "Annual revenue increased 31% YoY ($6.2M → $8.1M per D&B, 
fetched today). A new Products/Completed Ops claim appeared since last 
renewal (2023-002, $45,000 incurred, open). The premium may be 
understated given exposure growth. Review payroll figures and consider 
PCO sublimit adequacy."

supporting_diff_items: [
  { field: 'annual_revenue', delta_pct: 30.6, severity: 'escalate' },
  { field: 'new_pco_claim',  delta_pct: null,  severity: 'escalate' }
]
```

---

# CHAPTER IV — End-to-End Flow with Mock Data

## The Account: Meridian Plumbing & Mechanical LLC

We will follow one submission through the entire system with realistic mock data.

**The business:**
- Commercial plumbing contractor based in Atlanta, Georgia
- 12 years in business
- Primarily commercial new construction (60%) and service work (40%)
- 45 full-time employees plus regular subcontractor crews
- Seeking GL coverage for the first time with AIG (previously with Liberty Mutual)

---

## Stage 1 — Submission Arrives

**Date:** March 10, 2024

**Broker:** Hartwell Risk Partners LLC, Atlanta GA

Documents received:

```
submission_id: 7a3f-4e92-...

Documents:
  doc_001: ACORD_125          (14 pages)  ocr_status: done
  doc_002: ACORD_126_GL       (4 pages)   ocr_status: done
  doc_003: loss_run           (8 pages)   ocr_status: done  [Liberty Mutual, 5 years]
  doc_004: broker_email       (2 pages)   ocr_status: done
  doc_005: supplemental_app   (6 pages)   ocr_status: done  [Contractor supplement]
```

**Account record created:**

```sql
account:
  account_id:          f8a2-1c47-...
  legal_name:          Meridian Plumbing & Mechanical LLC
  fein:                47-3821904
  state_of_incorp:     GA
  primary_sic_code:    1711  (Plumbing, Heating, Air-Conditioning)
  years_in_business:   12
```

---

## Stage 2 — Extraction

The pipeline processes all five documents. Here are selected `extracted_fact` records:

```
From ACORD_125 (doc_001):

fact_id    fact_type            raw_value            normalized_value    confidence  extractor
ef-001     named_insured        "Meridian Plumbing   "Meridian Plumbing  0.99        acord-parser
                                 & Mechanical LLC"    & Mechanical LLC"
ef-002     fein                 "47-3821904"         "47-3821904"        0.99        acord-parser
ef-003     annual_revenue       "$7,200,000"         7200000.00          0.99        acord-parser
ef-004     total_payroll        "$3,100,000"         3100000.00          0.99        acord-parser
ef-005     num_employees        "45"                 45                  0.99        acord-parser
ef-006     sic_code             "1711"               "1711"              0.99        acord-parser

From ACORD_126_GL (doc_002):

ef-007     gl_occ_limit_req     "$1,000,000"         1000000.00          0.99        acord-parser
ef-008     gl_agg_limit_req     "$2,000,000"         2000000.00          0.99        acord-parser
ef-009     pco_flag             "Yes"                true                0.99        acord-parser
ef-010     gl_pco_limit_req     "$2,000,000"         2000000.00          0.99        acord-parser
ef-011     contractual_liab     "Yes - Blanket"      "blanket"           0.87        claude-sonnet

From broker_email (doc_004) — LLM extracted:

ef-012     operations_desc      "Commercial mechanical contractor      "commercial plumbing    0.78   claude-sonnet
                                 focused on new construction and        and mechanical,
                                 service for commercial clients.        commercial construction
                                 No residential work."                  and service"
ef-013     prior_carrier_reason "Liberty Mutual non-renewed due to     "non-renewal,           0.71   claude-sonnet
                                 adverse loss ratio in their book,      market withdrawal"
                                 not account-specific."
```

**D&B fetch triggered automatically:**

```
external_data_record:
  source:         DB
  fetched_at:     2024-03-10 09:47:22
  duns_number:    04-827-3910
  revenue_db:     5900000.00          ← D&B says $5.9M, ACORD says $7.2M
  employee_count: 38                  ← D&B says 38, ACORD says 45
  paydex_score:   82                  (good payment history)
  derogatory_flag: false
```

---

## Stage 3 — Conflict Detection

The conflict engine runs and finds two discrepancies:

**Conflict 1 — Annual Revenue:**

```
conflict_record:
  conflict_id:     cr-001
  fact_type:       annual_revenue
  conflicting_facts:
    ef-003: $7,200,000 (ACORD 125, broker-stated)
    [D&B]:  $5,900,000 (D&B verified)
  delta_pct:       22.0%
  conflict_type:   value_mismatch
  priority:        HIGH  ← auto-elevated (revenue drives premium)
  status:          open
```

**Conflict 2 — Employee Count:**

```
conflict_record:
  conflict_id:     cr-002
  fact_type:       num_employees
  conflicting_facts:
    ef-005: 45 (ACORD 125, broker-stated)
    [D&B]:  38 (D&B verified)
  delta_pct:       18.4%
  conflict_type:   value_mismatch
  priority:        medium
  status:          open
```

---

## Stage 4 — HITL Queue

Two items enter the UW review queue:

**HITL Item 1 (Revenue):**

```
hitl_review_queue:
  queue_id:      hq-001
  conflict_id:   cr-001
  assigned_uw:   [UW Marcus Rivera]

  context_snapshot: {
    "ACORD_125": {
      "value": 7200000,
      "raw_value": "$7,200,000",
      "page": 3,
      "field": "Q56",
      "note": "Broker-stated"
    },
    "DB": {
      "value": 5900000,
      "duns": "04-827-3910",
      "fetched_at": "2024-03-10",
      "paydex": 82,
      "employee_count_db": 38
    },
    "broker_context": {
      "ef-013": "Prior carrier non-renewed market-wide, not account-specific"
    },
    "gl_flags": {
      "pco_applicable": true,
      "contractual_liab_type": "blanket"
    }
  }

  llm_recommendation: "Revenue discrepancy likely reflects subcontractor
    pass-through costs included in the broker-stated figure but excluded
    from D&B revenue. For a commercial mechanical contractor with $3.1M
    payroll and 45 employees, $7.2M revenue is plausible if material and
    subcontractor costs are included. D&B typically captures net revenue.
    Recommend using the broker-stated $7.2M but requesting clarification
    on whether revenue includes pass-through subcontractor costs."

  llm_confidence: 0.74
```

**UW Marcus Rivera reviews the queue at 11:30 AM:**

After reviewing the context snapshot and LLM recommendation, he contacts the broker. The broker confirms that the $7.2M includes $1.8M in subcontractor pass-through costs that D&B would not capture. The net own-work revenue is approximately $5.4M — below D&B's figure, which was actually $5.9M.

**UW resolution:**

```
uw_decision:        manual_override
uw_override_value:  5900000.00   ← Uses D&B figure as more conservative
uw_notes:           "Confirmed with broker that $7.2M includes sub
                     pass-through costs. D&B $5.9M represents net
                     own-work revenue. Using D&B figure for rating."
resolved_at:        2024-03-10 13:15:00

→ FactNode created:
  fact_type:         annual_revenue
  resolved_value:    5900000.00
  resolution_status: hitl_resolved
  resolved_by:       [UW Marcus Rivera]
```

---

## Stage 5 — Triage & Appetite Check

With data extracted and conflicts resolved, automated triage runs:

```
TRIAGE CHECKS:

SIC Code 1711 (Plumbing/HVAC Contractor):
  ISO Class mapping: 91580 (Commercial General Contractor)
  iso_class_reference.appetite_flag: acceptable ✓
  iso_class_reference.pco_eligible: TRUE → PCO flag confirmed

Geography: Georgia
  AIG writes commercial GL in Georgia ✓

Revenue: $5,900,000 (resolved)
  Within acceptable band for this class ✓

Years in business: 12
  Exceeds minimum (iso_class_reference.min_years_in_business = 5) ✓

Prior carrier non-renewal:
  ef-013 flagged: "market withdrawal, not account-specific" 
  → Flag for UW review but not automatic decline ⚠

TRIAGE RESULT: ACCEPT → proceed to risk evaluation
```

---

## Stage 6 — Risk Evaluation & Classification

**UW Marcus Rivera assigns ISO class codes:**

```
gl_operation_class records:

op_class_id:    oc-001
iso_class_code: 91580   (Contractors — Commercial General)
operations_desc: "Commercial plumbing and mechanical contractor,
                  new construction and service, commercial only"
is_primary:     TRUE
revenue_pct:    60.0
pco_applicable: TRUE    ← completed work on commercial buildings
contractual_liab_applicable: TRUE  ← construction contracts typical
hazard_grade:   D
llm_extracted:  TRUE
llm_confidence: 0.82

op_class_id:    oc-002
iso_class_code: 91111   (Contractors — Service and Repair)
operations_desc: "Commercial plumbing service and repair, HVAC maintenance"
is_primary:     FALSE
revenue_pct:    40.0
pco_applicable: FALSE   ← service work, less completed ops exposure
contractual_liab_applicable: FALSE
hazard_grade:   C
llm_extracted:  TRUE
llm_confidence: 0.78
```

**Loss run analysis:**

```
Loss runs from Liberty Mutual (2019–2023):

gl_loss_run records:

Period 2019: 0 claims, $0 incurred. Clean year.
Period 2020: 1 claim
  gl_claim_event: Water damage to client building during pipe repair
    gl_coverage_part: property_damage
    incurred_amount:  $18,500
    claim_status:     closed
    pco_trigger:      FALSE (occurred during active operations)

Period 2021: 2 claims
  Claim 1: Employee of subcontractor slipped on wet floor
    gl_coverage_part: bodily_injury
    incurred_amount:  $42,000
    claim_status:     closed
    litigation_flag:  FALSE

  Claim 2: Client property damaged during new construction
    gl_coverage_part: property_damage
    incurred_amount:  $8,200
    claim_status:     closed

Period 2022: 1 claim
  Claim 1: Completed job — pipe joint failed 8 months after project completion
    gl_coverage_part: completed_ops  ← PCO trigger!
    incurred_amount:  $95,000
    claim_status:     closed
    pco_trigger:      TRUE          ← confirmed completed operations
    litigation_flag:  TRUE          ← client threatened suit, settled

Period 2023: 0 claims. Clean year.

TOTALS:
  5 years, 4 claims
  Total incurred: $163,700
  PCO claim: 1 (the $95K completed ops claim)
  Litigation: 1

gl_loss_trend (computed):
  claim_frequency:    0.8 per year (4 claims / 5 years)
  avg_severity:       $40,925
  large_loss_count:   0 (no claims over $100K)
  pco_claim_count:    1
  frequency_trend:    stable (no clear direction with only 4 claims)
```

---

## Stage 7 — Pricing & Structuring

**Exposure bases:**

```
gl_exposure_base:

exposure_type:  payroll
exposure_value: 3100000.00  (from ACORD, uncontested)
source:         broker_stated

exposure_type:  payroll_subcontractors
exposure_value: 1800000.00  (confirmed in HITL resolution)
source:         broker_stated
```

**Premium calculation:**

```
gl_pricing_factor records:

Type                    Basis               Value    $ Impact
base_rate (ISO 91580)  per $1,000 payroll  $5.20    $16,120
base_rate (ISO 91111)  per $1,000 payroll  $3.85    $4,943
sub_cost_surcharge     per $1,000 sub cost $2.10    $3,780
schedule_debit         PCO claim history   +10%     +$2,484
schedule_credit        12 yrs in business  -5%      -$1,242
schedule_credit        commercial only     -3%      -$745
                       (no residential)
pco_load               separate            flat     +$3,200
                                                    -------
SUBTOTAL:                                           $28,540
contractual_liab_load  blanket coverage    flat     +$1,100
                                                    -------
TOTAL PREMIUM:                                      $29,640
Minimum premium check: $5,000 ✓
```

**Coverage structure:**

```
gl_coverage_form:

occ_limit:              $1,000,000
general_aggregate:      $2,000,000
pco_aggregate:          $2,000,000     ← separate bucket for completed ops
deductible:             $5,000         ← UW raised from $2,500 (prior losses)
contractual_liab_type:  blanket
med_pay_included:       TRUE
med_pay_limit:          $5,000

gl_endorsement records:

CG 20 10  Additional Insured — Ongoing Ops    uw_required: TRUE
  (Required: broker confirmed GCs require this on all jobs)

CG 20 37  Additional Insured — Completed Ops  uw_required: TRUE
  (Required: given PCO history, protect GC clients for completed work)

IL 04 15  Protective Safeguards               uw_required: TRUE
  (Required: insured must maintain safety program; UW will verify at renewal)
```

---

## Stage 8 — Quote Issued

```
UWAction:
  action_type: quote
  performed_by: [UW Marcus Rivera]
  performed_at: 2024-03-11 16:30:00

Decision:
  outcome:    accept
  rationale:  "Commercial plumbing contractor, 12 years, reasonable loss
               history. PCO claim from 2022 is notable but isolated and
               closed. Revenue confirmed at $5.9M. Three required
               endorsements. Premium $29,640."
  llm_assist_used: TRUE
  llm_model:  claude-sonnet-4-6
```

Quote letter sent to broker on March 11, 2024.

---

## Stage 9 — Bind

On March 22, the broker submits a bind order. Coverage effective April 1, 2024.

```
UWAction:
  action_type: bind
  performed_at: 2024-03-22 10:15:00

gl_policy:
  policy_number:   AIG-GL-2024-88471   (assigned by PAS)
  status:          bound
  effective_date:  2024-04-01
  expiry_date:     2025-03-31
  total_premium:   $29,640

→ FactNode created:
  entity_type:    'gl_policy'
  fact_type:      'policy_number'
  resolved_value: 'AIG-GL-2024-88471'
  source:         PAS system push-back
  confidence:     1.0
  extractor_id:   'PAS-QUIC-integration'
```

---

## Stage 10 — Renewal (One Year Later)

April 2025. The account term expires. A new submission arrives from the broker.

**Account term snapshot created for 2024 term:**

```
account_term_snapshot:
  snapshot_date:     2025-03-01
  entity_hierarchy:  { same as prior year }
  financials:        { annual_revenue: 5900000, total_payroll: 3100000 }
  operation_classes: { same two classes, same revenue split }
  loss_summary:      { claim_count: 1, incurred: 14200, pco_count: 0 }
                       ← ONE claim during the policy year (minor PD, $14,200)
  coverage_in_force: { occ_limit: 1000000, agg: 2000000, pco_agg: 2000000 }
```

**Renewal broker submission states:**
- Revenue: $9,100,000 (broker-stated) — significantly higher
- Payroll: $4,200,000 (35% increase)
- New location: opened a second office in Charlotte, NC
- No new claims (consistent with loss summary)

**D&B re-fetch (triggered by new submission):**
- revenue_db: $7,400,000 (D&B verified)

**TermDiffReport generated (2025 vs 2024 snapshot):**

```
change_items:
[
  {
    "field":          "annual_revenue",
    "prior_value":    5900000,
    "current_value":  9100000,
    "delta_pct":      54.2,
    "change_type":    "exposure_growth",
    "severity":       "escalate"      ← exceeds 20% threshold
  },
  {
    "field":          "total_payroll",
    "prior_value":    3100000,
    "current_value":  4200000,
    "delta_pct":      35.5,
    "change_type":    "exposure_growth",
    "severity":       "escalate"      ← exceeds 20% threshold
  },
  {
    "field":          "new_location",
    "prior_value":    null,
    "current_value":  "Charlotte, NC",
    "delta_pct":      null,
    "change_type":    "new_location",
    "severity":       "flag"
  },
  {
    "field":          "revenue_db_vs_broker_gap",
    "prior_value":    22.0,
    "current_value":  22.9,
    "delta_pct":      null,
    "change_type":    "data_quality",
    "severity":       "flag"
  }
]

escalate_count: 2
flag_count:     2
```

**UWSignalQueue entry — what Marcus Rivera sees when he opens this renewal:**

```
uw_signal_queue:
  signal_type:    exposure_spike
  priority:       HIGH
  
  llm_summary: "Significant growth since last renewal. Broker-stated
    revenue increased 54% ($5.9M → $9.1M) and payroll 36% ($3.1M →
    $4.2M). D&B shows revenue at $7.4M (vs $9.1M broker-stated) — an
    18.7% gap that should be clarified given last year's sub pass-through
    discussion. A new Charlotte, NC location was added; verify that NC
    GL exposure is included and that territory rates apply. The account
    had only one minor claim ($14,200 PD) during the policy year — clean
    loss experience. Recommend premium reassessment based on verified
    exposure; current premium of $29,640 is likely understated at $9.1M
    revenue. Requires HITL review of revenue before quoting."

  supporting_diff_items: [revenue escalate, payroll escalate,
                           new_location flag, revenue_gap flag]
```

Instead of Marcus reviewing last year's paper file and manually comparing it to this year's submission, the system surfaces exactly what changed and why it matters — in plain language, with the supporting data behind it.

---

## Summary: What the System Did Automatically

Looking back at the Meridian Plumbing flow, here is what required human judgment vs what the system handled automatically:

| Step | Human Judgment Required | System Handled Automatically |
|---|---|---|
| Documents received | — | OCR, ingestion, storage |
| Facts extracted | — | LLM + ACORD parser extraction |
| D&B fetch | — | Triggered on submission receipt |
| Conflict detection | — | Engine ran, 2 conflicts found |
| Revenue conflict resolution | ✓ Marcus called broker | Queue created, context assembled, LLM recommendation generated |
| Employee count resolution | ✓ Marcus chose D&B figure | Queue created automatically |
| Triage checks | — | Appetite rules ran, result: accept |
| ISO class assignment | ✓ Marcus confirmed LLM classification | LLM proposed classes |
| Loss analysis | ✓ Marcus reviewed | Claim events parsed and structured |
| Premium calculation | ✓ Marcus applied schedule factors | Base rates calculated |
| Required endorsements | ✓ Marcus identified 3 endorsements | — |
| Policy issuance | — | PAS integration, number assigned |
| Renewal diff | — | Snapshots compared, DiffItems generated |
| Renewal signal | — | UWSignalQueue entry with LLM summary created |
| Renewal review | ✓ Marcus reviews the signal | Everything above it |

The goal of the ontology is not to eliminate human judgment from insurance underwriting. It is to **eliminate the mechanical work** so that human judgment is applied only where it adds value — and every application of that judgment is traceable.

---

*End of document. Proceed to implementation when ready.*
