"""Verity Reporting — metadata-driven compliance report engine.

A report is rows in:
    compliance.report_definition
    compliance.report_requirement (canonicals it covers)
    compliance.requirement_evidence_field (canonical → mart_field manifest)

The engine resolves a report definition to a `dataset` dict, then renders that
dataset through a docx template (docxtpl). Same dataset can also feed an HTML
preview or PDF (DOCX → PDF via LibreOffice).

Architecture: docs/architecture/compliance-stack.md (L4 + L5)
"""

from verity.reporting.engine import (
    list_reports,
    get_report_definition,
    get_report_field_manifest,
    get_report_canonicals,
    resolve_dataset,
)
from verity.reporting.composers import COMPOSERS
from verity.reporting.render import render_docx

__all__ = [
    "list_reports",
    "get_report_definition",
    "get_report_field_manifest",
    "get_report_canonicals",
    "resolve_dataset",
    "render_docx",
    "COMPOSERS",
]
