"""Runtime-side decision write: log every AI invocation.

This is one half of the core/decisions.py split:
- DecisionsWriter (this file) lives in the runtime plane. After every
  run_agent/run_task/run_tool completes (success or failure), the runtime
  calls log_decision() with a fully-populated DecisionLogCreate. This is
  the ONLY write the runtime makes to the governance audit table.
- DecisionsReader (verity.governance.decisions) handles all audit reads
  and the human-override write, which are governance/UI concerns.

Why split? The runtime needs this write to produce the audit trail; it
doesn't need any of the read surface. Separating the writer lets the
runtime ship with a minimal interface into governance — which matters
once the two planes are separate containers (Phase 5) and the writer
becomes an HTTP call (or Snowpipe Streaming insert) instead of a direct
DB call.
"""

import json

from verity.contracts.decision import DecisionLogCreate
from verity.db.connection import Database


class DecisionsWriter:
    """Write a decision record to agent_decision_log — the runtime's single write."""

    def __init__(self, db: Database):
        self.db = db

    async def log_decision(self, decision: DecisionLogCreate) -> dict:
        """Log an AI invocation (agent or task) to the decision log.

        Called by the runtime after every execution. Must happen BEFORE
        the result is used downstream so the audit trail is guaranteed.
        Returns the decision_log_id so the caller can link it.
        """
        params = {
            "entity_type": decision.entity_type.value,
            "entity_version_id": str(decision.entity_version_id),
            "prompt_version_ids": [str(p) for p in decision.prompt_version_ids],
            "inference_config_snapshot": json.dumps(decision.inference_config_snapshot),
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
            "run_purpose": decision.run_purpose.value,
            "reproduced_from_decision_id": str(decision.reproduced_from_decision_id) if decision.reproduced_from_decision_id else None,
            "execution_context_id": str(decision.execution_context_id) if decision.execution_context_id else None,
            "hitl_required": decision.hitl_required,
            "status": decision.status,
            "error_message": decision.error_message,
        }
        result = await self.db.execute_returning("log_decision", params)
        return {"decision_log_id": result["id"], "created_at": result["created_at"]}
