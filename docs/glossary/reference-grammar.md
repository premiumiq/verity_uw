# Reference Grammar

> **Tooltip:** Four-pattern DSL for I/O wiring: input.*, output.*, const:*, fetch:connector/method(input.X).

## Definition

The reference DSL used uniformly by source_binding rows and target_payload_field rows. Four patterns: `input.<path>` (caller-supplied input), `output.<path>` (the unit's own output, write targets only), `const:<literal>` (baked-in constant), `fetch:<connector>/<method>(input.<field>)` (connector call at resolution time, sources only). Path grammar uses dotted keys plus bracketed integer indices (`docs[0].kind`). No JSONPath, no arithmetic, no conditionals.

## See also

- [Source Binding](source-binding.md)
- [Write Target](write-target.md)
- [Target Payload Field](target-payload-field.md)

## Source

[`docs/architecture/execution.md`](../../docs/architecture/execution.md)
