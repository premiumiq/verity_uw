"""Report engine — resolves report_definition + scope params → dataset dict.

The dataset is a plain dict keyed for direct use by:
  - docxtpl (Word template rendering)
  - Jinja2 HTML preview
  - JSON/CSV export

Per-report logic lives in `composers.py` (one function per report code).
This module wires everything together: definition lookup, manifest assembly,
composer dispatch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


async def list_reports(verity) -> list[dict[str, Any]]:
    """Return all active report_definition rows (for the reports list page)."""
    return await verity.db.fetch_all_raw(
        """
        SELECT id, code, name, description, report_kind,
               docx_template, output_formats, scope_params,
               sort_seq, is_active, created_at
        FROM verity_compliance.report_definition
        WHERE is_active = true
        ORDER BY sort_seq, code
        """
    )


async def get_report_definition(verity, report_code: str) -> dict[str, Any] | None:
    """Look up one report by code. Returns None if unknown."""
    return await verity.db.fetch_one_raw(
        """
        SELECT id, code, name, description, report_kind,
               docx_template, output_formats, scope_params,
               sort_seq, is_active, created_at
        FROM verity_compliance.report_definition
        WHERE code = %(code)s
        """,
        {"code": report_code},
    )


async def get_report_field_manifest(
    verity, report_code: str
) -> list[dict[str, Any]]:
    """Walk report_definition → report_requirement → canonical_requirement
    → requirement_evidence_field → mart_field, returning the de-duplicated
    field list this report touches.

    Used both for the report-detail UI ("which evidence fields back this
    report") and as a sanity check before SQL planning.
    """
    return await verity.db.fetch_all_raw(
        """
        SELECT DISTINCT
               mf.id           AS mart_field_id,
               mf.table_name   AS table_name,
               mf.column_name  AS column_name,
               mf.semantic_type,
               mf.description,
               mf.is_pii,
               mf.sort_seq     AS field_sort_seq,
               ref.role,
               ref.aggregation,
               cr.code         AS canonical_code,
               cr.title        AS canonical_title,
               t.code          AS theme_code
        FROM verity_compliance.report_definition         rd
        JOIN verity_compliance.report_requirement        rr
             ON rr.report_id = rd.id
        JOIN verity_compliance.canonical_requirement     cr
             ON cr.id = rr.canonical_requirement_id
        JOIN verity_compliance.canonical_requirement_theme t
             ON t.id = cr.theme_id
        JOIN verity_compliance.requirement_evidence_field ref
             ON ref.canonical_requirement_id = cr.id
        JOIN verity_analytics.mart_field                  mf
             ON mf.id = ref.mart_field_id
        WHERE rd.code = %(code)s
        ORDER BY mf.table_name, field_sort_seq, mf.column_name
        """,
        {"code": report_code},
    )


async def get_report_canonicals(
    verity, report_code: str
) -> list[dict[str, Any]]:
    """Return the canonical requirements this report covers, in section order.

    Each row also carries:
      - `provisions`: list of {citation, title, framework_code, framework_name}
      - `frameworks`: list of distinct framework codes citing this canonical
      - `frameworks_label`: comma-separated framework codes for inline display
    """
    return await verity.db.fetch_all_raw(
        """
        SELECT cr.code, cr.title, cr.description,
               t.code AS theme_code, t.name AS theme_name,
               cov.coverage_level,
               rr.section, rr.sort_seq, rr.notes,
               COALESCE(
                   (SELECT json_agg(json_build_object(
                              'citation',       p.citation,
                              'title',          p.title,
                              'framework_code', f.code,
                              'framework_name', f.name
                          ) ORDER BY f.sort_seq, p.sort_seq)
                    FROM verity_compliance.provision_requirement_map prm
                    JOIN verity_compliance.regulatory_provision  p ON p.id = prm.provision_id
                    JOIN verity_compliance.regulatory_framework  f ON f.id = p.framework_id
                    WHERE prm.canonical_requirement_id = cr.id),
                   '[]'::json
               ) AS provisions,
               COALESCE(
                   (SELECT string_agg(DISTINCT f.code, ', ' ORDER BY f.code)
                    FROM verity_compliance.provision_requirement_map prm
                    JOIN verity_compliance.regulatory_provision  p ON p.id = prm.provision_id
                    JOIN verity_compliance.regulatory_framework  f ON f.id = p.framework_id
                    WHERE prm.canonical_requirement_id = cr.id),
                   '—'
               ) AS frameworks_label
        FROM verity_compliance.report_requirement       rr
        JOIN verity_compliance.report_definition        rd
             ON rd.id = rr.report_id
        JOIN verity_compliance.canonical_requirement    cr
             ON cr.id = rr.canonical_requirement_id
        JOIN verity_compliance.canonical_requirement_theme t
             ON t.id = cr.theme_id
        LEFT JOIN verity_compliance.requirement_coverage cov
             ON cov.canonical_requirement_id = cr.id
        WHERE rd.code = %(code)s
        ORDER BY rr.sort_seq, cr.sort_seq
        """,
        {"code": report_code},
    )


async def resolve_dataset(
    verity, report_code: str, scope: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Resolve a report into a dataset dict ready for rendering.

    Steps:
      1. Look up report_definition.
      2. Look up the canonicals it covers + their coverage.
      3. Look up the field manifest.
      4. Dispatch to the per-report composer (composers.py).
      5. Layer in standard fields (title, scope, generated_at, manifest).

    Returns a flat dict the docx template can consume directly.
    """
    from verity.reporting.composers import COMPOSERS

    scope = dict(scope or {})

    definition = await get_report_definition(verity, report_code)
    if not definition:
        raise ValueError(f"Unknown report code: {report_code!r}")

    composer = COMPOSERS.get(report_code)
    if composer is None:
        raise ValueError(
            f"No composer registered for report {report_code!r}. "
            f"Add one to verity/reporting/composers.py."
        )

    # Stage 1: report-specific data assembly.
    body = await composer(verity, scope)

    # Stage 2: standard envelope + governance metadata.
    canonicals = await get_report_canonicals(verity, report_code)
    manifest = await get_report_field_manifest(verity, report_code)

    return {
        "report_code":     definition["code"],
        "report_title":    definition["name"],
        "report_description": definition["description"] or "",
        "generated_at":    datetime.now(timezone.utc),
        "generated_at_str": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "scope":           scope,
        "scope_summary":   _format_scope(scope),
        "canonicals":      canonicals,
        "manifest":        manifest,
        **body,
    }


def _format_scope(scope: dict[str, Any]) -> str:
    """Render a one-line human-readable scope label for headers."""
    if not scope:
        return "All applications, all materiality tiers"
    parts = []
    if scope.get("application_code"):
        parts.append(f"application={scope['application_code']}")
    if scope.get("materiality_tier"):
        parts.append(f"materiality={scope['materiality_tier']}")
    if scope.get("as_of_date"):
        parts.append(f"as_of={scope['as_of_date']}")
    return ", ".join(parts) if parts else "All applications, all materiality tiers"
