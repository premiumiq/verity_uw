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

from collections import Counter
from typing import Any


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

    # Aggregate counts for the executive summary.
    materiality_counter = Counter(
        (r["materiality_tier"] or "—") for r in inventory_rows
    )
    state_counter       = Counter(
        (r["lifecycle_state"] or "—") for r in inventory_rows
    )
    type_counter        = Counter(
        (r["entity_type"] or "—") for r in inventory_rows
    )

    # Recent state transitions (the change-management evidence section).
    recent_events = await verity.db.fetch_all_raw(
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
            COALESCE(av.entity_name, tv.entity_name, pv.entity_name, '—') AS entity_name,
            COALESCE(av.version_label, tv.version_label, pv.version_label, '—') AS version_label
        FROM verity_analytics.v_lifecycle_event le
        LEFT JOIN verity_analytics.v_entity_version av
               ON av.source_pk = le.entity_version_id::text AND le.entity_type = 'agent'
        LEFT JOIN verity_analytics.v_entity_version tv
               ON tv.source_pk = le.entity_version_id::text AND le.entity_type = 'task'
        LEFT JOIN verity_analytics.v_entity_version pv
               ON pv.source_pk = le.entity_version_id::text AND le.entity_type = 'prompt'
        ORDER BY le.approved_at DESC
        LIMIT 25
        """
    )

    return {
        "inventory_rows":     inventory_rows,
        "inventory_count":    len(inventory_rows),
        "by_materiality":     dict(materiality_counter),
        "by_lifecycle_state": dict(state_counter),
        "by_entity_type":     dict(type_counter),
        "recent_lifecycle_events": recent_events,
        # Convenience counts for the executive summary template:
        "high_count":   materiality_counter.get("high", 0),
        "medium_count": materiality_counter.get("medium", 0),
        "low_count":    materiality_counter.get("low", 0),
        "total_count":  len(inventory_rows),
    }


# =============================================================================
# Registry — report code → composer
# =============================================================================

COMPOSERS: dict[str, callable] = {
    "model_inventory": compose_model_inventory,
}
