"""Insurance Document Generator.

Fill ACORD PDF forms and text templates from JSON company profiles.
All templates (PDFs, text, field maps) are shipped inside the package.

Usage as library:
    from insurance_docgen import DocumentGenerator

    gen = DocumentGenerator()
    gen.generate_all("profiles/companies.json", "output/")
    gen.fill_pdf("DOandEPLI", profile_dict, "output/do_app.pdf")
    gen.render_text("loss_run", profile_dict, "output/loss_run.txt")

Usage as CLI:
    python -m insurance_docgen generate-all --profiles companies.json --output-dir output/
    python -m insurance_docgen fill-pdf --form DOandEPLI --profile companies.json --company acme_dynamics --output out.pdf
    python -m insurance_docgen render-text --template loss_run --profile companies.json --company acme_dynamics --output out.txt
    python -m insurance_docgen list-fields --pdf some_form.pdf
"""

from insurance_docgen.generator import DocumentGenerator

__all__ = ["DocumentGenerator"]
