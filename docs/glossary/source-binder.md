# Source Binder

> **Tooltip:** Pre-LLM resolver that fetches data per source_binding row and binds to template vars or content blocks.

## Definition

A subsystem of the Verity Runtime that, immediately before prompt assembly, walks every source_binding row registered for the target Task or Agent version, resolves each binding's reference, and binds the result to either a template variable or a list of Claude content blocks.

## See also

- [Source Binding](source-binding.md)
- [Reference Grammar](reference-grammar.md)
- [Binding Kind](binding-kind.md)

## Source

[`verity/src/verity/runtime/engine.py`](../../verity/src/verity/runtime/engine.py)
