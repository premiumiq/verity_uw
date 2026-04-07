"""CLI entry point for insurance_docgen.

Usage:
    python -m insurance_docgen fill-pdf --form DOandEPLI --profile companies.json --company acme_dynamics --output out.pdf
    python -m insurance_docgen render-text --template loss_run --profile companies.json --company acme_dynamics --output out.txt
    python -m insurance_docgen generate-all --profiles companies.json --output-dir output/
    python -m insurance_docgen list-fields --pdf some_form.pdf
"""

import argparse
import json
import sys
from pathlib import Path

from insurance_docgen.generator import DocumentGenerator
from insurance_docgen.models import CompanyProfile
from insurance_docgen.pdf_filler import list_pdf_fields


def main():
    parser = argparse.ArgumentParser(
        prog="insurance-docgen",
        description="Insurance document generator - fill ACORD forms and text templates from JSON profiles",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # -- fill-pdf: fill a single built-in PDF form for one company --
    fill_parser = subparsers.add_parser(
        "fill-pdf",
        help="Fill a single PDF form from a company profile",
    )
    fill_parser.add_argument(
        "--form", required=True,
        help="Built-in form name (e.g., 'DOandEPLI' or 'acord-125'). "
             "Must match a PDF and field map in the package.",
    )
    fill_parser.add_argument("--profile", required=True, help="Path to companies.json")
    fill_parser.add_argument("--company", required=True, help="Company ID from profiles")
    fill_parser.add_argument("--output", required=True, help="Output PDF path")

    # -- render-text: render a single text template for one company --
    text_parser = subparsers.add_parser(
        "render-text",
        help="Render a text template from a company profile",
    )
    text_parser.add_argument(
        "--template", required=True,
        help="Built-in template name (e.g., 'loss_run', 'financial_statement')",
    )
    text_parser.add_argument("--profile", required=True, help="Path to companies.json")
    text_parser.add_argument("--company", required=True, help="Company ID from profiles")
    text_parser.add_argument("--output", required=True, help="Output text file path")

    # -- generate-all: batch generate for all companies --
    all_parser = subparsers.add_parser(
        "generate-all",
        help="Generate all documents for all profiles in one batch",
    )
    all_parser.add_argument("--profiles", required=True, help="Path to companies.json")
    all_parser.add_argument("--output-dir", required=True, help="Output directory")

    # -- list-fields: utility to inspect a PDF's form fields --
    list_parser = subparsers.add_parser(
        "list-fields",
        help="List all form fields in a PDF (utility for building field maps)",
    )
    list_parser.add_argument("--pdf", required=True, help="Path to any PDF file")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.command == "fill-pdf":
        _cmd_fill_pdf(args)
    elif args.command == "render-text":
        _cmd_render_text(args)
    elif args.command == "generate-all":
        _cmd_generate_all(args)
    elif args.command == "list-fields":
        _cmd_list_fields(args)
    else:
        parser.print_help()
        sys.exit(1)


def _load_company(profiles_path: str, company_id: str) -> CompanyProfile:
    """Load and validate a single company profile from the profiles JSON file."""
    profiles = json.loads(Path(profiles_path).read_text())
    for p in profiles:
        if p["company_id"] == company_id:
            return CompanyProfile(**p)
    print(f"ERROR: Company '{company_id}' not found in {profiles_path}")
    print(f"Available: {[p['company_id'] for p in profiles]}")
    sys.exit(1)


def _cmd_fill_pdf(args):
    from insurance_docgen.generator import _profile_to_data
    profile = _load_company(args.profile, args.company)
    data = _profile_to_data(profile, "do_application")
    gen = DocumentGenerator()
    result = gen.fill_pdf(args.form, data, args.output)
    print(f"Filled PDF saved to: {result}")


def _cmd_render_text(args):
    from insurance_docgen.generator import _profile_to_data
    profile = _load_company(args.profile, args.company)
    data = _profile_to_data(profile, args.template)
    gen = DocumentGenerator()
    result = gen.render_text(args.template, data, args.output)
    print(f"Rendered text saved to: {result}")


def _cmd_generate_all(args):
    gen = DocumentGenerator()
    generated = gen.generate_all(args.profiles, args.output_dir)
    print(f"\nDone. {len(generated)} files generated.")


def _cmd_list_fields(args):
    fields = list_pdf_fields(args.pdf)
    if args.json:
        print(json.dumps(fields, indent=2))
    else:
        for f in fields:
            print(f"p{f['page']} [{f['type']:12}] {f['name']}")
        print(f"\nTotal: {len(fields)} fields")


if __name__ == "__main__":
    main()
