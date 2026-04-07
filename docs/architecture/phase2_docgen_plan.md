# Phase 2: Document Generation - Plan & Solution Approach

## Context

The UW pipeline has 4 steps (classify -> extract -> triage -> appetite) but zero
actual document content exists. The 12 document references in document_tools.py
are metadata only (filenames, sizes). The classifier and extractor tasks have
nothing to classify or extract from. Ground truth validation is impossible
without source documents.

We now have real ACORD forms from the user:

| Form | Fillable | Fields | Use |
|---|---|---|---|
| DOandEPLI.pdf | Yes (157 fields) | D&O + EPLI combined application | D&O pipeline |
| ACORD 125 | Yes (365 fields) | Commercial insurance cover page | GL pipeline |
| ACORD 126 | No (static) | GL details - operations, products, hazards | GL pipeline supplement |
| ACORD 101 | TBD | Additional remarks overflow | Supplemental |
| ACORD 807 | No (static) | D&O section (attaches to 825) | Reference only |
| ACORD 825 | No (static) | Professional/specialty base app | Reference only |

**Key correction:** "ACORD 855" in the codebase is wrong - that's a NY construction
form. The D&O application is the DOandEPLI form. Classifier labels must be renamed.

---

## 1. Docgen Tool Architecture

### Pip-installable Python package at `insurance_docgen/`

Like Verity, this is a proper package - reusable across demos, test data
generation, training pipelines, and other projects.

```
insurance_docgen/
    pyproject.toml           # Package metadata, deps (PyMuPDF, Jinja2)
    src/
        insurance_docgen/
            __init__.py
            cli.py           # CLI entry point (python -m insurance_docgen)
            pdf_filler.py    # Fill fillable PDF form fields from JSON
            text_filler.py   # Fill text templates (Jinja2) from JSON
            generator.py     # High-level: profile + templates -> documents
            models.py        # Pydantic models for company profiles
            templates/       # Built-in Jinja2 templates (shipped with package)
                loss_run.txt.j2
                financial_statement.txt.j2
                board_resolution.txt.j2
                supplemental_gl.txt.j2
            field_maps/      # Built-in PDF field mappings (shipped with package)
                do_epli_fields.json
                acord_125_fields.json
```

Separate from Verity - this is a data generation utility, not governance code.
Verity must not import it. UW demo uses it during setup only.

### How it works

**As a library (from Python):**
```python
from insurance_docgen import DocumentGenerator

gen = DocumentGenerator()

# Fill a single D&O application from a profile dict
gen.fill_pdf(
    template_path="docs/acord/DOandEPLI.pdf",
    field_map="do_epli",             # Built-in field map name
    profile=company_profile_dict,
    output_path="output/do_app_acme.pdf",
)

# Render a loss run from a profile dict
gen.render_text(
    template="loss_run",             # Built-in template name
    profile=company_profile_dict,
    output_path="output/loss_run_acme.txt",
)

# Batch: generate all documents for all profiles
gen.generate_all(
    profiles_path="profiles/companies.json",
    templates_dir="docs/acord/",     # Where the blank PDFs live
    output_dir="output/filled/",
)
```

**As a CLI:**
```bash
# Single document
.venv/bin/python -m insurance_docgen fill-pdf \
    --template docs/acord/DOandEPLI.pdf \
    --field-map do_epli \
    --profile profiles/companies.json \
    --company acme_dynamics \
    --output output/do_app_acme.pdf

# Single text document
.venv/bin/python -m insurance_docgen render-text \
    --template loss_run \
    --profile profiles/companies.json \
    --company acme_dynamics \
    --output output/loss_run_acme.txt

# Batch generation - all companies, all document types
.venv/bin/python -m insurance_docgen generate-all \
    --profiles profiles/companies.json \
    --templates-dir docs/acord/ \
    --output-dir output/filled/
```

### Dependencies (in pyproject.toml)
- `PyMuPDF` - PDF form filling and text extraction
- `Jinja2` - text template rendering
- `pydantic` - profile validation

---

## 2. Field Mappings

### DOandEPLI.pdf (D&O Application) - Key Fields

| Profile JSON Key | PDF Form Field Name | Type | Notes |
|---|---|---|---|
| named_insured | Name of Applicant | Text | |
| address | Address of Applicant | Text | |
| city | City | Text | |
| state | State | Text | |
| zip | Zip | Text | |
| contact_name | Name | Text | Primary contact |
| contact_title | Title | Text | |
| contact_email | EMail Address | Text | |
| do_coverage | Directors & Officers | CheckBox | Check if requesting D&O |
| do_limit | Directors/Officers LoL | Text | Limit of liability |
| state_of_incorporation | State of Incorporation | Text | |
| date_established | Date Established | Text | |
| nature_of_business | Nature of the Applicants business 1 | Text | |
| total_employees | Total employees | Text | |
| annual_revenue | Annual Revenues | Text | |
| total_assets | DIRECTORS AND OFFICERS LIABILITY INFORMATION | Text | Field 12 - total assets |
| public_offering | Public or Private offering? | CheckBox | Yes/No pair |
| antitrust_litigation | Anti-trust, copyright | CheckBox | Yes/No pair |
| securities_violation | Violation of securities laws? | CheckBox | Yes/No pair |
| other_criminal | Other criminal actions? | CheckBox | Yes/No pair |
| prior_claims | Claim question | CheckBox | Yes/No pair |
| director_shareholder_1 | Names of Director or Officer ShareholdersRow1 | Text | |
| director_shareholder_2 | Names of Director or Officer ShareholdersRow2 | Text | |
| current_year_revenue | Current Year 1 | Text | Financial comparison |
| previous_year_revenue | Previous Year 1 | Text | |
| current_year_income | Current Year 2 | Text | |
| previous_year_income | Previous Year 2 | Text | |
| current_year_assets | Current Year 3 | Text | |
| previous_year_assets | Previous Year 3 | Text | |

### ACORD 125 (GL Application) - Key Fields

The ACORD 125 uses XFA form field names (topmostSubform[0].Page1[0]...).
The field_map JSON will map human-readable keys to these long XFA paths.

Key fields needed: FEIN, Named Insured, Mailing Address, Date Business Started,
SIC Code, Total Employees, Total Payroll, Total Revenues, Proposed Eff/Exp dates,
Loss Summary rows (5-year history).

---

## 3. Company Profiles (20 companies)

### Profile JSON Structure

```json
{
  "company_id": "acme_dynamics",
  "named_insured": "Acme Dynamics LLC",
  "fein": "12-3456789",
  "entity_type": "LLC",
  "state_of_incorporation": "Delaware",
  "address": "1200 Industrial Parkway",
  "city": "Wilmington",
  "state": "DE",
  "zip": "19801",
  "sic_code": "3599",
  "sic_description": "Industrial and Commercial Machinery NEC",
  "years_in_business": 15,
  "date_established": "2011-03-15",
  "annual_revenue": 50000000,
  "total_employees": 250,
  "nature_of_business": "Manufacturer of precision industrial machinery",

  "lob": "DO",
  "board_size": 7,
  "independent_directors": 4,
  "total_assets": 42000000,

  "loss_history": [
    {"year": 2023, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
    {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
    {"year": 2025, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0}
  ],

  "regulatory_investigation": null,
  "going_concern": false,
  "securities_class_action": false,
  "board_changes_recent": false,

  "documents_to_generate": ["do_application", "loss_run", "board_resolution"],

  "_ground_truth": {
    "classification": "do_application",
    "risk_score": "Green",
    "routing": "assign_to_uw",
    "appetite": "within_appetite",
    "extracted_fields": {
      "named_insured": "Acme Dynamics LLC",
      "annual_revenue": 50000000,
      "board_size": 7
    }
  },

  "_data_quality_notes": []
}
```

### 10 D&O Companies

| # | Company | Revenue | Board | Risk | Appetite | Data Quality Issue |
|---|---|---|---|---|---|---|
| 1 | Acme Dynamics LLC | $50M | 7 (4 ind) | Green | Within | Clean - baseline |
| 2 | Pinnacle Software Corp | $85M | 8 (5 ind) | Green | Within | Clean |
| 3 | Westfield Manufacturing Inc | $120M | 9 (6 ind) | Green | Within | Clean |
| 4 | TechFlow Industries Inc | $120M | 9 (5 ind) | Amber | Borderline | SEC routine inquiry - tests "routine vs enforcement" distinction |
| 5 | Horizon Capital Group | $45M | 6 (3 ind) | Amber | Borderline | Board exactly 50% independent (not majority) |
| 6 | Sterling Advisory Partners | $28M | 5 (3 ind) | Amber | Borderline | 2 D&O claims in 5 years (at threshold) |
| 7 | NovaTech Holdings LLC | $9.5M | 4 (2 ind) | Red | Outside | Revenue below $10M minimum |
| 8 | Pacific Ventures Group | $75M | 6 (3 ind) | Red | Outside | Going concern opinion from auditor |
| 9 | Continental Services Inc | $200M | 11 (7 ind) | Red | Outside | DOJ investigation (not routine) |
| 10 | Brightline Analytics Corp | $60M | 7 (4 ind) | Amber | Borderline | **Revenue field left blank** on form. Financial stmt has the data. |

### 10 GL Companies

| # | Company | Revenue | SIC | Risk | Appetite | Data Quality Issue |
|---|---|---|---|---|---|---|
| 11 | Meridian Holdings Corp | $25M | 6159 | Red | Outside | SIC in excluded financial services range |
| 12 | Atlas Building Supply | $35M | 5211 | Green | Within | Retail lumber/building - standard GL |
| 13 | Cascade Precision Mfg | $55M | 3462 | Green | Within | Light manufacturing (3400-3599 range) |
| 14 | Granite Peak Construction | $40M | 1542 | Amber | Borderline | Construction - needs separate contractor liability |
| 15 | Lakeshore Food Processing | $70M | 2099 | Green | Within | Food manufacturing - standard |
| 16 | Ironworks Heavy Industries | $90M | 3312 | Amber | Borderline | Heavy manufacturing (3300-3399) - needs senior UW |
| 17 | Bayview Chemical Corp | $30M | 2899 | Amber | Borderline | Chemical manufacturing - hazmat supplemental needed |
| 18 | Summit Mining & Resources | $150M | 1040 | Red | Outside | SIC in excluded mining range (1000-1499) |
| 19 | Clearwater Environmental | $18M | 4953 | Red | Outside | Going concern + 8 claims in 3 years |
| 20 | Redwood Timber Products | $42M | 2421 | Amber | Borderline | **Revenue stated as range "$40-45M"** on form. 6 claims/3yr (above 5 threshold) |

### Data Quality Issues (Realistic Imperfections)

| Issue | Company | What | Why It Matters |
|---|---|---|---|
| Missing field | #10 Brightline | Revenue blank on D&O form | Extractor must return null + low confidence. Triage must use financial statement data. |
| Ambiguous value | #20 Redwood | Revenue as "$40-45M" range | Extractor must handle non-numeric. Triage/appetite must pick a value or flag. |
| Threshold boundary | #7 NovaTech | Revenue $9.5M (below $10M min) | Tests exact boundary checking in appetite guidelines |
| Threshold boundary | #5 Horizon | Board 50% independent (not majority) | Tests "majority" interpretation in governance check |
| At-threshold claims | #6 Sterling | Exactly 2 D&O claims in 5yr | Tests "maximum 2" - is 2 acceptable or a fail? |
| Routine vs enforcement | #4 TechFlow | SEC "routine inquiry" | Guidelines say routine is acceptable; tests agent distinction |
| Hard enforcement | #9 Continental | Active DOJ investigation | Clearly disqualifying - not ambiguous |
| Going concern withdrawn | Profile TBD | Going concern issued then withdrawn | Tests the §4.3 exception clause |
| Claims trending up | #19 Clearwater | 2, 3, 3 claims per year | Tests "frequency trending upward" guideline |
| Disputed claim | Profile TBD | One claim in litigation, disputed | Tests whether disputed claims count toward frequency |

---

## 4. Document Inventory

### Per Company - What Gets Generated

**D&O Companies (#1-10):**
- 1 filled DOandEPLI.pdf (D&O application)
- 1 loss run report (.txt)
- Some get: financial statement, board resolution

**GL Companies (#11-20):**
- 1 filled ACORD 125 (.pdf - GL cover page)
- 1 loss run report (.txt)
- Some get: financial statement, supplemental operations description

### Complete Inventory

| Document Type | Count | Format | Template Source |
|---|---|---|---|
| D&O Application (DOandEPLI) | 10 | Filled PDF | docs/acord/DOandEPLI.pdf |
| GL Application (ACORD 125) | 10 | Filled PDF | docs/acord/Acord-125-...pdf |
| Loss Run Reports | 20 | Text (.txt) | Jinja2 template |
| Financial Statements | 6 | Text (.txt) | Jinja2 template |
| Board Resolutions | 4 | Text (.txt) | Jinja2 template |
| GL Supplemental (operations) | 4 | Text (.txt) | Jinja2 template |
| Edge cases (ambiguous docs) | 2 | Text (.txt) | Deliberately hybrid |
| Non-insurance (negative cases) | 2 | Text (.txt) | Random non-insurance text |
| **Total** | **58** | | |

### Output Directory Structure

```
uw_demo/seed_docs/
    filled/
        do_app_acme_dynamics.pdf
        do_app_pinnacle_software.pdf
        ...
        gl_app_atlas_building.pdf
        gl_app_cascade_precision.pdf
        ...
        loss_run_acme_dynamics.txt
        loss_run_pinnacle_software.txt
        ...
        financial_stmt_techflow.txt
        ...
        board_resolution_acme_dynamics.txt
        ...
        supplemental_gl_ironworks.txt
        ...
        edge_case_mixed_doc_01.txt
        edge_case_mixed_doc_02.txt
        non_insurance_01.txt
        non_insurance_02.txt
```

---

## 5. Text Templates (Non-PDF Documents)

### Loss Run Template (loss_run.txt.j2)

```
LOSS RUN REPORT
===============

Insured: {{ named_insured }}
Policy Number: {{ policy_number }}
Line of Business: {{ lob_display }}
Report Date: {{ report_date }}
Report Period: {{ report_start }} to {{ report_end }}

CLAIMS SUMMARY
--------------

Year    Claims  Incurred ($)  Paid ($)    Reserves ($)  Status
------  ------  -----------   --------    -----------   ------
{% for yr in loss_history %}
{{ yr.year }}    {{ yr.claims }}       {{ "{:,.0f}".format(yr.incurred) }}         {{ "{:,.0f}".format(yr.paid) }}        {{ "{:,.0f}".format(yr.reserves) }}        {{ yr.status|default("Closed") }}
{% endfor %}

TOTALS: {{ total_claims }} claims, ${{ "{:,.0f}".format(total_incurred) }} incurred

{% if claim_details %}
CLAIM DETAILS
-------------
{% for claim in claim_details %}
Claim #{{ claim.number }}
  Date of Loss: {{ claim.date_of_loss }}
  Claimant: {{ claim.claimant }}
  Type: {{ claim.type }}
  Description: {{ claim.description }}
  Status: {{ claim.status }}
  Paid: ${{ "{:,.0f}".format(claim.paid) }}
  Reserves: ${{ "{:,.0f}".format(claim.reserves) }}
{% endfor %}
{% endif %}

{% if notes %}
NOTES
-----
{{ notes }}
{% endif %}

Report prepared by: {{ prepared_by }}
```

### Financial Statement Template (financial_statement.txt.j2)

Includes: Balance sheet summary, income statement, auditor opinion (with going
concern language when applicable), 2-year comparison.

### Board Resolution Template (board_resolution.txt.j2)

Includes: Board composition, committee structure, D&O insurance authorization,
director election details.

### GL Supplemental Template (supplemental_gl.txt.j2)

Includes: Operations description, products manufactured, hazmat handling status,
contractor usage, recall exposure.

---

## 6. Classifier Label Rename

The codebase uses "acord_855" for D&O and "acord_125" for GL. These need renaming:

| Old Label | New Label | Reason |
|---|---|---|
| `acord_855` | `do_application` | ACORD 855 is NY construction, not D&O |
| `acord_125` | `gl_application` | More descriptive; GL is actually 125+126 stack |
| `supplemental_do` | `supplemental_do` | Keep as-is |
| `supplemental_gl` | `supplemental_gl` | Keep as-is |
| `loss_runs` | `loss_run` | Singular for consistency |
| `financial_statements` | `financial_statement` | Singular |
| `board_resolution` | `board_resolution` | Keep as-is |
| (new) `other` | `other` | Non-classifiable documents |

### Files to Update

- `uw_demo/app/tools/document_tools.py` - Document type references
- `uw_demo/app/setup/register_all.py` - Prompt text, test cases, mock outputs
- `uw_demo/app/pipeline.py` - Mock output classification labels
- `verity/src/verity/web/templates/pipeline_detail.html` - Display links (if any)
- Classifier prompt text (Phase 3 rewrite)
- Extractor prompt text (Phase 3 rewrite)
- Test case expected outputs
- Ground truth dataset labels

---

## 7. How Quality Is Verified

### Before Generation (Profile Review)

Each company profile in companies.json has:
- `_ground_truth` section: expected classification, risk score, appetite, extracted fields
- `_data_quality_notes`: deliberately introduced issues documented
- All fields cross-checked against guidelines (revenue thresholds, SIC ranges, claims limits)

**User reviews profiles before any documents are generated.**

### After Generation (Document Review)

1. **PDF Fill Verification:** Open 2-3 filled PDFs manually, confirm fields populated correctly
2. **Text Template Verification:** Read 2-3 loss runs and financial statements, confirm data matches profile
3. **Classifier Sanity Check:** Each document's text must contain enough classification markers:
   - D&O apps: "Directors and Officers", "Board of Directors", coverage sections
   - GL apps: "Commercial Insurance Application", "General Liability", operations
   - Loss runs: "LOSS RUN REPORT", "CLAIMS SUMMARY", year/claims/incurred columns
   - Financial: "BALANCE SHEET", "INCOME STATEMENT", auditor opinion

4. **Extraction Sanity Check:** ACORD fields must be extractable:
   - Text extraction from filled PDF (PyMuPDF get_text()) returns field values
   - Named insured, revenue, employees visible in extracted text

5. **Data Quality Issues Verified:**
   - Company #10: Revenue field actually blank in generated PDF
   - Company #20: Revenue shows "$40-45M" not a clean number
   - Company #7: Revenue shows $9,500,000 (below $10M threshold)

### Ground Truth Cross-Check

Each document's `_ground_truth` is validated against the guidelines:
- Green companies must pass ALL guideline criteria
- Red companies must violate at least one disqualifying criterion
- Amber companies must have 1-2 borderline issues but no disqualifiers
- Appetite determinations match specific guideline sections

---

## 8. Implementation Order

| Step | What | Output |
|---|---|---|
| 1 | Create `insurance_docgen/` package structure with pyproject.toml | Package scaffolding |
| 2 | Build models.py (Pydantic profile models) | Profile validation |
| 3 | Build pdf_filler.py (PyMuPDF form filling) | PDF fill capability |
| 4 | Build field maps (do_epli_fields.json, acord_125_fields.json) | Field name mappings |
| 5 | Build text_filler.py (Jinja2 template rendering) | Text fill capability |
| 6 | Create text templates (loss_run, financial, board, supplemental) | 4 Jinja2 templates |
| 7 | Build generator.py (high-level orchestration) | Generate-all capability |
| 8 | Build cli.py (CLI entry point) | Command-line interface |
| 9 | Create companies.json (all 20 profiles) | **USER REVIEWS THIS** |
| 10 | pip install -e insurance_docgen/ into .venv | Package usable |
| 11 | Generate all 58 documents | `uw_demo/seed_docs/filled/` |
| 12 | Rename classifier labels across codebase | Updated code |
| 13 | Upload to MinIO during seed setup | Documents accessible at runtime |

---

## 9. Verification

```bash
# Install the package in dev mode
.venv/bin/pip install -e insurance_docgen/

# Generate all documents
.venv/bin/python -m insurance_docgen generate-all \
    --profiles insurance_docgen/profiles/companies.json \
    --templates-dir docs/acord/ \
    --output-dir uw_demo/seed_docs/filled/

# Verify count
ls uw_demo/seed_docs/filled/ | wc -l  # Should be ~58

# Verify a filled PDF has content
.venv/bin/python -c "
import fitz
doc = fitz.open('uw_demo/seed_docs/filled/do_app_acme_dynamics.pdf')
text = doc[0].get_text()
assert 'Acme Dynamics' in text
print('OK: D&O app has content')
"

# Verify a loss run has content
grep 'Acme Dynamics' uw_demo/seed_docs/filled/loss_run_acme_dynamics.txt

# Start the app and verify documents appear in the pipeline
docker compose up -d --build
```
