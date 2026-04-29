"""Declarative layout map for submission-level fields.

The single source of truth for "which fields exist, where they
appear in the form, and how they're formatted".

Used by:
  - The Submission Details tab template (read-only render).
  - The inline field editor (decides which input element a
    formatter implies — text vs select vs date picker).
  - The HITL queue UI (deep-links by field_name).
  - Any future form surface that displays submission fields.

Defining once keeps every consumer in lockstep — adding a field
or moving it to a different section is a one-line change here.

Each entry:
  ("field_name", "Display Label", "formatter")

`field_name` matches:
  - Column on `submission` (the broker-stated value).
  - `field_name` row in `submission_extraction` (the AI-extracted
    counterpart, when one exists).

`formatter` is one of:
  text       — render the value as-is
  int        — integer (no decimals, no separator)
  count      — integer with thousand separator
  currency   — currency, dollar sign, no decimals (e.g. $5,000,000)
  date       — formatted date (e.g. Jul 01, 2026); accepts a
               date / datetime object or an ISO-8601 string
  badge      — render in a verity-badge container (used for LOB)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional


# Each top-level entry is (section_title, [fields], lob_filter).
# lob_filter=None means "show for every LOB"; a value like "DO"
# means "only for D&O submissions".

FIELD_GROUPS: list[tuple[str, list[tuple[str, str, str]], Optional[str]]] = [
    ("Company", [
        ("named_insured",          "Named Insured",         "text"),
        ("fein",                   "FEIN",                  "text"),
        ("entity_type",            "Entity Type",           "text"),
        ("state_of_incorporation", "State of Incorporation","text"),
        ("sic_code",               "SIC Code",              "text"),
        ("sic_description",        "Industry",              "text"),
        ("annual_revenue",         "Annual Revenue",        "currency"),
        ("employee_count",         "Employee Count",        "count"),
    ], None),

    ("Policy", [
        ("lob",                    "Line of Business",      "badge"),
        ("effective_date",         "Effective Date",        "date"),
        ("expiration_date",        "Expiration Date",       "date"),
        ("limits_requested",       "Limits Requested",      "currency"),
        ("retention_requested",    "Retention",             "currency"),
    ], None),

    ("Prior Coverage", [
        ("prior_carrier",          "Prior Carrier",         "text"),
        ("prior_premium",          "Prior Premium",         "currency"),
    ], None),

    # D&O-specific board details. Hidden for GL submissions; the
    # template checks `lob_filter` per section.
    ("Board (D&O)", [
        ("board_size",             "Board Size",            "int"),
        ("independent_directors",  "Independent Directors", "int"),
    ], "DO"),
]


# Set of all field_names defined in the layout. Useful for
# validating that an edit / queue deep-link refers to a real
# layout field before persisting.
LAYOUT_FIELD_NAMES: frozenset[str] = frozenset(
    fname for _, fields, _ in FIELD_GROUPS for fname, _, _ in fields
)


def format_value(raw, formatter: str) -> str:
    """Format a raw value for display per the layout's formatter
    string. Returns '—' for None/empty so blank fields render
    consistently.

    The reverse direction (parsing user-typed text back into a
    Python value) lives in the edit handler, not here — keeping
    the read path small."""
    if raw is None or raw == "":
        return "—"
    try:
        if formatter == "currency":
            return f"${int(raw):,}"
        if formatter == "count":
            return f"{int(raw):,}"
        if formatter == "int":
            return f"{int(raw)}"
        if formatter == "date":
            # Accept date / datetime / iso-8601 string. AI-extracted
            # dates come through as strings ("2026-07-01"); broker-
            # stated dates come from psycopg as date objects. Both
            # need the same human-readable rendering.
            if isinstance(raw, (date, datetime)):
                return raw.strftime("%b %d, %Y")
            if isinstance(raw, str):
                # Accept the ISO date prefix and ignore any time
                # component if present. fromisoformat handles both
                # 'YYYY-MM-DD' and 'YYYY-MM-DDTHH:MM:SS'.
                try:
                    return date.fromisoformat(raw[:10]).strftime("%b %d, %Y")
                except ValueError:
                    return raw
            return str(raw)
        # 'text' and 'badge' fall through.
        return str(raw)
    except (TypeError, ValueError):
        return str(raw)
