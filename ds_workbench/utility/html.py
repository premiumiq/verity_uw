"""Verity-UI-styled HTML building blocks for notebooks.

Makes notebook outputs look like mini-Verity-admin-UI views — the
same tables, badges, cards, and detail layouts the user sees at
`/admin/*`, rendered inside cell outputs via `IPython.display.HTML`.

Scope
-----
This module provides *building blocks only*: a stylesheet and a
small set of generic primitives. It does NOT try to recreate every
admin page. Notebooks call the primitives with their own column
and section choices — that keeps each notebook's rendering under
its own control and avoids a flurry of entity-specific renderers
that would duplicate what the admin UI already provides.

Design
------
- Zero CDN dependencies. All styles are inlined in `VERITY_STYLESHEET`
  so notebooks render identically offline and online.
- `inject_style()` is called once at the top of a notebook; every
  subsequent `HTML(...)` cell output picks up the same classes.
- Be defensive about missing keys in data — a helper that works for
  an empty list or a partial row keeps the notebooks simple.

Usage
-----
    from utility.html import inject_style, badge, render_list, render_detail, render_cards
    inject_style()
    render_list(agents, columns=[
        ("display_name", "Agent"),
        ("materiality_tier", "Materiality", "*"),
        ("lifecycle_state", "State", "*"),
    ], title="Agents")

Primitives return `IPython.display.HTML` objects — pass them as the
last cell value or through `display(...)`.
"""

from html import escape
from typing import Any, Iterable, Optional, Union

from IPython.display import HTML


# ── Inline stylesheet — ported from verity/src/verity/web/static/verity.css ──
# Kept small: only the classes the primitives below emit. Colours are
# the Verity palette — match them to the admin UI so a screenshot
# of a notebook cell looks indistinguishable from the admin view.

VERITY_STYLESHEET = """
<style>
.verity-scope {
    font-family: 'Segoe UI', 'Poppins', system-ui, -apple-system, sans-serif;
    color: #4D4D4D;
    font-size: 13px;
    line-height: 1.45;
}
.verity-scope h2 { font-size: 1.25rem; font-weight: 600; margin: 0 0 6px 0; color: #2B4D8A; }
.verity-scope h3 { font-size: 0.95rem; font-weight: 600; margin: 18px 0 8px 0; color: #405A8A;
                    text-transform: uppercase; letter-spacing: .4px; }
.verity-scope p.verity-desc { color: #7F7F7F; margin: 0 0 14px 0; font-size: 0.85rem; }
.verity-scope .verity-section { margin-top: 14px; }

/* Tables */
.verity-scope table.verity-table {
    width: 100%; border-collapse: collapse; font-size: 0.85rem; background: white;
    border: 1px solid #DBDBDB; border-radius: 6px; overflow: hidden;
}
.verity-scope table.verity-table thead th {
    text-align: left; padding: 9px 12px;
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: .5px;
    color: #7F7F7F; font-weight: 600;
    border-bottom: 2px solid #DBDBDB; background: #F8FAFC;
}
.verity-scope table.verity-table tbody td {
    padding: 9px 12px; border-bottom: 1px solid #EDEDED; color: #4D4D4D;
    vertical-align: top;
}
.verity-scope table.verity-table tbody tr:nth-child(even) { background: #F9FAFB; }
.verity-scope table.verity-table tbody tr:hover { background: #E8EEF8; }

/* Badges */
.verity-scope .verity-badge {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: .3px;
    white-space: nowrap;
}
.verity-scope .badge-draft      { background: #E2E8F0; color: #64748B; }
.verity-scope .badge-candidate  { background: #E8EEF8; color: #2B4D8A; }
.verity-scope .badge-staging    { background: #D2DDF1; color: #405A8A; }
.verity-scope .badge-shadow     { background: #F9F0DA; color: #816014; }
.verity-scope .badge-challenger { background: #F9F0DA; color: #816014; }
.verity-scope .badge-champion   { background: #E8F0E9; color: #3E6044; }
.verity-scope .badge-deprecated { background: #D1D5DB; color: #4B5563; border: 1px solid #9CA3AF; }
.verity-scope .badge-high       { background: #F4DEDE; color: #A23838; }
.verity-scope .badge-medium     { background: #F9F0DA; color: #816014; }
.verity-scope .badge-low        { background: #E8F0E9; color: #3E6044; }
.verity-scope .badge-complete   { background: #E8F0E9; color: #3E6044; }
.verity-scope .badge-failed     { background: #F4DEDE; color: #A23838; }
.verity-scope .badge-pending    { background: #D2DDF1; color: #405A8A; }
.verity-scope .badge-agent      { background: #E8EEF8; color: #2B4D8A; }
.verity-scope .badge-task       { background: #E8EEF8; color: #405A8A; }
.verity-scope .badge-prompt     { background: #EDE9FE; color: #5B21B6; }
.verity-scope .badge-tool       { background: #FEF3C7; color: #92400E; }
.verity-scope .badge-pipeline   { background: #FCE7F3; color: #9D174D; }
.verity-scope .badge-neutral    { background: #F2F2F2; color: #4D4D4D; border: 1px solid #E5E7EB; }

/* Cards (dashboard + detail) */
.verity-scope .verity-cards {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px; margin: 12px 0;
}
.verity-scope .verity-card {
    background: white; border: 1px solid #DBDBDB; border-radius: 6px;
    padding: 14px 16px;
}
.verity-scope .verity-card .card-label {
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: .5px;
    color: #7F7F7F; font-weight: 600; margin-bottom: 6px;
}
.verity-scope .verity-card .card-value {
    font-size: 1.75rem; font-weight: 700; color: #2B4D8A; line-height: 1;
}
.verity-scope .verity-card .card-footer {
    font-size: 0.75rem; color: #7F7F7F; margin-top: 4px;
}

/* Detail views — two-column key/value grid */
.verity-scope .verity-kv {
    display: grid; grid-template-columns: 180px 1fr; gap: 6px 16px;
    margin: 6px 0 14px 0; font-size: 0.85rem;
}
.verity-scope .verity-kv .k { color: #7F7F7F; font-weight: 500; }
.verity-scope .verity-kv .v { color: #4D4D4D; word-break: break-word; }
.verity-scope .verity-kv .v code {
    background: #F2F2F2; padding: 1px 5px; border-radius: 3px;
    font-family: 'SF Mono', Consolas, monospace; font-size: 0.8rem;
}

/* Detail header */
.verity-scope .verity-header {
    display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
    margin-bottom: 10px;
}
.verity-scope .verity-header .title { font-size: 1.2rem; font-weight: 600; color: #2B4D8A; }
.verity-scope .verity-header .subtitle { color: #7F7F7F; font-size: 0.85rem; font-family: monospace; }

/* Empty state */
.verity-scope .verity-empty {
    text-align: center; color: #94A3B8; font-style: italic;
    padding: 30px 20px; border: 1px dashed #DBDBDB; border-radius: 6px; background: #FAFAFA;
}
</style>
""".strip()


# ── Setup ────────────────────────────────────────────────────

def inject_style() -> HTML:
    """Inject the Verity stylesheet into the notebook. Call once per
    notebook — usually in the setup cell right after imports. Every
    subsequent `HTML(...)` cell output picks up the same classes."""
    return HTML(VERITY_STYLESHEET)


# ── Primitive helpers ────────────────────────────────────────

# Known badge vocabularies — lifecycle state, materiality tier, entity
# type, decision status. `badge()` passes the value through and falls
# back to the "neutral" style when the variant is unrecognized.
_KNOWN_VARIANTS = {
    "draft", "candidate", "staging", "shadow", "challenger", "champion", "deprecated",
    "high", "medium", "low",
    "complete", "failed", "pending",
    "agent", "task", "prompt", "tool", "pipeline",
    "neutral",
}


def badge(text: Optional[Any], variant: Optional[str] = None) -> str:
    """Render one lozenge-shaped status badge as an HTML snippet.

    If `variant` is omitted, uses `str(text).lower()` as the variant
    key so passing a lifecycle state works both ways: `badge('champion')`
    and `badge('champion', 'champion')` render identically.
    """
    if text is None or text == "":
        return ""
    v = (variant or str(text).lower()).strip()
    if v not in _KNOWN_VARIANTS:
        v = "neutral"
    return f'<span class="verity-badge badge-{escape(v)}">{escape(str(text))}</span>'


def kv(label: str, value: Any) -> str:
    """Render one key-value row. Designed to be concatenated inside a
    `.verity-kv` grid container (see `render_detail`)."""
    if value is None or value == "":
        value_html = '<span style="color:#94A3B8;">—</span>'
    elif hasattr(value, "_repr_html_"):
        value_html = value._repr_html_()
    else:
        value_html = escape(str(value))
    return f'<div class="k">{escape(label)}</div><div class="v">{value_html}</div>'


def _cell(value: Any) -> str:
    """Table-cell formatter: None → em-dash; lists → comma-joined;
    long strings truncated to keep tables readable in notebook cells."""
    if value is None or value == "":
        return '<span style="color:#94A3B8;">—</span>'
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) if value else "—"
    s = str(value)
    if len(s) > 120:
        s = s[:117] + "…"
    return escape(s)


def _empty(message: str = "No records") -> str:
    return f'<div class="verity-empty">{escape(message)}</div>'


# ── Generic list / detail / cards primitives ─────────────────

ColumnSpec = Union[
    str,                          # field name (label = field name)
    tuple[str, str],              # (field, label)
    tuple[str, str, str],         # (field, label, badge_variant_field_or_literal)
]


def render_list(
    records: Iterable[dict],
    columns: list[ColumnSpec],
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    empty_message: str = "No records.",
) -> HTML:
    """Generic Verity-UI-styled table.

    `columns` entries:
      - "field_name"                              — plain text column
      - ("field_name", "Column Label")            — custom header label
      - ("field_name", "Label", "variant_or_*")   — render as a badge.
        If the third element is the literal "*", the value itself is
        used as the badge variant (e.g. "champion" → badge-champion).
        Otherwise, the third element is the name of *another* field
        in the row that holds the variant.
    """
    records = list(records or [])
    header_bits = []
    if title:
        header_bits.append(f'<h2>{escape(title)}</h2>')
    if description:
        header_bits.append(f'<p class="verity-desc">{escape(description)}</p>')

    if not records:
        body = _empty(empty_message)
        return HTML(f'<div class="verity-scope">{"".join(header_bits)}{body}</div>')

    # Normalize column spec.
    norm: list[tuple[str, str, Optional[str]]] = []
    for c in columns:
        if isinstance(c, str):
            norm.append((c, c.replace("_", " "), None))
        elif len(c) == 2:
            norm.append((c[0], c[1], None))
        else:
            norm.append((c[0], c[1], c[2]))

    thead = "".join(f'<th>{escape(lbl)}</th>' for _, lbl, _ in norm)
    rows_html: list[str] = []
    for r in records:
        cells: list[str] = []
        for field, _, badge_src in norm:
            raw = r.get(field)
            if badge_src is None:
                cells.append(f'<td>{_cell(raw)}</td>')
            else:
                variant = raw if badge_src == "*" else r.get(badge_src)
                cells.append(f'<td>{badge(raw, variant) if raw else ""}</td>')
        rows_html.append(f'<tr>{"".join(cells)}</tr>')

    body = (
        '<table class="verity-table">'
        f'<thead><tr>{thead}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        '</table>'
    )
    return HTML(f'<div class="verity-scope">{"".join(header_bits)}{body}</div>')


def render_detail(
    title: str,
    *,
    subtitle: Optional[str] = None,
    header_badges: Optional[list[tuple[str, Optional[str]]]] = None,
    sections: Optional[list[dict]] = None,
) -> HTML:
    """Generic Verity-UI-styled detail view.

    Each section is a dict:
        {"title": "Identity",                       # required
         "fields": [("label", value), ...],         # optional — key/value grid
         "table":  {"columns": [...], "rows": [...]},  # optional — embed a table
         "html":   "<p>...</p>"}                    # optional — raw HTML block

    Notebooks compose their own sections; this helper just handles
    layout and style. Use `badge()` inline in `fields` values or in
    the optional `header_badges` tuples.
    """
    parts: list[str] = ['<div class="verity-scope">']
    head_bits = [f'<span class="title">{escape(title)}</span>']
    if subtitle:
        head_bits.append(f'<span class="subtitle">{escape(subtitle)}</span>')
    for badge_text, variant in (header_badges or []):
        head_bits.append(badge(badge_text, variant))
    parts.append(f'<div class="verity-header">{"".join(head_bits)}</div>')

    for section in sections or []:
        parts.append('<div class="verity-section">')
        parts.append(f'<h3>{escape(section["title"])}</h3>')
        if "fields" in section and section["fields"]:
            inner = "".join(kv(lbl, val) for lbl, val in section["fields"])
            parts.append(f'<div class="verity-kv">{inner}</div>')
        if "table" in section and section["table"]:
            t = section["table"]
            t_html = render_list(
                t["rows"], t["columns"], empty_message=t.get("empty", "No rows."),
            )
            # Unwrap — the inner render_list already included .verity-scope.
            inner_data = t_html.data.replace('<div class="verity-scope">', "", 1)
            if inner_data.endswith("</div>"):
                inner_data = inner_data[:-6]
            parts.append(inner_data)
        if "html" in section and section["html"]:
            parts.append(section["html"])
        parts.append('</div>')

    parts.append('</div>')
    return HTML("".join(parts))


def render_cards(tiles: list[tuple[str, Any, Optional[str]]]) -> HTML:
    """Tile row for dashboards / summary panels. Each tile is a
    `(label, value, footer or None)` tuple.

    Use inside any notebook to show counts / totals as a compact
    row of Verity-blue cards. For a specific entity's "stat"
    grid (decisions + overrides + contexts + mappings for an
    application, say), just build the tile list from your data
    and hand it to this function.
    """
    tile_parts: list[str] = []
    for label, value, footer in tiles:
        footer_html = (
            f'<div class="card-footer">{escape(footer)}</div>' if footer else ""
        )
        tile_parts.append(
            '<div class="verity-card">'
            f'<div class="card-label">{escape(label)}</div>'
            f'<div class="card-value">{escape(str(value))}</div>'
            f'{footer_html}'
            '</div>'
        )
    inner = "".join(tile_parts)
    return HTML(f'<div class="verity-scope"><div class="verity-cards">{inner}</div></div>')
