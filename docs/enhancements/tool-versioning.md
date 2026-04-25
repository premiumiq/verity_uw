# Tool Versioning

> **Status:** planned (not built); foundational gap for full audit replay
> **Source:** [archive/future_capabilities.md FC-13](../archive/future_capabilities.md)
> **Priority:** high — needed for full version-pinned execution and audit completeness; not blocking demo

## What's missing today

`agent` and `task` have full version tables (`agent_version`, `task_version`). `prompt` has `prompt_version`. `inference_config` is treated as a frozen reference. **Tools** are different: the `tool` table represents current state only, with no `tool_version` table.

This breaks the version-composition immutability principle:

- Tool implementation changes are not tracked (no version history)
- Tool implementations cannot be version-pinned at execution time
- Agent versions reference `tool_id`, not `tool_version_id` — which means the tool implementation under an agent version can silently change
- Audit replay cannot verify that the same tool implementation was used as the original run

## Proposed approach

Add `tool_version`, mirroring `agent_version` / `task_version`:

```sql
CREATE TABLE tool_version (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tool_id             UUID NOT NULL REFERENCES tool(id),
    major_version       INTEGER NOT NULL DEFAULT 1,
    minor_version       INTEGER NOT NULL DEFAULT 0,
    patch_version       INTEGER NOT NULL DEFAULT 0,
    version_label       VARCHAR(20) GENERATED ALWAYS AS
                        (major_version::text || '.' || minor_version::text || '.' || patch_version::text) STORED,
    lifecycle_state     lifecycle_state NOT NULL DEFAULT 'draft',
    implementation_path VARCHAR(500) NOT NULL,
    input_schema        JSONB NOT NULL,
    output_schema       JSONB NOT NULL,
    mock_responses      JSONB DEFAULT '{}',
    valid_from          TIMESTAMP,
    valid_to            TIMESTAMP,
    change_summary      TEXT,
    developer_name      VARCHAR(200),
    created_at          TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_tool_version UNIQUE (tool_id, major_version, minor_version, patch_version)
);
```

Update junction tables `agent_version_tool` and `task_version_tool` to reference `tool_version_id` instead of `tool_id`. Same for `mcp_server` (if we adopt versioning of MCP server registrations).

Migration plan:

1. Create `tool_version` table; back-fill one v1.0.0 row per existing `tool` row
2. Add nullable `tool_version_id` columns alongside the existing `tool_id` on the junction tables
3. Back-fill the new columns from the v1.0.0 versions
4. Make `tool_version_id` NOT NULL, drop the old `tool_id` columns

## Acceptance criteria

- `tool_version` table + back-fill migration
- `agent_version_tool.tool_version_id` and `task_version_tool.tool_version_id` populated; old `tool_id` columns dropped
- New tool implementations require a new `tool_version` row; the runtime resolves the pinned version
- Audit replay successfully resolves the historical tool implementation given a decision_log row from before the change

## Notes

This is the last gap in version composition immutability. Until it lands, "the model that was validated is the model that runs in production" has an asterisk: tool implementations may have changed silently.
