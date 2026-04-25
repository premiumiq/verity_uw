# End-to-End Execution Event Streaming

> **Status:** partial — `ExecutionEvent` contract present; UI not subscribed
> **Source:** [vision.md § Runtime plane](../vision.md), `verity/src/verity/contracts/`
> **Priority:** medium (improves UX during long runs; not blocking demo)

## What's missing today

The Runtime emits an `ExecutionEvent` stream during each agent / task invocation (turn-started, tool-called, tool-returned, claude-responded, completed) and the contract object exists. What's not finished:

- Workers don't publish the events to a transport that the UI can subscribe to. They land in logs and decision_log, not on a wire.
- The Admin UI's run detail page polls `execution_run_current` for status; it doesn't show streaming intermediate events.
- HTMX SSE endpoint not wired.

## Proposed approach

### Transport

Two acceptable options, decide before implementation:

- **Postgres LISTEN/NOTIFY** — simplest. Worker writes the event to a `runtime_event` table AND issues `NOTIFY runtime_event_<run_id>`. UI subscribes via `LISTEN`. No new infra. Limit: one postgres backend, ~8KB payload max.
- **NATS JetStream** — already proposed in the K8s plan as the Phase 2.5 dispatch layer. If we adopt NATS for run dispatch, reuse the same broker for events.

Postgres LISTEN/NOTIFY first; NATS later when K8s lands.

### UI subscription

Add an HTMX SSE endpoint at `/admin/runs/{run_id}/events` that:

1. Opens a Postgres LISTEN on `runtime_event_<run_id>`
2. Streams events as `text/event-stream`
3. Closes when the run reaches a terminal state (`completion` or `error`)

The run detail page swaps in event lines as they arrive — turn started, tool called, tool returned, decision logged.

### Event shape (already defined)

```python
class ExecutionEvent(BaseModel):
    run_id: UUID
    event_kind: Literal["turn_started", "tool_called", "tool_returned",
                        "claude_responded", "decision_logged", "completed", "errored"]
    timestamp: datetime
    payload: dict  # event-specific
```

## Acceptance criteria

- New `runtime_event` append-only table; worker inserts one row per event
- Worker also fires `NOTIFY` on insert
- `/admin/runs/{id}/events` SSE endpoint streams to a connected UI
- Run detail page renders events as they arrive (HTMX `hx-sse`)
- Events stop streaming when terminal status hits

## Notes

The decision_log row remains the canonical post-hoc record. Events are the in-flight overlay. They are not the audit trail.
