# Verity Glossary

A term-per-file reference for Verity's vocabulary. Stays in sync with [`architecture/`](../architecture/) and the database schema.

## How to use this glossary

**Major user-facing docs** (README, vision, getting-started, [example-end-to-end.md](../example-end-to-end.md)) wrap each term's first occurrence in an `<abbr>` so hovering shows the tooltip and clicking navigates here:

```markdown
The <abbr title="Pre-LLM resolver that fetches data per source_binding row...">[Source Binder](../glossary/source-binder.md)</abbr> fetches data...
```

**Detailed reference docs** (the [application guide](../development/application-guide.md), `architecture/*`, `enhancements/*`) use plain links without `<abbr>` to keep the source readable:

```markdown
The [Source Binder](../glossary/source-binder.md) fetches data...
```

In both cases, the linked file is this directory. Both work in GitHub, GitLab, and VS Code's Markdown preview.

## When to add a term

Add an entry when a term:

1. Appears in more than one doc, **and**
2. Has a non-obvious meaning that a new reader would need to look up, **and**
3. Doesn't already have a canonical 1-line definition somewhere obvious.

Don't add: implementation details that change every release; project management terms; anything documented only for historical context (those belong in `archive/`).

## Term file template

```markdown
# Term Name

> **Tooltip:** One sentence. Plain text only — used in `<abbr title=...>`.

## Definition

One paragraph. Be precise.

## See also

- [Related Term](other-term.md)

## Source

[`path/to/canonical/source`](../../path/to/canonical/source)
```

Filenames are kebab-case, matching the term name.

---

## Index

| Term | One-liner |
|---|---|
| [Agent](agent.md) | Multi-turn agentic loop with tool use and (optionally) sub-agent delegation. Authorized tools per version. |
| [Application](application.md) | Consuming business app registered with Verity; every entity and decision is scoped/attributed to one or more applications. |
| [Approval Record](approval-record.md) | Per-promotion-gate sign-off row: who approved, what evidence reviewed, rationale. |
| [Asset Registry](asset-registry.md) | Verity Governance subsystem storing every governed entity as a versioned database record. |
| [Binding Kind](binding-kind.md) | Whether a source_binding produces a template variable string (text) or Claude content blocks (content_blocks, e.g. PDF vision input). |
| [Capability Type](capability-type.md) | Entity classifier (classification/extraction/judgment/generation/matching/validation) shaping default validation metrics. |
| [Champion Resolution](champion-resolution.md) | How Verity picks which version to run: default current champion, date-pinned (SCD-2 temporal), or version-pinned by ID. |
| [Channel](channel.md) | Per-call hint (production / staging / shadow / challenger / champion / validation) that drives default write behavior. |
| [Data Classification](data-classification.md) | Max sensitivity an entity may handle (public/internal/confidential/restricted); filters tool authorizations. |
| [Data Connector](data-connector.md) | Registered integration providing fetch/write methods used by source_bindings and write_targets. Vault is the canonical example. |
| [Decision Log](decision-log.md) | One immutable row per AI invocation in agent_decision_log capturing prompts, config, I/O, tool calls, tokens, durations. |
| [Enforce Output Schema](enforce-output-schema.md) | Per-call agent option that injects a synthetic submit_output tool to structurally guarantee output. |
| [Evaluation Run](evaluation-run.md) | Lighter-weight scoring of an entity against test cases or selected ground-truth slices; not a promotion gate. |
| [Execution Context](execution-context.md) | Business-level grouping registered by the consuming app; opaque to Verity. Scopes runs to a customer-facing operation (e.g. submission). |
| [Execution Run](execution-run.md) | Event-sourced record of one Task or Agent invocation; lifecycle events live in execution_run_status. |
| [Governance Tier](governance-tier.md) | Prompt-level flag (standard/high) gating conditional template sections for high-materiality entities. |
| [Governed Entity](governed-entity.md) | Supertype: anything Verity tracks as a versioned record (Agent, Task, Prompt, Tool, Pipeline). |
| [Ground Truth Dataset](ground-truth-dataset.md) | SME-labeled data scoped to one governed entity. Three tables: dataset (metadata), record (input items), annotation (labels). |
| [Incident](incident.md) | Production triage row: legacy incidents + active quota breaches. Surfaces in the unified Incidents page. |
| [Inference Config](inference-config.md) | Versioned LLM API parameter set: model, temperature, max_tokens, extended_params. Frozen on entity version promotion. |
| [Lifecycle State](lifecycle-state.md) | Seven states an entity version moves through: draft → candidate → staging → shadow → challenger → champion → deprecated. |
| [Materiality Tier](materiality-tier.md) | Per-entity risk tier (low/medium/high) that drives lifecycle gate strictness and validation thresholds. |
| [MCP Server](mcp-server.md) | Registered MCP server endpoint used as a transport for tools whose transport='mcp_*'. |
| [Metric Threshold](metric-threshold.md) | Configured pass/fail thresholds for validation run metrics; per-entity, per-materiality-tier. |
| [Mock Context](mock-context.md) | Per-call mocking object with four levels: step / tool / source / target. Step mocks are strict (no fall-through). |
| [Mock Kind](mock-kind.md) | Type discriminator on a test_case_mock: tool / source / target. Step-level mocks live on MockContext only. |
| [Model Card](model-card.md) | Per-entity documentation of purpose, design, limitations, conditions of use, validation evidence (SR 11-7 style). |
| [Override Log](override-log.md) | Separate immutable record of a human disagreeing with an AI decision; preserves both AI recommendation and human decision. |
| [Parent Decision](parent-decision.md) | FK on agent_decision_log linking a sub-agent's decision to its parent; decision_depth records the depth in the delegation tree. |
| [Prompt Version](prompt-version.md) | Versioned prompt template with governance_tier. Pinned to entity versions; immutable after promotion. |
| [Quota](quota.md) | Spend or invocation-count budget scoped by application/model/entity over a rolling time window. Soft today; hard enforcement is an enhancement. |
| [Reference Grammar](reference-grammar.md) | Four-pattern DSL for I/O wiring: input.*, output.*, const:*, fetch:connector/method(input.X). |
| [Run Purpose](run-purpose.md) | Reason for an execution: production / test / validation / audit_rerun. Independent of channel. |
| [Source Binder](source-binder.md) | Pre-LLM resolver that fetches data per source_binding row and binds to template vars or content blocks. |
| [Source Binding](source-binding.md) | Declarative input I/O row: (reference, binding_kind, maps_to_template_var) defining what to fetch and where to put it. |
| [Sub-Agent Delegation](sub-agent-delegation.md) | Built-in delegate_to_agent meta-tool; parent → child relationships authorized via agent_version_delegation. |
| [Target Payload Field](target-payload-field.md) | One row per output field per write_target; uses reference grammar to map LLM output fields to a connector payload. |
| [Task](task.md) | Single-shot LLM call with input_schema → structured output_schema. No tool loop, no sub-agents. |
| [Verity Planes](verity-planes.md) | The four logical layers of Verity: Governance (registry, lifecycle, audit), Runtime (execution, connectors, MCP), Agents (future automation), Studio (future UI authoring). |
| [Tool](tool.md) | Callable action available to an Agent; has a transport (python_inprocess or mcp_*) and is authorized per agent version. |
| [Tool Authorization](tool-authorization.md) | Per-agent-version `agent_version_tool` row authorizing one tool. Unauthorized tool calls are rejected and Claude is informed. |
| [Trust Level](trust-level.md) | Entity flag (experimental/supervised/autonomous) hinting at HITL expectations. |
| [Validation Run](validation-run.md) | Execution of an entity version against every record in a ground-truth dataset; computes aggregate metrics, gates staging→shadow. |
| [Vault](vault.md) | Companion document service (collections, lineage, tags, text extraction). Independent DB. Verity reaches it via the canonical data_connector. |
| [Workflow Run ID](workflow-run-id.md) | Caller-supplied UUID threaded through every execute_* call in one workflow so the audit clusters correctly. |
| [Write Mode](write-mode.md) | Per-call override (auto / log_only / write) for declared target writes; auto = channel-gated default. |
| [Write Target](write-target.md) | Declarative output I/O row: (connector, method, container_ref) describing where to write the LLM output. |
| [Write Target Dispatcher](write-target-dispatcher.md) | Post-LLM subsystem that fires every write_target row, building payloads from target_payload_field references. |

---

_48 terms._
