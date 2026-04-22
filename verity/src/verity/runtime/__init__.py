"""Verity runtime plane — execution of agents, tasks, and pipelines.

This subpackage holds the execution machinery:

- engine             — the agentic loop (will be swapped to Claude Agent SDK in Phase 3)
- pipeline           — multi-step orchestrator with dependency resolution
- test_runner        — executes test suites against entity versions
- validation_runner  — runs entity versions against ground truth datasets
- mock_context       — runtime-side helpers for caller-supplied mocks
- metrics            — pure computation for F1, kappa, field accuracy, etc.
- decisions_writer   — single write: log_decision() to governance's audit table
- tool_registry      — the in-process Python callables dict for tool dispatch
- runtime            — internal facade that wires the above together

Populated over Phase 2 of the registry/runtime split. During the
transition, verity.core.* modules exist as thin shims that re-export
from here so no caller has to change in a single step.
"""
