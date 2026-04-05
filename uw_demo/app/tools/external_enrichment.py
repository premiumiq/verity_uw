"""External Enrichment Tools — LexisNexis, D&B, Pitchbook data.

In production, these would call real third-party APIs. For the demo,
they return realistic hardcoded data keyed by company name.
"""


_ENRICHMENT_DATA = {
    "Acme Dynamics LLC": {
        "lexisnexis": {
            "litigation_history": [],
            "regulatory_actions": [],
            "bankruptcy_filings": [],
            "risk_score": "low",
        },
        "dnb": {
            "duns_number": "12-345-6789",
            "financial_stress_score": 85,
            "payment_performance": "prompt",
            "employee_count_verified": 245,
            "revenue_verified": 48500000,
        },
        "pitchbook": {
            "company_type": "Private",
            "industry": "Industrial Machinery",
            "total_funding": None,
            "last_funding_round": None,
            "key_investors": [],
        },
    },
    "TechFlow Industries Inc": {
        "lexisnexis": {
            "litigation_history": [
                {"case": "SEC v. TechFlow", "type": "regulatory_inquiry", "status": "pending",
                 "filed": "2025-08", "description": "Routine review of revenue recognition practices"},
            ],
            "regulatory_actions": [
                {"agency": "SEC", "type": "inquiry", "status": "open", "severity": "routine"},
            ],
            "bankruptcy_filings": [],
            "risk_score": "medium",
        },
        "dnb": {
            "duns_number": "98-765-4321",
            "financial_stress_score": 72,
            "payment_performance": "generally_prompt",
            "employee_count_verified": 790,
            "revenue_verified": 118000000,
        },
        "pitchbook": {
            "company_type": "Private",
            "industry": "Enterprise Software",
            "total_funding": 45000000,
            "last_funding_round": "Series C - 2023",
            "key_investors": ["Sequoia Capital", "Accel Partners"],
        },
    },
    "Meridian Holdings Corp": {
        "lexisnexis": {
            "litigation_history": [
                {"case": "Smith v. Meridian", "type": "negligence", "status": "settled",
                 "filed": "2024-03", "amount": 125000},
                {"case": "Jones v. Meridian", "type": "breach_of_contract", "status": "pending",
                 "filed": "2025-01"},
            ],
            "regulatory_actions": [],
            "bankruptcy_filings": [],
            "risk_score": "high",
        },
        "dnb": {
            "duns_number": "55-123-4567",
            "financial_stress_score": 45,
            "payment_performance": "slow",
            "employee_count_verified": 148,
            "revenue_verified": 23500000,
        },
        "pitchbook": {
            "company_type": "Public (OTC)",
            "industry": "Financial Services",
            "total_funding": None,
            "last_funding_round": None,
            "key_investors": [],
        },
    },
}


def get_enrichment_data(company_name: str) -> dict:
    """Returns enrichment data from LexisNexis, D&B, and Pitchbook.

    Called by triage_agent to supplement submission data with
    third-party intelligence for risk assessment.
    """
    data = _ENRICHMENT_DATA.get(company_name)
    if data:
        return data

    # Fuzzy match — try partial match if exact not found
    for key, value in _ENRICHMENT_DATA.items():
        if company_name.lower() in key.lower() or key.lower() in company_name.lower():
            return value

    # Unknown company — return neutral data
    return {
        "lexisnexis": {"litigation_history": [], "regulatory_actions": [], "risk_score": "unknown"},
        "dnb": {"financial_stress_score": None, "payment_performance": "unknown"},
        "pitchbook": {"company_type": "Unknown"},
        "note": f"No enrichment data found for '{company_name}'",
    }
