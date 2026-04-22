"""Verity governance plane — registry, lifecycle, decision log, compliance.

This subpackage holds everything that Verity the governance platform does,
independent of how any particular execution runs:

- registry     — agent/task/prompt/tool/pipeline/inference_config definitions
- lifecycle    — the 7-state machine, promotion gates, approval records
- decisions    — audit trail reads + override writes
- reporting    — dashboard + model inventory aggregations
- testing_meta — test suite / ground truth metadata (not execution)
- coordinator  — internal facade that wires the above together

Populated over Phase 2 of the registry/runtime split. During the
transition, verity.core.* modules exist as thin shims that re-export
from here so no caller has to change in a single step.
"""
