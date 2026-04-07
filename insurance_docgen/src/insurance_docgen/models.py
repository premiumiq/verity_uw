"""Pydantic models for company profiles and ground truth metadata.

Each company profile contains all the data needed to generate filled
insurance documents (D&O applications, GL applications, loss runs,
financial statements, board resolutions, supplementals).

The _ground_truth section captures expected outputs for classifier,
extractor, triage, and appetite - enabling validation dataset creation.
"""

from typing import Any, Optional
from pydantic import BaseModel


class LossYear(BaseModel):
    """One year of loss history."""
    year: int
    claims: int
    incurred: float          # Total incurred amount ($)
    paid: float              # Amount paid ($)
    reserves: float          # Outstanding reserves ($)
    status: str = "Closed"   # "Closed", "Open", "Subrogation"


class ClaimDetail(BaseModel):
    """Detail for an individual claim (used in loss run reports)."""
    number: str              # Claim number (e.g., "CLM-2024-001")
    date_of_loss: str        # YYYY-MM-DD
    claimant: str
    type: str                # "Bodily Injury", "Property Damage", "D&O Wrongful Act", etc.
    description: str
    status: str              # "Closed", "Open", "Reserved", "In Litigation"
    paid: float
    reserves: float


class FinancialData(BaseModel):
    """Two-year financial comparison for financial statements."""
    current_year: int
    prior_year: int
    current_revenue: float
    prior_revenue: float
    current_net_income: float
    prior_net_income: float
    current_total_assets: float
    prior_total_assets: float
    current_total_liabilities: float
    prior_total_liabilities: float
    current_equity: float
    prior_equity: float
    auditor_name: str = "Smith & Associates CPAs"
    auditor_opinion: str = "Unqualified"  # "Unqualified", "Qualified", "Going Concern"
    going_concern_note: Optional[str] = None  # Text of going concern paragraph if applicable


class BoardMember(BaseModel):
    """Director/officer for board resolution and D&O application."""
    name: str
    title: str                # "Director", "Chairman", "CEO", "CFO", etc.
    is_independent: bool
    committee: Optional[str] = None  # "Audit", "Compensation", "Governance", etc.
    shares_owned: Optional[str] = None  # Percentage or count


class GroundTruth(BaseModel):
    """Expected outputs for each pipeline step - used to create validation datasets."""
    classification: str                      # "do_application", "gl_application", etc.
    risk_score: str                          # "Green", "Amber", "Red"
    routing: str                             # "assign_to_uw", "assign_to_senior_uw", etc.
    appetite: str                            # "within_appetite", "borderline", "outside_appetite"
    appetite_key_citations: list[str] = []   # e.g., ["§2.1 Revenue > $10M", "§3.2 No SEC enforcement"]
    extracted_fields: dict[str, Any] = {}    # Field name -> expected value


class CompanyProfile(BaseModel):
    """Complete company profile for document generation.

    One profile generates multiple documents: an application form,
    a loss run, and optionally financial statements, board resolutions,
    and supplementals.
    """
    # -- Identity --
    company_id: str                          # Machine name (e.g., "acme_dynamics")
    named_insured: str                       # Legal name
    fein: str                                # Federal Employer ID (XX-XXXXXXX)
    entity_type: str                         # LLC, Corporation, Partnership, etc.
    state_of_incorporation: str
    address: str
    city: str
    state: str
    zip: str
    phone: str = ""
    website: str = ""

    # -- Business --
    sic_code: str
    sic_description: str
    naics_code: str = ""
    years_in_business: int
    date_established: str                    # YYYY-MM-DD
    nature_of_business: str                  # Short description of operations
    annual_revenue: float                    # May be 0 if intentionally blank
    annual_revenue_display: Optional[str] = None  # Override display (e.g., "$40-45M" for ambiguous cases)
    total_employees: int
    total_payroll: float = 0

    # -- Line of Business --
    lob: str                                 # "DO" or "GL"

    # -- D&O Specific --
    board_size: Optional[int] = None
    independent_directors: Optional[int] = None
    board_members: list[BoardMember] = []
    total_assets: Optional[float] = None
    has_audit_committee: bool = True
    audit_committee_financial_expert: bool = True

    # -- GL Specific --
    manufacturing_operations: bool = False
    products_liability_exposure: Optional[str] = None
    hazmat_handling: bool = False
    construction_operations: bool = False

    # -- Coverage --
    effective_date: str = "2026-07-01"
    expiration_date: str = "2027-07-01"
    limits_requested: float = 5000000
    retention_requested: float = 50000
    prior_carrier: str = "None"
    prior_premium: float = 0

    # -- Risk Factors --
    regulatory_investigation: Optional[str] = None  # Description if any
    regulatory_type: Optional[str] = None            # "routine_inquiry", "enforcement", "doj", etc.
    going_concern: bool = False
    going_concern_withdrawn: bool = False             # True = was issued then withdrawn
    securities_class_action: bool = False
    board_changes_recent: bool = False
    ipo_planned: bool = False
    merger_acquisition: bool = False
    bankruptcy_history: bool = False
    non_renewed_by_carrier: bool = False

    # -- Loss History --
    loss_history: list[LossYear] = []
    claim_details: list[ClaimDetail] = []
    loss_notes: Optional[str] = None                 # Notes for loss run (e.g., "Claim #3 in dispute")

    # -- Financial Data (for financial statement generation) --
    financial_data: Optional[FinancialData] = None

    # -- Documents to Generate --
    documents_to_generate: list[str] = []
    # Values: "do_application", "gl_application", "loss_run",
    #         "financial_statement", "board_resolution", "supplemental_gl"

    # -- Ground Truth --
    ground_truth: GroundTruth

    # -- Data Quality Notes (intentional issues for testing) --
    data_quality_notes: list[str] = []
    # e.g., ["Revenue field intentionally left blank on form",
    #        "Revenue stated as range $40-45M"]
