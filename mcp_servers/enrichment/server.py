"""Enrichment MCP server — simulated third-party data providers.

Exposes four tools over MCP stdio, each mimicking a data provider an
underwriter subscribes to in production. Every tool takes a single
`company_name` argument and returns provider-native JSON:

  - lexisnexis_lookup   litigation + regulatory + sanctions + adverse media
  - dnb_lookup          Duns number + credit scores + firmographics
  - pitchbook_lookup    funding rounds + investors + valuation + exits
  - factset_lookup      financial fundamentals + credit rating + ratios

Data source: curated profiles in data/profiles.json for the UW demo's
seeded companies; deterministic synthetic fallback (seeded by the
company name) for any other name. The same company name always produces
the same output — stable for demos and audit reruns.

Provider-native shape means: LexisNexis returns legal records, not
financial data; D&B returns credit, not funding. The agent sees four
targeted data sources instead of one blob, enabling more granular
prompts, better audit trails (each provider call logs separately in
tool_calls_made), and a realistic migration path from mocked Python
tools to governed MCP-sourced tools.

Launch standalone:
    python -m mcp_servers.enrichment.server
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger("mcp.enrichment")


# ── DATA LOADING ────────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROFILES_PATH = os.path.join(_HERE, "data", "profiles.json")

with open(_PROFILES_PATH) as _f:
    PROFILES: dict[str, dict[str, Any]] = json.load(_f)


# ── SERVER INSTANCE ─────────────────────────────────────────────

server: Server = Server(
    name="enrichment",
    version="0.1.0",
    instructions=(
        "Third-party company enrichment data (LexisNexis, D&B, PitchBook, "
        "FactSet). Use during underwriting triage to gather litigation "
        "history, financial stress scores, funding data, and fundamentals. "
        "Every tool takes a company_name and returns provider-native JSON."
    ),
)


# ── TOOL DEFINITIONS ────────────────────────────────────────────

_COMPANY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "company_name": {
            "type": "string",
            "description": "The legal entity name of the company to look up.",
        },
    },
    "required": ["company_name"],
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Advertise the four provider tools."""
    return [
        Tool(
            name="lexisnexis_lookup",
            description=(
                "LexisNexis Risk — returns litigation history, regulatory "
                "actions, bankruptcy filings, OFAC sanctions check, and "
                "adverse media hit count. Use for legal/regulatory risk "
                "assessment on a company name."
            ),
            inputSchema=_COMPANY_INPUT_SCHEMA,
        ),
        Tool(
            name="dnb_lookup",
            description=(
                "Dun & Bradstreet — returns DUNS number, Financial Stress "
                "Score (0-100, higher=better), Paydex score, payment "
                "performance, years in business, SIC/NAICS industry codes, "
                "verified headcount and revenue, and legal entity type. "
                "Use for financial stability + firmographic verification."
            ),
            inputSchema=_COMPANY_INPUT_SCHEMA,
        ),
        Tool(
            name="pitchbook_lookup",
            description=(
                "PitchBook — returns company type (Private/Public), industry, "
                "founding year, total funding raised, last funding round, "
                "investor list, latest valuation, and exit history. Use "
                "for growth-stage and investor profile on private companies."
            ),
            inputSchema=_COMPANY_INPUT_SCHEMA,
        ),
        Tool(
            name="factset_lookup",
            description=(
                "FactSet — returns ticker/exchange (if public), trailing "
                "twelve-month revenue, EBITDA margin, net debt to EBITDA, "
                "current ratio, credit rating with agency, and going-concern "
                "opinion flag. Use for financial fundamentals analysis."
            ),
            inputSchema=_COMPANY_INPUT_SCHEMA,
        ),
    ]


# ── TOOL DISPATCH ───────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch the named provider tool."""
    company = (arguments or {}).get("company_name", "").strip()
    if not company:
        return [TextContent(type="text", text="Error: company_name is required and must be non-empty.")]

    handlers = {
        "lexisnexis_lookup": _lookup_lexisnexis,
        "dnb_lookup": _lookup_dnb,
        "pitchbook_lookup": _lookup_pitchbook,
        "factset_lookup": _lookup_factset,
    }
    handler = handlers.get(name)
    if handler is None:
        return [TextContent(type="text", text=f"Unknown tool: {name!r}. Available: {sorted(handlers.keys())}")]

    try:
        result = handler(company)
    except Exception as e:
        logger.exception("enrichment tool %s failed for %r", name, company)
        return [TextContent(type="text", text=f"Lookup failed: {type(e).__name__}: {e}")]

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


# ── PROVIDER HANDLERS ───────────────────────────────────────────

def _lookup_lexisnexis(company: str) -> dict[str, Any]:
    """Return LexisNexis-shaped data. Curated if known, otherwise synthetic."""
    curated = _find_curated(company)
    if curated and "lexisnexis" in curated:
        return {"company_name": company, "source": "curated", **curated["lexisnexis"]}

    rng = _rng_for(company, "lexisnexis")
    # Risk score distribution: most companies are low-medium
    risk_score = rng.choices(
        ["low", "low", "low", "medium", "medium", "high"],
        k=1,
    )[0]
    n_lit = rng.randint(0, 2 if risk_score == "low" else 4)
    litigation_history = [_synthetic_lawsuit(rng, company, i) for i in range(n_lit)]
    n_reg = 0 if risk_score == "low" else rng.randint(0, 2)
    regulatory_actions = [_synthetic_reg_action(rng) for _ in range(n_reg)]

    return {
        "company_name": company,
        "source": "synthetic",
        "risk_score": risk_score,
        "litigation_history": litigation_history,
        "regulatory_actions": regulatory_actions,
        "bankruptcy_filings": [],
        "ofac_sanctions_check": "clear",
        "adverse_media_hits": rng.randint(0, 8 if risk_score == "high" else 3),
        "last_searched": "2026-04-15",
    }


def _lookup_dnb(company: str) -> dict[str, Any]:
    """Return D&B-shaped firmographics + credit data."""
    curated = _find_curated(company)
    if curated and "dnb" in curated:
        return {"company_name": company, "source": "curated", **curated["dnb"]}

    rng = _rng_for(company, "dnb")
    # Duns number: pretend it's `99-XXX-XXXX` where XXX is deterministic
    duns = f"99-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"
    stress = rng.randint(45, 90)
    years = rng.randint(3, 35)
    employees = rng.choice([15, 50, 120, 300, 800, 2500])
    revenue_ranges = [2_000_000, 10_000_000, 40_000_000, 120_000_000, 500_000_000]
    revenue = rng.choice(revenue_ranges) + rng.randint(-500_000, 500_000)

    return {
        "company_name": company,
        "source": "synthetic",
        "duns_number": duns,
        "financial_stress_score": stress,
        "paydex_score": min(100, max(40, stress + rng.randint(-8, 8))),
        "payment_performance": (
            "prompt" if stress >= 80
            else "generally_prompt" if stress >= 65
            else "slow" if stress >= 50
            else "slow_to_very_slow"
        ),
        "years_in_business": years,
        "sic_code": rng.choice(["7372", "5411", "5812", "1711", "6159", "3674"]),
        "naics_code": rng.choice(["511210", "722513", "238220", "522220"]),
        "industry": rng.choice([
            "Enterprise Software", "Industrial Machinery", "Financial Services",
            "Construction Services", "Retail Trade",
        ]),
        "employees_verified": employees,
        "annual_revenue_verified_usd": max(500_000, revenue),
        "legal_entity_type": rng.choice(["LLC", "C-Corp", "Corporation"]),
        "state_of_incorporation": rng.choice(["DE", "CA", "NY", "TX", "FL", "NV"]),
    }


def _lookup_pitchbook(company: str) -> dict[str, Any]:
    """Return PitchBook-shaped funding/investor data."""
    curated = _find_curated(company)
    if curated and "pitchbook" in curated:
        return {"company_name": company, "source": "curated", **curated["pitchbook"]}

    rng = _rng_for(company, "pitchbook")
    is_private = rng.random() > 0.2
    ever_funded = is_private and rng.random() > 0.5
    total_funding = rng.choice([None, None, 5_000_000, 25_000_000, 80_000_000, 250_000_000]) if ever_funded else None

    return {
        "company_name": company,
        "source": "synthetic",
        "company_type": "Private" if is_private else rng.choice(["Public", "Public (OTC)"]),
        "industry": rng.choice([
            "Enterprise Software", "Industrial Machinery", "Consumer Internet",
            "Financial Services", "Healthcare IT", "Construction Services",
        ]),
        "founded_year": 2026 - rng.randint(3, 40),
        "total_funding_usd": total_funding,
        "last_funding_round": (
            f"Series {rng.choice(['B', 'C', 'D'])} - {2026 - rng.randint(0, 4)}"
            if total_funding else None
        ),
        "investors": (
            rng.sample(
                ["Sequoia Capital", "Accel Partners", "Founders Fund", "a16z",
                 "Benchmark", "Lightspeed", "Tiger Global", "Insight Partners"],
                k=rng.randint(1, 3),
            ) if total_funding else []
        ),
        "latest_valuation_usd": (
            int((total_funding or 0) * rng.uniform(4, 15)) if total_funding else None
        ),
        "exits": [],
        "ipo_expected": bool(total_funding and total_funding >= 80_000_000),
    }


def _lookup_factset(company: str) -> dict[str, Any]:
    """Return FactSet-shaped financial fundamentals."""
    curated = _find_curated(company)
    if curated and "factset" in curated:
        return {"company_name": company, "source": "curated", **curated["factset"]}

    rng = _rng_for(company, "factset")
    is_public = rng.random() < 0.4
    ticker = _synthetic_ticker(rng, company) if is_public else None
    revenue = rng.choice([5_000_000, 25_000_000, 100_000_000, 500_000_000, 2_000_000_000])
    ebitda_margin = round(rng.uniform(-5.0, 28.0), 2)
    going_concern = rng.random() < 0.05

    return {
        "company_name": company,
        "source": "synthetic",
        "ticker": ticker,
        "exchange": rng.choice(["NYSE", "NASDAQ", "OTC"]) if is_public else None,
        "revenue_ttm_usd": revenue,
        "ebitda_margin_pct": ebitda_margin,
        "net_debt_to_ebitda": (
            round(rng.uniform(-1.0, 5.5), 2) if ebitda_margin > 0 else None
        ),
        "current_ratio": round(rng.uniform(0.7, 3.2), 2),
        "credit_rating_agency": rng.choice(["S&P", "Moody's", None]) if is_public else None,
        "credit_rating": _synthetic_credit_rating(rng) if is_public else None,
        "going_concern_opinion": going_concern,
    }


# ── HELPERS ─────────────────────────────────────────────────────

def _find_curated(company: str) -> dict[str, Any] | None:
    """Exact or case-insensitive substring match against curated profiles."""
    if company in PROFILES:
        return PROFILES[company]
    needle = company.lower()
    for key, value in PROFILES.items():
        if needle == key.lower() or needle in key.lower() or key.lower() in needle:
            return value
    return None


def _rng_for(company: str, provider: str) -> random.Random:
    """Deterministic PRNG seeded by company+provider.

    Same (company, provider) always yields the same random sequence, so
    a synthetic lookup returns the same data every call — useful for
    demos and audit reruns.
    """
    seed_str = f"{company.strip().lower()}::{provider}"
    seed = int(hashlib.sha256(seed_str.encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def _synthetic_lawsuit(rng: random.Random, company: str, i: int) -> dict[str, Any]:
    case_type = rng.choice([
        "breach_of_contract", "negligence", "employment_dispute",
        "ip_infringement", "product_liability",
    ])
    status = rng.choices(["settled", "dismissed", "pending"], weights=[4, 2, 3], k=1)[0]
    year = 2026 - rng.randint(0, 4)
    month = rng.randint(1, 12)
    entry = {
        "case": f"Plaintiff{i + 1} v. {company}",
        "type": case_type,
        "status": status,
        "filed": f"{year:04d}-{month:02d}-{rng.randint(1, 28):02d}",
    }
    if status == "settled":
        entry["amount_usd"] = rng.choice([25_000, 75_000, 150_000, 400_000])
    return entry


def _synthetic_reg_action(rng: random.Random) -> dict[str, Any]:
    return {
        "agency": rng.choice(["FTC", "SEC", "DOJ", "State AG", "OSHA", "EPA"]),
        "type": rng.choice(["inquiry", "citation", "consent_decree"]),
        "status": rng.choice(["open", "resolved"]),
        "severity": rng.choice(["routine", "moderate", "significant"]),
        "opened": f"{2026 - rng.randint(0, 3):04d}-{rng.randint(1, 12):02d}",
    }


def _synthetic_ticker(rng: random.Random, company: str) -> str:
    """Build a 3-4 letter ticker from the company name (deterministic)."""
    letters = "".join(c for c in company.upper() if c.isalpha())
    if len(letters) >= 4:
        return letters[:4]
    # Pad with deterministic random letters if needed
    pad = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(4 - len(letters)))
    return (letters + pad)[:4]


def _synthetic_credit_rating(rng: random.Random) -> str:
    return rng.choice(["AAA", "AA", "A", "BBB", "BB", "B", "CCC"])


# ── STDIO ENTRY POINT ───────────────────────────────────────────

async def _main() -> None:
    """Run the server over stdin/stdout for MCP stdio transport."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
