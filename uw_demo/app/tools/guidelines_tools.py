"""Guidelines Tools — return underwriting guidelines text.

These guidelines are what the appetite agent reads to determine
whether a submission falls within underwriting appetite. Each
guideline section has specific criteria that the agent evaluates.
"""


_DO_GUIDELINES = """
DIRECTORS & OFFICERS LIABILITY — UNDERWRITING GUIDELINES
Verity Insurance Company
Effective: January 1, 2026

§1. GENERAL ELIGIBILITY
1.1 Entity must be incorporated or organized in the United States.
1.2 Minimum 3 years in business (waiver available for well-capitalized startups with experienced board).
1.3 Annual revenue between $10M and $500M (refer to excess lines for larger).

§2. FINANCIAL REQUIREMENTS
2.1 Annual revenue must exceed $10M.
2.2 No going concern qualification from auditors in most recent fiscal year.
2.3 Positive net income in at least 2 of the last 3 fiscal years.
2.4 Debt-to-equity ratio below 3:1.

§3. GOVERNANCE REQUIREMENTS
3.1 Board must have minimum 5 members.
3.2 No pending SEC enforcement actions or DOJ investigations. Routine SEC inquiries (comment letters, routine reviews) are acceptable with documentation.
3.3 Majority of board must be independent directors.
3.4 Must have audit committee with at least one financial expert.

§4. EXCLUSIONS
4.1 Entities with SIC codes in financial services (6000-6199) require special approval.
4.2 Cannabis-related businesses excluded.
4.3 Entities with going concern opinions excluded unless auditor has withdrawn the opinion.
4.4 Entities that have filed for bankruptcy protection in the last 5 years excluded.

§5. CLAIMS HISTORY
5.1 Maximum 2 D&O claims in the last 5 years.
5.2 No single claim exceeding $1M incurred in the last 3 years.
5.3 Securities class action history requires referral to senior underwriter.

§6. PRICING GUIDELINES
6.1 Base rate: $8-12 per $1,000 of limit for standard risk.
6.2 Schedule credit up to 30% for favorable risk characteristics.
6.3 Schedule debit up to 50% for adverse risk characteristics.
6.4 Minimum premium: $15,000.
"""


_GL_GUIDELINES = """
GENERAL LIABILITY — UNDERWRITING GUIDELINES
Verity Insurance Company
Effective: January 1, 2026

§1. GENERAL ELIGIBILITY
1.1 Business must be operating in the United States.
1.2 Minimum 2 years in business.
1.3 Annual revenue between $5M and $250M.

§2. FINANCIAL REQUIREMENTS
2.1 Annual revenue must exceed $5M.
2.2 No going concern qualification.
2.3 Current on all tax obligations.

§3. OPERATIONS
3.1 Must provide detailed description of operations.
3.2 Hazardous materials handling requires environmental supplemental.
3.3 Construction operations require separate contractor's liability coverage.

§4. EXCLUSIONS
4.1 SIC codes 6000-6199 (financial services) excluded from GL program.
4.2 Mining operations (SIC 1000-1499) excluded.
4.3 Entities with going concern opinions excluded.
4.4 Aviation-related operations excluded.

§5. MANUFACTURING RISKS
5.1 Light manufacturing (SIC 3400-3599) acceptable at standard rates.
5.2 Heavy manufacturing (SIC 3300-3399) requires senior UW approval.
5.3 Products liability exposure must be documented with product descriptions.
5.4 Recall exposure requires separate coverage endorsement.

§6. CLAIMS HISTORY
6.1 Maximum 5 GL claims in the last 3 years for standard approval.
6.2 Claims frequency trending upward requires senior UW review.
6.3 Any single claim exceeding $500K requires referral.

§7. PRICING GUIDELINES
7.1 Base rate varies by SIC code and revenue band.
7.2 Schedule modifications: credit up to 25%, debit up to 40%.
7.3 Minimum premium: $10,000.
"""


def get_underwriting_guidelines(lob: str) -> dict:
    """Returns underwriting guidelines for the specified line of business.

    Args:
        lob: "DO" for Directors & Officers, "GL" for General Liability.

    Called by appetite_agent to evaluate submissions against guidelines.
    """
    if lob == "DO":
        return {
            "lob": "Directors & Officers Liability",
            "guidelines_text": _DO_GUIDELINES,
            "version": "2026-01",
            "sections": ["§1 General Eligibility", "§2 Financial Requirements",
                         "§3 Governance Requirements", "§4 Exclusions",
                         "§5 Claims History", "§6 Pricing Guidelines"],
        }
    elif lob == "GL":
        return {
            "lob": "General Liability",
            "guidelines_text": _GL_GUIDELINES,
            "version": "2026-01",
            "sections": ["§1 General Eligibility", "§2 Financial Requirements",
                         "§3 Operations", "§4 Exclusions",
                         "§5 Manufacturing Risks", "§6 Claims History",
                         "§7 Pricing Guidelines"],
        }
    return {"error": f"Unknown LOB: {lob}. Expected 'DO' or 'GL'."}
