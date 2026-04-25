# Write Target

> **Tooltip:** Declarative output I/O row: (connector, method, container_ref) describing where to write the LLM output.

## Definition

A row in the `write_target` table, owned by a Task or Agent version, that declares one post-LLM write: the connector and method to call, plus a container reference (e.g. parent document ID for Vault writes). Payload fields are described separately by target_payload_field rows.

## See also

- [Target Payload Field](target-payload-field.md)
- [Write Target Dispatcher](write-target-dispatcher.md)
- [Channel](channel.md)
- [Write Mode](write-mode.md)
- [Data Connector](data-connector.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
