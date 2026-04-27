"""UW-side stage-aware state machine.

Two responsibilities live here:

  1. transition_stage(...) — guard a single stage's status change
     against the per-status rule table. Every stage status change
     in the app must go through this helper so we have one
     chokepoint for the rules and for emitting audit events.

  2. record_event(...) — append a row to submission_event for
     user actions, pipeline lifecycle moments, and system actions.
     transition_stage() calls this internally for state changes.

Plus two read helpers:

  3. current_stage(...) — return the active stage of a submission
     (the lowest-priority stage whose status isn't `complete`,
     except 'declined' which short-circuits the lookup).

  4. ensure_stages(...) — make sure every canonical stage row
     exists for a submission, with default `pending` status.
     Used at submission creation / seed time.

These helpers don't own the database connection. They take a
psycopg cursor so the caller decides transactional grouping.

Why state.py and not a class:
  The helpers are stateless. A free-function module is the
  smallest thing that does the job and avoids dragging classes
  into a codebase that already prefers plain functions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional


# ── STAGE ORDERING ───────────────────────────────────────────
#
# Canonical order of stages as they progress through the
# underwriting workflow. The "current stage" of a submission is the
# lowest-priority stage in this order whose status isn't `complete`.
# `declined` is terminal and short-circuits — when present in
# any non-pending state it's the current stage regardless of the
# others.

STAGE_ORDER: list[str] = [
    "intake",
    "document_processing",
    "information_review",
    "triage",
    "appetite",
]

# All stages including the terminal 'declined'. Used by
# ensure_stages so a fresh submission has a row per stage.
ALL_STAGES: list[str] = [*STAGE_ORDER, "declined"]


# ── ALLOWED TRANSITIONS ──────────────────────────────────────
#
# Per stage_status, which stage_status values it may transition to.
# These rules apply uniformly across stages — a stage that is
# `complete` can be pulled back to `running` (the re-entry case),
# and so on. Each stage's *own* state machine.

ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending":          {"running", "blocked_on_input", "complete", "failed"},
    "running":          {"complete", "failed", "blocked_on_input"},
    "blocked_on_input": {"running", "complete", "failed"},
    # complete and failed can both be re-entered to running — for
    # example, Information Review → Document Processing when more
    # docs arrive, or a retry after a failed run.
    "complete":         {"running", "blocked_on_input"},
    "failed":           {"running", "blocked_on_input"},
}


# ── EXCEPTIONS ───────────────────────────────────────────────


class InvalidStageTransitionError(ValueError):
    """Raised when a caller asks for a stage_status change the rules forbid."""

    def __init__(self, stage: str, from_status: str, to_status: str):
        self.stage = stage
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Invalid transition for stage {stage!r}: "
            f"{from_status!r} → {to_status!r}. "
            f"Allowed from {from_status!r}: "
            f"{sorted(ALLOWED_STATUS_TRANSITIONS.get(from_status, set()))}"
        )


# Backwards-compat alias — earlier scaffolding referenced this name.
InvalidTransitionError = InvalidStageTransitionError


# ── STAGE INITIALISATION ─────────────────────────────────────


async def ensure_stages(cur, submission_id: str) -> None:
    """Make sure every canonical stage row exists for the submission.

    Inserts any missing rows with status='pending'. Idempotent —
    safe to call repeatedly. Called at submission creation, and
    can be called by seed scripts to backfill rows for submissions
    that pre-date this table."""
    for stage in ALL_STAGES:
        await cur.execute(
            """INSERT INTO submission_stage (submission_id, stage, status)
            VALUES (%s, %s::submission_stage_enum, 'pending'::stage_status_enum)
            ON CONFLICT (submission_id, stage) DO NOTHING""",
            (submission_id, stage),
        )


# ── STAGE STATUS TRANSITION ──────────────────────────────────


async def transition_stage(
    cur,
    submission_id: str,
    stage: str,
    new_status: str,
    *,
    changed_by: str,
    run_id: Optional[str] = None,
    reason: Optional[str] = None,
    blocked_reason: Optional[str] = None,
) -> str:
    """Move one stage's status forward (or back, on re-entry).

    Args:
      cur:           psycopg cursor (caller controls transaction).
      submission_id: UUID string.
      stage:         submission_stage_enum value
                     ('intake', 'document_processing', etc.).
      new_status:    stage_status_enum value
                     ('pending', 'running', 'blocked_on_input',
                      'complete', 'failed').
      changed_by:    Actor name ('uw_user', 'system', a username).
      run_id:        Optional Verity run id when the change was
                     triggered by a pipeline outcome. Stored on
                     submission_stage.last_run_id.
      reason:        Optional free-text reason; goes to the audit event.
      blocked_reason:Optional text written to submission_stage when
                     transitioning to 'blocked_on_input'.

    Returns:
      The previous stage_status (for callers that want to log it).

    Raises:
      InvalidStageTransitionError when the transition is not allowed.
      ValueError when the (submission, stage) row does not exist.
    """
    # Read the current row under the same cursor so we see writes
    # from earlier in this transaction.
    await cur.execute(
        """SELECT status::text, enter_count FROM submission_stage
        WHERE submission_id = %s AND stage = %s::submission_stage_enum""",
        (submission_id, stage),
    )
    row = await cur.fetchone()
    if not row:
        raise ValueError(
            f"submission_stage row missing for ({submission_id}, {stage}). "
            f"Did you call ensure_stages() at submission creation?"
        )
    from_status, enter_count = row

    # Idempotency: same-state is a no-op (no event, no error). Lets
    # callers skip "already there" checks before calling.
    if from_status == new_status:
        return from_status

    allowed = ALLOWED_STATUS_TRANSITIONS.get(from_status, set())
    if new_status not in allowed:
        raise InvalidStageTransitionError(stage, from_status, new_status)

    # Compose the update. We always touch status; we conditionally
    # touch started_at, completed_at, blocked_reason, last_run_id,
    # and enter_count based on the transition shape.
    sets = ["status = %s::stage_status_enum"]
    params: list[Any] = [new_status]

    # Bump enter_count whenever we (re-)enter the running state,
    # including from complete or failed (re-entry).
    if new_status == "running":
        sets.append("enter_count = enter_count + 1")
        # First-ever entry — set started_at if it was NULL. We
        # COALESCE so re-entries keep the original started_at as
        # the "first time entered" anchor; per-entry timestamps
        # live in submission_event.
        sets.append("started_at = COALESCE(started_at, NOW())")
        # Re-entering clears the prior completion/blocked.
        sets.append("completed_at = NULL")
        sets.append("blocked_reason = NULL")

    if new_status == "complete":
        sets.append("completed_at = NOW()")
        sets.append("blocked_reason = NULL")

    if new_status == "failed":
        sets.append("completed_at = NOW()")
        sets.append("blocked_reason = NULL")

    if new_status == "blocked_on_input":
        sets.append("blocked_reason = %s")
        params.append(blocked_reason)

    if run_id is not None:
        sets.append("last_run_id = %s")
        params.append(run_id)

    # Touch the submission's updated_at so the detail-page "Last
    # update" context strip stays fresh. We do this in a separate
    # UPDATE to keep the stage update atomic; both are inside the
    # caller's transaction.
    params_for_stage_update = [*params, submission_id, stage]
    await cur.execute(
        f"""UPDATE submission_stage SET {', '.join(sets)}
        WHERE submission_id = %s AND stage = %s::submission_stage_enum""",
        params_for_stage_update,
    )
    await cur.execute(
        "UPDATE submission SET updated_at = NOW() WHERE id = %s",
        (submission_id,),
    )

    # Audit event for the state change. Payload carries enough
    # context for the audit-trail UI to render the change without
    # joining other tables.
    await record_event(
        cur,
        submission_id,
        event_category="state_change",
        event_type="stage_status_changed",
        actor=changed_by,
        payload={
            "stage": stage,
            "from": from_status,
            "to": new_status,
            "reason": reason,
            "blocked_reason": blocked_reason,
            "enter_count": enter_count + (1 if new_status == "running" else 0),
        },
        workflow_run_id=run_id,
    )

    return from_status


# ── CURRENT STAGE RESOLVER ───────────────────────────────────


async def current_stage(cur, submission_id: str) -> tuple[str, str]:
    """Return (stage, status) for the submission's current stage.

    Rule:
      1. If 'declined' is non-pending, return that — it's terminal.
      2. Otherwise return the lowest-priority stage in STAGE_ORDER
         whose status isn't 'complete'.
      3. If every stage is complete, return ('appetite', 'complete')
         since 'appetite' is the last forward stage.

    The caller can use this to drive action-bar logic and the
    submission-list status pill."""
    # Pull every stage row for this submission once; decide here.
    await cur.execute(
        """SELECT stage::text, status::text FROM submission_stage
        WHERE submission_id = %s""",
        (submission_id,),
    )
    rows = await cur.fetchall()
    by_stage = {stage: status for stage, status in rows}

    # Rule 1: declined short-circuit.
    declined_status = by_stage.get("declined", "pending")
    if declined_status != "pending":
        return ("declined", declined_status)

    # Rule 2: first non-complete in canonical order.
    for stage in STAGE_ORDER:
        status = by_stage.get(stage, "pending")
        if status != "complete":
            return (stage, status)

    # Rule 3: every forward stage complete.
    return ("appetite", "complete")


# ── EVENT LOGGING ────────────────────────────────────────────


async def record_event(
    cur,
    submission_id: str,
    *,
    event_category: str,
    event_type: str,
    actor: str,
    payload: Optional[dict[str, Any]] = None,
    workflow_run_id: Optional[str] = None,
    document_id: Optional[str] = None,
    field_name: Optional[str] = None,
) -> None:
    """Append a row to submission_event.

    Caller controls the transaction (no commit here). Use this for:
      - state changes (transition_stage calls this for you)
      - user actions (uploads, edits, approvals, button clicks)
      - pipeline lifecycle events (submitted, completed, failed)
      - system events (auto-triggered runs, etc.)

    payload is loose-shape — each event_type has its own keys.
    Keep them small and meaningful; this is a high-write table.
    """
    await cur.execute(
        """INSERT INTO submission_event (
            submission_id, event_category, event_type, actor,
            payload, workflow_run_id, document_id, field_name
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            submission_id,
            event_category,
            event_type,
            actor,
            json.dumps(payload or {}),
            workflow_run_id,
            document_id,
            field_name,
        ),
    )


# ── BACKWARDS-COMPAT SHIM ────────────────────────────────────
#
# Earlier scaffolding (4.3.a) imported `transition_status`. That
# function is gone — callers must move to `transition_stage` —
# but we keep the import name resolvable so module load doesn't
# explode while the migration is in progress. The shim raises
# rather than silently doing the wrong thing.

async def transition_status(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError(
        "transition_status was replaced by transition_stage(...). "
        "Migrate the caller to the stage-aware API."
    )
