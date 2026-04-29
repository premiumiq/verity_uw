"""Per-report composer functions.

A composer takes (verity_client, scope_dict) and returns a body dict that
gets merged into the standard report envelope (see engine.resolve_dataset).

Adding a new report:
  1. Define the report in compliance_seed_reports.yaml (and seed-reports).
  2. Add a composer function here.
  3. Register it in COMPOSERS at the bottom.

Composers query analytics.* views ONLY — they never touch L1 directly.
This is the bright line that makes the reports portable to a customer warehouse.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


# =============================================================================
# Display-name maps — used by every report's composer to humanize codes.
# The DOCX template uses `_display` fields exclusively; raw codes are kept
# only for filtering/grouping.
# =============================================================================

ASSET_TYPE_DISPLAY = {"agent": "Agent", "task": "Task", "prompt": "Prompt"}
ASSET_TYPE_PLURAL  = {"agent": "Agents", "task": "Tasks", "prompt": "Prompts"}
LIFECYCLE_DISPLAY  = {
    "draft":      "Draft",
    "candidate":  "Candidate",
    "staging":    "Staging",
    "shadow":     "Shadow",
    "challenger": "Challenger",
    "champion":   "Champion",
    "deprecated": "Deprecated",
}
MATERIALITY_DISPLAY = {"high": "High", "medium": "Medium", "low": "Low"}


def _humanize_asset(row: dict[str, Any]) -> dict[str, Any]:
    """Add `_display` fields to a v_entity_version row for the docx template."""
    r = dict(row)
    r["asset_type_display"]      = ASSET_TYPE_DISPLAY.get(r.get("entity_type"), r.get("entity_type") or "—")
    r["lifecycle_state_display"] = LIFECYCLE_DISPLAY.get(r.get("lifecycle_state"), r.get("lifecycle_state") or "—")
    r["materiality_display"]     = MATERIALITY_DISPLAY.get(r.get("materiality_tier"), r.get("materiality_tier") or "—")
    # Prefer display name; fall back to code when display name is missing.
    r["display_name"]            = r.get("entity_display_name") or r.get("entity_name") or "—"
    return r


def _humanize_event(row: dict[str, Any]) -> dict[str, Any]:
    """Add `_display` fields to a v_lifecycle_event row."""
    r = dict(row)
    r["asset_type_display"] = ASSET_TYPE_DISPLAY.get(r.get("entity_type"), r.get("entity_type") or "—")
    r["from_state_display"] = LIFECYCLE_DISPLAY.get(r.get("from_state"), r.get("from_state") or "draft")
    r["to_state_display"]   = LIFECYCLE_DISPLAY.get(r.get("to_state"),   r.get("to_state")   or "—")
    return r


# =============================================================================
# Model Inventory
# =============================================================================

async def compose_model_inventory(
    verity, scope: dict[str, Any]
) -> dict[str, Any]:
    """Enumerate every (entity_type, entity, version) registered to Verity.

    Sections in the dataset:
      - inventory_rows:        the big table — one row per entity_version
      - by_materiality:        count breakdown for executive-summary stats
      - by_lifecycle_state:    count breakdown
      - by_entity_type:        count breakdown
      - recent_lifecycle_events: last 25 state transitions
    """
    application_code = scope.get("application_code") or None
    materiality      = scope.get("materiality_tier") or None

    inventory_rows = await verity.db.fetch_all_raw(
        """
        SELECT
            ev.entity_type,
            ev.entity_name,
            ev.entity_display_name,
            ev.entity_description,
            ev.version_label,
            ev.lifecycle_state,
            ev.materiality_tier,
            ev.owner_name,
            ev.owner_email,
            ev.domain,
            ev.created_at,
            COALESCE(
              string_agg(DISTINCT ae.application_name, ', ' ORDER BY ae.application_name),
              '—'
            ) AS applications
        FROM analytics.v_entity_version ev
        LEFT JOIN analytics.v_application_entity ae
            ON ae.entity_id   = ev.entity_id
           AND ae.entity_type = ev.entity_type
        WHERE
            (%(application_code)s::text  IS NULL OR ae.application_name = %(application_code)s)
        AND (%(materiality_tier)s::text  IS NULL OR ev.materiality_tier = %(materiality_tier)s)
        GROUP BY
            ev.entity_type, ev.entity_name, ev.entity_display_name,
            ev.entity_description, ev.version_label, ev.lifecycle_state,
            ev.materiality_tier, ev.owner_name, ev.owner_email,
            ev.domain, ev.created_at
        ORDER BY
            CASE ev.materiality_tier
                WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4
            END,
            ev.entity_type,
            ev.entity_name,
            ev.version_label
        """,
        {
            "application_code": application_code,
            "materiality_tier": materiality,
        },
    )

    # Humanize + group by asset type so the template can sub-section.
    inventory_rows = [_humanize_asset(r) for r in inventory_rows]
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in inventory_rows:
        by_type[r["entity_type"]].append(r)

    # Aggregate counts for the executive summary.
    materiality_counter = Counter(
        (r.get("materiality_tier") or "—") for r in inventory_rows
    )
    state_counter       = Counter(
        (r.get("lifecycle_state") or "—") for r in inventory_rows
    )
    type_counter        = Counter(
        (r.get("entity_type") or "—") for r in inventory_rows
    )

    # Recent state transitions (the change-management evidence section).
    recent_events_raw = await verity.db.fetch_all_raw(
        """
        SELECT
            le.entity_type,
            le.from_state,
            le.to_state,
            le.gate_type,
            le.approver_name,
            le.approver_role,
            le.rationale,
            le.approved_at,
            COALESCE(av.entity_display_name, tv.entity_display_name, pv.entity_display_name,
                     av.entity_name, tv.entity_name, pv.entity_name, '—') AS asset_display_name,
            COALESCE(av.version_label, tv.version_label, pv.version_label, '—') AS version_label
        FROM analytics.v_lifecycle_event le
        LEFT JOIN analytics.v_entity_version av
               ON av.source_pk = le.entity_version_id::text AND le.entity_type = 'agent'
        LEFT JOIN analytics.v_entity_version tv
               ON tv.source_pk = le.entity_version_id::text AND le.entity_type = 'task'
        LEFT JOIN analytics.v_entity_version pv
               ON pv.source_pk = le.entity_version_id::text AND le.entity_type = 'prompt'
        ORDER BY le.approved_at DESC
        LIMIT 50
        """
    )
    recent_events = [_humanize_event(e) for e in recent_events_raw]

    events_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in recent_events:
        events_by_type[e["entity_type"]].append(e)

    return {
        # Inventory grouped by asset type — the docx template iterates
        # over the named slots, not a generic loop, so each type can be
        # sub-sectioned with its own heading.
        "agents":  by_type.get("agent",  []),
        "tasks":   by_type.get("task",   []),
        "prompts": by_type.get("prompt", []),

        "agent_count":  len(by_type.get("agent",  [])),
        "task_count":   len(by_type.get("task",   [])),
        "prompt_count": len(by_type.get("prompt", [])),

        # Lifecycle events sub-sectioned by asset type.
        "lifecycle_agents":  events_by_type.get("agent",  []),
        "lifecycle_tasks":   events_by_type.get("task",   []),
        "lifecycle_prompts": events_by_type.get("prompt", []),

        # Aggregates for the executive summary.
        "by_materiality":     dict(materiality_counter),
        "by_lifecycle_state": dict(state_counter),
        "by_entity_type":     dict(type_counter),

        "high_count":   materiality_counter.get("high", 0),
        "medium_count": materiality_counter.get("medium", 0),
        "low_count":    materiality_counter.get("low", 0),
        "total_count":  len(inventory_rows),
        "lifecycle_events_total": len(recent_events),
    }


# =============================================================================
# Decision Audit Trail — ONE decision deep-dive
# =============================================================================

async def compose_decision_audit_trail(
    verity, scope: dict[str, Any]
) -> dict[str, Any]:
    """Single-decision deep-dive. Required scope: `decision_id`.

    Pulls one row from v_decision (with the producing entity_version's
    display name resolved), all overrides applied to that decision, and
    aggregate values for the executive summary.
    """
    decision_id = scope.get("decision_id")
    if not decision_id:
        raise ValueError("decision_audit_trail requires scope.decision_id")

    decision = await verity.db.fetch_one_raw(
        """
        SELECT
            d.decision_id, d.execution_context_id, d.workflow_run_id,
            d.entity_type, d.entity_version_id, d.application_code,
            d.channel, d.run_purpose, d.step_name,
            d.input_summary, d.output_summary, d.reasoning_text,
            d.confidence_score, d.duration_ms,
            d.input_tokens, d.output_tokens, d.model_used,
            d.hitl_required, d.hitl_completed, d.low_confidence_flag,
            d.created_at,
            COALESCE(av.entity_display_name, tv.entity_display_name, pv.entity_display_name,
                     av.entity_name, tv.entity_name, pv.entity_name, '—') AS asset_display_name,
            COALESCE(av.entity_description, tv.entity_description, pv.entity_description, '') AS asset_description,
            COALESCE(av.version_label, tv.version_label, pv.version_label, '—') AS version_label,
            COALESCE(av.materiality_tier, tv.materiality_tier, '—') AS materiality_tier,
            COALESCE(av.owner_name, tv.owner_name, '—') AS owner_name
        FROM analytics.v_decision d
        LEFT JOIN analytics.v_entity_version av
               ON av.source_pk = d.entity_version_id::text AND d.entity_type = 'agent'
        LEFT JOIN analytics.v_entity_version tv
               ON tv.source_pk = d.entity_version_id::text AND d.entity_type = 'task'
        LEFT JOIN analytics.v_entity_version pv
               ON pv.source_pk = d.entity_version_id::text AND d.entity_type = 'prompt'
        WHERE d.decision_id = %(id)s::uuid
        """,
        {"id": decision_id},
    )
    if not decision:
        raise ValueError(
            f"decision_audit_trail: no decision found with id={decision_id!r}"
        )
    decision["asset_type_display"]  = ASSET_TYPE_DISPLAY.get(decision["entity_type"], decision["entity_type"] or "—")
    decision["materiality_display"] = MATERIALITY_DISPLAY.get(decision["materiality_tier"], decision["materiality_tier"] or "—")

    overrides = await verity.db.fetch_all_raw(
        """
        SELECT o.override_id, o.fact_type, o.output_path,
               o.ai_value, o.hitl_value, o.ai_found, o.override_reason,
               o.overridden_by, o.created_at,
               o.business_entity_type, o.business_entity_reference
        FROM analytics.v_override o
        WHERE o.decision_id = %(id)s::uuid
        ORDER BY o.created_at
        """,
        {"id": decision_id},
    )

    return {
        "decision":       decision,
        "overrides":      overrides,
        "override_count": len(overrides),
    }


# =============================================================================
# Workflow Audit Trail — all decisions in one workflow_run_id
# =============================================================================

async def compose_workflow_audit_trail(
    verity, scope: dict[str, Any]
) -> dict[str, Any]:
    """End-to-end audit of one workflow's decisions, in chronological order,
    plus all overrides applied to any of those decisions.

    Required scope: `workflow_run_id`.
    """
    workflow_run_id = scope.get("workflow_run_id")
    if not workflow_run_id:
        raise ValueError(
            "workflow_audit_trail requires scope.workflow_run_id"
        )

    decisions = await verity.db.fetch_all_raw(
        """
        SELECT
            d.decision_id, d.execution_context_id, d.workflow_run_id,
            d.entity_type, d.entity_version_id, d.application_code,
            d.channel, d.run_purpose, d.step_name,
            d.input_summary, d.output_summary, d.reasoning_text,
            d.confidence_score, d.duration_ms,
            d.input_tokens, d.output_tokens, d.model_used,
            d.hitl_required, d.hitl_completed, d.low_confidence_flag,
            d.created_at,
            COALESCE(av.entity_display_name, tv.entity_display_name, pv.entity_display_name,
                     av.entity_name, tv.entity_name, pv.entity_name, '—') AS asset_display_name,
            COALESCE(av.version_label, tv.version_label, pv.version_label, '—') AS version_label
        FROM analytics.v_decision d
        LEFT JOIN analytics.v_entity_version av
               ON av.source_pk = d.entity_version_id::text AND d.entity_type = 'agent'
        LEFT JOIN analytics.v_entity_version tv
               ON tv.source_pk = d.entity_version_id::text AND d.entity_type = 'task'
        LEFT JOIN analytics.v_entity_version pv
               ON pv.source_pk = d.entity_version_id::text AND d.entity_type = 'prompt'
        WHERE d.workflow_run_id = %(wf)s::uuid
        ORDER BY d.created_at, d.decision_id
        """,
        {"wf": workflow_run_id},
    )
    for d in decisions:
        d["asset_type_display"] = ASSET_TYPE_DISPLAY.get(d["entity_type"], d["entity_type"] or "—")

    overrides = await verity.db.fetch_all_raw(
        """
        SELECT o.override_id, o.decision_id, o.fact_type, o.output_path,
               o.ai_value, o.hitl_value, o.ai_found, o.override_reason,
               o.overridden_by, o.created_at,
               o.business_entity_type, o.business_entity_reference
        FROM analytics.v_override o
        WHERE o.decision_id IN (
            SELECT decision_id FROM analytics.v_decision
            WHERE workflow_run_id = %(wf)s::uuid
        )
        ORDER BY o.created_at
        """,
        {"wf": workflow_run_id},
    )

    distinct_assets = len({(d["entity_type"], d["asset_display_name"]) for d in decisions})
    total_duration_ms = sum((d["duration_ms"] or 0) for d in decisions)
    confidences = [float(d["confidence_score"]) for d in decisions if d["confidence_score"] is not None]
    avg_confidence = (sum(confidences) / len(confidences)) if confidences else None
    hitl_required_count = sum(1 for d in decisions if d["hitl_required"])

    return {
        "workflow_run_id":     workflow_run_id,
        "decisions":           decisions,
        "decision_count":      len(decisions),
        "distinct_assets":     distinct_assets,
        "total_duration_ms":   total_duration_ms,
        "avg_confidence":      avg_confidence,
        "hitl_required_count": hitl_required_count,
        "overrides":           overrides,
        "override_count":      len(overrides),
    }


# =============================================================================
# Fairness Validation Summary
# =============================================================================

async def compose_fairness_validation_summary(
    verity, scope: dict[str, Any]
) -> dict[str, Any]:
    """Aggregates pre-deployment validation/fairness test runs by asset.

    Optional scope: entity_type, entity_name. With no scope, returns every
    validation result on file.
    """
    entity_type = scope.get("entity_type") or None
    entity_name = scope.get("entity_name") or None

    rows = await verity.db.fetch_all_raw(
        """
        SELECT
            vr.test_log_id, vr.entity_type, vr.entity_version_id,
            vr.suite_id, vr.test_case_id,
            vr.passed, vr.duration_ms, vr.metric_type, vr.metric_result,
            vr.failure_reason, vr.channel, vr.mock_mode, vr.run_at,
            COALESCE(ev.entity_display_name, ev.entity_name, '—') AS asset_display_name,
            ev.version_label, ev.materiality_tier, ev.owner_name
        FROM analytics.v_validation_result vr
        LEFT JOIN analytics.v_entity_version ev
               ON ev.source_pk = vr.entity_version_id::text
              AND ev.entity_type = vr.entity_type
        WHERE (%(t)s::text IS NULL OR vr.entity_type = %(t)s)
          AND (%(n)s::text IS NULL OR ev.entity_name = %(n)s)
        ORDER BY vr.run_at DESC NULLS LAST, vr.test_log_id
        """,
        {"t": entity_type, "n": entity_name},
    )

    for r in rows:
        r["asset_type_display"]   = ASSET_TYPE_DISPLAY.get(r["entity_type"], r["entity_type"] or "—")
        r["materiality_display"]  = MATERIALITY_DISPLAY.get(r.get("materiality_tier"), r.get("materiality_tier") or "—")
        r["passed_display"]       = "Pass" if r.get("passed") else "Fail"

    # Group by asset (entity_type + version) for the body table.
    by_asset: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        key = (r["entity_type"], r["asset_display_name"], r["version_label"])
        bucket = by_asset.setdefault(key, {
            "asset_type_display":  r["asset_type_display"],
            "asset_display_name":  r["asset_display_name"],
            "version_label":       r["version_label"] or "—",
            "materiality_display": r["materiality_display"],
            "owner_name":          r["owner_name"] or "—",
            "results":             [],
            "pass_count":          0,
            "fail_count":          0,
        })
        bucket["results"].append(r)
        if r["passed"]:
            bucket["pass_count"] += 1
        else:
            bucket["fail_count"] += 1

    asset_summaries = sorted(
        by_asset.values(),
        key=lambda x: (x["asset_type_display"], x["asset_display_name"]),
    )

    pass_count = sum(1 for r in rows if r["passed"])
    fail_count = sum(1 for r in rows if not r["passed"])

    return {
        "validation_results":  rows,
        "result_count":        len(rows),
        "pass_count":          pass_count,
        "fail_count":          fail_count,
        "asset_summaries":     asset_summaries,
        "asset_count":         len(asset_summaries),
    }


# =============================================================================
# NAIC Exhibit C — High-Risk System Deep Dive
# =============================================================================

async def compose_naic_exhibit_c(
    verity, scope: dict[str, Any]
) -> dict[str, Any]:
    """Single-asset deep-dive: registration, ownership, lifecycle, validation,
    every decision the asset has made, and every override against those decisions.

    Required scope: entity_type, entity_name. Optional: version_label.
    """
    entity_type = scope.get("entity_type")
    entity_name = scope.get("entity_name")
    version_label = scope.get("version_label") or None

    if not entity_type or not entity_name:
        raise ValueError(
            "naic_exhibit_c requires scope.entity_type and scope.entity_name"
        )

    # Find the target entity_version. If version_label given, match exactly.
    # Otherwise pick the current Champion (or most recent if no champion).
    versions = await verity.db.fetch_all_raw(
        """
        SELECT
            ev.source_pk, ev.entity_type, ev.entity_id,
            ev.entity_name, ev.entity_display_name, ev.entity_description,
            ev.version_label, ev.lifecycle_state, ev.channel,
            ev.materiality_tier, ev.owner_name, ev.owner_email,
            ev.domain, ev.created_at,
            COALESCE(
              (SELECT string_agg(DISTINCT ae.application_name, ', ' ORDER BY ae.application_name)
                 FROM analytics.v_application_entity ae
                WHERE ae.entity_id   = ev.entity_id
                  AND ae.entity_type = ev.entity_type),
              '—'
            ) AS applications
        FROM analytics.v_entity_version ev
        WHERE ev.entity_type = %(t)s
          AND ev.entity_name = %(n)s
          AND (%(v)s::text IS NULL OR ev.version_label = %(v)s)
        ORDER BY
            CASE ev.lifecycle_state WHEN 'champion' THEN 1 ELSE 2 END,
            ev.created_at DESC
        """,
        {"t": entity_type, "n": entity_name, "v": version_label},
    )

    if not versions:
        raise ValueError(
            f"naic_exhibit_c: no entity_version found for "
            f"type={entity_type!r}, name={entity_name!r}, version={version_label!r}"
        )

    target = _humanize_asset(versions[0])
    target_version_id = target["source_pk"]

    # Lifecycle history for this entity_version.
    lifecycle = await verity.db.fetch_all_raw(
        """
        SELECT le.gate_type, le.from_state, le.to_state,
               le.approver_name, le.approver_role, le.rationale,
               le.approved_at
        FROM analytics.v_lifecycle_event le
        WHERE le.entity_version_id::text = %(vid)s
          AND le.entity_type = %(t)s
        ORDER BY le.approved_at
        """,
        {"vid": target_version_id, "t": entity_type},
    )
    lifecycle = [_humanize_event({**ev, "entity_type": entity_type}) for ev in lifecycle]

    # All decisions this entity_version has produced.
    decisions = await verity.db.fetch_all_raw(
        """
        SELECT
            d.decision_id, d.execution_context_id, d.workflow_run_id,
            d.step_name, d.input_summary, d.output_summary, d.reasoning_text,
            d.confidence_score, d.duration_ms, d.model_used,
            d.hitl_required, d.hitl_completed, d.low_confidence_flag,
            d.created_at, d.application_code, d.channel, d.run_purpose
        FROM analytics.v_decision d
        WHERE d.entity_version_id::text = %(vid)s
          AND d.entity_type = %(t)s
        ORDER BY d.created_at DESC
        LIMIT 100
        """,
        {"vid": target_version_id, "t": entity_type},
    )

    # Validation results for this entity_version.
    validation = await verity.db.fetch_all_raw(
        """
        SELECT vr.test_log_id, vr.suite_id, vr.test_case_id,
               vr.passed, vr.metric_type, vr.metric_result,
               vr.failure_reason, vr.duration_ms, vr.run_at,
               vr.channel, vr.mock_mode
        FROM analytics.v_validation_result vr
        WHERE vr.entity_version_id::text = %(vid)s
          AND vr.entity_type = %(t)s
        ORDER BY vr.run_at DESC NULLS LAST
        """,
        {"vid": target_version_id, "t": entity_type},
    )
    for v in validation:
        v["passed_display"] = "Pass" if v.get("passed") else "Fail"

    # All overrides against this entity_version's decisions.
    overrides = await verity.db.fetch_all_raw(
        """
        SELECT o.override_id, o.decision_id, o.fact_type, o.output_path,
               o.ai_value, o.hitl_value, o.ai_found, o.override_reason,
               o.overridden_by, o.created_at,
               o.business_entity_type, o.business_entity_reference
        FROM analytics.v_override o
        WHERE o.decision_id IN (
            SELECT decision_id FROM analytics.v_decision
            WHERE entity_version_id::text = %(vid)s
              AND entity_type = %(t)s
        )
        ORDER BY o.created_at DESC
        """,
        {"vid": target_version_id, "t": entity_type},
    )

    # Aggregates.
    confidences = [float(d["confidence_score"]) for d in decisions if d["confidence_score"] is not None]
    avg_confidence = (sum(confidences) / len(confidences)) if confidences else None
    pass_count = sum(1 for v in validation if v["passed"])
    fail_count = sum(1 for v in validation if not v["passed"])

    return {
        "target":                target,
        "lifecycle_events":      lifecycle,
        "lifecycle_count":       len(lifecycle),
        "decisions":             decisions,
        "decision_count":        len(decisions),
        "avg_confidence":        avg_confidence,
        "validation_results":    validation,
        "validation_count":      len(validation),
        "validation_pass_count": pass_count,
        "validation_fail_count": fail_count,
        "overrides":             overrides,
        "override_count":        len(overrides),
    }


# =============================================================================
# Registry — report code → composer
# =============================================================================

COMPOSERS: dict[str, callable] = {
    "model_inventory":             compose_model_inventory,
    "decision_audit_trail":        compose_decision_audit_trail,    # single decision
    "workflow_audit_trail":        compose_workflow_audit_trail,    # one workflow
    "fairness_validation_summary": compose_fairness_validation_summary,
    "naic_exhibit_c":              compose_naic_exhibit_c,
}
