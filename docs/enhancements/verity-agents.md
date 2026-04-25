# Verity Agents — Governance Automation

> **Status:** planned (not built)
> **Source:** [vision.md § Verity Agents (future)](../vision.md), [architecture/technical-design.md](../architecture/technical-design.md)
> **Priority:** high (the main forward roadmap item beyond production-hardening)

## What's missing today

Three operational tasks today require a human to notice, initiate, and drive:

1. **Drift detection.** Nobody is continuously watching the decision log for distribution shift, accuracy regression, or override-rate anomalies. Drift is caught by accident, not by design.
2. **Lifecycle initiation.** When a champion's metrics regress, somebody has to manually clone it into a candidate and start the promotion sequence.
3. **Validation routing.** Validation runs land in the database, but routing the result to the right SME, collecting their sign-off, and advancing the version through `staging → shadow → challenger → champion` is all manual.

## Proposed approach

Three governance-plane agents, **themselves Verity-governed** (registered, versioned, validated, decision-logged like any other agent):

### Agent 1 — Drift Detector

- Reads from `agent_decision_log`, `model_invocation_log`, `override_log`
- Compares running distributions of confidence_score, output classes, override rate, latency, and token consumption against baselines stored at promotion time
- When any metric crosses a threshold (configurable per entity, per materiality tier), opens an `incident` row and notifies the entity owner

### Agent 2 — Lifecycle Initiator

- Subscribes to incidents from Agent 1 (and to failed validation runs)
- Decides whether to draft a new candidate version (clone-and-edit from champion)
- Pre-fills the change summary with observed drift / failure context
- Hands the draft to a human author for prompt/config tuning, then re-enters the lifecycle at `candidate`

### Agent 3 — Validator with HITL Gates

- Triggers validation runs against candidate versions on a defined schedule
- Routes results to a designated SME via the existing `approval_record` flow
- Advances the version through promotion gates only after each HITL gate is signed off
- Falls back to human escalation on any unexpected metric regression

## What's already in place

The scaffolding these agents need is shipped:

- `incident` table for drift events
- `approval_record` for HITL gates
- `override_log` for override-rate analysis
- `validation_run` + `validation_record_result` for scheduled validation
- 7-state lifecycle with promotion API
- Clone-and-edit authoring (`cloned_from_version_id` lineage)

What's *not* in place: the agent definitions themselves (prompts, tools, inference configs) and the scheduling/triggering layer.

## Acceptance criteria

- All three agents registered as `materiality_tier = high` Agents in the asset registry
- Each has a documented test suite + ground truth dataset for its own validation
- Each writes to the standard `agent_decision_log` with `application = 'verity_agents'`
- Drift Detector runs on a schedule (cron / NATS) and produces an incident in <60s of detected drift
- Lifecycle Initiator's drafts are accepted by the lifecycle API (no special-case path)
- Validator's gate sign-offs flow through the same HITL approval UI used by humans

## Notes

The recursion is intentional: the governance system governing itself. Each Verity Agent's decisions are logged and auditable just like any other agent — including its drift detection conclusions and lifecycle initiation decisions. A regulator asking "why did you promote this model" gets the same answer for human-driven and Verity-Agent-driven promotions.
