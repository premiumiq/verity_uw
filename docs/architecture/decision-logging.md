# Decision Logging Levels — Verity Governance Architecture

The `agent_decision_log` table stores the logs of every AI invocation — including `input_json`, `output_json`, `message_history`, and `tool_calls_made`. What goes to the governance database. Controlled by `decision_log_detail` configuration. This is for **governance** — audit trail, compliance, replay, regulatory evidence.

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