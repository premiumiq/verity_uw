"""UW Demo Pipeline — fixture builders for two pipelines.

Provides fixture dicts for:
1. Document Processing pipeline (classify + extract)
2. Risk Assessment pipeline (triage + appetite)

IMPORTANT: This module does NOT bypass the governance trail. Fixtures
go through FixtureEngine, which resolves the entity's config from the
registry (so decision_log.entity_version_id is correct), then logs a
DecisionLogCreate with mock_mode=True. The trail is identical in shape
to a live run — just without the real LLM or tool calls.

Submission data is now in uw_db (no longer hardcoded here).
This module only provides pre-built pipeline-step outputs for demo mode.
"""

from typing import Optional

from verity.runtime.fixture_backend import Fixture


# ══════════════════════════════════════════════════════════════
# PIPELINE 1: DOCUMENT PROCESSING FIXTURES
# ══════════════════════════════════════════════════════════════

def get_fixtures_doc_processing(submission_id: str) -> Optional[dict[str, Fixture]]:
    """Build fixtures (keyed by pipeline step_name) for the doc-processing pipeline.

    2 steps: classify_documents → extract_fields. Fixture keys match the
    step_names registered in register_all.py so FixtureEngine routes each
    step to the right pre-built output.

    Returns None when there's no fixture for this submission_id — the
    caller should fall back to live execution in that case.
    """
    outputs = _get_doc_processing_outputs(submission_id)
    if not outputs:
        return None
    return {
        "classify_documents": Fixture(output=outputs["classify_documents"]),
        "extract_fields": Fixture(output=outputs["extract_fields"]),
    }


def _get_doc_processing_outputs(submission_id: str) -> Optional[dict]:
    """Pre-built AI outputs for document processing steps."""
    if submission_id.startswith("00000001"):
        return {
            "classify_documents": {
                "documents_classified": [
                    {"document_id": "mock-001", "document_type": "do_application", "confidence": 0.97,
                     "classification_notes": "Clear D&O liability application with board composition section"},
                    {"document_id": "mock-002", "document_type": "loss_run", "confidence": 0.95,
                     "classification_notes": "Loss run report with 3-year claims summary"},
                    {"document_id": "mock-003", "document_type": "board_resolution", "confidence": 0.93,
                     "classification_notes": "Board resolution authorizing D&O coverage"},
                ],
                "total_documents": 3,
            },
            "extract_fields": {
                "fields": {
                    "named_insured": {"value": "Acme Dynamics LLC", "confidence": 0.98, "note": "Section I header"},
                    "fein": {"value": "12-3456789", "confidence": 0.97, "note": "Section I, FEIN field"},
                    "entity_type": {"value": "LLC", "confidence": 0.95, "note": "Entity type checkbox"},
                    "state_of_incorporation": {"value": "Delaware", "confidence": 0.96, "note": "State field"},
                    "annual_revenue": {"value": 50000000, "confidence": 0.95, "note": "Section II revenue"},
                    "employee_count": {"value": 250, "confidence": 0.94, "note": "Section II employees"},
                    "board_size": {"value": 7, "confidence": 0.92, "note": "Section III directors"},
                    "independent_directors": {"value": 4, "confidence": 0.90, "note": "Section III independent"},
                    "effective_date": {"value": "2026-07-01", "confidence": 0.98, "note": "Coverage dates"},
                    "expiration_date": {"value": "2027-07-01", "confidence": 0.98, "note": "Coverage dates"},
                    "limits_requested": {"value": 5000000, "confidence": 0.96, "note": "Coverage limits"},
                    "retention_requested": {"value": 100000, "confidence": 0.95, "note": "Retention field"},
                    "prior_carrier": {"value": "National Union", "confidence": 0.93, "note": "Prior coverage"},
                    "prior_premium": {"value": 45000, "confidence": 0.91, "note": "Prior premium"},
                    "ipo_planned": {"value": False, "confidence": 0.88, "note": "IPO question - No checked"},
                    "going_concern_opinion": {"value": False, "confidence": 0.90, "note": "Going concern - No"},
                    "non_renewed_by_carrier": {"value": False, "confidence": 0.89, "note": "Non-renewal - No"},
                },
                "low_confidence_fields": [],
                "unextractable_fields": ["securities_class_action_history", "merger_acquisition_activity", "regulatory_investigation_history"],
                "extraction_complete": True,
            },
        }
    elif submission_id.startswith("00000002"):
        return {
            "classify_documents": {
                "documents_classified": [
                    {"document_id": "mock-004", "document_type": "do_application", "confidence": 0.94,
                     "classification_notes": "D&O application with some non-standard formatting"},
                    {"document_id": "mock-005", "document_type": "loss_run", "confidence": 0.96,
                     "classification_notes": "Loss run with claim details"},
                    {"document_id": "mock-006", "document_type": "financial_statement", "confidence": 0.92,
                     "classification_notes": "Financial statements with auditor report"},
                ],
                "total_documents": 3,
            },
            "extract_fields": {
                "fields": {
                    "named_insured": {"value": "TechFlow Industries Inc", "confidence": 0.98, "note": "Header"},
                    "annual_revenue": {"value": 120000000, "confidence": 0.95, "note": "Revenue field"},
                    "employee_count": {"value": 800, "confidence": 0.94, "note": "Employees field"},
                    "board_size": {"value": 9, "confidence": 0.92, "note": "Directors section"},
                    "regulatory_investigation_history": {"value": "SEC inquiry pending", "confidence": 0.65, "note": "Regulatory section - text unclear"},
                },
                "low_confidence_fields": ["regulatory_investigation_history"],
                "unextractable_fields": [],
                "extraction_complete": True,
            },
        }
    elif submission_id.startswith("00000003"):
        return {
            "classify_documents": {
                "documents_classified": [
                    {"document_id": "mock-007", "document_type": "gl_application", "confidence": 0.91,
                     "classification_notes": "GL application form"},
                    {"document_id": "mock-008", "document_type": "loss_run", "confidence": 0.95,
                     "classification_notes": "Loss run report"},
                    {"document_id": "mock-009", "document_type": "financial_statement", "confidence": 0.90,
                     "classification_notes": "Financial statements"},
                ],
                "total_documents": 3,
            },
            "extract_fields": {
                "fields": {
                    "named_insured": {"value": "Meridian Holdings Corp", "confidence": 0.97, "note": "Header"},
                    "annual_revenue": {"value": 25000000, "confidence": 0.94, "note": "Revenue"},
                    "employee_count": {"value": 150, "confidence": 0.93, "note": "Employees"},
                },
                "low_confidence_fields": ["prior_premium"],
                "unextractable_fields": ["board_size"],
                "extraction_complete": True,
            },
        }
    elif submission_id.startswith("00000004"):
        return {
            "classify_documents": {
                "documents_classified": [
                    {"document_id": "mock-010", "document_type": "gl_application", "confidence": 0.93,
                     "classification_notes": "Standard GL application"},
                    {"document_id": "mock-011", "document_type": "loss_run", "confidence": 0.95,
                     "classification_notes": "Loss run report"},
                ],
                "total_documents": 2,
            },
            "extract_fields": {
                "fields": {
                    "named_insured": {"value": "Acme Dynamics LLC", "confidence": 0.97, "note": "Header"},
                    "annual_revenue": {"value": 50000000, "confidence": 0.95, "note": "Revenue"},
                    "employee_count": {"value": 250, "confidence": 0.94, "note": "Employees"},
                },
                "low_confidence_fields": [],
                "unextractable_fields": [],
                "extraction_complete": True,
            },
        }
    return None


# ══════════════════════════════════════════════════════════════
# PIPELINE 2: RISK ASSESSMENT FIXTURES
# ══════════════════════════════════════════════════════════════

def get_fixtures_risk_assessment(submission_id: str) -> Optional[dict[str, Fixture]]:
    """Build fixtures (keyed by pipeline step_name) for the risk-assessment pipeline.

    2 steps: triage_submission → assess_appetite. Fixture keys match the
    step_names registered in register_all.py.

    Returns None when there's no fixture for this submission_id — the
    caller should fall back to live execution in that case.
    """
    outputs = _get_risk_assessment_outputs(submission_id)
    if not outputs:
        return None
    return {
        "triage_submission": Fixture(output=outputs["triage_submission"]),
        "assess_appetite": Fixture(output=outputs["assess_appetite"]),
    }


def _get_risk_assessment_outputs(submission_id: str) -> Optional[dict]:
    """Pre-built AI outputs for risk assessment steps."""
    if submission_id.startswith("00000001"):
        return {
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
    elif submission_id.startswith("00000002"):
        return {
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
    elif submission_id.startswith("00000003"):
        return {
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
    elif submission_id.startswith("00000004"):
        return {
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
    return None
