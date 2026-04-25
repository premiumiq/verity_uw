# Mock Context

> **Tooltip:** Per-call mocking object with four levels: step / tool / source / target. Step mocks are strict (no fall-through).

## Definition

A per-call object passed via `mock=MockContext(...)` that controls what gets mocked. Four independent levels: step_responses (short-circuit a whole step with a fixed response), tool_responses (replace specific tool returns), source_responses (skip connector fetches), target_blocks (skip writes, log only). Step mocks are strict — a missing step fixture raises MockMissingError, never falls through to a live Claude call. Tool-level mocks support partial mocking.

## See also

- [Mock Kind](mock-kind.md)

## Source

[`verity/src/verity/contracts/mock.py`](../../verity/src/verity/contracts/mock.py)
