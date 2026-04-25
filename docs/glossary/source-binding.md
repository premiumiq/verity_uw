# Source Binding

> **Tooltip:** Declarative input I/O row: (reference, binding_kind, maps_to_template_var) defining what to fetch and where to put it.

## Definition

A row in the `source_binding` table, owned by a Task or Agent version, that declares one input wiring: the reference grammar to fetch from, the binding kind (text vs content_blocks), and the template variable to bind it to (for text bindings).

## See also

- [Source Binder](source-binder.md)
- [Reference Grammar](reference-grammar.md)
- [Binding Kind](binding-kind.md)
- [Data Connector](data-connector.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
