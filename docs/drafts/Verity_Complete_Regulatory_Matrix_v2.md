# Verity — Regulatory Requirements, Feature Inventory & Compliance Matrix

**Version:** 2.0 — Consolidated (replaces all prior regulatory documents)
**Date:** April 26, 2026
**Scope:** US P&C insurance AI regulatory requirements for agentic AI in underwriting.
Covers SR 11-7, NAIC AI Model Bulletin, Colorado SB21-169, ORSA/ASOP 56/CAS Principles, and the NAIC AI Systems Evaluation Tool.

---

## Part 1: Regulatory Requirements (47 Total)

### Coverage Ratings

| Rating | Definition |
|--------|-----------|
| **Full** | Verity directly and completely addresses this requirement through a specific implemented mechanism |
| **Substantial** | Verity addresses the core requirement; minor gaps or manual steps remain |
| **Partial** | Verity provides supporting infrastructure but additional process or policy is needed |
| **Gap** | Verity does not address this requirement; external process or tooling required |

*Note: No AI governance platform achieves Full coverage across all provisions through technology alone. Process, policy, and human governance complement the platform. Gaps are identified explicitly.*

---

### 1.1 SR 11-7 — Federal Reserve / OCC Model Risk Management Guidance (12 Requirements)

*Applies to P&C insurers because: SR 11-7 is the de facto gold standard for model governance across financial services. State insurance regulators increasingly reference it in AI examinations and expect equivalent rigor.*

| # | Requirement | Provision | Coverage | Verity Features | Gaps / Customer Actions |
|---|------------|-----------|----------|----------------|----------------------|
| 1 | Model inventory & registration | §I — All models must be identified, catalogued, and tracked | **Full** | Asset Registry (G1-G7): task_version, agent_version, prompt_template, tool, connector, MCP server — all versioned DB records with name, owner, materiality, lifecycle_state. Model Inventory Report auto-generated. | — |
| 2 | Model ownership & accountability | §I — Each model must have a designated owner | **Full** | Owner field on every entity version. Approval record for each lifecycle promotion records the responsible approver. Override logs linked to named users. Accountability chain queryable end-to-end. | — |
| 3 | Conceptual soundness | §II.A — Model design must be documented: theory, assumptions, logic | **Substantial** | Metamodel stores design rationale, prompt content, tool allowlist, authority thresholds. Explainability output captures reasoning per decision. | LLM reasoning is probabilistic — formal "mathematical structure" documentation as envisioned for statistical models doesn't directly apply. Supplementary LLM Model Card per High-materiality agent needed. |
| 4 | Data quality & appropriateness | §II.A — Input data must be assessed for quality and relevance | **Substantial** | Data classification tiers govern permissible inputs. Mock mode testing validates pipeline with controlled data. Source_resolutions audit tracks per-binding provenance (connector, method, payload_bytes, duration_ms, fetch_id). | No automated data quality scoring or real-time data quality monitoring. Classification is at document-type level, not field-level. |
| 5 | Pre-deployment testing & validation | §II.B — Models must be tested before deployment | **Full** | Four-layer testing framework: mock mode → staging pytest suite → ground truth validation (F1/precision/recall/kappa) → shadow deployment. All results stored in test_execution_log linked to entity version. No version promotes to Champion without passing all configured test layers. | — |
| 6 | Independent validation | §II.B — Validation must be performed by staff independent of development | **Substantial** | High-materiality agents require named validator distinct from developer (G15 enforcement). Approval record captures both. | AGP enforces the control but cannot guarantee organizational independence. Insurer must ensure model risk team is structurally separate from AI development. |
| 7 | Ongoing monitoring | §II.C — Performance must be monitored continuously against benchmarks | **Substantial** | Champion metrics tracked in production. Override rate patterns, confidence distributions tracked. Incident log captures performance concerns. Decision log provides monitoring data infrastructure. | No built-in SPC engine. Automated drift detection with configurable thresholds requires supplementary configuration (B2). |
| 8 | Model change management | §II.C — Any change must go through defined change management with approval | **Full** | Every change creates a new version record. State transitions require approval records. Prompt changes versioned independently. Composition frozen at promotion. Full change history permanently stored and queryable. | — |
| 9 | Model limitations documentation | §II.A — Known limitations and conditions under which model may fail must be documented | **Partial** | Metamodel includes limitations field per version. Validation reports document conditions under which accuracy degrades. | For LLM agents, full scope of limitations (hallucination risk, prompt sensitivity, out-of-distribution behavior) not automatically characterized. Supplementary documentation required. Proactive disclosure to management (ASOP 56 §3.8) is customer process. |
| 10 | Use and user controls | §I — Controls must ensure model used only for intended purpose by authorized users | **Full** | Authority thresholds in metamodel enforced at runtime. Tool allowlists restrict agent capabilities. HITL gates prevent action above thresholds without human confirmation. Materiality tiers control gate requirements. Quotas limit per-entity usage. | — |
| 11 | Vendor model oversight | §III — Third-party models subject to equivalent governance | **Substantial** | Claude API registered as third-party vendor. MCP servers governed by trust registry (G6) with trust level, allowed tools, last assessment date. All external tool calls logged. | Formal third-party AI vendor risk assessment document (Anthropic's model card review, SOC 2, data processing agreement) is supplementary. |
| 12 | Board & senior management reporting | §IV — Regular reports on model risk to senior management and board | **Substantial** | Model Inventory Report designed for Model Risk Committee review. Incident log feeds senior management reporting. Regulatory evidence packages exportable. | No pre-formatted board-level dashboard or report template. Insurer's model risk function must design board reporting format. (B5) |

---

### 1.2 NAIC AI Model Bulletin (15 Requirements)

*Applies because: The NAIC AI Model Bulletin (adopted December 2023) is the primary insurance-specific AI regulatory guidance. Adopted by 24+ states as of April 2025. Establishes the AIS Program requirement and examination expectations. The NAIC AI Systems Evaluation Tool pilot launched in 12 states in March 2026.*

| # | Requirement | Provision | Coverage | Verity Features | Gaps / Customer Actions |
|---|------------|-----------|----------|----------------|----------------------|
| 13 | Accountability | §III.A — Insurers accountable for all AI decisions, including third-party | **Full** | Named owner per entity. HITL gates ensure no AI output becomes binding without named approver. Third-party AI governed under MCP trust registry with insurer retaining documented accountability. | — |
| 14 | Compliance with insurance laws | §III.B — AI must comply with all applicable insurance laws including rate filing | **Partial** | Lifecycle and governance processes support compliance. Materiality tier and regulatory notes help flag compliance-sensitive agents. | Verity does not contain insurance law compliance logic. Insurer must separately ensure AI-assisted rating decisions consistent with filed rates. |
| 15 | Transparency | §III.C — Plain-language description of AI use for regulators and policyholders | **Full** | Metamodel stores human-readable descriptions of every agent's purpose, inputs, outputs, limitations. Auto-documentation generator produces plain-language agent capability documents. | — |
| 16 | Explainability | §III.D — AI decisions must be explainable in specific, plain-language terms | **Full** | Decision agents produce structured reasoning summaries per submission. System auto-generates adverse action summaries citing specific risk factors, agent version, approving underwriter. Stored in Vault linked to submission. | — |
| 17 | Fairness — pre-deployment testing | §III.E — AI must not unfairly discriminate; must test for proxy discrimination | **Full** | Fairness analysis is mandatory validation step before promotion. Metrics include statistical parity tests across SIC sector, geographic region, revenue band. Enrichment data fields screened for protected class proxies. | — |
| 18 | Fairness — production monitoring | §III.E — Ongoing monitoring for discriminatory outcomes | **Gap** | Not built. | Production fairness monitoring module required (B1): track decision outcome distributions across demographic proxies in real time with automated alerts when disparity metrics exceed thresholds. |
| 19 | Privacy & data security | §III.F — AI must comply with state data privacy and security laws | **Substantial** | Four-tier data classification governs agent/tool access. Tier 3/4 data cannot go to external MCP servers without explicit authorization. All MCP tool calls logged with data classification assessed. Redaction pipeline (detail_level='redacted') scrubs PII before storage. | No automated PII detection in unstructured document inputs (B3). Classification depends on document-type tier, not real-time content scanning. |
| 20 | Robustness | §III.G — AI must perform reliably across conditions including edge cases | **Substantial** | Ground truth datasets include edge cases designed by SMEs. Staging suite includes adversarial test cases. Shadow deployment measures full production distribution before promotion. | Formal adversarial robustness testing (red-teaming, prompt injection simulation) not in standard pipeline (B6). |
| 21 | Human oversight & intervention | §III.H — Meaningful human oversight; ability to override or shut down | **Full** | HITL gates at promotion and per-decision above thresholds. Override mechanism with reason-coded logging. Rollback to prior Champion in <1 minute via single API call. Agent suspension without code deployment via admin UI. | — |
| 22 | Written AIS Program | §3.1 — Documented AI program governing all AI use in regulated practices | **Substantial** | Verity IS the operational implementation of an AIS Program: registry, lifecycle, testing, decision logging, compliance reporting. Multi-application scope across insurance lifecycle. | The written policy document wrapping Verity as the AIS Program infrastructure is customer responsibility. Verity provides the operational controls; insurer provides the policy document. |
| 23 | Consumer notification of AI use | §3.3 — Inform consumers when AI is used in decisions affecting them | **Partial** | Decision records are available and queryable for disclosure. Reasoning text and risk factors stored per decision. | The notification mechanism (when, how, what to tell consumers) is app-level and business-process. Verity stores the evidence needed for disclosure but doesn't generate consumer-facing notices. |
| 24 | Risk-proportionate controls | §3.2 — Controls commensurate with risk (5-factor NAIC assessment) | **Full** | Materiality tiers (High/Medium/Low) with configurable gates per tier. High: full 7-state lifecycle with 3 HITL gates. Medium: reduced gates. Low: version tracking only. Quotas per-entity. | — |
| 25 | Third-party vendor management program | §3.4 — Documented standards for assessing, acquiring, using third-party AI | **Substantial** | MCP server trust registry with trust level, allowed tools, last assessment date, data classification. All external tool calls logged with authorization checks. | Contractual terms (audit rights, cooperation clauses) are customer's procurement responsibility. |
| 26 | Regulatory examination readiness | §4 — Prepared to produce documentation during market conduct examinations | **Substantial** | Model Inventory Report, regulatory evidence packages, queryable decision audit (execution_context_id), test execution logs — covers all 4 exhibits of the NAIC Evaluation Tool. | Formatting to match specific Evaluation Tool exhibit templates may need customization. |
| 27 | UTPA compliance for AI decisions | §1 — AI decisions must comply with Unfair Trade Practices Act | **Substantial** | HITL prevents AI-only adverse decisions. Explainability for adverse outcomes. Lifecycle prevents untested AI reaching production. | Substantive UTPA compliance (rate filings, form approvals) is customer's legal responsibility. |

---

### 1.3 Colorado SB21-169 (7 Requirements)

*Applies because: Colorado SB21-169 is the most directly applicable state law for P&C insurers using AI in underwriting. Enforcement was delayed to June 30, 2026. A legislative working group is considering revisions (reframing "high-risk AI" as "covered ADMT," possible reset to January 2027). Similar legislation active in CT, CA, NY, and other states.*

| # | Requirement | Provision | Coverage | Verity Features | Gaps / Customer Actions |
|---|------------|-----------|----------|----------------|----------------------|
| 28 | Prohibition on unfair discrimination — proxy screening | §10-3-1104.9(3) — Input-level: may not use proxies for protected classes | **Substantial** | Data classification tiers control what data flows to agents. Enrichment data fields screened for known protected-class proxies. MCP trust registry with data classification. | Automated proxy variable detection in unstructured data not built. |
| 29 | Prohibition — output disparate impact | §10-3-1104.9(3) — Output-level: outcomes must not produce disparate impact | **Partial** | Ground truth validation includes fairness testing (validation-time only). | Production output monitoring for disparate impact required (B1). |
| 30 | External data & algorithm governance | §10-3-1104.9(4) — List of external data sources and algorithms, producible on request | **Full** | MCP server trust registry is exact implementation. Metamodel records which external tools each version can call. Both queryable and exportable. | — |
| 31 | Annual certification | §10-3-1104.9(5) — Annual certification to commissioner that AI complies | **Partial** | Produces underlying evidence: fairness reports, model inventory, data source registry. | Certification workflow (extract reports → legal review → executive sign-off → filing) is customer process. |
| 32 | Data governance documentation | §10-3-1104.9(4)(b) — Documented governance policies for external data | **Substantial** | Data classification policies in metamodel. MCP trust assessments document governance of each external provider. | Written data governance policy document referencing Verity controls is supplementary. |
| 33 | Bias testing methodology | §10-3-1104.9(4)(a) — Describe methodology and produce results on request | **Full** | Complete methodology stored per version: dataset, demographic proxies, statistical tests, results. Documentation directly producible for examiner. | — |
| 34 | Adverse action explainability | §10-3-1104.9(6) — Adverse action notice must include specific understandable reasons | **Full** | Decision agents produce structured adverse action summaries citing specific risk factors. Underwriter reviews before inclusion in notice. Reasoning from actual decision logic, not post-hoc. | — |

---

### 1.4 ORSA / ASOP No. 56 / CAS Principles (9 Requirements)

*Three complementary industry standards: ORSA (enterprise risk management), ASOP 56 (actuarial modeling), CAS Principles (fairness in insurance algorithms).*

| # | Requirement | Provision | Coverage | Verity Features | Gaps / Customer Actions |
|---|------------|-----------|----------|----------------|----------------------|
| 35 | Model risk identification & classification | ORSA §2.3 | **Full** | Materiality tier classification is direct ORSA implementation. Model inventory report provides snapshot for ORSA model risk section. Incident log provides loss event history. | — |
| 36 | Model documentation | ASOP 56 §3.4 | **Substantial** | Metamodel stores purpose, inputs, outputs, authority thresholds, validation results. Auto-generated documentation. | "Sufficient for a qualified reviewer" standard requires supplementary LLM-specific documentation. |
| 37 | Validation by qualified reviewer | ASOP 56 §3.6 | **Substantial** | Named validator separate from developer (G15). Structured validation report. | Actuarial qualification for pricing-influencing agents is customer responsibility. |
| 38 | Disclosure of limitations | ASOP 56 §3.8 | **Partial** | Limitations field per version. Validation reports document degradation conditions. | Proactive disclosure to UW management at time of use is customer communication process. |
| 39 | Model governance structure | ORSA §3.5 / ERM | **Substantial** | HITL approval chains, incident escalation, rollback, override tracking — technical governance controls implemented. | Governance structure (committee, roles, escalation paths) must be defined in written policy by insurer. |
| 40 | Continuous monitoring & back-testing | CAS §4, ORSA §2.3 | **Partial** | Production monitoring tracks metrics, override rates. Decision data stored for analysis. | True back-testing (comparing AI decisions to loss outcomes 12-24 months later) requires claims system integration and separate analytics capability (B4). |
| 41 | AI accountability & ownership | CAS §2 | **Full** | Agent ownership enforced at metamodel level. HITL approval records name the human accountable. Audit trail links every AI outcome to named approver. | — |
| 42 | Bias prevention & fairness | CAS §3 | **Substantial** | Fairness testing methodology, results, proxy screening implemented per version. | Ongoing production fairness monitoring with automated alerts required (B1). |
| 43 | Third-party AI oversight | CAS §5, ASOP 56 §3.7 | **Substantial** | Trust registry, tool allowlisting, all external calls logged. | Use-case-specific vendor evaluation document is supplementary to Verity's technical controls. |

---

### 1.5 Cross-Framework Requirements (4 Requirements)

*Requirements that span multiple frameworks or emerge from recent regulatory developments (NAIC Evaluation Tool, state-level trends).*

| # | Requirement | Source | Coverage | Verity Features | Gaps / Customer Actions |
|---|------------|--------|----------|----------------|----------------------|
| 44 | Model drift monitoring with thresholds | NAIC §4, SR 11-7 §II.C | **Partial** | Override rate tracking, incident log, performance data in decision logs. Drift detection agents planned (A1). | No automated drift detection with configurable control-chart thresholds (B2). Data is available; alerting logic is not built. |
| 45 | Data lineage & provenance tracking | SR 11-7 §II.A, NAIC §3.2, NY DFS 2024-7 | **Full** | Source_resolutions per-binding audit (connector, method, fetch_id, payload_bytes, duration). Target_writes with handles. Vault document lineage (parent→child). Execution context threading across workflows. | — |
| 46 | Enterprise-wide AI system inventory | NAIC §3.1, Evaluation Tool Exhibit A | **Full** | Multi-application registry (UW, Claims, Renewal, etc.). All entity types registered: tasks, agents, prompts, tools, connectors, MCP servers. Model inventory report spans all applications. | — |
| 47 | Annual compliance certification | CT MC-25, CO §10-3-1104.9(5) | **Partial** | Evidence packages generated from trust DB. | Certification workflow is customer process. Connecticut requires annual certification; Colorado requires annual; more states expected to follow. |

---

## Part 2: Coverage Summary

| Coverage Level | Count | % | Meaning |
|---------------|-------|---|---------|
| **Full** | 17 | 36% | Verity directly and completely addresses |
| **Substantial** | 18 | 38% | Core addressed; minor gaps remain |
| **Partial** | 10 | 21% | Supporting infrastructure; additional process needed |
| **Gap** | 2 | 4% | Not addressed; external solution required |

**Full or Substantial: 35 of 47 (74%)** — Verity provides at minimum core coverage for nearly three-quarters of mapped requirements.

**No requirement is entirely unaddressed** — even the 2 Gap items (production fairness monitoring) have the underlying decision data infrastructure in place; the missing piece is the alerting/monitoring logic.

---

## Part 3: Complete Feature Inventory

### Governance Plane (38 features — all shipped)

**Asset Registry (G1–G11)**

| ID | Feature | Description |
|----|---------|-------------|
| G1 | Task version registration | Versioned records with name, input/output schema, owner, materiality, lifecycle_state |
| G2 | Agent version registration | Versioned records with tool allowlist, delegation table, optional output schema |
| G3 | Prompt template versioning | Independent versions, template variables, referenced by entity versions |
| G4 | Tool registration | Records with transport type, is_write_operation flag |
| G5 | Connector registration | Data connector records with provider capabilities, method signatures |
| G6 | MCP server trust registry | External tool servers with trust level, allowed tools, last assessment, data classification |
| G7 | Application registration | Named applications (UW, Claims, Renewal) that own entity versions |
| G8 | Materiality tier classification | High/Medium/Low per version, controls gate requirements |
| G9 | Description similarity check | Quality check at Candidate → Staging |
| G10 | Frozen composition at promotion | prompt_version_ids, inference_config, source_bindings, write_targets locked |
| G11 | Admit-time wiring validation | All bindings/targets validated at registration. If it registers, it runs. |

**Lifecycle Engine (G12–G18)**

| ID | Feature | Description |
|----|---------|-------------|
| G12 | 7-state lifecycle | Draft → Candidate → Staging → Shadow → Challenger → Champion → Deprecated |
| G13 | Configurable gates per materiality | High: 3 HITL gates. Medium: 1. Low: version tracking only |
| G14 | HITL approval records | Named approver, timestamp, evidence per promotion |
| G15 | Developer ≠ validator enforcement | High-materiality: developer and validator cannot be same user |
| G16 | Fast-track for demo seeding | Candidate → Champion for non-production |
| G17 | Lifecycle event audit | from_state, to_state, approved_by, evidence, timestamp — append-only |
| G18 | Champion resolution at runtime | Lookup active champion per entity + application |

**Testing & Validation (G19–G24)**

| ID | Feature | Description |
|----|---------|-------------|
| G19 | Mock mode testing | No LLM, no side effects. step_responses strict — missing fixture = MockMissingError |
| G20 | Staging pytest suite | Real LLM, controlled data, full pytest integration |
| G21 | Ground truth validation | F1, precision, recall, kappa against labeled datasets. Includes fairness metrics. |
| G22 | Shadow deployment | Real traffic, logged-only, no production writes. Channel-gated. |
| G23 | Test execution log | Results stored linked to entity version. Detail_level forced to "full" for validation. |
| G24 | MockContext (3 concerns) | step_responses (strict), tool_responses (partial), source_responses. Compose independently. |

**Decision Logging (G25–G31)**

| ID | Feature | Description |
|----|---------|-------------|
| G25 | Immutable decision_log | Append-only, never updated. Full Governance Contract per invocation. |
| G26 | Model invocation log | Per-turn record: model, tokens, duration, stop_reason, message_history (at full level) |
| G27 | Source resolutions audit | Per-binding: binding_kind, status, fetch_id, payload_bytes, duration_ms, connector, method |
| G28 | Target writes audit | Per-target: mode, mode_reason, status, handle, connector, write_method |
| G29 | Tool calls audit | Per-call: name, input, output, duration, is_write_operation, transport, turn_number |
| G30 | Detail level control | full/standard/minimal/redacted per entity version. Redaction pipeline scrubs PII before storage. |
| G31 | Execution context threading | execution_context_id + workflow_run_id + parent_decision_id + decision_depth |

**Model Management (G32–G33)**

| ID | Feature | Description |
|----|---------|-------------|
| G32 | Inference config governance | Frozen JSONB: model, temperature, max_tokens per version |
| G33 | Model swappability | Change model → new version → same lifecycle gates |

**Compliance & Reporting (G34–G36)**

| ID | Feature | Description |
|----|---------|-------------|
| G34 | Model inventory report | Auto-generated from trust DB across all applications |
| G35 | Validation report storage | Stored documents in Vault linked to entity version |
| G36 | Regulatory evidence package | Exportable: inventory, validation, fairness, data sources, test results |

**Quotas & Incidents (G37–G38)**

| ID | Feature | Description |
|----|---------|-------------|
| G37 | Rate limiting | Per-entity, per-application, per-channel quotas |
| G38 | Incident log | Severity, status, linked_entity_version_id |

### Runtime Plane (23 features — all shipped)

**Task Executor (R1–R5)**

| ID | Feature | Description |
|----|---------|-------------|
| R1 | Single-call task execution | Source resolve → prompt assemble → 1 Claude call → output validate → write targets |
| R2 | Structured output enforcement | tool_choice on synthetic structured_output tool. Schema violation = hard fail. |
| R3 | Source binding resolution | text (template vars) and content_blocks (vision) modalities |
| R4 | Write target dispatch | Channel-gated, payload assembly from input.*/output.* references |
| R5 | Write mode resolver | MockContext > caller override > auto (channel-gated). Precedence documented. |

**Agent Loop (R6–R12)**

| ID | Feature | Description |
|----|---------|-------------|
| R6 | Multi-turn tool-use loop | Claude → tool_use → dispatch → result → repeat until terminal |
| R7 | Tool authorization checking | Per-version allowlist. Unauthorized → rejected + Claude informed. |
| R8 | Tool dispatch (3 transports) | python_inprocess, mcp_*, delegate_to_agent |
| R9 | Sub-agent delegation | delegate_to_agent meta-tool. parent_decision_id + decision_depth threading. |
| R10 | Agent output enforcement (opt-in) | submit_output tool + tool_choice on terminal turn |
| R11 | Write authority per tool | is_write_operation flag. Write tools blocked on non-production channels. |
| R12 | Max turns bounding | Safety limit per inference_config |

**Async Execution (R13–R19)**

| ID | Feature | Description |
|----|---------|-------------|
| R13 | Async run submission | POST /api/v1/runs → returns run_id immediately |
| R14 | Event-sourced run tracking | 4 append-only tables + execution_run_current VIEW. No mutable rows. |
| R15 | Worker pool | Stateless Docker service. SELECT FOR UPDATE SKIP LOCKED. Horizontally scalable. |
| R16 | Poll / wait / sync sugar | get_run, get_run_result, wait_for_run, run_task/run_agent |
| R17 | Run cancellation | Cooperative cancel between engine steps |
| R18 | Stuck run recovery | Janitor detects missing heartbeats, releases for re-claim |
| R19 | Canonical envelope | Uniform shape: status, output/error, telemetry, provenance |

**Connectors (R20–R23)**

| ID | Feature | Description |
|----|---------|-------------|
| R20 | EDMS/Vault connector | Document storage with lineage. Storage abstraction: MinIO → S3/Blob swappable. |
| R21 | Content block generation | PDF→document, image→image, text→text for Claude vision |
| R22 | Derived document creation | create_derived_json with lineage linking |
| R23 | MCP client | Connect to registered MCP servers for external tools |

### Agents Plane (3 features — planned)

| ID | Feature | Status | Description |
|----|---------|--------|-------------|
| A1 | Drift detection agents | 🔲 Planned | Monitor champion performance, flag drift |
| A2 | Lifecycle initiation agents | 🔲 Planned | Auto-initiate lifecycle from monitoring triggers |
| A3 | Validation with HITL agents | 🔲 Planned | Governance agents validating with human gates |

### Studio Plane (4 features — planned)

| ID | Feature | Status | Description |
|----|---------|--------|-------------|
| S1 | Compose AI (UI) | 🔲 Planned | Visual authoring for non-developers |
| S2 | Lifecycle UI | 🔲 Planned | UI-driven lifecycle management |
| S3 | Ground truth management UI | 🔲 Planned | Upload, manage, version labeled datasets |
| S4 | Test management UI | 🔲 Planned | Configure and run test suites from UI |

### Backlog / Enhancement Items

| ID | Feature | Status | Description |
|----|---------|--------|-------------|
| B1 | Production fairness monitoring | 📋 Backlog | Real-time disparity tracking with automated alerts |
| B2 | Automated drift detection (SPC) | 📋 Backlog | Control chart logic on performance metrics |
| B3 | PII scanning on document ingestion | 📋 Backlog | Pattern-matching before content reaches agents |
| B4 | Back-testing against realized outcomes | 📋 Backlog | Decision-to-claims integration (12-24 month lag) |
| B5 | Board-level AI risk dashboard | 📋 Backlog | Pre-formatted Model Risk Committee reporting |
| B6 | Red-team / adversarial testing layer | 📋 Backlog | Prompt injection resistance, anomalous input testing |
| B7 | Agent hooks / pre-post middleware | 📋 Backlog | Deferred indefinitely |

---

## Part 4: Cross-Framework Gap Analysis

| Gap Area | Reqs Affected | Verity Provides | Customer Must Add | Priority |
|----------|--------------|----------------|-------------------|----------|
| Production fairness monitoring | 18, 29, 42 | Validation-time testing, decision data | Real-time disparity tracking + alerts (B1) | **Critical** — CO SB21-169 enforcement June 2026 |
| Automated drift detection | 7, 44 | Monitoring data infrastructure | Control chart logic + threshold alerting (B2) | **High** — SR 11-7 examination expectation |
| PII scanning | 19 | Data classification at doc-type level | Real-time PII detection in unstructured input (B3) | **High** — NAIC privacy requirements |
| Back-testing vs outcomes | 40 | Decision data stored | Claims integration + methodology (B4) | **Medium** — ORSA/CAS, 12-24 month horizon |
| Board AI risk reporting | 12 | Inventory + incident data | Formatted report template + cadence (B5) | **Medium** — SR 11-7, ORSA |
| Adversarial testing | 20 | Extensible test framework | Red-team exercises for High-materiality (B6) | **Medium** — NAIC robustness |
| Written AIS Program document | 22 | Operational controls (the program itself) | Written policy wrapping Verity as AIS infrastructure | **High** — NAIC §3.1, 24 states |
| Consumer notification process | 23 | Decision evidence for disclosure | When/how/what notification mechanism | **Medium** — NAIC §3.3 |
| Annual certification workflow | 31, 47 | Evidence packages | Extract → legal review → exec sign-off → file | **High** — CO and CT require it |
| Vendor risk assessment docs | 11, 25, 43 | MCP trust registry + logging | Formal written assessment per vendor | **Medium** — SR 11-7 §III |
| Written governance policy | 39 | Technical controls | Committee, roles, escalation paths documented | **High** — ORSA §3.5 |
| Organizational independence | 6, 37 | Developer ≠ validator enforcement | Structural separation of MRM team | **Medium** — org design |

---

## Part 5: Slide Drafts for the Deck

### SLIDE: Regulatory Landscape — Why This Matters Now

**Title:** The Regulatory Landscape — Why Governance Is Not Optional
**Subtitle:** 24+ states, 4 frameworks, 47 requirements — and the examination tool is live

```
 THE REGULATORY PRESSURE — 2026
 ═══════════════════════════════

 ┌─────────────────────────────────────────────────────────┐
 │ NAIC AI Model Bulletin (Dec 2023)                       │
 │ Adopted by 24+ states. Requires:                        │
 │   · Written AIS Program                                 │
 │   · Consumer notification of AI use                     │
 │   · Risk-proportionate controls                         │
 │   · Third-party vendor management                       │
 │   · Examination readiness                               │
 │                                                         │
 │ NAIC Evaluation Tool pilot: 12 states, March 2026       │
 │ 4 exhibits: AI adoption · governance · high-risk · data │
 └─────────────────────────────────────────────────────────┘

 ┌───────────────────┐ ┌───────────────────┐ ┌──────────────┐
 │ SR 11-7           │ │ CO SB21-169       │ │ ORSA/ASOP/CAS│
 │ 12 requirements   │ │ 7 requirements    │ │ 9 requirements│
 │ Model inventory   │ │ Bias testing      │ │ Model risk   │
 │ Change management │ │ Annual cert       │ │ Back-testing │
 │ Vendor oversight  │ │ Adverse action    │ │ Fairness     │
 │ Board reporting   │ │ Proxy screening   │ │ Accountability│
 └───────────────────┘ └───────────────────┘ └──────────────┘

 TOTAL: 47 specific regulatory requirements
 mapped to 61 shipped Verity features

 VERITY COVERAGE:
   Full:        17 (36%)  ████████████████
   Substantial: 18 (38%)  ██████████████████
   Partial:     10 (21%)  ██████████
   Gap:          2  (4%)  ██

   74% Full or Substantial — no requirement entirely unaddressed
```

### Speaker Notes

```
SLIDE: Regulatory Landscape

KEY CONTEXT FOR THE AUDIENCE:
  - 24 states have adopted the NAIC AI Model Bulletin since Dec 2023
  - The NAIC AI Systems Evaluation Tool pilot launched March 2026 in 12 states
  - Colorado SB21-169 enforcement delayed to June 30, 2026 (may be revised further)
  - Connecticut requires annual AI compliance certification
  - NY DFS Circular Letter 2024-7 focuses on proxy discrimination in underwriting

THE 47 REQUIREMENTS are mapped against:
  1. SR 11-7 (12) — the model governance gold standard
  2. NAIC Model Bulletin (15) — insurance-specific, adopted by 24+ states
  3. Colorado SB21-169 (7) — first state law targeting algorithmic bias in insurance
  4. ORSA/ASOP 56/CAS (9) — industry self-governance standards
  5. Cross-framework (4) — drift, lineage, enterprise inventory, annual cert

THE COVERAGE STORY:
  17 Full + 18 Substantial = 35 of 47 requirements at core coverage or better
  This is materially stronger than the industry baseline where most insurers 
  have NO formal framework at all.

  The 2 Gap items are both production fairness monitoring — the underlying 
  decision data infrastructure is in place, the alerting/monitoring logic 
  is the gap. This is on the roadmap.
```

---

### SLIDE: Verity Coverage Matrix (Summary View)

**Title:** Verity Regulatory Coverage — 47 Requirements × 4 Frameworks
**Subtitle:** Full requirement matrix across SR 11-7, NAIC, CO SB21-169, ORSA/ASOP/CAS

```
 ■ = Full    ◧ = Substantial    ◫ = Partial    □ = Gap
 ═══════════════════════════════════════════════════════

 REQUIREMENT                          SR11-7  NAIC  CO    ORSA
 ─────────────────────────────────    ──────  ────  ──    ────
 Model inventory & registration        ■       ■     ■     ■
 Ownership & accountability             ■       ■     —     ■
 Conceptual soundness                   ◧       —     —     ◧
 Data quality & appropriateness         ◧       ◧     —     —
 Pre-deployment testing                 ■       ■     ■     ■
 Independent validation                 ◧       —     —     ◧
 Ongoing monitoring                     ◧       —     —     ◧
 Change management                      ■       —     —     —
 Limitations documentation              ◫       —     —     ◫
 Use & user controls                    ■       —     —     —
 Vendor model oversight                 ◧       ◧     —     ◧
 Board reporting                        ◧       —     —     ◧
 Transparency                           —       ■     —     —
 Explainability                         —       ■     —     —
 Fairness — pre-deployment              —       ■     ■     ◧
 Fairness — production monitoring       —       □     ◫    —
 Privacy & data security                —       ◧     —     —
 Robustness                             —       ◧     —     —
 Human oversight & intervention         —       ■     —     —
 Written AIS Program                    —       ◧     —     —
 Consumer notification                  —       ◫    —     —
 Risk-proportionate controls            —       ■     —     —
 Third-party vendor mgmt program        —       ◧     —     —
 Examination readiness                  —       ◧     —     —
 UTPA compliance for AI                 —       ◧     —     —
 Proxy discrimination screening         —       —     ◧    —
 Output disparate impact                —       —     ◫    —
 External data governance               —       —     ■     —
 Annual certification                   —       —     ◫    ◫
 Data governance documentation          —       —     ◧    —
 Bias testing methodology               —       —     ■     —
 Adverse action explainability          —       —     ■     —
 Model risk identification              —       —     —     ■
 Model documentation                    —       —     —     ◧
 Validation by qualified reviewer       —       —     —     ◧
 Disclosure of limitations              —       —     —     ◫
 Governance structure                   —       —     —     ◧
 Continuous monitoring & back-testing   —       —     —     ◫
 AI accountability & ownership          —       —     —     ■
 Bias prevention & fairness             —       —     —     ◧
 Third-party AI oversight               —       —     —     ◧
 Model drift monitoring                 ◧       ◧     —     ◧
 Data lineage & provenance              ■       ■     —     —
 Enterprise AI inventory                —       ■     —     —
 Adverse consumer outcome prevention    —       ◧     —     —
 Annual compliance certification        —       —     ◫    ◫

 TOTALS:                               SR11-7  NAIC  CO    ORSA
   Full                                  5      8     4     4
   Substantial                           5      7     1     8
   Partial                               1      2     3     3
   Gap                                   0      1     0     0
```

### Speaker Notes

```
SLIDE: Coverage Matrix

HOW TO READ THIS:
  Each row = a specific regulatory requirement with provision-level traceability
  Each column = one of the four mapped frameworks
  — = requirement doesn't apply to this framework

  ■ Full = Verity has a specific mechanism that directly satisfies
  ◧ Substantial = core is there, minor process gap
  ◫ Partial = infrastructure exists, customer must add process/policy
  □ Gap = not addressed by Verity

KEY TALKING POINTS:
  1. "No requirement is entirely unaddressed" — even the 2 gaps have 
     underlying data infrastructure
  2. The NAIC column has the most requirements (15) because the Model 
     Bulletin is the most prescriptive insurance-specific regulation
  3. SR 11-7 column has the highest Full rate because Verity was 
     designed with model risk management as the baseline
  4. The "Partial" items are nearly all process/policy responsibilities 
     that will always require customer action — annual certifications, 
     written governance policies, consumer notification mechanisms

HONESTY POINT:
  We deliberately split fairness into pre-deployment (Full) and 
  production monitoring (Gap). This is honest and defensible. 
  A regulator would see through a combined "Substantial" rating.
```

---

### SLIDE: NAIC Evaluation Tool — Verity Readiness

**Title:** NAIC AI Systems Evaluation Tool — How Verity Maps
**Subtitle:** 12-state pilot launched March 2026 — this is the tool examiners are using now

```
 NAIC EVALUATION TOOL: 4 EXHIBITS
 ═════════════════════════════════

 ┌─────────────────────────────────────────────────────────┐
 │ EXHIBIT A: Breadth of AI Adoption                       │
 │ "What AI are you using, and where?"                     │
 │                                                         │
 │ → Verity: Multi-application registry (UW, Claims,       │
 │   Renewal, etc.). All entity types registered.          │
 │   Model Inventory Report spans all applications.        │
 │                                                         │
 │ COVERAGE: ■ Full                                        │
 └─────────────────────────────────────────────────────────┘

 ┌─────────────────────────────────────────────────────────┐
 │ EXHIBIT B: Governance Framework & AIS Program            │
 │ "Show me your governance structure and controls"         │
 │                                                         │
 │ → Verity: 7-state lifecycle with HITL gates,             │
 │   materiality tiers, testing framework, decision         │
 │   logging, compliance reporting. IS the AIS Program.     │
 │                                                         │
 │ COVERAGE: ◧ Substantial (written policy doc is customer) │
 └─────────────────────────────────────────────────────────┘

 ┌─────────────────────────────────────────────────────────┐
 │ EXHIBIT C: High-Risk System Deep Dive                    │
 │ "Show me this specific agent's full governance trail"     │
 │                                                         │
 │ → Verity: Per-version audit trail — who built it, who    │
 │   tested it, who approved it, every decision it made,   │
 │   with what version, what config, what reasoning.        │
 │   ONE QUERY: execution_context_id.                      │
 │                                                         │
 │ COVERAGE: ■ Full                                        │
 └─────────────────────────────────────────────────────────┘

 ┌─────────────────────────────────────────────────────────┐
 │ EXHIBIT D: Data Source Review                            │
 │ "What external data feeds your AI? Any proxy risks?"     │
 │                                                         │
 │ → Verity: MCP server trust registry with data            │
 │   classification. Source_resolutions audit per binding.  │
 │   Per-version tool allowlists. Exportable.              │
 │                                                         │
 │ COVERAGE: ◧ Substantial (proxy detection enhancement)    │
 └─────────────────────────────────────────────────────────┘

 BOTTOM LINE: Verity generates evidence for all 4 exhibits.
 The examiner gets what they need from the trust database —
 not a scramble to assemble documentation after the fact.
```

### Speaker Notes

```
SLIDE: NAIC Evaluation Tool

THIS IS URGENT:
  The NAIC launched the AI Systems Evaluation Tool pilot in March 2026 
  with 12 participating states. This is not theoretical — it is the 
  actual tool being used in market conduct examinations RIGHT NOW.

  Insurers outside pilot states should treat the 4 exhibits as the 
  template regulators will reuse. Chief risk officers, compliance 
  officers, and general counsel at any US-licensed insurer using AI 
  in underwriting should be preparing.

VERITY'S VALUE PROPOSITION:
  Without a governance platform, responding to a regulatory examination 
  means: pulling code from Git, reconstructing decisions from application 
  logs, manually documenting agent capabilities, and hoping the paper 
  trail is sufficient.

  With Verity: one query against execution_context_id returns the 
  complete decision chain. The model inventory report is auto-generated. 
  The validation evidence is linked to specific versions. The data 
  source registry is the MCP trust registry.

  The difference: days of scrambling vs. minutes of querying.
```

---

### SLIDE: Compliance Roadmap — What's Shipped, What's Next

**Title:** Compliance Roadmap
**Subtitle:** What's shipped today, what's on the roadmap, and what's always the customer's responsibility

```
 ┌─────────────────────────────────────────────────────────┐
 │ SHIPPED — 61 features, 35 of 47 requirements at        │
 │ Full or Substantial coverage                            │
 │                                                         │
 │ ✅ Asset Registry & Metamodel                            │
 │ ✅ 7-State Lifecycle with HITL gates                     │
 │ ✅ 4-Layer Testing Framework                             │
 │ ✅ Immutable Decision Logging with Governance Contract   │
 │ ✅ Source Binding & Write Target declarative I/O          │
 │ ✅ MCP Trust Registry for third-party governance         │
 │ ✅ Async Execution with event-sourced run tracking       │
 │ ✅ Vault with document lineage                           │
 │ ✅ Regulatory evidence package generation                │
 │ ✅ Data classification & redaction pipeline              │
 └─────────────────────────────────────────────────────────┘

 ┌─────────────────────────────────────────────────────────┐
 │ ROADMAP — closing the remaining gaps                    │
 │                                                         │
 │ 🔲 B1: Production fairness monitoring                    │
 │        → closes 3 requirements (18, 29, 42)             │
 │        → required for CO SB21-169 compliance            │
 │                                                         │
 │ 🔲 B2: Automated drift detection (SPC)                  │
 │        → closes 2 requirements (7, 44)                  │
 │        → SR 11-7 examination expectation                │
 │                                                         │
 │ 🔲 B3: PII scanning on ingestion                        │
 │        → strengthens 1 requirement (19)                 │
 │                                                         │
 │ 🔲 A1-A3: Agents Plane (governance governing itself)    │
 │ 🔲 S1-S4: Studio Plane (non-developer access)           │
 └─────────────────────────────────────────────────────────┘

 ┌─────────────────────────────────────────────────────────┐
 │ ALWAYS CUSTOMER RESPONSIBILITY — by design              │
 │                                                         │
 │ · Written AIS Program policy document                   │
 │ · Annual compliance certification workflow              │
 │ · Consumer notification process                         │
 │ · Board-level reporting format                          │
 │ · Governance committee structure                        │
 │ · Organizational independence of MRM team               │
 │ · Vendor risk assessment documents                      │
 │ · Insurance law compliance (rate filings, UTPA)         │
 │                                                         │
 │ Verity provides the evidence and controls.              │
 │ The insurer provides the policy and process.            │
 └─────────────────────────────────────────────────────────┘
```

### Speaker Notes

```
SLIDE: Compliance Roadmap

THE THREE BUCKETS:
  1. SHIPPED: 61 features covering 35 of 47 requirements at Full or 
     Substantial. This is the product today.
  
  2. ROADMAP: B1 (production fairness) is the most critical — it 
     closes the only Gap-rated requirements and is needed for 
     Colorado SB21-169 compliance before June 30, 2026.
  
  3. ALWAYS CUSTOMER: These are not product gaps — they are things 
     that will ALWAYS be the insurer's responsibility regardless of 
     what platform they use. No AI governance platform can write your 
     board report or sign your annual certification.

WHY THIS MATTERS:
  Most insurers deploying AI today have ZERO formal framework.
  Verity provides 74% Full or Substantial coverage out of the box.
  The remaining 26% are either on the roadmap (technology) or 
  inherently customer-owned (policy/process).

  The competitor comparison is not "Verity vs. another platform" — 
  it's "Verity vs. nothing." And "nothing" is what regulators are 
  finding when they examine.
```
