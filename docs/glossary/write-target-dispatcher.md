# Write Target Dispatcher

> **Tooltip:** Post-LLM subsystem that fires every write_target row, building payloads from target_payload_field references.

## Definition

A subsystem of the Verity Runtime that, after the LLM call returns, walks every write_target row registered for the unit and either fires the connector write or records a log-only intent (depending on channel and write_mode).

## See also

- [Write Target](write-target.md)
- [Target Payload Field](target-payload-field.md)
- [Channel](channel.md)
- [Write Mode](write-mode.md)

## Source

[`verity/src/verity/runtime/engine.py`](../../verity/src/verity/runtime/engine.py)
