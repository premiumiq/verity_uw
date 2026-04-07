"""PDF form filler - fills fillable PDF form fields from a data dictionary.

Uses PyMuPDF (fitz) to set form field values programmatically.
Supports text fields, checkboxes, and radio buttons.

The field_map JSON defines the mapping between profile data keys and
PDF form field names. This keeps the filler generic - the same code
works for any fillable PDF as long as you provide the right field map.
"""

import json
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


# Built-in field maps and PDF templates are shipped with the package
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_FIELD_MAPS_DIR = _TEMPLATES_DIR / "field_maps"
_PDF_TEMPLATES_DIR = _TEMPLATES_DIR / "pdf"


def load_field_map(name_or_path: str) -> dict:
    """Load a field map by built-in name or file path.

    Built-in names: "DOandEPLI", "acord-125"
    Or pass a full path to a custom field map JSON.
    """
    # Check if it's a built-in name
    builtin_path = _FIELD_MAPS_DIR / f"{name_or_path}.json"
    if builtin_path.exists():
        return json.loads(builtin_path.read_text())

    # Otherwise treat as a file path
    path = Path(name_or_path)
    if path.exists():
        return json.loads(path.read_text())

    raise FileNotFoundError(
        f"Field map '{name_or_path}' not found. "
        f"Checked: {builtin_path}, {path}"
    )


def fill_pdf(
    template_path: str | Path,
    field_map: dict,
    data: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Fill a PDF form from a data dictionary using a field map.

    Args:
        template_path: Path to the blank fillable PDF template.
        field_map: Dict mapping data keys to PDF form field names.
                   Each entry: {"data_key": {"pdf_field": "Name of Applicant", "type": "text"}}
                   Types: "text", "checkbox_yes", "checkbox_no", "checkbox_pair"
        data: Dict of values to fill (keyed by data_key names from field_map).
        output_path: Where to save the filled PDF.

    Returns:
        Path to the saved file.

    Field map format:
        {
            "named_insured": {
                "pdf_field": "Name of Applicant",
                "type": "text"
            },
            "do_coverage": {
                "pdf_field_yes": "Directors & Officers",
                "pdf_field_no": null,
                "type": "checkbox_pair"
            }
        }
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Open the template
    doc = fitz.open(str(template_path))

    # Build a reverse lookup: pdf_field_name -> (data_key, mapping)
    # so we can match widgets as we iterate page by page
    field_lookup: dict[str, tuple[str, dict]] = {}
    for data_key, mapping in field_map.items():
        value = data.get(data_key)
        if value is None:
            continue
        field_type = mapping.get("type", "text")
        if field_type == "text":
            field_lookup[mapping["pdf_field"]] = (data_key, mapping, value)
        elif field_type == "checkbox_pair":
            target = mapping.get("pdf_field_yes") if value else mapping.get("pdf_field_no")
            if target:
                field_lookup[target] = (data_key, mapping, True)
        elif field_type == "checkbox":
            field_lookup[mapping["pdf_field"]] = (data_key, mapping, bool(value))

    # Fill fields page by page (keeps widget-to-page binding intact)
    filled_count = 0
    skipped = []

    for page in doc:
        for widget in page.widgets():
            name = widget.field_name
            if not name or name not in field_lookup:
                continue
            data_key, mapping, value = field_lookup[name]
            field_type = mapping.get("type", "text")
            try:
                if field_type == "text":
                    widget.field_value = str(value)
                else:
                    # Checkbox - set to checked
                    widget.field_value = True
                widget.update()
                filled_count += 1
            except (RuntimeError, Exception) as e:
                skipped.append(f"{data_key} -> {name} (error: {e})")

    # Save the filled PDF
    doc.save(str(output_path))
    doc.close()

    return output_path


def list_pdf_fields(pdf_path: str | Path) -> list[dict]:
    """Utility: list all form fields in a PDF with their names and types.

    Useful for building field maps for new PDF templates.
    """
    doc = fitz.open(str(pdf_path))
    fields = []
    for page_num, page in enumerate(doc):
        for widget in page.widgets():
            fields.append({
                "page": page_num + 1,
                "name": widget.field_name,
                "type": widget.field_type_string,
                "value": widget.field_value,
            })
    doc.close()
    return fields
