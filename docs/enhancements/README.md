# Verity Future Enhancements

A categorized index of capabilities that are designed but not built, partially shipped, or planned for the next phase. The README links here from its **Future Enhancements** section.

Status legend:

- **planned** — designed, not yet built
- **partial** — schema or contract exists; the feature isn't end-to-end usable
- **designed** — design document exists; integration / adapter work pending

> **Note:** items listed in [vision.md § Full Feature List](../vision.md) as **Coming** or **Partial** all have a corresponding file here.

---

## Production deployment & topology

| File | Status | Priority |
|---|---|---|
| [production-readiness-k8s.md](production-readiness-k8s.md) | planned | high — full K8s migration plan including Vault rename, per-service Dockerfiles, runtime extraction, NATS dispatch (optional), Helm chart, observability |
| [sidecar-topology.md](sidecar-topology.md) | designed | medium — "governance-as-sidecar" mode for external orchestrators (LangGraph, CrewAI, Bedrock) |
| [rest-api-auth.md](rest-api-auth.md) | planned | high — API keys + OIDC for the Admin UI, blocker for any non-localhost deployment |

## Governance automation

| File | Status | Priority |
|---|---|---|
| [verity-agents.md](verity-agents.md) | planned | high — drift detection, lifecycle initiation, validation-with-HITL agents |
| [description-similarity.md](description-similarity.md) | partial | medium — pgvector embeddings for promotion gate |
| [regulatory-evidence-packages.md](regulatory-evidence-packages.md) | partial | medium-high — SR 11-7 / NAIC / CO SB21-169 / NIST / ISO 42001 generators |

## Authoring & UX

| File | Status | Priority |
|---|---|---|
| [verity-studio.md](verity-studio.md) | future, not yet designed | medium-high — UI-driven Compose AI · Lifecycle · Ground Truth · Test Management for non-developer users (a fourth Verity plane) |

## Runtime robustness

| File | Status | Priority |
|---|---|---|
| [rate-limit-retry-backoff.md](rate-limit-retry-backoff.md) | planned | medium — declarative retry policy in `inference_config.extended_params` |
| [streaming-events.md](streaming-events.md) | partial | medium — wire `ExecutionEvent` to UI via Postgres LISTEN/NOTIFY (then NATS later) |
| [batch-api-support.md](batch-api-support.md) | planned | low — Anthropic Batch API for high-volume back-office workloads |
| [session-conversation-continuity.md](session-conversation-continuity.md) | planned | low for demo, medium for production multi-turn UX |
| [system-prompt-caching.md](system-prompt-caching.md) | partial | medium — emit `cache_control` hints to populate Anthropic's prompt cache |

## Quotas, cost, notifications

| File | Status | Priority |
|---|---|---|
| [hard-quotas.md](hard-quotas.md) | partial | medium-high — runtime enforcement, scheduled checker, Slack/email notifications |

## Composition completeness

| File | Status | Priority |
|---|---|---|
| [tool-versioning.md](tool-versioning.md) | planned | high — last gap in version-composition immutability |

## Future shared services

| File | Status | Priority |
|---|---|---|
| [mdm-and-enrichment.md](mdm-and-enrichment.md) | planned | low for v0.1 — MDM (entity resolution) + Enrichment (LexisNexis / D&B / PitchBook) as shared services alongside Vault |

## UI

| File | Status | Priority |
|---|---|---|
| [gui-sort-search-filter.md](gui-sort-search-filter.md) | planned | medium — generalized table sort/search/filter spec for Admin UI |

---

## Explicitly out of scope

These were proposed and **rejected** with documented rationale. They are not on the roadmap. See [archive/future_capabilities.md FC-3](../archive/future_capabilities.md) for the full case.

| What was proposed | Why rejected |
|---|---|
| **Pre/post agent execution hooks** (imperative middleware) | Every concrete use case is already covered by a *declarative* governance primitive (`input_schema`, `output_schema`, quotas, tool flags, declarative targets). Imperative hooks would sit outside the metamodel — unversioned, invisible to governance reviewers, untested at admit time. The "extension point" itself is the bug. |

---

## How to add a new enhancement

1. Create a new `kebab-case.md` file in this directory.
2. Use the standard header (Status / Source / Priority).
3. Add a row in the right table above.
4. If the source is a still-relevant doc in `docs/archive/`, link it.
