# Decision Logging Levels — Verity Governance Architecture

## Problem

The `agent_decision_log` table stores the full payload of every AI invocation — including `input_json`, `output_json`, `message_history`, and `tool_calls_made`. This creates two problems:

1. **Bloat**: When a classifier receives PDF content blocks (base64), the entire ~670KB base64 string is stored in `input_json` and again in `message_history`. A single pipeline run with 3 PDFs produces ~4MB of base64 in the database.

2. **No control**: Every invocation logs everything. There's no way to say "log the triage agent's full reasoning but skip the classifier's input payload." In production, a high-volume extraction task might run 10,000 times/day — logging full inputs for all of them is wasteful.

## Design: Two Separate Concerns

### Concern 1: Application Logging (Python `logging` module)
What goes to stdout/files. Controlled by `LOG_LEVEL` (DEBUG/INFO/WARNING/ERROR). Already implemented. This is for **operations** — debugging, monitoring, alerting.

### Concern 2: Decision Logging (Verity `agent_decision_log` table)
What goes to the governance database. Controlled by `decision_log_detail` configuration. This is for **governance** — audit trail, compliance, replay, regulatory evidence.

These are independent. You can have `LOG_LEVEL=WARNING` (quiet console) with `decision_log_detail=full` (everything in the audit trail), or vice versa.

---

## Decision Log Detail Levels

Five levels, from most to least verbose:

| Level | input_json | output_json | message_history | tool_calls_made | Use case |
|---|---|---|---|---|---|
| `full` | Complete payload | Complete payload | Full conversation | Full call details | Development, debugging, audit reproduction |
| `standard` | Redacted (binary content removed, large fields truncated) | Complete | Redacted (binary content blocks removed) | Names + summaries | **Default for production** |
| `summary` | First 500 chars | First 500 chars | Omitted | Names only (no payloads) | High-volume tasks where you need the audit record but not the payload |
| `metadata` | Omitted | Omitted | Omitted | Omitted | Maximum volume, minimum storage. Status, duration, tokens, entity info only |
| `none` | — | — | — | — | No decision log entry created. **Dangerous for governance** — only for testing/throwaway |

### What "redacted" means

For `standard` level, the engine applies these transformations before writing:

**input_json redaction:**
- Remove any key starting with `_` (internal keys like `_documents`)
- Replace any string value longer than 10KB with `"[REDACTED: {len} chars]"`
- Replace any value matching base64 pattern with `"[REDACTED: base64 content, {len} chars]"`

**message_history redaction:**
- Remove content blocks of type `document` or `image` (replace with `{"type": "document", "redacted": true, "original_size": N}`)
- Truncate text content blocks longer than 5KB

**tool_calls_made redaction:**
- Keep tool name, call order, duration
- Truncate input_data and output_data to 1KB each

### What gets stored when content is redacted

The decision log record indicates what was redacted:

```json
// New field on agent_decision_log
"redaction_applied": {
    "level": "standard",
    "input_fields_redacted": ["_documents", "document_text"],
    "message_blocks_redacted": 3,
    "tool_payloads_truncated": 2
}
```

This way, anyone reading the audit trail knows: "the full input was not captured; here's what was removed and why."

---

## Where Configuration Lives

### Layer 1: Agent/Task Version (registration time)

Add a `decision_log_detail` column to `agent_version` and `task_version` tables:

```sql
ALTER TABLE agent_version ADD COLUMN decision_log_detail VARCHAR(20) DEFAULT 'standard';
ALTER TABLE task_version ADD COLUMN decision_log_detail VARCHAR(20) DEFAULT 'standard';
```

Set at registration time in `register_all.py`:
```python
await verity.registry.register_agent_version(
    agent_id=...,
    decision_log_detail="full",   # triage agent: log everything (high materiality)
    ...
)

await verity.registry.register_task_version(
    task_id=...,
    decision_log_detail="standard",  # classifier: redact PDF content
    ...
)
```

This is the **asset-level default**. Different agents/tasks can have different levels based on their materiality tier and data sensitivity.

### Layer 2: Runtime Override (execution time)

The `execute_pipeline()` and `execute_agent()` calls accept an optional `decision_log_detail` parameter that overrides the asset default for that specific execution:

```python
# Override for a specific pipeline run (e.g., debugging a failure)
result = await verity.execute_pipeline(
    pipeline_name="uw_document_processing",
    context=pipeline_context,
    decision_log_detail="full",  # override: capture everything for this run
)
```

### Layer 3: Global Override (app_settings table)

A global setting that overrides all assets. Useful for switching an entire environment between levels:

```sql
-- In app_settings (or a new verity_db settings table):
INSERT INTO app_settings (key, value) VALUES ('decision_log_detail_override', 'full');
```

When set, this overrides all asset-level and runtime-level settings. Remove the row to go back to per-asset defaults.

### Resolution Order

```
global_override > runtime_parameter > asset_version_default > 'standard'
```

---

## Recommended Defaults by Materiality

| Materiality Tier | Default Level | Rationale |
|---|---|---|
| High (triage, appetite) | `full` | Regulatory requirement. Every input/output must be reproducible. |
| Medium (classifier, extractor) | `standard` | Audit trail needed but PDF base64 is waste. Redact binary, keep text. |
| Low (event logging, status updates) | `summary` | Only need to know it happened, not what the full payload was. |

---

## Schema Changes

### agent_decision_log table

Add two columns:

```sql
-- What detail level was used for this log entry
ALTER TABLE agent_decision_log
    ADD COLUMN decision_log_detail VARCHAR(20) DEFAULT 'standard';

-- What was redacted (null if nothing was redacted)
ALTER TABLE agent_decision_log
    ADD COLUMN redaction_applied JSONB;
```

### agent_version and task_version tables

Add one column each:

```sql
ALTER TABLE agent_version
    ADD COLUMN decision_log_detail VARCHAR(20) DEFAULT 'standard';

ALTER TABLE task_version
    ADD COLUMN decision_log_detail VARCHAR(20) DEFAULT 'standard';
```

---

## Implementation in Execution Engine

The `_log_decision()` method in `execution.py` applies redaction based on the resolved detail level before writing to the database:

```python
async def _log_decision(self, ..., decision_log_detail: str = None):
    # Resolve detail level: global > runtime > asset > default
    level = self._resolve_log_detail(config, decision_log_detail)

    # Apply redaction
    logged_input, logged_output, logged_history, logged_tools, redaction_info = (
        _apply_decision_redaction(level, context, output, message_history, tool_calls_made)
    )

    return await self.decisions.log_decision(DecisionLogCreate(
        ...
        input_json=logged_input,
        output_json=logged_output,
        message_history=logged_history,
        tool_calls_made=logged_tools,
        decision_log_detail=level,
        redaction_applied=redaction_info,
    ))
```

The `_apply_decision_redaction()` function handles each level:

```python
def _apply_decision_redaction(level, input_data, output, history, tools):
    redaction_info = {"level": level}

    if level == "full":
        return input_data, output, history, tools, None  # no redaction

    if level == "metadata" or level == "none":
        return None, None, None, None, redaction_info

    if level == "summary":
        return (
            str(input_data)[:500] if input_data else None,
            str(output)[:500] if output else None,
            None,  # no history
            [{"tool_name": t["tool_name"]} for t in (tools or [])],  # names only
            redaction_info,
        )

    # level == "standard" (default)
    logged_input = _redact_input(input_data, redaction_info)
    logged_history = _redact_message_history(history, redaction_info)
    logged_tools = _redact_tool_calls(tools, redaction_info)
    return logged_input, output, logged_history, logged_tools, redaction_info
```

---

## Interaction with Replay

The `full` level preserves everything needed for `MockContext.from_decision_log()` replay. Lower levels trade replay capability for storage efficiency:

| Level | Can replay? | Notes |
|---|---|---|
| `full` | Yes | Complete message history + tool calls preserved |
| `standard` | Partial | Text content replayable, document content blocks lost |
| `summary` | No | Message history omitted |
| `metadata` | No | Nothing to replay |

The decision log `redaction_applied` field tells the replay system what's missing, so it can fail with a clear error instead of silently producing wrong results.

---

## Implementation Phases

### Phase 1: Redaction function + _log_decision changes
- Create `_apply_decision_redaction()` in execution.py
- Modify `_log_decision()` to accept and resolve detail level
- Apply redaction before writing to DB
- Add `decision_log_detail` and `redaction_applied` columns to schema

### Phase 2: Asset configuration
- Add `decision_log_detail` column to agent_version and task_version
- Update registry to read/write this field
- Update register_all.py seed data with appropriate defaults per entity

### Phase 3: Runtime override
- Add `decision_log_detail` parameter to `execute_agent()`, `execute_task()`, `execute_pipeline()`
- Pass through to `_log_decision()`

### Phase 4: Global override
- Add verity_db settings mechanism (or reuse app_settings pattern)
- Read in `_resolve_log_detail()`
