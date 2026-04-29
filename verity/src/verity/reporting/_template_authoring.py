"""One-shot script to produce a starter .docx template for a report.

Usage (from the project root, via venv):
    python -m verity.reporting._template_authoring model_inventory

This generates a .docx file at:
    verity/src/verity/reporting/templates/<report_code>.docx

The output is a *starter* — a styled Word document with the correct
docxtpl placeholders ({{...}}, {%tr ... %}). Designers/compliance teams
open this in Word and restyle freely (logo, colors, watermark) without
touching placeholders.

Why a script: the .docx files in the repo are binary blobs. Generating
them from code keeps the placeholder list documented and makes
starter-content changes reviewable in PRs.
"""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document  # type: ignore
from docx.enum.table import WD_ALIGN_VERTICAL, WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Pt, RGBColor, Inches, Cm


TEMPLATES_DIR = Path(__file__).parent / "templates"


# =============================================================================
# Styling constants — change these in one place and rerun the script.
# =============================================================================

HEADING_FONT       = "Georgia"
BODY_FONT          = "Poppins"
BRAND_BLUE         = RGBColor(0x1A, 0x36, 0x5D)
BRAND_BLUE_LIGHT   = RGBColor(0x6E, 0x8F, 0xCC)
BODY_GRAY          = RGBColor(0x33, 0x33, 0x33)
MUTED_GRAY         = RGBColor(0x6B, 0x6B, 0x6B)
CARD_SHADE_HEX     = "F4F6FA"   # subtle cool gray for card cell background


# =============================================================================
# Low-level helpers
# =============================================================================

def _set_run_font(run, *, name=BODY_FONT, size=11, bold=False, italic=False, color=BODY_GRAY):
    run.font.name = name
    # `w:eastAsia` font also needs to be set for some renderers.
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"),    name)
    rFonts.set(qn("w:hAnsi"),    name)
    rFonts.set(qn("w:cs"),       name)
    rFonts.set(qn("w:eastAsia"), name)
    run.font.size  = Pt(size)
    run.font.bold  = bold
    run.font.italic = italic
    run.font.color.rgb = color


def _add_styled_para(doc, text="", *, font=BODY_FONT, size=11, bold=False,
                     italic=False, color=BODY_GRAY, align=WD_ALIGN_PARAGRAPH.LEFT,
                     space_before=0, space_after=4):
    """Add a paragraph with a single styled run."""
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after  = Pt(space_after)
    if text:
        run = p.add_run(text)
        _set_run_font(run, name=font, size=size, bold=bold, italic=italic, color=color)
    return p


def _add_heading(doc, text, *, level=1, page_break_before=False):
    """Add a heading paragraph using Georgia + brand blue.

    level=1 → 22pt, level=2 → 16pt, level=3 → 13pt.
    """
    sizes = {1: 22, 2: 16, 3: 13}
    p = doc.add_paragraph()
    if page_break_before:
        p.paragraph_format.page_break_before = True
    p.paragraph_format.space_before = Pt(6 if level > 1 else 0)
    p.paragraph_format.space_after  = Pt(6)
    run = p.add_run(text)
    _set_run_font(run, name=HEADING_FONT, size=sizes[level], bold=True, color=BRAND_BLUE)
    return p


def _add_page_break(doc):
    """Insert a hard page break."""
    p = doc.add_paragraph()
    p.add_run().add_break(WD_BREAK.PAGE)


def _shade_cell(cell, hex_color):
    """Apply background shading to a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_color)
    tcPr.append(shd)


def _set_cell_borders(cell, *, color="C5CDDC", size_eighths=6):
    """Apply 1pt borders to all four sides of a cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        b = OxmlElement(f"w:{edge}")
        b.set(qn("w:val"),   "single")
        b.set(qn("w:sz"),    str(size_eighths))
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), color)
        tcBorders.append(b)
    tcPr.append(tcBorders)


def _enable_different_first_page_header_footer(section):
    """Tell Word: page 1 of this section gets its own (empty) header/footer."""
    sectPr = section._sectPr
    titlePg = sectPr.find(qn("w:titlePg"))
    if titlePg is None:
        titlePg = OxmlElement("w:titlePg")
        sectPr.append(titlePg)


# =============================================================================
# Card builders — each asset type's section uses a single-column table where
# every body row is a "card" repeated by docxtpl via {%tr%}.
# =============================================================================

def _add_asset_card_table(doc, *, item_var: str, list_var: str):
    """Add a single-column table that docxtpl will repeat once per asset.

    Each card cell contains:
      - Title line: {{ display_name }}  v{{ version_label }}  ·  {{ status }}
      - Description (italic, smaller, gray)
      - Facts line: Materiality · Owner · Application(s)
    """
    # Three rows: {%tr open%} · body · {%tr close%}.
    table = doc.add_table(rows=3, cols=1)
    table.autofit = False
    table.columns[0].width = Inches(6.5)

    # tr-open marker row
    tr_open = table.rows[0].cells[0]
    tr_open.text = ""
    p = tr_open.paragraphs[0]
    p.add_run("{%tr for a in " + list_var + " %}")

    # body row — the actual card
    body = table.rows[1].cells[0]
    body.width = Inches(6.5)
    _shade_cell(body, CARD_SHADE_HEX)
    _set_cell_borders(body, color="C5CDDC")
    body.vertical_alignment = WD_ALIGN_VERTICAL.TOP
    # Clear the default empty paragraph
    body._tc.remove(body.paragraphs[0]._p)

    # Card paragraph 1 — title line
    p = body.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after  = Pt(2)
    run = p.add_run("{{ a.display_name }}")
    _set_run_font(run, name=BODY_FONT, size=13, bold=True, color=BRAND_BLUE)
    run = p.add_run("    v{{ a.version_label }}    ·    ")
    _set_run_font(run, name=BODY_FONT, size=11, color=MUTED_GRAY)
    run = p.add_run("{{ a.lifecycle_state_display }}")
    _set_run_font(run, name=BODY_FONT, size=11, bold=True, color=BRAND_BLUE_LIGHT)

    # Card paragraph 2 — description (italic, gray)
    p = body.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after  = Pt(4)
    run = p.add_run("{{ a.entity_description or '—' }}")
    _set_run_font(run, name=BODY_FONT, size=10, italic=True, color=MUTED_GRAY)

    # Card paragraph 3 — facts (Materiality · Owner · Apps)
    p = body.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after  = Pt(8)
    facts = [
        ("Materiality: ",  "{{ a.materiality_display }}"),
        ("    ·    Owner: ",         "{{ a.owner_name or '—' }}"),
        ("    ·    Application(s): ", "{{ a.applications }}"),
    ]
    for label, value in facts:
        run = p.add_run(label)
        _set_run_font(run, name=BODY_FONT, size=10, color=MUTED_GRAY)
        run = p.add_run(value)
        _set_run_font(run, name=BODY_FONT, size=10, bold=True, color=BODY_GRAY)

    # tr-close marker row
    tr_close = table.rows[2].cells[0]
    tr_close.text = ""
    p = tr_close.paragraphs[0]
    p.add_run("{%tr endfor %}")
    return table


def _add_lifecycle_table(doc, list_var: str):
    """Add a 5-column lifecycle-events table for one asset type."""
    table = doc.add_table(rows=4, cols=5)
    table.style = "Light Grid Accent 1"

    headers = ["Asset", "Transition", "Gate", "Approver", "Approved At"]
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        run = p.add_run(h)
        _set_run_font(run, name=BODY_FONT, size=10, bold=True, color=BRAND_BLUE)

    # tr-open
    tr_open = table.rows[1].cells[0]
    tr_open.text = "{%tr for ev in " + list_var + " %}"
    table.rows[1].cells[0].merge(table.rows[1].cells[4])

    # body
    body = table.rows[2].cells
    cells_text = [
        "{{ ev.asset_display_name }}  v{{ ev.version_label }}",
        "{{ ev.from_state_display }} → {{ ev.to_state_display }}",
        "{{ ev.gate_type }}",
        "{{ ev.approver_name }}",
        "{{ ev.approved_at.strftime('%Y-%m-%d %H:%M') if ev.approved_at else '—' }}",
    ]
    for i, txt in enumerate(cells_text):
        body[i].text = ""
        p = body[i].paragraphs[0]
        run = p.add_run(txt)
        _set_run_font(run, name=BODY_FONT, size=10, color=BODY_GRAY)

    # tr-close
    tr_close = table.rows[3].cells[0]
    tr_close.text = "{%tr endfor %}"
    table.rows[3].cells[0].merge(table.rows[3].cells[4])
    return table


# =============================================================================
# Model Inventory starter template
# =============================================================================

def author_model_inventory() -> Path:
    doc = Document()

    # Establish Normal style font (Poppins) globally.
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(11)
    rPr = normal.element.get_or_add_rPr()
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), BODY_FONT)
    rFonts.set(qn("w:hAnsi"), BODY_FONT)
    rFonts.set(qn("w:cs"),    BODY_FONT)
    rFonts.set(qn("w:eastAsia"), BODY_FONT)
    # remove any existing rFonts before appending
    existing = rPr.find(qn("w:rFonts"))
    if existing is not None:
        rPr.remove(existing)
    rPr.append(rFonts)

    # ── Page setup ─────────────────────────────────────────────
    section = doc.sections[0]
    section.top_margin    = Inches(0.85)
    section.bottom_margin = Inches(0.85)
    section.left_margin   = Inches(0.9)
    section.right_margin  = Inches(0.9)
    _enable_different_first_page_header_footer(section)

    # The first-page header/footer are explicitly empty (no chrome on cover).
    fp_header = section.first_page_header
    fp_header.is_linked_to_previous = False
    fp_header.paragraphs[0].text = ""
    fp_footer = section.first_page_footer
    fp_footer.is_linked_to_previous = False
    fp_footer.paragraphs[0].text = ""

    # Default header (page 2+)
    header_p = section.header.paragraphs[0]
    header_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = header_p.add_run("VERITY · {{ report_title }}")
    _set_run_font(run, name=HEADING_FONT, size=9, bold=True, color=BRAND_BLUE)

    # Default footer (page 2+)
    footer_p = section.footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = footer_p.add_run("{{ report_title }}  ·  Generated {{ generated_at_str }}  ·  Scope: {{ scope_summary }}")
    _set_run_font(run, name=BODY_FONT, size=8, color=MUTED_GRAY)

    # ════════════════════════════════════════════════════════════
    # PAGE 1 — COVER
    # ════════════════════════════════════════════════════════════
    # Vertical spacing to push title to roughly center of page.
    for _ in range(8):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("VERITY")
    _set_run_font(run, name=HEADING_FONT, size=14, bold=True, color=BRAND_BLUE_LIGHT)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run("Compliance Report")
    _set_run_font(run, name=HEADING_FONT, size=11, color=MUTED_GRAY)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(28)
    p.paragraph_format.space_after = Pt(8)
    run = p.add_run("{{ report_title }}")
    _set_run_font(run, name=HEADING_FONT, size=36, bold=True, color=BRAND_BLUE)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(20)
    run = p.add_run("Generated {{ generated_at_str }}")
    _set_run_font(run, name=BODY_FONT, size=12, color=BODY_GRAY)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    run = p.add_run("Scope: {{ scope_summary }}")
    _set_run_font(run, name=BODY_FONT, size=11, italic=True, color=MUTED_GRAY)

    _add_page_break(doc)

    # ════════════════════════════════════════════════════════════
    # PAGE 2 — PURPOSE & AUDIENCE
    # ════════════════════════════════════════════════════════════
    _add_heading(doc, "Purpose and Audience", level=1)

    _add_styled_para(
        doc,
        "Purpose",
        font=HEADING_FONT, size=13, bold=True, color=BRAND_BLUE,
        space_before=10, space_after=4,
    )
    _add_styled_para(
        doc,
        "{{ report_description }}",
        font=BODY_FONT, size=11, color=BODY_GRAY, space_after=10,
    )
    _add_styled_para(
        doc,
        "This report enumerates {{ total_count }} AI asset version(s) registered to "
        "Verity at the time of generation: {{ agent_count }} agent(s), "
        "{{ task_count }} task(s), and {{ prompt_count }} prompt(s). "
        "The breakdown by materiality is {{ high_count }} high, {{ medium_count }} medium, "
        "and {{ low_count }} low.",
        font=BODY_FONT, size=11, color=BODY_GRAY, space_after=14,
    )

    _add_styled_para(
        doc,
        "Intended audience",
        font=HEADING_FONT, size=13, bold=True, color=BRAND_BLUE,
        space_before=10, space_after=4,
    )
    _add_styled_para(
        doc,
        "Model Risk Management committees, compliance officers, internal audit teams, "
        "and external regulatory examiners. The report is organized to be read top-to-"
        "bottom: cover → this purpose page → executive summary → AI asset inventory "
        "(grouped by asset type, with one card per registered asset) → recent lifecycle "
        "changes → regulatory coverage table mapping the report sections back to the "
        "canonical regulatory requirements they evidence.",
        font=BODY_FONT, size=11, color=BODY_GRAY, space_after=10,
    )

    _add_styled_para(
        doc,
        "Data lineage",
        font=HEADING_FONT, size=13, bold=True, color=BRAND_BLUE,
        space_before=10, space_after=4,
    )
    _add_styled_para(
        doc,
        "All figures in this report are queried at generation time from the Verity "
        "compliance metamodel — frameworks, provisions, canonical requirements, "
        "Verity features, and the bidirectional bridges that connect them. No data "
        "is imported from external systems; nothing is computed offline. Every value "
        "is traceable back to a source row in the metamodel.",
        font=BODY_FONT, size=11, color=BODY_GRAY,
    )

    _add_page_break(doc)

    # ════════════════════════════════════════════════════════════
    # PAGE 3 — EXECUTIVE SUMMARY
    # ════════════════════════════════════════════════════════════
    _add_heading(doc, "Executive Summary", level=1)

    _add_styled_para(
        doc,
        "At the time of generation, Verity governs {{ total_count }} AI asset version(s) "
        "across {{ by_entity_type|length }} asset type(s). The asset inventory is "
        "broken down as follows:",
        space_after=8,
    )
    _add_styled_para(
        doc,
        "• Agents: {{ agent_count }}     • Tasks: {{ task_count }}     "
        "• Prompts: {{ prompt_count }}",
        font=BODY_FONT, size=11, bold=True, color=BRAND_BLUE, space_after=8,
    )
    _add_styled_para(
        doc,
        "By materiality tier: {{ high_count }} high, {{ medium_count }} medium, "
        "{{ low_count }} low. {{ lifecycle_events_total }} lifecycle state "
        "transitions are recorded in the recent-changes section of this report.",
    )

    _add_page_break(doc)

    # ════════════════════════════════════════════════════════════
    # PAGE 4 — AI ASSET INVENTORY
    # ════════════════════════════════════════════════════════════
    _add_heading(doc, "AI Asset Inventory", level=1)

    _add_styled_para(
        doc,
        "Every AI asset registered to Verity is listed below, grouped by asset type. "
        "Each card shows the asset's display name, current version label, lifecycle "
        "state, plain-language description, materiality tier, named owner, and the "
        "applications it serves.",
        space_after=14,
    )

    # ── Agents subsection ──────────────────────────────────────
    _add_heading(doc, "Agents ({{ agent_count }})", level=2)
    _add_asset_card_table(doc, item_var="a", list_var="agents")

    # ── Tasks subsection ───────────────────────────────────────
    _add_heading(doc, "Tasks ({{ task_count }})", level=2, page_break_before=False)
    _add_styled_para(doc, "", space_before=8)
    _add_asset_card_table(doc, item_var="a", list_var="tasks")

    # ── Prompts subsection ─────────────────────────────────────
    _add_heading(doc, "Prompts ({{ prompt_count }})", level=2, page_break_before=False)
    _add_styled_para(doc, "", space_before=8)
    _add_asset_card_table(doc, item_var="a", list_var="prompts")

    _add_page_break(doc)

    # ════════════════════════════════════════════════════════════
    # PAGE 5 — RECENT LIFECYCLE CHANGES
    # ════════════════════════════════════════════════════════════
    _add_heading(doc, "Recent Lifecycle Changes", level=1)

    _add_styled_para(
        doc,
        "Up to the 50 most recent state transitions across all assets, sub-grouped "
        "by asset type. Each row reflects a HITL approval gate.",
        space_after=10,
    )

    _add_heading(doc, "Agents", level=2)
    _add_lifecycle_table(doc, "lifecycle_agents")

    _add_styled_para(doc, "", space_before=10)
    _add_heading(doc, "Tasks", level=2)
    _add_lifecycle_table(doc, "lifecycle_tasks")

    _add_styled_para(doc, "", space_before=10)
    _add_heading(doc, "Prompts", level=2)
    _add_lifecycle_table(doc, "lifecycle_prompts")

    _add_page_break(doc)

    # ════════════════════════════════════════════════════════════
    # PAGE 6 — REGULATORY COVERAGE
    # ════════════════════════════════════════════════════════════
    _add_heading(doc, "Regulatory Coverage", level=1)

    _add_styled_para(
        doc,
        "This report provides evidence for the following canonical regulatory "
        "requirements within the Verity compliance metamodel.",
        space_after=10,
    )

    can_table = doc.add_table(rows=4, cols=4)
    can_table.style = "Light Grid Accent 1"
    headers = ["Theme", "Canonical Requirement", "Coverage", "Section"]
    for i, h in enumerate(headers):
        cell = can_table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        _set_run_font(run, name=BODY_FONT, size=10, bold=True, color=BRAND_BLUE)

    can_table.rows[1].cells[0].text = "{%tr for c in canonicals %}"
    can_table.rows[1].cells[0].merge(can_table.rows[1].cells[3])

    body = can_table.rows[2].cells
    cells_text = [
        "{{ c.theme_name }}",
        "{{ c.title }}",
        "{{ c.coverage_level or '—' }}",
        "{{ c.section or '—' }}",
    ]
    for i, txt in enumerate(cells_text):
        body[i].text = ""
        run = body[i].paragraphs[0].add_run(txt)
        _set_run_font(run, name=BODY_FONT, size=10, color=BODY_GRAY)

    can_table.rows[3].cells[0].text = "{%tr endfor %}"
    can_table.rows[3].cells[0].merge(can_table.rows[3].cells[3])

    # ── Save ───────────────────────────────────────────────────
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    out = TEMPLATES_DIR / "model_inventory.docx"
    doc.save(out)
    return out


# =============================================================================
# Dispatcher
# =============================================================================

AUTHORS = {
    "model_inventory": author_model_inventory,
}


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: python -m verity.reporting._template_authoring <report_code>")
        print(f"Available: {list(AUTHORS)}")
        sys.exit(1)
    code = sys.argv[1]
    if code not in AUTHORS:
        print(f"Unknown report {code!r}. Available: {list(AUTHORS)}")
        sys.exit(1)
    out = AUTHORS[code]()
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
