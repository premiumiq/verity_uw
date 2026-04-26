"""High-level document generator - orchestrates PDF filling and text rendering.

Takes a company profile and produces all documents listed in its
documents_to_generate field. Handles the data transformation from
profile model to the flat dicts that pdf_filler and text_filler expect.

All templates (PDF forms, text templates, field maps) are shipped inside
the package under src/insurance_docgen/templates/. No external template
directory is needed.
"""

import json
from pathlib import Path

from insurance_docgen.models import CompanyProfile
from insurance_docgen.pdf_filler import fill_pdf, load_field_map, _PDF_TEMPLATES_DIR
from insurance_docgen.text_filler import render_text


# Map document type -> generation config.
#
# For PDF types:
#   pdf_template: filename in templates/pdf/ (must match a shipped PDF)
#   field_map:    filename stem in templates/field_maps/ (must match the PDF name)
#
# For text types:
#   template: filename stem in templates/text/ (e.g., "loss_run" -> loss_run.txt.j2)
#
# The naming convention is: PDF file, field map, and doc type config all
# share the same base name. To add a new form, add the PDF + field map +
# a config entry here. See README.md for full instructions.

_DOC_TYPE_CONFIG = {
    "do_application": {
        "method": "pdf",
        "pdf_template": "DOandEPLI.pdf",
        "field_map": "DOandEPLI",
        "output_prefix": "do_app",
    },
    "gl_application": {
        "method": "pdf",
        "pdf_template": "acord-125.pdf",
        "field_map": "acord-125",
        "output_prefix": "gl_app",
    },
    "loss_run": {
        "method": "text",
        "template": "loss_run",
        "output_prefix": "loss_run",
        "output_ext": ".txt",
    },
    "financial_statement": {
        "method": "text",
        "template": "financial_statement",
        "output_prefix": "financial_stmt",
        "output_ext": ".txt",
    },
    "board_resolution": {
        "method": "text",
        "template": "board_resolution",
        "output_prefix": "board_resolution",
        "output_ext": ".txt",
    },
    "supplemental_gl": {
        "method": "text",
        "template": "supplemental_gl",
        "output_prefix": "supplemental_gl",
        "output_ext": ".txt",
    },
}


class DocumentGenerator:
    """Generate insurance documents from company profiles.

    All templates are built into the package. You only provide:
    1. A companies.json file with company profiles
    2. An output directory

    Usage:
        gen = DocumentGenerator()

        # Generate all documents for all profiles
        gen.generate_all("profiles/companies.json", "output/filled/")

        # Or generate a single document
        gen.fill_pdf("DOandEPLI", profile_dict, "output/do_app_acme.pdf")
        gen.render_text("loss_run", profile_dict, "output/loss_run_acme.txt")
    """

    def fill_pdf(
        self,
        form_name: str,
        profile: dict,
        output_path: str | Path,
    ) -> Path:
        """Fill a built-in PDF form from a profile dict.

        Args:
            form_name: Name of the PDF form (e.g., "DOandEPLI" or "acord-125").
                       Must match a file in templates/pdf/{form_name}.pdf and
                       a field map in templates/field_maps/{form_name}.json.
            profile: Dict of values (typically from CompanyProfile).
            output_path: Where to save the filled PDF.
        """
        template_path = _PDF_TEMPLATES_DIR / f"{form_name}.pdf"
        if not template_path.exists():
            raise FileNotFoundError(
                f"PDF template '{form_name}.pdf' not found in {_PDF_TEMPLATES_DIR}. "
                f"Available: {[f.stem for f in _PDF_TEMPLATES_DIR.glob('*.pdf')]}"
            )
        field_map = load_field_map(form_name)
        field_map = {k: v for k, v in field_map.items() if not k.startswith("_")}
        return fill_pdf(template_path, field_map, profile, output_path)

    def render_text(
        self,
        template_name: str,
        profile: dict,
        output_path: str | Path,
    ) -> Path:
        """Render a built-in text template from a profile dict."""
        return render_text(template_name, profile, output_path)

    def generate_all(
        self,
        profiles_path: str | Path,
        output_dir: str | Path,
    ) -> list[Path]:
        """Generate all documents for all company profiles.

        Args:
            profiles_path: Path to companies.json (list of profile dicts).
            output_dir: Where to save generated documents.

        Returns:
            List of paths to generated files.
        """
        profiles_path = Path(profiles_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        raw_profiles = json.loads(profiles_path.read_text())
        profiles = [CompanyProfile(**p) for p in raw_profiles]

        generated = []

        for profile in profiles:
            print(f"Generating documents for: {profile.named_insured} ({profile.company_id})")

            for doc_type in profile.documents_to_generate:
                config = _DOC_TYPE_CONFIG.get(doc_type)
                if not config:
                    print(f"  WARNING: Unknown document type '{doc_type}', skipping")
                    continue

                data = _profile_to_data(profile, doc_type)

                if config["method"] == "pdf":
                    output_path = output_dir / f"{config['output_prefix']}_{profile.company_id}.pdf"
                    form_name = config["pdf_template"].replace(".pdf", "")
                    self.fill_pdf(form_name, data, output_path)

                elif config["method"] == "text":
                    ext = config.get("output_ext", ".txt")
                    output_path = output_dir / f"{config['output_prefix']}_{profile.company_id}{ext}"
                    self.render_text(config["template"], data, output_path)

                generated.append(output_path)
                print(f"  + {output_path.name}")

        print(f"\nGenerated {len(generated)} documents in {output_dir}/")
        return generated


def _profile_to_data(profile: CompanyProfile, doc_type: str) -> dict:
    """Transform a CompanyProfile into a flat dict for template rendering.

    Different document types need different data shapes. This function
    handles the transformation so templates and field maps stay simple.
    """
    # Start with all profile fields as a base
    data = profile.model_dump()

    # Add computed fields
    data["company_id"] = profile.company_id
    data["lob_display"] = "Directors & Officers" if profile.lob == "DO" else "General Liability"

    # Revenue display: use override if set, otherwise format the number
    if profile.annual_revenue_display:
        data["annual_revenue_display"] = profile.annual_revenue_display
    elif profile.annual_revenue > 0:
        data["annual_revenue_display"] = f"${profile.annual_revenue:,.0f}"
    else:
        data["annual_revenue_display"] = ""  # Intentionally blank

    # Employee display
    data["total_employees_display"] = str(profile.total_employees) if profile.total_employees else ""

    # D&O limit display
    data["do_limit_display"] = f"${profile.limits_requested:,.0f}" if profile.limits_requested else ""
    data["do_coverage_requested"] = True  # Always requesting D&O if doc_type is do_application

    # Total assets display
    if profile.total_assets:
        data["total_assets_display"] = f"${profile.total_assets:,.0f}"
    else:
        data["total_assets_display"] = ""

    # Financial comparison (for D&O form page 2)
    if profile.financial_data:
        fd = profile.financial_data
        data["current_year_revenue"] = f"${fd.current_revenue:,.0f}"
        data["previous_year_revenue"] = f"${fd.prior_revenue:,.0f}"
        data["current_year_income"] = f"${fd.current_net_income:,.0f}"
        data["previous_year_income"] = f"${fd.prior_net_income:,.0f}"
        data["current_year_assets"] = f"${fd.current_total_assets:,.0f}"
        data["previous_year_assets"] = f"${fd.prior_total_assets:,.0f}"

    # Checkbox fields for D&O risk questions
    data["securities_offering"] = profile.ipo_planned or profile.securities_class_action
    data["antitrust_litigation"] = False  # Default
    data["securities_violation"] = profile.securities_class_action
    data["other_criminal"] = False  # Default
    data["prior_claims"] = any(yr.claims > 0 for yr in profile.loss_history)
    data["reorganization"] = profile.bankruptcy_history
    data["consolidations_layoffs"] = False  # Default
    data["notice_of_claim"] = any(yr.claims > 0 for yr in profile.loss_history)

    # Director names for the D&O form shareholder section
    if profile.board_members:
        for i, member in enumerate(profile.board_members[:2]):
            data[f"director_{i+1}_name"] = member.name
            data[f"director_{i+1}_shares"] = member.shares_owned or ""

    # Contact info
    data["contact_name"] = profile.board_members[0].name if profile.board_members else ""
    data["contact_title"] = profile.board_members[0].title if profile.board_members else ""
    data["contact_email"] = ""  # Not in profile

    # ACORD 125 specific
    data["mailing_address"] = f"{profile.address}, {profile.city}, {profile.state} {profile.zip}"
    data["application_date"] = "03/01/2026"
    data["agency"] = "Verity Insurance Services"
    data["proposed_eff_date"] = profile.effective_date
    data["proposed_exp_date"] = profile.expiration_date
    data["date_business_started"] = profile.date_established
    data["location_1"] = f"{profile.address}, {profile.city}, {profile.state} {profile.zip}"

    # Loss run computed totals
    data["total_claims"] = sum(yr.claims for yr in profile.loss_history)
    data["total_incurred"] = sum(yr.incurred for yr in profile.loss_history)
    data["total_paid"] = sum(yr.paid for yr in profile.loss_history)
    data["total_reserves"] = sum(yr.reserves for yr in profile.loss_history)

    # Policy number (synthetic)
    lob_prefix = "DO" if profile.lob == "DO" else "GL"
    data["policy_number"] = f"PLY-{lob_prefix}-{profile.company_id[:8].upper()}-2026"

    return data
