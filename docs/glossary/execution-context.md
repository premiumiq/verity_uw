# Execution Context

> **Tooltip:** Business-level grouping registered by the consuming app; opaque to Verity. Scopes runs to a customer-facing operation (e.g. submission).

## Definition

A row in `execution_context` registering one business operation (`context_ref` is opaque to Verity; the app defines what it means). Scoped per application. One execution_context can span many workflow_run_ids — e.g. an initial document workflow plus a later risk-assessment workflow on the same submission.

## See also

- [Application](application.md)
- [Workflow Run ID](workflow-run-id.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
