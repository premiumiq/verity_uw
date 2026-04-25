# Governance-as-Sidecar for External Orchestrators

> **Status:** designed; API surface ready, no orchestrator integration built
> **Source:** [vision.md § Deployment Topologies](../vision.md), [architecture/execution.md](../architecture/execution.md)
> **Priority:** medium (validates the metamodel-only governance value proposition for shops that won't use Verity Runtime)

## What's missing today

Today Verity Governance and Verity Runtime live in the same process; the consuming app imports the SDK and the SDK calls Runtime methods. The Governance Contract (the canonical decision_log row shape) is documented but not exercised by any non-Verity-Runtime caller.

What's missing:

- A reference integration that proves an external orchestrator (LangGraph, CrewAI, Bedrock Agents, Anthropic Agent SDK) can run an agent and report into Verity Governance via the contract
- Documentation of the contract handoff points (which Governance reads to invoke from outside; which writes to satisfy)
- A "governance-only" deployment mode for `verity` that disables Runtime endpoints

## Proposed approach

### Reference integration

Pick one orchestrator (probably LangGraph — easiest API surface) and build a thin adapter:

1. Adapter calls Verity Governance `GET /api/v1/agents/{name}/champion` to get the resolved configuration (prompts, tools, inference config) for the current champion
2. Adapter assembles its own prompt and calls Claude (or another LLM)
3. Adapter calls Verity Governance `POST /api/v1/decisions` with a fully-populated decision_log payload matching the Governance Contract
4. Decision rows are indistinguishable from Verity-Runtime-produced rows except for the `submitted_by` field

### Governance-only mode

Add a `VERITY_RUNTIME_ENABLED` env var (default `true`). When `false`:

- Runtime SDK methods raise `RuntimeDisabledError` if called in-process
- `/runs/*` endpoints return 404
- The worker doesn't start
- Only Governance read APIs and the decision-log write endpoint are exposed

This is the deployable shape for shops that bring their own orchestrator.

### Contract documentation

A new `docs/architecture/governance-contract.md` (small, focused) extracted from `vision.md § The Governance Contract` and `architecture/execution.md`. Spells out exactly which fields are mandatory, how to handle parent_decision_id for sub-agents, and how `model_invocation_log` rows pair with decisions.

## Acceptance criteria

- Working LangGraph adapter that runs `triage_agent` end-to-end and produces a decision_log row that passes the same audit-trail UI as a Verity-Runtime-produced row
- `VERITY_RUNTIME_ENABLED=false` deployment works in Docker Compose
- Governance Contract doc exists and is the authoritative spec for external integrations
- A second orchestrator (CrewAI or Bedrock) integrated as a smoke test

## Notes

This is the "Verity Governance is the governance layer that any orchestrator reports to" pitch. Important for the long-term positioning even if no shop adopts the sidecar mode in year one.
