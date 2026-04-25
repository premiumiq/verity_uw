"""Builds the canonical ExecutionEnvelope from persisted state.

Read-side composer: pulls fields from execution_run_current (the
unioned view over the four run-tracking tables) and agent_decision_log
(the immutable audit row), reshapes them into the envelope contract.

This is the only place that knows the field-by-field translation
between "what we store" and "what consumers see," so changes to either
the storage shape or the envelope contract land here.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from verity.contracts.envelope import (
    EnvelopeEntity,
    EnvelopeError,
    EnvelopeProvenance,
    EnvelopeTelemetry,
    ExecutionEnvelope,
)
from verity.models.run import ExecutionRunCurrent


def build_envelope(
    run: ExecutionRunCurrent,
    decision: Optional[dict[str, Any]] = None,
    *,
    version_label: Optional[str] = None,
) -> ExecutionEnvelope:
    """Assemble an ExecutionEnvelope from a run-state view row + audit row.

    Args:
      run: ExecutionRunCurrent (the resolved-status view shape).
      decision: agent_decision_log row dict, or None when the run
        terminated without producing an audit row (e.g. cancelled
        before claim).
      version_label: optional SemVer string for the entity_version_id;
        callers that already loaded it can pass it through. Otherwise
        the envelope's entity.version_label is None — consumers can
        look it up if they need the human-readable label.

    Returns:
      ExecutionEnvelope with status discriminated as 'success' or
      'failure' and `output`/`error` populated accordingly.
    """
    # ── status / output / error ──────────────────────────────────
    # current_status comes from the view's resolution precedence
    # (completion > error > latest status event). We map it onto the
    # envelope's two-value status enum:
    #   complete           → success, output populated
    #   cancelled / failed → failure, error populated
    #   anything else      → caller bug (envelope shouldn't be built
    #                        for non-terminal runs); raise.
    current = run.current_status.value
    if current == "complete":
        status: str = "success"
        output_block = (decision or {}).get("output_json") or {}
        error_block: Optional[EnvelopeError] = None
    elif current in ("cancelled", "failed"):
        status = "failure"
        output_block = None
        error_block = _build_error(run, decision, current)
    else:
        # Submitted/claimed/heartbeat/released — non-terminal. Caller
        # should have gated on this before invoking the builder.
        raise ValueError(
            f"build_envelope called for non-terminal run {run.id} "
            f"(current_status={current!r}). Envelopes are only valid "
            "for terminal runs."
        )

    # ── entity ──────────────────────────────────────────────────
    entity = EnvelopeEntity(
        type=run.entity_kind,                    # 'task' | 'agent'
        name=run.entity_name,
        version_label=version_label,             # optional pre-resolved label
        version_id=run.entity_version_id,
        channel=run.channel,
    )

    # ── telemetry ───────────────────────────────────────────────
    # Pull from the decision log when present; fall back to None when
    # the run terminated without a decision row.
    telem = EnvelopeTelemetry(
        input_tokens=_get(decision, "input_tokens"),
        output_tokens=_get(decision, "output_tokens"),
        tool_calls=_count(_get(decision, "tool_calls_made")),
        sources_resolved=_resolution_names(_get(decision, "source_resolutions")),
        targets_fired=_target_names(_get(decision, "target_writes")),
        # cost_usd / turns / mocks_used are forward-compatible — the
        # runtime doesn't compute them yet. Leave as None / [].
    )

    # ── provenance ──────────────────────────────────────────────
    provenance = EnvelopeProvenance(
        decision_log_id=_decision_log_id(decision, run),
        execution_run_id=run.id,
        workflow_run_id=run.workflow_run_id,
        execution_context_id=run.execution_context_id,
        parent_decision_id=run.parent_decision_id,
        mock_mode=run.mock_mode,
        application=run.application,
    )

    return ExecutionEnvelope(
        run_id=run.id,
        # parent_run_id is for cross-run linking (an agent that spawned
        # this one, or an app chaining workflows). Verity doesn't track
        # cross-run parents today; reserved for future use.
        parent_run_id=None,
        entity=entity,
        status=status,
        output=output_block,
        error=error_block,
        started_at=run.first_started_at,
        completed_at=run.completed_at or run.failed_at,
        duration_ms=run.duration_ms,
        telemetry=telem,
        provenance=provenance,
    )


# ── internal helpers ────────────────────────────────────────────


def _get(decision: Optional[dict[str, Any]], key: str) -> Any:
    if not decision:
        return None
    return decision.get(key)


def _count(value: Any) -> Optional[int]:
    """len() iff iterable; None otherwise. Used for tool_calls counter."""
    if value is None:
        return None
    try:
        return len(value)
    except TypeError:
        return None


def _resolution_names(source_resolutions: Any) -> list[str]:
    """Extract the template_var of every resolved source_binding entry.

    Returns the labels consumers see in `telemetry.sources_resolved`.
    Failed and skipped entries are excluded — only resolutions that
    actually produced a value count.
    """
    if not isinstance(source_resolutions, list):
        return []
    names: list[str] = []
    for entry in source_resolutions:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "resolved":
            continue
        name = entry.get("template_var") or entry.get("input_field")
        if name:
            names.append(name)
    return names


def _target_names(target_writes: Any) -> list[str]:
    """Extract the target_name of every fired write_target entry.

    Includes 'wrote' AND 'logged' entries — both count as "this target
    fired" for telemetry purposes; the difference is whether the
    connector was actually called or only the intent was recorded.
    Failed / skipped entries are excluded.
    """
    if not isinstance(target_writes, list):
        return []
    names: list[str] = []
    for entry in target_writes:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") not in ("wrote", "logged"):
            continue
        name = entry.get("target_name") or entry.get("output_field")
        if name:
            names.append(name)
    return names


def _build_error(
    run: ExecutionRunCurrent,
    decision: Optional[dict[str, Any]],
    current: str,
) -> EnvelopeError:
    """Compose the envelope's error block from view + decision row.

    The error_message + error_code on the run come from
    execution_run_error; the decision_log row may also carry an
    error_message captured by the engine. Prefer the view's fields
    (terminal authority) and fall back to the decision row's.
    """
    if current == "cancelled":
        return EnvelopeError(
            code="cancelled",
            message="Run was cancelled before completion.",
            retriable=False,
        )
    # 'failed'
    msg = run.error_message or _get(decision, "error_message") or "Run failed without an error message."
    code = run.error_code or "execution_failed"
    # No retry semantics computed today — most callers can re-submit
    # with the same input without harm; flag retriable=False
    # conservatively until we have category-specific signals
    # (transient connector vs schema-violation, etc.).
    return EnvelopeError(code=code, message=msg, retriable=False)


def _decision_log_id(
    decision: Optional[dict[str, Any]], run: ExecutionRunCurrent,
) -> Optional[UUID]:
    """Pick the right decision_log_id source.

    The run-state view exposes both completion_decision_log_id and
    error_decision_log_id; either may be set (or neither). Prefer the
    completion id when present (success path); fall back to the error
    id (failure path with a partial audit row); finally, walk the
    decision dict if the caller provided it directly.
    """
    if run.completion_decision_log_id:
        return run.completion_decision_log_id
    if run.error_decision_log_id:
        return run.error_decision_log_id
    if decision and decision.get("id"):
        return UUID(str(decision["id"]))
    return None
