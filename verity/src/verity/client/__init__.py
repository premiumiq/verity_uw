"""Verity client SDK — what consuming applications use to talk to Verity.

This subpackage holds the consumer-facing ergonomic wrapper that UW (and
future apps like Claims, Renewals, etc.) import to get at both the
governance plane and the runtime plane.

- inprocess — direct Python calls: governance coordinator + runtime facade,
              both wired in one process. Used during Phases 1-4 and for
              tests/dev where running three containers is overkill.
- http      — (Phase 4+) REST-backed client that talks to a remote governance
              service and remote runtime service. Same public interface as
              inprocess, swappable by config.

The `Verity` class exposed here preserves the flat API consuming apps
used before the split (verity.execute_pipeline, verity.get_audit_trail,
etc.), so no business-app code has to change.
"""
