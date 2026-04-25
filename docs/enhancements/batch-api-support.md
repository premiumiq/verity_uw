# Batch API Support

> **Status:** planned (not built)
> **Source:** [archive/future_capabilities.md FC-6](../archive/future_capabilities.md)
> **Priority:** low — batch is a high-volume production optimization, not relevant to demo

## What's missing today

All executions are synchronous-per-request. For high-volume back-office use cases (e.g., processing a renewal book of 10,000 submissions overnight), the synchronous Anthropic API is wasteful — Anthropic's Batch API offers ~50% cost savings with a 24-hour SLA, perfect for non-interactive batch work.

## Proposed approach

A new `batch_run_tasks` SDK method that:

1. Accepts a list of task invocations (each with input + workflow_run_id + execution_context_id)
2. Assembles them into an Anthropic Batch API request
3. Submits and stores a `batch_request` row capturing the batch ID, item count, submitted-at, and per-item cross-references
4. Polls for completion (or accepts a webhook from Anthropic)
5. On completion, walks the results, writes one `agent_decision_log` row per item plus one `model_invocation_log` row per item (with the batch discount factored into the cost calculation)
6. Notifies the caller (callback or table-poll)

```python
batch = await verity.batch_run_tasks(
    task_name="document_classifier",
    items=[
        {"input": {...}, "execution_context_id": ctx, "workflow_run_id": wr1},
        {"input": {...}, "execution_context_id": ctx, "workflow_run_id": wr2},
        ...
    ],
)
# batch.id, batch.item_count, batch.estimated_completion
```

Decision logs from a batch are indistinguishable from synchronous decision logs except for a `batch_request_id` column linking them back.

## Acceptance criteria

- `batch_request` table with status, item count, submitted/completed timestamps
- `agent_decision_log.batch_request_id` column added
- `verity.batch_run_tasks` SDK method
- Worker / cron poller that finalizes completed batches
- Cost view (`v_model_invocation_cost`) honors batch discount

## Notes

Don't build batch for Agents — batch only makes sense for tasks (single-shot, no tool loop). Agents need the interactive loop and aren't compatible with the Batch API contract.
