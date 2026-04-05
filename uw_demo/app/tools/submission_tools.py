"""Submission Tools — return realistic insurance submission data.

These are the tool implementations that Claude calls during agent execution.
For the demo, they return hardcoded realistic data keyed by submission_id.
In production, these would query pas_db and external APIs.

Each function's signature must match the tool's registered input_schema.
The execution engine calls these as: func(**tool_input) where tool_input
is the dict Claude provides.
"""


# ── MOCK SUBMISSION DATA ──────────────────────────────────────
# Realistic D&O and GL submission profiles for the 4 demo submissions.

_SUBMISSIONS = {
    "00000001-0001-0001-0001-000000000001": {
        "account": {
            "name": "Acme Dynamics LLC",
            "fein": "12-3456789",
            "entity_type": "LLC",
            "state_of_incorporation": "Delaware",
            "sic_code": "3559",
            "sic_description": "Special Industry Machinery",
            "years_in_business": 15,
        },
        "submission": {
            "id": "00000001-0001-0001-0001-000000000001",
            "lob": "DO",
            "named_insured": "Acme Dynamics LLC",
            "annual_revenue": 50000000,
            "employee_count": 250,
            "board_size": 7,
            "independent_directors": 4,
            "effective_date": "2026-07-01",
            "expiration_date": "2027-07-01",
            "limits_requested": 5000000,
            "retention_requested": 100000,
            "prior_carrier": "National Union",
            "prior_premium": 45000,
        },
        "loss_history": [
            {"year": 2023, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
        ],
    },
    "00000002-0002-0002-0002-000000000002": {
        "account": {
            "name": "TechFlow Industries Inc",
            "fein": "98-7654321",
            "entity_type": "Corporation",
            "state_of_incorporation": "California",
            "sic_code": "7372",
            "sic_description": "Prepackaged Software",
            "years_in_business": 8,
        },
        "submission": {
            "id": "00000002-0002-0002-0002-000000000002",
            "lob": "DO",
            "named_insured": "TechFlow Industries Inc",
            "annual_revenue": 120000000,
            "employee_count": 800,
            "board_size": 9,
            "independent_directors": 5,
            "effective_date": "2026-06-01",
            "expiration_date": "2027-06-01",
            "limits_requested": 10000000,
            "retention_requested": 250000,
            "prior_carrier": "AIG",
            "prior_premium": 125000,
            "regulatory_investigation": "SEC inquiry pending — routine review of revenue recognition practices",
            "board_changes": "3 directors replaced in last 12 months",
        },
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 75000, "paid": 50000, "reserves": 25000},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 1, "incurred": 150000, "paid": 0, "reserves": 150000},
        ],
    },
    "00000003-0003-0003-0003-000000000003": {
        "account": {
            "name": "Meridian Holdings Corp",
            "fein": "55-1234567",
            "entity_type": "Corporation",
            "state_of_incorporation": "New York",
            "sic_code": "6159",
            "sic_description": "Federal-Sponsored Credit Agencies",
            "years_in_business": 22,
        },
        "submission": {
            "id": "00000003-0003-0003-0003-000000000003",
            "lob": "GL",
            "named_insured": "Meridian Holdings Corp",
            "annual_revenue": 25000000,
            "employee_count": 150,
            "effective_date": "2026-09-01",
            "expiration_date": "2027-09-01",
            "limits_requested": 2000000,
            "retention_requested": 50000,
            "prior_carrier": "Hartford",
            "prior_premium": 35000,
            "going_concern_opinion": True,
            "auditor_note": "Qualified opinion — substantial doubt about ability to continue as going concern",
        },
        "loss_history": [
            {"year": 2023, "claims": 5, "incurred": 320000, "paid": 280000, "reserves": 40000},
            {"year": 2024, "claims": 4, "incurred": 185000, "paid": 150000, "reserves": 35000},
            {"year": 2025, "claims": 3, "incurred": 95000, "paid": 60000, "reserves": 35000},
        ],
    },
    "00000004-0004-0004-0004-000000000004": {
        "account": {
            "name": "Acme Dynamics LLC",
            "fein": "12-3456789",
            "entity_type": "LLC",
            "state_of_incorporation": "Delaware",
            "sic_code": "3559",
            "sic_description": "Special Industry Machinery",
            "years_in_business": 15,
        },
        "submission": {
            "id": "00000004-0004-0004-0004-000000000004",
            "lob": "GL",
            "named_insured": "Acme Dynamics LLC",
            "annual_revenue": 50000000,
            "employee_count": 250,
            "effective_date": "2026-07-01",
            "expiration_date": "2027-07-01",
            "limits_requested": 3000000,
            "retention_requested": 75000,
            "prior_carrier": "Travelers",
            "prior_premium": 28000,
            "manufacturing_operations": True,
            "products_liability_exposure": "Industrial machinery components sold to OEMs",
        },
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 45000, "paid": 45000, "reserves": 0},
            {"year": 2024, "claims": 2, "incurred": 80000, "paid": 60000, "reserves": 20000},
            {"year": 2025, "claims": 2, "incurred": 65000, "paid": 40000, "reserves": 25000},
        ],
    },
}


# ── TOOL IMPLEMENTATIONS ──────────────────────────────────────

def get_submission_context(submission_id: str) -> dict:
    """Returns full submission data: account, submission details, loss history.

    Called by triage_agent and appetite_agent to gather context
    before making their assessment.
    """
    data = _SUBMISSIONS.get(submission_id)
    if not data:
        return {"error": f"Submission {submission_id} not found"}
    return data


def get_loss_history(account_id: str) -> dict:
    """Returns loss history for an account.

    Note: In the demo, account_id maps to submission_id since
    we don't have a separate account table.
    """
    data = _SUBMISSIONS.get(account_id)
    if data:
        return {
            "account": data["account"]["name"],
            "years": data["loss_history"],
            "total_claims": sum(y["claims"] for y in data["loss_history"]),
            "total_incurred": sum(y["incurred"] for y in data["loss_history"]),
        }
    return {"error": f"Account {account_id} not found", "years": [], "total_claims": 0, "total_incurred": 0}


def store_triage_result(submission_id: str, risk_score: str, routing: str = "", reasoning: str = "") -> dict:
    """Stores the triage result. In demo, just acknowledges the write."""
    return {"stored": True, "submission_id": submission_id, "risk_score": risk_score}


def update_submission_event(submission_id: str, event_type: str, details: dict = None) -> dict:
    """Logs a workflow event. In demo, just acknowledges."""
    return {"event_id": f"evt-{submission_id[:8]}", "event_type": event_type, "logged": True}
