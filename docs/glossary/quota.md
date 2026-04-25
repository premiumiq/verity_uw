# Quota

> **Tooltip:** Spend or invocation-count budget scoped by application/model/entity over a rolling time window. Soft today; hard enforcement is an enhancement.

## Definition

A row in `quota` defining a spend or invocation-count budget scoped by application, model, or entity over a rolling time window (daily/weekly/monthly). Today: soft (informational only) — `quota_check` rows record breach state and surface in the Incidents UI. Hard enforcement at invocation time is planned (see [`enhancements/hard-quotas.md`](../enhancements/hard-quotas.md)).

## See also

- [Incident](incident.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
