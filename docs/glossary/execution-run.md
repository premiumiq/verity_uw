# Execution Run

> **Tooltip:** Event-sourced record of one Task or Agent invocation; lifecycle events live in execution_run_status.

## Definition

An append-only row in `execution_run` representing one submitted invocation. Lifecycle is event-sourced across four tables (`execution_run`, `execution_run_status`, `execution_run_completion`, `execution_run_error`) and surfaced via the `execution_run_current` view. States: submitted → claimed → running → completed | failed | released.

## See also

- [Workflow Run ID](workflow-run-id.md)
- [Decision Log](decision-log.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
