# Hard Quota Enforcement + Scheduled Checker + Notifications

> **Status:** partial — soft quotas shipped, hard enforcement and scheduling not built
> **Source:** [vision.md § Quotas & Incidents](../vision.md), schema `quota` / `quota_check` tables
> **Priority:** medium-high (cost-control discipline before opening Verity to multi-tenant use)

## What's missing today

Soft quotas are shipped: `quota` rows define spend / invocation-count budgets scoped by application, model, or entity over a rolling window; an on-demand checker writes `quota_check` rows showing breaches; the Incidents page surfaces active breaches.

What's **not** there:

- **Hard enforcement at invocation time** — quota state is informational. Nothing in the runtime path blocks a `run_task` / `run_agent` call when a quota is over budget.
- **Scheduled checker** — quota evaluation is on-demand only. No background job re-runs checks every N minutes.
- **Notifications** — breaches surface in the UI but no Slack / email / PagerDuty webhook fires.

## Proposed approach

### Hard enforcement at runtime

Add a pre-flight check in the Execution Engine, between `submit_run` and `claim_run`:

1. Resolve all `quota` rows whose scope matches the run (application, model, entity).
2. For each, query rolling-window usage from `model_invocation_log` (joined to `model_price` for spend).
3. If any quota is over budget AND has `enforcement_mode = 'hard'`, fail the submission with `QuotaExceededError` and write an `execution_run_error` row.
4. If `enforcement_mode = 'soft'` (the current default), proceed and write a `quota_check` row noting the over-budget state — same behaviour as today.

Add an `enforcement_mode` column to `quota` (default `'soft'`).

### Scheduled checker

A new `verity-quota-checker` worker (similar to `verity-worker`) that wakes every 5 minutes, evaluates all `quota` rows whose `enabled=true`, and writes `quota_check` rows. State change (newly-firing or newly-resolved) emits a notification event.

### Notifications

Add a `notification_target` table:

```
id, scope_type, scope_id, channel (slack|email|webhook),
config (jsonb — webhook URL, slack channel, email list),
events (jsonb array — quota.fired, quota.resolved, incident.opened, ...)
```

The scheduled checker (and the incident creation path) emit events; a small dispatcher consults `notification_target` and POSTs / sends accordingly.

## Acceptance criteria

- `enforcement_mode` column added to `quota` with migration; default `'soft'` preserves current behaviour
- New `QuotaExceededError` raised at submit time when a hard quota is over budget
- `verity-quota-checker` Docker service ships in `docker-compose.yml`; runs every 5 minutes
- At least one notification channel (Slack webhook) reaches end-to-end test parity
- The Incidents page shows the same quota state whether evaluated on-demand or by the scheduled checker

## Notes

Keep `soft` as default — turning hard enforcement on by accident in the demo would break things. Hard mode is per-quota, opt-in.
