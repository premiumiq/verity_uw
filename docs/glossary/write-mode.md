# Write Mode

> **Tooltip:** Per-call override (auto / log_only / write) for declared target writes; auto = channel-gated default.

## Definition

A per-call enum that overrides the channel default. `auto` = channel decides (default); `log_only` = forced dry run regardless of channel (used by replay, debugging, shadow comparisons); `write` = forced write regardless of channel (production callers only). MockContext.target_blocks always wins — anything in that set is log-only even under write_mode='write'.

## See also

- [Channel](channel.md)
- [Write Target](write-target.md)
- [Mock Context](mock-context.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
