"""Verity Decisions — log every AI invocation, query audit trails, record overrides.

Every Claude call — agent or task — creates a record in agent_decision_log
with the full inference_config_snapshot, prompt versions, inputs, outputs.
This is the audit trail that answers regulatory questions.
"""

import json
from typing import Any, Optional
from uuid import UUID

from verity.db.connection import Database
from verity.models.decision import (
    AuditTrailEntry,
    DecisionLog,
    DecisionLogCreate,
    DecisionLogDetail,
    OverrideLogCreate,
)


class Decisions:
    """Log decisions, query audit trails, record overrides."""

    def __init__(self, db: Database):
        self.db = db

    async def log_decision(self, decision: DecisionLogCreate) -> dict:
        """Log an AI invocation (agent or task) to the decision log.

        This must be called BEFORE the result is used downstream.
        Returns the decision_log_id for linking.
        """
        params = {
            "entity_type": decision.entity_type.value,
            "entity_version_id": str(decision.entity_version_id),
            "prompt_version_ids": [str(p) for p in decision.prompt_version_ids],
            "inference_config_snapshot": json.dumps(decision.inference_config_snapshot),
            "submission_id": str(decision.submission_id) if decision.submission_id else None,
            "policy_id": str(decision.policy_id) if decision.policy_id else None,
            "renewal_id": str(decision.renewal_id) if decision.renewal_id else None,
            "business_entity": decision.business_entity,
            "channel": decision.channel.value,
            "mock_mode": decision.mock_mode,
            "pipeline_run_id": str(decision.pipeline_run_id) if decision.pipeline_run_id else None,
            "parent_decision_id": str(decision.parent_decision_id) if decision.parent_decision_id else None,
            "decision_depth": decision.decision_depth,
            "step_name": decision.step_name,
            "input_summary": decision.input_summary,
            "input_json": json.dumps(decision.input_json) if decision.input_json else None,
            "output_json": json.dumps(decision.output_json) if decision.output_json else None,
            "output_summary": decision.output_summary,
            "reasoning_text": decision.reasoning_text,
            "risk_factors": json.dumps(decision.risk_factors) if decision.risk_factors else None,
            "confidence_score": decision.confidence_score,
            "low_confidence_flag": decision.low_confidence_flag,
            "model_used": decision.model_used,
            "input_tokens": decision.input_tokens,
            "output_tokens": decision.output_tokens,
            "duration_ms": decision.duration_ms,
            "tool_calls_made": json.dumps(decision.tool_calls_made) if decision.tool_calls_made else None,
            "message_history": json.dumps(decision.message_history) if decision.message_history else None,
            "application": decision.application,
            "hitl_required": decision.hitl_required,
            "status": decision.status,
            "error_message": decision.error_message,
        }
        result = await self.db.execute_returning("log_decision", params)
        return {"decision_log_id": result["id"], "created_at": result["created_at"]}

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

    async def get_audit_trail(self, submission_id: UUID) -> list[AuditTrailEntry]:
        """Get the full decision chain for a submission.

        Returns every task and agent that ran, in order, with exact versions
        and outputs. This is the regulatory audit trail.
        """
        rows = await self.db.fetch_all("list_decisions_by_submission", {
            "submission_id": str(submission_id),
        })
        return [
            AuditTrailEntry(
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
            for r in rows
        ]

    async def get_audit_trail_by_run(self, pipeline_run_id: UUID) -> list[AuditTrailEntry]:
        """Get the full decision chain for a pipeline run.

        This is the CORRECT way to query audit trails — uses Verity's own
        pipeline_run_id (unique per execution), not the business app's key.
        No cross-application collision possible.
        """
        rows = await self.db.fetch_all("list_decisions_by_pipeline_run", {
            "pipeline_run_id": str(pipeline_run_id),
        })
        return [
            AuditTrailEntry(
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
            for r in rows
        ]

    async def record_override(self, override: OverrideLogCreate) -> dict:
        """Record a human override of an AI decision."""
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
            "submission_id": str(override.submission_id) if override.submission_id else None,
        }
        result = await self.db.execute_returning("record_override", params)
        return {"override_id": result["id"], "created_at": result["created_at"]}

    async def list_recent_decisions(self, limit: int = 10) -> list[DecisionLog]:
        """List most recent decisions (for dashboard)."""
        rows = await self.db.fetch_all("list_recent_decisions", {"limit": limit})
        return [DecisionLog(**row) for row in rows]


def _to_float(val) -> Optional[float]:
    if val is None:
        return None
    return float(val)
