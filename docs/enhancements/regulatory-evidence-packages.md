# Regulatory Evidence Packages

> **Status:** partial — underlying data shipped; package generators stubbed
> **Source:** [vision.md § Compliance & Reporting](../vision.md), [vision.md § Five Capabilities — 05 COMPLY](../vision.md)
> **Priority:** medium-high (the actual product output a CIO will demo to a regulator)

## What's missing today

Verity has all the data needed to produce regulator-ready evidence packages — model inventory, decision log, override log, validation runs, ground truth, model cards, lifecycle approval records — but the *packages themselves* are not generated. A request for "show me the SR 11-7 model risk artifacts for Q3" is answered by hand-assembling pieces from various admin pages.

## Proposed approach

Build one generator per regulatory framework. Each consumes governance data and emits a single bundle (HTML report + supporting JSON / CSV exhibits). All produced on demand from live data — no nightly snapshots, no manual editing.

### Frameworks in scope

| Framework | What it expects | Verity sources |
|---|---|---|
| **SR 11-7** (Fed model risk guidance) | Model inventory, model cards, validation evidence, change management trail, override analysis | `agent`/`task`, `model_card`, `validation_run` + results, `agent_decision_log`, `lifecycle_approval`, `override_log` |
| **NAIC AI Model Bulletin** | Transparency, governance, testing, monitoring | Same as SR 11-7, plus quota/incident history |
| **CO SB21-169** (Colorado AI insurance bill) | Adverse-action explainability, bias testing | `agent_decision_log` (with `submission_id` ref), `validation_run` (bias-tagged), `override_log`, ground truth IAA metrics |
| **NIST AI RMF** | Govern / Map / Measure / Manage evidence | Cross-cutting selection from all of the above |
| **ISO 42001** | AI management system controls | Cross-cutting selection |

### Generator architecture

Each generator is a `regulatory_evidence_*` Python module that:

1. Accepts scope params (date range, application, materiality_tier filter)
2. Queries the relevant tables
3. Renders an HTML report from a Jinja template
4. Bundles supporting CSV / JSON exhibits
5. Returns a downloadable `.zip`

Reports are themselves logged: a `regulatory_evidence_export` table records who exported what, when, with which params (so the export itself is auditable).

### UI

A new `/admin/compliance` page:

- Pick framework (SR 11-7, NAIC, CO SB21-169, NIST, ISO 42001)
- Pick scope (date range, application, materiality)
- Click Generate → background job assembles the bundle → download link

## Acceptance criteria

- At least SR 11-7 and CO SB21-169 generators ship
- Each generator's output passes a manual review by someone familiar with the framework
- The export action writes a `regulatory_evidence_export` audit row
- Every value in the report is traceable back to the source row(s) by ID (no derived numbers without provenance)

## Notes

Don't try to make these "submit-ready". The product promise is *evidence packages*, not auto-filed regulatory submissions. A human reviewer always inspects before sending to a regulator. Focus on completeness and traceability over polish.
