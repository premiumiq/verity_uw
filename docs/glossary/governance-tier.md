# Governance Tier

> **Tooltip:** Prompt-level flag (standard/high) gating conditional template sections for high-materiality entities.

## Definition

An enum field on prompt rows used by the Jinja prompt assembler. Prompts can carry conditional sections (`{% if governance_tier == 'high' %}…{% endif %}`) that fire only for entities promoted into high-tier use. A way to express stricter instructions without forking the prompt.

## See also

- [Prompt Version](prompt-version.md)
- [Materiality Tier](materiality-tier.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
