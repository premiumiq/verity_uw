"""Verity runtime plane — execution of agents and tasks.

This subpackage holds the execution machinery:

- engine             — the agentic loop (Claude Messages API, in-process)
- worker             — async run worker that claims execution_run rows
- test_runner        — executes test suites against entity versions
- validation_runner  — runs entity versions against ground truth datasets
- metrics            — pure computation for F1, kappa, field accuracy, etc.
- decisions_writer   — single write: log_decision() to governance's audit table
- tool_registry      — the in-process Python callables dict for tool dispatch
- runtime            — internal facade that wires the above together
"""
