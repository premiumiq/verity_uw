"""UW Demo Pipeline — submission data and mock context builder.

This module provides:
1. Static submission metadata (in a real app, this would come from pas_db)
2. get_mock_context() — builds a MockContext from pre-built outputs so the
   pipeline can run through Verity's execution engine without calling Claude

IMPORTANT: This module does NOT bypass the execution engine.
Mock mode uses MockContext → goes through the gateway → skips Claude →
logs decisions normally. The governance trail is identical to live mode.
"""

from typing import Any, Optional

from verity.core.mock_context import MockContext


# ══════════════════════════════════════════════════════════════
# SUBMISSION DATA (static for demo — would come from pas_db)
# ══════════════════════════════════════════════════════════════

SUBMISSIONS = [
    {
        "id": "00000001-0001-0001-0001-000000000001",
        "named_insured": "Acme Dynamics LLC",
        "lob": "D&O",
        "revenue": "$50,000,000",
        "employees": "250",
        "risk_score": "Green",
        "appetite": "within_appetite",
        "has_override": False,
        "steps_complete": 4,
        # Verity-owned pipeline_run_id from seed data — used for "View in Verity" links.
        # When a new pipeline run happens (mock or live), this gets overwritten.
        "last_pipeline_run_id": "aaaa0001-0001-0001-0001-000000000001",
    },
    {
        "id": "00000002-0002-0002-0002-000000000002",
        "named_insured": "TechFlow Industries Inc",
        "lob": "D&O",
        "revenue": "$120,000,000",
        "employees": "800",
        "risk_score": "Amber",
        "appetite": "borderline",
        "has_override": True,
        "steps_complete": 4,
        "last_pipeline_run_id": "aaaa0002-0002-0002-0002-000000000002",
    },
    {
        "id": "00000003-0003-0003-0003-000000000003",
        "named_insured": "Meridian Holdings Corp",
        "lob": "GL",
        "revenue": "$25,000,000",
        "employees": "150",
        "risk_score": "Red",
        "appetite": "outside_appetite",
        "has_override": True,
        "steps_complete": 4,
        "last_pipeline_run_id": "aaaa0003-0003-0003-0003-000000000003",
    },
    {
        "id": "00000004-0004-0004-0004-000000000004",
        "named_insured": "Acme Dynamics LLC",
        "lob": "GL",
        "revenue": "$50,000,000",
        "employees": "250",
        "risk_score": "Amber",
        "appetite": "within_appetite",
        "has_override": False,
        "steps_complete": 4,
        "last_pipeline_run_id": "aaaa0004-0004-0004-0004-000000000004",
    },
]

SUBMISSIONS_BY_ID = {s["id"]: s for s in SUBMISSIONS}


# ══════════════════════════════════════════════════════════════
# MOCK CONTEXT BUILDER
# ══════════════════════════════════════════════════════════════

def get_mock_context(submission_id: str) -> Optional[MockContext]:
    """Build a MockContext with pre-built outputs for each pipeline step.

    The MockContext provides LLM responses for each step so the execution
    engine skips Claude and returns these outputs instead.

    For a 4-step pipeline (classify → extract → triage → appetite),
    we need 4 LLM responses — one per step.
    """
    outputs = _get_step_outputs(submission_id)
    if not outputs:
        return None

    # Each pipeline step will consume the next LLM response in order.
    # Step 1 (classify) gets outputs[0], step 2 (extract) gets outputs[1], etc.
    return MockContext(
        llm_responses=[
            outputs["classify_documents"],
            outputs["extract_fields"],
            outputs["triage_submission"],
            outputs["assess_appetite"],
        ],
        # Also mock all tools (since mock LLM won't actually call tools)
        mock_all_tools=True,
    )


def _get_step_outputs(submission_id: str) -> Optional[dict[str, dict]]:
    """Get pre-built AI outputs for each pipeline step."""
    if submission_id.startswith("00000001"):
        return _outputs_acme_do()
    elif submission_id.startswith("00000002"):
        return _outputs_techflow_do()
    elif submission_id.startswith("00000003"):
        return _outputs_meridian_gl()
    elif submission_id.startswith("00000004"):
        return _outputs_acme_gl()
    return None


# ── Pre-built outputs per submission ──────────────────────────

def _outputs_acme_do() -> dict:
    return {
        "classify_documents": {
            "document_type": "do_application", "confidence": 0.97,
            "classification_notes": "Clear D&O liability application header",
        },
        "extract_fields": {
            "fields": {"named_insured": "Acme Dynamics LLC", "annual_revenue": 50000000,
                       "employee_count": 250, "board_size": 7, "entity_type": "LLC",
                       "state_of_incorporation": "Delaware"},
            "low_confidence_fields": [], "unextractable_fields": [], "extraction_complete": True,
        },
        "triage_submission": {
            "risk_score": "Green", "routing": "assign_to_uw", "confidence": 0.89,
            "reasoning": "Strong financials with $50M revenue, clean loss history, experienced 7-member board.",
            "risk_factors": [{"factor": "Revenue concentration", "severity": "low", "detail": "Single market segment"}],
        },
        "assess_appetite": {
            "determination": "within_appetite", "confidence": 0.92,
            "reasoning": "Meets all D&O guidelines criteria per §2.1-2.4.",
            "guideline_citations": [
                {"section": "§2.1", "criterion": "Revenue > $10M", "submission_value": "$50M", "meets_criterion": True},
            ],
        },
    }


def _outputs_techflow_do() -> dict:
    return {
        "classify_documents": {
            "document_type": "do_application", "confidence": 0.94,
            "classification_notes": "D&O application with some non-standard formatting",
        },
        "extract_fields": {
            "fields": {"named_insured": "TechFlow Industries Inc", "annual_revenue": 120000000,
                       "employee_count": 800, "board_size": 9},
            "low_confidence_fields": ["regulatory_investigation_history"],
            "unextractable_fields": [], "extraction_complete": True,
        },
        "triage_submission": {
            "risk_score": "Amber", "routing": "assign_to_senior_uw", "confidence": 0.72,
            "reasoning": "Mixed profile. Strong revenue but pending SEC inquiry and recent board turnover.",
            "risk_factors": [
                {"factor": "Regulatory investigation", "severity": "medium", "detail": "SEC inquiry pending"},
                {"factor": "Board turnover", "severity": "low", "detail": "3 directors replaced in 12 months"},
            ],
        },
        "assess_appetite": {
            "determination": "borderline", "confidence": 0.65,
            "reasoning": "Meets most criteria but §3.2 flags pending regulatory matters.",
            "guideline_citations": [
                {"section": "§3.2", "criterion": "No pending regulatory investigations", "submission_value": "SEC inquiry pending", "meets_criterion": False},
            ],
        },
    }


def _outputs_meridian_gl() -> dict:
    return {
        "classify_documents": {
            "document_type": "gl_application", "confidence": 0.91,
            "classification_notes": "General liability application form",
        },
        "extract_fields": {
            "fields": {"named_insured": "Meridian Holdings Corp", "annual_revenue": 25000000,
                       "employee_count": 150},
            "low_confidence_fields": ["prior_premium"],
            "unextractable_fields": ["board_size"], "extraction_complete": True,
        },
        "triage_submission": {
            "risk_score": "Red", "routing": "refer_to_management", "confidence": 0.85,
            "reasoning": "High claims frequency, going concern qualification, excluded SIC codes.",
            "risk_factors": [
                {"factor": "Claims frequency", "severity": "high", "detail": "12 claims in 3 years"},
                {"factor": "Going concern", "severity": "critical", "detail": "Auditor qualified opinion"},
            ],
        },
        "assess_appetite": {
            "determination": "outside_appetite", "confidence": 0.94,
            "reasoning": "Multiple guideline violations: §4.1 excluded SIC code and §4.3 going concern.",
            "guideline_citations": [
                {"section": "§4.1", "criterion": "SIC code not excluded", "submission_value": "Excluded SIC", "meets_criterion": False},
                {"section": "§4.3", "criterion": "No going concern opinion", "submission_value": "Qualified opinion", "meets_criterion": False},
            ],
        },
    }


def _outputs_acme_gl() -> dict:
    return {
        "classify_documents": {
            "document_type": "gl_application", "confidence": 0.93,
            "classification_notes": "Standard GL application",
        },
        "extract_fields": {
            "fields": {"named_insured": "Acme Dynamics LLC", "annual_revenue": 50000000,
                       "employee_count": 250},
            "low_confidence_fields": [], "unextractable_fields": [], "extraction_complete": True,
        },
        "triage_submission": {
            "risk_score": "Amber", "routing": "assign_to_senior_uw", "confidence": 0.74,
            "reasoning": "Adequate financials but GL exposure from manufacturing operations.",
            "risk_factors": [
                {"factor": "Manufacturing operations", "severity": "medium", "detail": "Products liability exposure"},
                {"factor": "Claims trend", "severity": "low", "detail": "Increasing frequency, stable severity"},
            ],
        },
        "assess_appetite": {
            "determination": "within_appetite", "confidence": 0.81,
            "reasoning": "Meets GL criteria. Manufacturing operations within acceptable risk classes per §5.2.",
            "guideline_citations": [
                {"section": "§5.2", "criterion": "Manufacturing SIC codes allowed", "submission_value": "Allowed SIC", "meets_criterion": True},
            ],
        },
    }
