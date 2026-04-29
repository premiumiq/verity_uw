"""Render a resolved dataset into a DOCX file via docxtpl.

PDF rendering (via LibreOffice headless) is intentionally deferred — for now
we ship DOCX only and let users open it in Word.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from docxtpl import DocxTemplate  # type: ignore


# Paths
TEMPLATES_DIR = Path(__file__).parent / "templates"
DEFAULT_OUTPUT_DIR = Path("/tmp/verity-reports")


def _resolve_template_path(docx_template: str | None, report_code: str) -> Path:
    """Locate the .docx template for a report.

    Looks up either the explicit path declared in report_definition.docx_template
    (relative to the verity package root) or falls back to
    `templates/<report_code>.docx`.
    """
    if docx_template:
        # Explicit path. Allow either an absolute path, a path relative to the
        # verity package, or a path relative to TEMPLATES_DIR.
        p = Path(docx_template)
        if p.is_absolute() and p.exists():
            return p
        # `reports/model_inventory.docx` → templates/model_inventory.docx
        candidates = [
            TEMPLATES_DIR / Path(docx_template).name,
            Path(__file__).parents[1] / docx_template,
        ]
        for c in candidates:
            if c.exists():
                return c

    # Fallback: templates/<report_code>.docx
    fallback = TEMPLATES_DIR / f"{report_code}.docx"
    if not fallback.exists():
        raise FileNotFoundError(
            f"No DOCX template found for report {report_code!r}. "
            f"Expected at {fallback} or via report_definition.docx_template. "
            f"Generate one with: python -m verity.reporting._template_authoring {report_code}"
        )
    return fallback


def render_docx(
    dataset: dict[str, Any],
    *,
    report_code: str,
    docx_template: str | None = None,
    output_path: Path | str | None = None,
) -> Path:
    """Fill a Word template with the dataset and write a DOCX file.

    Args:
        dataset: dict produced by verity.reporting.resolve_dataset().
        report_code: report_definition.code (used for the default file name).
        docx_template: optional override; defaults to report_definition.docx_template
            or templates/<report_code>.docx.
        output_path: where to save. Defaults to
            /tmp/verity-reports/<report_code>__<timestamp>.docx.

    Returns the saved file path.
    """
    template_path = _resolve_template_path(docx_template, report_code)

    if output_path is None:
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        output_path = DEFAULT_OUTPUT_DIR / f"{report_code}__{ts}.docx"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tpl = DocxTemplate(str(template_path))
    tpl.render(dataset)
    tpl.save(str(output_path))
    return output_path
