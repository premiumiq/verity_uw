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


# =============================================================================
# Intake context resolution — joins a registry entity to its parent intake
# so reports can surface the use-case context (HITL strategy, risk tier,
# business owner, intake code/title) alongside the entity itself.
# =============================================================================

async def _resolve_intake_context_for_entities(
    verity, entity_type: str, entity_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Map entity_id -> intake context (or {} when no intake link).

    The intake_entity_link table points at the entity HEADER (agent, task,
    prompt), not at a specific version. So lookups use the entity_id from
    v_entity_version (which is the header id, despite the column name).

    When an entity is linked to multiple intakes, the most-recent live or
    approved intake wins. This is the right tiebreaker for reports —
    auditors want the operative use-case context, not historical ones.
    """
    if not entity_ids:
        return {}
    rows = await verity.db.fetch_all_raw(
        """
        WITH ranked AS (
            SELECT
                l.entity_id,
                i.code              AS intake_code,
                i.title             AS intake_title,
                i.ai_risk_tier::text AS intake_risk_tier,
                i.naic_materiality::text AS intake_naic_materiality,
                i.business_owner_name,
                i.hitl_strategy,
                i.hitl_review_threshold,
                i.status::text      AS intake_status,
                ROW_NUMBER() OVER (
                    PARTITION BY l.entity_id
                    ORDER BY
                        CASE i.status::text
                            WHEN 'live' THEN 0 WHEN 'approved' THEN 1
                            WHEN 'in_build' THEN 2 ELSE 3 END,
                        i.intake_at DESC
                ) AS rn
            FROM governance.intake_entity_link l
            JOIN governance.intake i ON i.id = l.intake_id
            WHERE l.entity_type = %(entity_type)s::governance.entity_type
              AND l.entity_id = ANY(%(entity_ids)s::uuid[])
        )
        SELECT *
        FROM ranked
        WHERE rn = 1
        """,
        {
            "entity_type": entity_type,
            "entity_ids": [str(eid) for eid in entity_ids],
        },
    )
    return {str(r["entity_id"]): dict(r) for r in rows}


def _attach_intake_context(asset_row: dict[str, Any], context_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Merge intake context fields onto an asset row.

    Adds (always present, '—' when missing):
      intake_code, intake_title, intake_risk_tier, intake_naic_materiality,
      intake_status, business_owner_name (overrides asset's own owner),
      hitl_strategy, hitl_review_threshold

    Reports can render these unconditionally without an existence check.
    """
    eid = str(asset_row.get("entity_id") or "")
    ctx = context_map.get(eid) or {}
    asset_row["intake_code"]               = ctx.get("intake_code") or "—"
    asset_row["intake_title"]              = ctx.get("intake_title") or "—"
    asset_row["intake_risk_tier"]          = ctx.get("intake_risk_tier") or "—"
    asset_row["intake_naic_materiality"]   = ctx.get("intake_naic_materiality") or "—"
    asset_row["intake_status"]             = ctx.get("intake_status") or "—"
    asset_row["intake_business_owner"]     = ctx.get("business_owner_name") or "—"
    asset_row["hitl_strategy"]             = ctx.get("hitl_strategy") or "Not recorded"
    asset_row["hitl_review_threshold"]     = ctx.get("hitl_review_threshold") or "—"
    return asset_row


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

    # Attach intake context (HITL strategy, risk tier, business owner)
    # to each row by joining through intake_entity_link. Per-entity-type
    # because the link table is polymorphic on (entity_type, entity_id).
    by_type_ids: dict[str, list[str]] = defaultdict(list)
    for r in inventory_rows:
        if r.get("entity_id") and r.get("entity_type") in ("agent", "task", "prompt"):
            by_type_ids[r["entity_type"]].append(r["entity_id"])
    context_maps: dict[str, dict[str, dict[str, Any]]] = {}
    for et, ids in by_type_ids.items():
        context_maps[et] = await _resolve_intake_context_for_entities(verity, et, ids)
    for r in inventory_rows:
        cmap = context_maps.get(r.get("entity_type"), {})
        _attach_intake_context(r, cmap)

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

    # Attach intake context — HITL strategy, risk tier, business owner —
    # so the high-risk deep-dive Word doc shows the use-case framing
    # alongside the model. Single-entity lookup; cheap.
    _ctx_map = await _resolve_intake_context_for_entities(
        verity, target["entity_type"], [target["entity_id"]],
    )
    _attach_intake_context(target, _ctx_map)
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
# Use Case Intake Inventory
# =============================================================================

async def compose_intake_inventory(
    verity, scope: dict[str, Any]
) -> dict[str, Any]:
    """Enumerate every recorded use case, with realisation counts.

    Optional scope:
      intake_code     — restrict to one intake
      ai_risk_tier    — restrict to one risk tier
      status          — restrict to one intake status

    Returns:
      intakes                 — list of intake rows with realisation counts
      by_risk_tier            — Counter for executive summary
      by_status               — Counter for executive summary
      total_count             — len(intakes)
      high_risk_count         — count where ai_risk_tier='high'
    """
    rows = await verity.db.fetch_all_raw(
        """
        SELECT
            v.intake_code,
            v.intake_title,
            v.problem_statement,
            v.expected_benefit,
            v.in_scope_decisions,
            v.out_of_scope_decisions,
            v.affected_populations,
            v.business_owner_name,
            v.business_owner_email,
            v.requesting_team,
            v.ai_risk_tier,
            v.naic_materiality,
            v.risk_classification_rationale,
            v.intake_status,
            v.intake_at,
            v.approved_at,
            v.retired_at,
            v.hitl_strategy,
            v.hitl_review_threshold,
            (SELECT COUNT(*) FROM governance.intake_entity_link l
              WHERE l.intake_id = v.intake_id) AS linked_entity_count,
            (SELECT COUNT(*) FROM governance.intake_requirement r
              WHERE r.intake_id = v.intake_id) AS requirement_count,
            (SELECT COUNT(*) FROM governance.intake_artifact_plan p
              WHERE p.intake_id = v.intake_id
                AND p.status = 'realized') AS realized_plan_count,
            (SELECT COUNT(*) FROM governance.intake_artifact_plan p
              WHERE p.intake_id = v.intake_id
                AND p.status = 'proposed') AS proposed_plan_count
        FROM analytics.v_intake v
        WHERE
            (%(intake_code)s::text IS NULL OR v.intake_code = %(intake_code)s)
        AND (%(ai_risk_tier)s::text IS NULL OR v.ai_risk_tier = %(ai_risk_tier)s)
        AND (%(status)s::text IS NULL OR v.intake_status = %(status)s)
        ORDER BY
            CASE v.ai_risk_tier
                WHEN 'high'         THEN 1
                WHEN 'limited'      THEN 2
                WHEN 'minimal'      THEN 3
                WHEN 'unacceptable' THEN 4
                ELSE 5
            END,
            v.intake_at DESC
        """,
        {
            "intake_code":  scope.get("intake_code") or None,
            "ai_risk_tier": scope.get("ai_risk_tier") or None,
            "status":       scope.get("status") or None,
        },
    )

    intakes = [dict(r) for r in rows]
    # Defensive defaults for HITL on unrecorded intakes — keeps the
    # template render stable.
    for r in intakes:
        r["hitl_strategy"] = r.get("hitl_strategy") or "Not recorded"
        r["hitl_review_threshold"] = r.get("hitl_review_threshold") or "—"

    by_risk_tier = Counter(r.get("ai_risk_tier") or "—" for r in intakes)
    by_status    = Counter(r.get("intake_status") or "—" for r in intakes)

    return {
        "intakes":          intakes,
        "by_risk_tier":     dict(by_risk_tier),
        "by_status":        dict(by_status),
        "total_count":      len(intakes),
        "high_risk_count":  by_risk_tier.get("high", 0),
        "limited_count":    by_risk_tier.get("limited", 0),
        "minimal_count":    by_risk_tier.get("minimal", 0),
        "approved_count":   by_status.get("approved", 0) + by_status.get("live", 0),
    }


# =============================================================================
# Approval Audit Log
# =============================================================================

async def compose_approval_audit_log(
    verity, scope: dict[str, Any]
) -> dict[str, Any]:
    """Per-signoff audit log scoped to an intake or program-wide.

    Optional scope:
      intake_code        — restrict to one intake
      signed_after       — ISO 8601 datetime; signed_at >= this
      signed_before      — ISO 8601 datetime; signed_at < this
      signoff_role       — restrict to one approval role
    """
    rows = await verity.db.fetch_all_raw(
        """
        SELECT
            v.intake_code,
            v.intake_title,
            v.ai_risk_tier,
            v.approval_kind,
            v.approval_request_status,
            v.approval_summary,
            v.opened_at,
            v.opened_by,
            v.opened_by_role,
            v.decided_at,
            v.signoff_role,
            v.approver_name,
            v.approver_email,
            v.signoff_decision,
            v.signoff_comment,
            v.evidence_url,
            v.signed_at
        FROM analytics.v_intake_approval v
        WHERE v.signoff_role IS NOT NULL  -- exclude not-yet-signed pending requests
            AND (%(intake_code)s::text IS NULL OR v.intake_code = %(intake_code)s)
            AND (%(signed_after)s::timestamptz IS NULL
                 OR v.signed_at >= %(signed_after)s::timestamptz)
            AND (%(signed_before)s::timestamptz IS NULL
                 OR v.signed_at < %(signed_before)s::timestamptz)
            AND (%(signoff_role)s::text IS NULL OR v.signoff_role = %(signoff_role)s)
        ORDER BY v.signed_at DESC
        """,
        {
            "intake_code":   scope.get("intake_code") or None,
            "signed_after":  scope.get("signed_after") or None,
            "signed_before": scope.get("signed_before") or None,
            "signoff_role":  scope.get("signoff_role") or None,
        },
    )
    signoffs = [dict(r) for r in rows]
    by_role     = Counter(r.get("signoff_role")     or "—" for r in signoffs)
    by_decision = Counter(r.get("signoff_decision") or "—" for r in signoffs)
    by_kind     = Counter(r.get("approval_kind")    or "—" for r in signoffs)

    return {
        "signoffs":        signoffs,
        "signoff_count":   len(signoffs),
        "by_role":         dict(by_role),
        "by_decision":     dict(by_decision),
        "by_kind":         dict(by_kind),
        "approved_count":  by_decision.get("approved", 0),
        "rejected_count":  by_decision.get("rejected", 0),
    }


# =============================================================================
# Impact Assessment Register
# =============================================================================

async def compose_intake_impact_assessment_register(
    verity, scope: dict[str, Any]
) -> dict[str, Any]:
    """Register of intakes with their impact assessments.

    Default scope: ai_risk_tier='high'. Set to 'limited' (or unset
    via scope.include_limited=true) to widen.
    """
    intake_code = scope.get("intake_code") or None
    risk_tier   = scope.get("ai_risk_tier") or "high"

    rows = await verity.db.fetch_all_raw(
        """
        SELECT
            v.intake_code,
            v.intake_title,
            v.business_owner_name,
            v.requesting_team,
            v.ai_risk_tier,
            v.naic_materiality,
            v.intake_status,
            v.affected_populations,
            v.hitl_strategy,
            v.hitl_review_threshold,
            ia.data_sources,
            ia.potential_harms,
            ia.mitigations,
            ia.fairness_considerations,
            ia.privacy_considerations,
            ia.human_oversight_plan,
            ia.completed_at         AS assessment_completed_at,
            ia.completed_by         AS assessment_completed_by,
            ia.notes                AS assessment_notes,
            (ia.id IS NOT NULL)     AS has_assessment
        FROM analytics.v_intake v
        LEFT JOIN governance.intake_impact_assessment ia
            ON ia.intake_id = v.intake_id
        WHERE v.ai_risk_tier = %(risk_tier)s
          AND (%(intake_code)s::text IS NULL OR v.intake_code = %(intake_code)s)
        ORDER BY v.intake_at DESC
        """,
        {"risk_tier": risk_tier, "intake_code": intake_code},
    )
    intakes = [dict(r) for r in rows]
    for r in intakes:
        r["hitl_strategy"]            = r.get("hitl_strategy") or "Not recorded"
        r["hitl_review_threshold"]    = r.get("hitl_review_threshold") or "—"
        r["fairness_considerations"]  = r.get("fairness_considerations") or "—"
        r["privacy_considerations"]   = r.get("privacy_considerations") or "—"
        r["human_oversight_plan"]     = r.get("human_oversight_plan") or "—"

    completed = [r for r in intakes if r["has_assessment"] and r["assessment_completed_at"]]
    return {
        "intakes":          intakes,
        "intake_count":     len(intakes),
        "completed_count":  len(completed),
        "missing_count":    len(intakes) - len(completed),
        "risk_tier":        risk_tier,
    }


# =============================================================================
# Registry — report code → composer
# =============================================================================

COMPOSERS: dict[str, callable] = {
    "model_inventory":                  compose_model_inventory,
    "decision_audit_trail":             compose_decision_audit_trail,    # single decision
    "workflow_audit_trail":             compose_workflow_audit_trail,    # one workflow
    "fairness_validation_summary":      compose_fairness_validation_summary,
    "naic_exhibit_c":                   compose_naic_exhibit_c,
    # Phase B — governance intake reports.
    "intake_inventory":                 compose_intake_inventory,
    "approval_audit_log":               compose_approval_audit_log,
    "intake_impact_assessment_register": compose_intake_impact_assessment_register,
}
