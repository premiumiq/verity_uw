"""EDMS text extraction — extract readable text from documents.

Supports:
- PDF files: extracts page text + form field values using PyMuPDF
- Text files: reads content directly (no extraction needed)

The extracted text is what gets fed to Verity's classifier and
extractor agents via tool calls.
"""

import io
from pathlib import Path

import fitz  # PyMuPDF


def extract_text_from_bytes(content: bytes, filename: str) -> str:
    """Extract text from a document's raw bytes.

    Args:
        content: File content as bytes (from MinIO download)
        filename: Original filename (used to determine file type)

    Returns:
        Extracted text as a string.

    Raises:
        ValueError: If file type is not supported for text extraction.
    """
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        return _extract_from_pdf(content)
    elif suffix in (".txt", ".text", ".csv"):
        return content.decode("utf-8", errors="replace")
    elif suffix in (".json",):
        return content.decode("utf-8", errors="replace")
    else:
        raise ValueError(
            f"Unsupported file type '{suffix}' for text extraction. "
            f"Supported: .pdf, .txt, .csv, .json"
        )


def _extract_from_pdf(content: bytes) -> str:
    """Extract text from a PDF document.

    Combines two sources of text:
    1. Page text (from rendered text layer — what you see when reading)
    2. Form field values (from fillable form fields — what was typed in)

    This is important because filled ACORD forms have data in form fields
    that may not appear in the page text layer.
    """
    doc = fitz.open(stream=content, filetype="pdf")
    parts = []

    # First: extract form field values (if any fillable fields exist)
    form_values = []
    for page in doc:
        for widget in page.widgets():
            name = widget.field_name or "unnamed"
            value = widget.field_value
            if value and str(value).strip():
                form_values.append(f"{name}: {value}")

    if form_values:
        parts.append("=== FORM FIELD VALUES ===")
        parts.append("\n".join(form_values))
        parts.append("")

    # Second: extract page text (the rendered text layer)
    parts.append("=== DOCUMENT TEXT ===")
    for page_num, page in enumerate(doc):
        page_text = page.get_text().strip()
        if page_text:
            parts.append(f"--- Page {page_num + 1} ---")
            parts.append(page_text)

    doc.close()

    return "\n".join(parts)
