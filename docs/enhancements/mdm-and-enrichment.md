# MDM + Enrichment Shared Services

> **Status:** planned (not built); sits alongside Vault as future shared services
> **Source:** [vision.md § Shared Services](../vision.md), [vision.md § The Three-Layer Architecture](../vision.md)
> **Priority:** low for v0.1; medium once Verity goes beyond a single app

## What's missing today

Vault is the only shared service that exists. The product vision lists two more in the same architectural slot:

- **MDM (Master Data Management)** — entity resolution, golden record management, matching rules. The "is Acme Corp the same as Acme Corporation Ltd." problem.
- **Enrichment Services** — third-party data feeds (LexisNexis litigation history, D&B financials, PitchBook company intel, regulatory feeds).

Without these, agents that need clean entity identifiers or external context end up coding the resolution / fetch logic into tools, which is fine for a demo but doesn't scale across applications.

## Proposed approach

### MDM service (`mdm`, port 8003)

Independent service, own database (`mdm_db`), own UI. Same architectural pattern as Vault:

- REST API for entity CRUD, match-resolve, golden-record lookup
- Verity reaches it through `data_connector` (for declarative source binding) and through a tools (for agent-driven matches)
- Matching rules are governed records in `mdm_db` (not Verity's metamodel — MDM has its own governance)

### Enrichment services (`enrichment`, port 8004)

Single service that proxies multiple external providers (LexisNexis, D&B, PitchBook, OFAC sanctions, FAA registry, etc.). Each provider exposed as:

- A Verity `data_connector` `fetch_method` (e.g., `fetch:enrichment/get_dnb_financials(input.duns)`)
- Or an MCP tool (when the provider exposes an MCP server)

Caching layer to avoid hammering paid APIs; cache TTLs per provider.

### Connector vs. tool — when to use which

- **Connector** when the data is needed *before* prompt assembly (declarative source binding)
- **Tool** when the agent decides at runtime whether and what to fetch

Most enrichment fits naturally as a tool (agent decides). MDM fits both — declarative source binding for "always normalize the incoming insured name" plus tool for ad-hoc resolution.

## Acceptance criteria

- MDM service shipped as a Docker service with a working entity-resolve endpoint
- Enrichment service shipped with at least one provider integrated (LexisNexis Litigation, since UW agents already need it)
- Both services produce decision-log entries (via Verity tool calls) so the audit trail captures "which external data did this decision use"
- Vault, MDM, and Enrichment all reachable from `docs/apps/`

## Notes

The point of separating these from Verity is the same point as separating Vault: each owns its database and lifecycle. Verity governs the *use* of these services (tool authorizations, source binding declarations) but doesn't host the services or their data.
