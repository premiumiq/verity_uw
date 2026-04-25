# Session / Conversation Continuity

> **Status:** planned (not built)
> **Source:** [archive/future_capabilities.md FC-2](../archive/future_capabilities.md)
> **Priority:** low for current single-shot demo, medium for production multi-turn UX (e.g., underwriter chat)

## What's missing today

Each `run_agent()` call starts with a fresh message history. No state is preserved across calls. There is no way to model a multi-turn conversation where an underwriter and an agent go back and forth on a submission with the agent retaining context.

## Proposed approach

A new `session` table captures the conversation state:

```sql
CREATE TABLE session (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type     entity_type NOT NULL,
    entity_name     VARCHAR(100) NOT NULL,
    submission_id   UUID,                  -- or generic context_ref
    message_history JSONB NOT NULL DEFAULT '[]',
    execution_context_id UUID REFERENCES execution_context(id),
    created_at      TIMESTAMP DEFAULT NOW(),
    last_active_at  TIMESTAMP DEFAULT NOW()
);
```

SDK additions:

```python
session = await verity.create_session("triage_agent", submission_id=...)
result1 = await verity.continue_session(session.id, new_message="What's the loss history?")
result2 = await verity.continue_session(session.id, new_message="Why did you score it 65?")
```

Each `continue_session` call:

1. Loads the existing message history from the session row
2. Appends the new user message
3. Calls Claude with the full history
4. Persists the assistant response back into the session
5. Writes a normal `agent_decision_log` row, with a new column `session_id` linking the decision to the conversation

## Acceptance criteria

- `session` table + migrations
- `verity.create_session` / `verity.continue_session` SDK methods
- `agent_decision_log.session_id` column added
- The Admin UI "Audit by submission" view threads conversations together visually
- Concurrent updates to the same session use row-level locking (a session is single-writer)

## Notes

This is the "underwriter chat with the triage agent" use case. Until that UX exists, defer.
