# Task

> **Tooltip:** Single-shot LLM call with input_schema → structured output_schema. No tool loop, no sub-agents.

## Definition

One of two execution units in Verity. Bounded, single-purpose: validates `input_data` against `input_schema`, resolves source bindings, calls Claude once with no tools, parses output, validates against `output_schema`, fires write targets. Use Tasks for classification, extraction, summarization, scoring — any single-shot mapping with a clear structured output.

## See also

- [Agent](agent.md)
- [Source Binding](source-binding.md)
- [Write Target](write-target.md)

## Source

[`verity/src/verity/runtime/engine.py`](../../verity/src/verity/runtime/engine.py)
