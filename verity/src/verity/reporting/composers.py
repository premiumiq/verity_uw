"""Per-report composer functions.

A composer takes (verity_client, scope_dict) and returns a body dict that
gets merged into the standard report envelope (see engine.resolve_dataset).

Adding a new report:
  1. Define the report in compliance_seed_reports.yaml (and seed-reports).
  2. Add a composer function here.
  3. Register it in COMPOSERS at the bottom.

Composers query verity_analytics.* views ONLY — they never touch L1 directly.
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
        FROM verity_analytics.v_entity_version ev
        LEFT JOIN verity_analytics.v_application_entity ae
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
        FROM verity_analytics.v_lifecycle_event le
        LEFT JOIN verity_analytics.v_entity_version av
               ON av.source_pk = le.entity_version_id::text AND le.entity_type = 'agent'
        LEFT JOIN verity_analytics.v_entity_version tv
               ON tv.source_pk = le.entity_version_id::text AND le.entity_type = 'task'
        LEFT JOIN verity_analytics.v_entity_version pv
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
# Registry — report code → composer
# =============================================================================

COMPOSERS: dict[str, callable] = {
    "model_inventory": compose_model_inventory,
}
