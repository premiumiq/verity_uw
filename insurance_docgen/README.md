# Insurance Document Generator

A Python package that generates filled insurance documents from JSON company profiles. Takes blank ACORD PDF forms and text templates, fills them with company data, and produces realistic insurance application packages.

Built as a reusable tool for PremiumIQ Verity - generates test data, ground truth datasets, and demo submissions.

## How It Works

The tool combines two inputs to produce filled documents:

```
BLANK TEMPLATE  +  COMPANY PROFILE (JSON)  =  FILLED DOCUMENT
```

There are two types of templates, both shipped inside the package:

**PDF templates** are blank fillable ACORD forms (e.g., DOandEPLI.pdf for D&O applications, acord-125.pdf for GL applications). The tool opens the blank PDF, finds form fields by name, writes values from the company profile into each field, and saves a new filled PDF. A **field map** (JSON file) tells the tool which company profile key maps to which PDF form field name.

**Text templates** are Jinja2 files for documents that don't have standard forms - loss run reports, financial statements, board resolutions, GL supplemental questionnaires. The tool renders the template with company data and saves a `.txt` file.

Each company profile lists which documents to generate in its `documents_to_generate` array. The `generate-all` command loops through every company and produces the right documents.

## Package Structure

```
insurance_docgen/
    pyproject.toml
    profiles/
        companies.json              # 20 company profiles (the data input)
    src/
        insurance_docgen/
            __init__.py
            cli.py                  # Command-line interface
            generator.py            # High-level orchestrator
            models.py               # Pydantic models for company profiles
            pdf_filler.py           # PDF form field filling (PyMuPDF)
            text_filler.py          # Jinja2 text template rendering
            templates/
                pdf/                # Blank fillable PDF forms
                    DOandEPLI.pdf       # D&O + EPLI application (157 fields)
                    acord-125.pdf       # GL commercial insurance application (365 fields)
                    acord-126.pdf       # GL details section (reference, not filled)
                    acord-101.pdf       # Additional remarks overflow (reference)
                field_maps/         # JSON mappings: profile key -> PDF field name
                    DOandEPLI.json      # Field map for DOandEPLI.pdf
                    acord-125.json      # Field map for acord-125.pdf
                text/               # Jinja2 text templates
                    loss_run.txt.j2
                    financial_statement.txt.j2
                    board_resolution.txt.j2
                    supplemental_gl.txt.j2
```

**Naming convention:** For PDF forms, the PDF file, field map, and document type config all share the same base name. `DOandEPLI.pdf` has field map `DOandEPLI.json`. `acord-125.pdf` has field map `acord-125.json`.

## Installation

```bash
# From the project root
.venv/bin/pip install -e insurance_docgen/
```

## CLI Usage

### Generate all documents for all companies (most common)

```bash
.venv/bin/python -m insurance_docgen generate-all \
    --profiles insurance_docgen/profiles/companies.json \
    --output-dir uw_demo/seed_docs/filled/
```

This reads every company from `companies.json`, and for each one, generates the documents listed in its `documents_to_generate` field. Output files are named `{type}_{company_id}.{ext}`.

### Fill a single PDF form for one company

```bash
.venv/bin/python -m insurance_docgen fill-pdf \
    --form DOandEPLI \
    --profile insurance_docgen/profiles/companies.json \
    --company acme_dynamics \
    --output output/do_app_acme.pdf
```

The `--form` argument is the base name of a built-in PDF template (without `.pdf`). It automatically finds the matching PDF and field map inside the package.

### Render a single text document for one company

```bash
.venv/bin/python -m insurance_docgen render-text \
    --template loss_run \
    --profile insurance_docgen/profiles/companies.json \
    --company acme_dynamics \
    --output output/loss_run_acme.txt
```

### List form fields in any PDF (utility)

```bash
# Human-readable format
.venv/bin/python -m insurance_docgen list-fields --pdf docs/acord/DOandEPLI.pdf

# JSON format (useful for building field maps)
.venv/bin/python -m insurance_docgen list-fields --pdf docs/acord/DOandEPLI.pdf --json
```

Use this to inspect a new PDF form's field names before creating a field map.

## Python API

```python
from insurance_docgen import DocumentGenerator

gen = DocumentGenerator()

# Batch: generate all documents for all profiles
gen.generate_all("insurance_docgen/profiles/companies.json", "output/")

# Single PDF form
gen.fill_pdf("DOandEPLI", profile_dict, "output/do_app_acme.pdf")

# Single text document
gen.render_text("loss_run", profile_dict, "output/loss_run_acme.txt")
```

## Company Profiles (companies.json)

The profiles file is a JSON array of company objects. Each company has:

- **Identity:** `company_id`, `named_insured`, `fein`, `entity_type`, `state_of_incorporation`, address fields
- **Business:** `sic_code`, `years_in_business`, `annual_revenue`, `total_employees`, `nature_of_business`
- **Line of business:** `lob` ("DO" or "GL")
- **D&O-specific:** `board_size`, `independent_directors`, `board_members` array, `total_assets`
- **GL-specific:** `manufacturing_operations`, `products_liability_exposure`, `hazmat_handling`
- **Coverage:** `effective_date`, `limits_requested`, `retention_requested`, `prior_carrier`
- **Risk factors:** `regulatory_investigation`, `going_concern`, `securities_class_action`, etc.
- **Loss history:** `loss_history` array (year, claims, incurred, paid, reserves) + `claim_details`
- **Financial data:** `financial_data` object (two-year comparison, auditor opinion)
- **Documents:** `documents_to_generate` - which documents to produce for this company
- **Ground truth:** `ground_truth` - expected classifier label, risk score, appetite, extracted fields
- **Data quality notes:** `data_quality_notes` - intentional imperfections for testing

See `insurance_docgen/profiles/companies.json` for 20 complete examples.

### Supported document types (for `documents_to_generate`)

| Value | Output | Template Used |
|---|---|---|
| `do_application` | Filled D&O application PDF | `DOandEPLI.pdf` + `DOandEPLI.json` |
| `gl_application` | Filled GL application PDF | `acord-125.pdf` + `acord-125.json` |
| `loss_run` | Loss run report text file | `loss_run.txt.j2` |
| `financial_statement` | Financial statement text file | `financial_statement.txt.j2` |
| `board_resolution` | Board resolution text file | `board_resolution.txt.j2` |
| `supplemental_gl` | GL supplemental questionnaire text file | `supplemental_gl.txt.j2` |

## Adding a New PDF Form Template

To add support for a new fillable PDF form (e.g., a Workers' Comp application):

### Step 1: Inspect the PDF's form fields

```bash
.venv/bin/python -m insurance_docgen list-fields --pdf path/to/workers_comp.pdf --json > fields.json
```

This outputs every form field with its name, type, and page number.

### Step 2: Add the blank PDF to the package

Copy the blank PDF into the templates directory:

```
insurance_docgen/src/insurance_docgen/templates/pdf/workers-comp.pdf
```

### Step 3: Create a field map

Create a JSON file with the **same base name** as the PDF:

```
insurance_docgen/src/insurance_docgen/templates/field_maps/workers-comp.json
```

The field map maps your company profile keys to the PDF's form field names:

```json
{
    "_comment": "Field map: CompanyProfile keys -> workers-comp.pdf form field names",

    "named_insured": {
        "pdf_field": "Applicant Name",
        "type": "text"
    },
    "fein": {
        "pdf_field": "FEIN Number",
        "type": "text"
    },
    "total_employees": {
        "pdf_field": "Number of Employees",
        "type": "text"
    },
    "workers_comp_requested": {
        "pdf_field_yes": "Coverage Requested Yes",
        "type": "checkbox_pair"
    }
}
```

**Field types:**
- `text` - Fill a text field. Uses `pdf_field` for the PDF field name.
- `checkbox` - Check a single checkbox. Uses `pdf_field`.
- `checkbox_pair` - A Yes/No checkbox pair. Uses `pdf_field_yes` (checked when value is truthy) and optionally `pdf_field_no`.

Keys starting with `_` (like `_comment`) are ignored during filling.

### Step 4: Register the document type in generator.py

Add an entry to `_DOC_TYPE_CONFIG`:

```python
"wc_application": {
    "method": "pdf",
    "pdf_template": "workers-comp.pdf",
    "field_map": "workers-comp",
    "output_prefix": "wc_app",
},
```

### Step 5: Add the type to company profiles

In `companies.json`, add `"wc_application"` to the company's `documents_to_generate` array, and ensure the profile has the fields referenced by the field map.

## Adding a New Text Template

### Step 1: Create a Jinja2 template

Create a `.txt.j2` file in the text templates directory:

```
insurance_docgen/src/insurance_docgen/templates/text/workers_comp_schedule.txt.j2
```

Template example:

```
WORKERS COMPENSATION SCHEDULE
==============================

Insured: {{ named_insured }}
FEIN:    {{ fein }}

PAYROLL BY CLASSIFICATION
-------------------------
{% for cls in wc_classifications %}
Class Code: {{ cls.code }}  Description: {{ cls.description }}
Payroll:    {{ cls.payroll | currency }}
{% endfor %}
```

Available filters: `{{ value | currency }}` (formats as $1,234,567), `{{ value | pct }}` (formats as 85.0%).

### Step 2: Register in generator.py

```python
"wc_schedule": {
    "method": "text",
    "template": "workers_comp_schedule",
    "output_prefix": "wc_schedule",
    "output_ext": ".txt",
},
```

### Step 3: Add data transformation in generator.py

If your template needs computed fields beyond what's directly in the company profile, add the logic to `_profile_to_data()`.

## Dependencies

- **PyMuPDF** (fitz) - PDF form field manipulation
- **Jinja2** - Text template rendering
- **Pydantic** - Company profile validation
