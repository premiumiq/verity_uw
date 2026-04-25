# Prompt Version

> **Tooltip:** Versioned prompt template with governance_tier. Pinned to entity versions; immutable after promotion.

## Definition

A row in the `prompt_version` table representing one immutable version of a prompt template. Carries the template text, governance_tier flag, and metadata. Pinned to entity versions; cannot be modified after the parent entity version leaves draft state.

## See also

- [Governance Tier](governance-tier.md)
- [Lifecycle State](lifecycle-state.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
