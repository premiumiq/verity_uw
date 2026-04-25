# Data Classification

> **Tooltip:** Max sensitivity an entity may handle (public/internal/confidential/restricted); filters tool authorizations.

## Definition

An enum field bounding the data sensitivity an entity may interact with. Tools whose `data_classification_max` exceeds this bound are filtered out at authorization time, preventing accidental escalation.

## See also

- [Tool](tool.md)
- [Tool Authorization](tool-authorization.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
