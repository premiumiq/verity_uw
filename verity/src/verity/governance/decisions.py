"""Governance-side decision operations — audit reads + override record.

This is one half of the core/decisions.py split:
- DecisionsReader (this file) lives in the governance plane. It queries the
  audit trail (list/get/count/by-context/by-run) and records human overrides
  of AI decisions.
- DecisionsWriter (verity.runtime.decisions_writer) lives in the runtime
  plane. It handles the single write the runtime makes per execution:
  log_decision().

Why the split? The governance plane doesn't execute anything, so it never
needs to call log_decision — that's the runtime's job. By contrast, the
audit trail reads and override recording are compliance/UI concerns that
belong with governance, even though record_override is technically a write.
"""

import json
from typing import Any, Optional
from uuid import UUID

from verity.db.connection import Database
from verity.models.decision import (
    AuditTrailEntry,
    DecisionLog,
    DecisionLogDetail,
    OverrideLogCreate,
)


class DecisionsReader:
    """Query the audit trail and record human overrides.

    Every AI invocation produces a row in agent_decision_log (written by
    the runtime's DecisionsWriter). This class reads those rows back for
    the admin UI, audit trail views, compliance reports, and replay tools,
    and it records human overrides when an underwriter/approver disagrees
    with an AI decision.
    """

    def __init__(self, db: Database):
        self.db = db

    async def get_decision(self, decision_id: UUID) -> Optional[DecisionLogDetail]:
        """Get full details for a single decision."""
        row = await self.db.fetch_one("get_decision_by_id", {"decision_id": str(decision_id)})
        if not row:
            return None
        return DecisionLogDetail(**row)

    async def list_decisions(self, limit: int = 50, offset: int = 0) -> list[DecisionLog]:
        """List decisions (most recent first)."""
        rows = await self.db.fetch_all("list_decisions", {"limit": limit, "offset": offset})
        return [DecisionLog(**row) for row in rows]

    async def count_decisions(self) -> int:
        """Count total decisions."""
        row = await self.db.fetch_one("count_decisions")
        return row["total"] if row else 0

    async def list_recent_decisions(self, limit: int = 10) -> list[DecisionLog]:
        """List most recent decisions (for dashboard)."""
        rows = await self.db.fetch_all("list_recent_decisions", {"limit": limit})
        return [DecisionLog(**row) for row in rows]

    async def get_audit_trail(self, execution_context_id: UUID) -> list[AuditTrailEntry]:
        """Get the full decision chain for an execution context.

        Returns every task and agent that ran, in order, with exact versions
        and outputs. This is the regulatory audit trail.
        Uses execution_context_id (Verity's abstraction), not business keys.
        """
        rows = await self.db.fetch_all("list_decisions_by_execution_context", {
            "execution_context_id": str(execution_context_id),
        })
        return [_row_to_audit_entry(r) for r in rows]

    async def get_audit_trail_by_run(self, pipeline_run_id: UUID) -> list[AuditTrailEntry]:
        """Get the full decision chain for a pipeline run.

        This is the CORRECT way to query audit trails — uses Verity's own
        pipeline_run_id (unique per execution), not the business app's key.
        No cross-application collision possible.
        """
        rows = await self.db.fetch_all("list_decisions_by_pipeline_run", {
            "pipeline_run_id": str(pipeline_run_id),
        })
        return [_row_to_audit_entry(r) for r in rows]

    async def get_decisions_by_context(self, execution_context_id: UUID) -> list[dict]:
        """Get all decisions for an execution context (spans multiple pipeline runs)."""
        return await self.db.fetch_all("list_decisions_by_context", {
            "execution_context_id": str(execution_context_id),
        })

    async def record_override(self, override: OverrideLogCreate) -> dict:
        """Record a human override of an AI decision.

        This is a write, but it's a governance-side write — it captures a
        human's disagreement with an AI recommendation, which is compliance
        data, not runtime execution data. The runtime never calls this.
        """
        params = {
            "decision_log_id": str(override.decision_log_id),
            "entity_type": override.entity_type.value,
            "entity_version_id": str(override.entity_version_id),
            "overrider_name": override.overrider_name,
            "overrider_role": override.overrider_role,
            "override_reason_code": override.override_reason_code,
            "override_notes": override.override_notes,
            "ai_recommendation": json.dumps(override.ai_recommendation) if override.ai_recommendation else None,
            "human_decision": json.dumps(override.human_decision) if override.human_decision else None,
        }
        result = await self.db.execute_returning("record_override", params)
        return {"override_id": result["id"], "created_at": result["created_at"]}


def _row_to_audit_entry(r: dict) -> AuditTrailEntry:
    """Build an AuditTrailEntry from a DB row (shared by both audit-trail queries)."""
    return AuditTrailEntry(
        decision_id=r["id"],
        entity_type=r["entity_type"],
        entity_name=r.get("entity_name", "unknown"),
        entity_display_name=r.get("entity_display_name", "Unknown"),
        version_label=r.get("version_label", "0.0.0"),
        capability_type=r.get("capability_type"),
        channel=r["channel"],
        parent_decision_id=r.get("parent_decision_id"),
        decision_depth=r.get("decision_depth", 0),
        step_name=r.get("step_name"),
        output_summary=r.get("output_summary"),
        reasoning_text=r.get("reasoning_text"),
        confidence_score=_to_float(r.get("confidence_score")),
        risk_factors=r.get("risk_factors"),
        duration_ms=r.get("duration_ms"),
        tool_calls_made=r.get("tool_calls_made"),
        hitl_required=r.get("hitl_required", False),
        hitl_completed=r.get("hitl_completed", False),
        status=r.get("status", "complete"),
        created_at=r.get("created_at"),
    )


def _to_float(val) -> Optional[float]:
    """Coerce a nullable numeric DB value (Decimal, int, float, None) to float or None."""
    if val is None:
        return None
    return float(val)
