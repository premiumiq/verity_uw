"""Seed one fully-populated intake — ``uw-bop-eligibility`` — for the demo.

This seed produces:

  - A `high` AI risk tier intake with a real business case.
  - 4 requirements (1 BR, 2 FR, 1 NFR) — embedded for redundancy search.
  - A completed impact assessment (data sources, harms, mitigations,
    fairness/privacy/oversight plan).
  - 5 approval signoffs (business_owner, compliance, legal, model_risk,
    ai_governance) — drives the intake to status='approved' and triggers
    auto plan-generation.
  - 3 auto-generated plan rows from the rule-based generator (one task
    per matching FR plus the high-risk-tier validation pair).

The seed is idempotent — re-running on an existing intake returns the
existing row without modification.

Run:
    .venv/bin/python -m verity.setup.seed_intake_example
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from verity import Verity
from verity.governance.intake import IntakeService
from verity.governance.plan_generator import generate_plan
from verity.models.intake import (
    AIRiskTier,
    NAICMateriality,
    RequirementKind,
    RequirementStatus,
    StudioRole,
)


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


INTAKE_CODE = "uw-bop-eligibility"


async def _resolve_seed_application(intake_service) -> str:
    """Pick the application to attach the seed intake to.

    Prefers ``uw_demo`` (the consuming app this intake is for) when the
    business app's setup script has registered it; falls back to the
    always-seeded ``ai_ops`` governance application so the seed runs
    cleanly on a fresh dev DB.
    """
    for code in ("uw_demo", "ai_ops"):
        row = await intake_service.db.fetch_one(
            "get_application_by_name", {"app_name": code},
        )
        if row:
            return code
    raise RuntimeError(
        "Neither 'uw_demo' nor 'ai_ops' application is registered. "
        "Register one before seeding the intake example."
    )


async def seed_uw_bop_eligibility(intake_service: IntakeService) -> dict:
    """Idempotent: returns the existing intake when already seeded."""
    app_code = await _resolve_seed_application(intake_service)
    existing = await intake_service.get_intake_by_code(app_code, INTAKE_CODE)
    if existing:
        logger.info("Intake %s already exists (id=%s) — skipping seed.",
                    INTAKE_CODE, existing["id"])
        return existing

    logger.info("Seeding intake %s ...", INTAKE_CODE)

    # 1. Submit the intake (status -> proposed).
    intake = await intake_service.create_intake(
        # Owning application — every intake belongs to a registered app.
        # uw_demo is registered by the consuming app's setup; if it
        # hasn't been registered yet (e.g. fresh dev DB), fall back to
        # the always-seeded ai_ops governance application.
        application_code=app_code,
        code=INTAKE_CODE,
        title="BOP Submission Eligibility Classification",
        problem_statement=(
            "Underwriters spend ~40 minutes per submission manually "
            "checking eligibility against the BOP appetite. Most "
            "submissions are out-of-appetite or duplicate. The team "
            "needs a faster first-pass classifier so SMEs can focus "
            "their time on in-appetite, complex risks."
        ),
        expected_benefit=(
            "50% reduction in time-to-clear-or-decline; underwriter "
            "capacity reallocated to higher-value placement work; "
            "broker SLA on first-response improves from 48h to 24h."
        ),
        in_scope_decisions=(
            "- Eligibility classification (in-appetite / out-of-appetite / "
            "needs-review) for BOP submissions arriving from broker portals.\n"
            "- Appetite-rule reasoning narrative attached to each "
            "classification."
        ),
        out_of_scope_decisions=(
            "- Pricing or premium calculation.\n"
            "- Coverage form generation.\n"
            "- Final binding authority — humans always make the bind/decline "
            "decision; the AI produces a recommendation only."
        ),
        affected_populations=["applicants", "brokers", "underwriters"],
        business_owner_name="Sarah Chen",
        business_owner_email="sarah.chen@example-insurer.com",
        requesting_team="BOP Underwriting",
        ai_risk_tier=AIRiskTier.HIGH,
        risk_classification_rationale=(
            "Direct and material influence on underwriting eligibility "
            "decisions for a regulated insurance product. Falls under "
            "NAIC AI Bulletin §3 (Material AI Systems) and NYDFS "
            "Circular Letter No. 7 (AI/ECDIS in underwriting). High-risk "
            "by EU AI Act framing because it affects access to insurance "
            "products."
        ),
        naic_materiality=NAICMateriality.MATERIAL.value,
        notes=(
            "Demo intake exercising the full Phase A flow: triage, "
            "impact assessment, multi-role approvals, and rule-based "
            "plan generation."
        ),
        hitl_strategy=(
            "Every classification output is reviewed by a licensed "
            "underwriter before any bind/decline action is communicated "
            "to the broker. The AI never auto-acts on submissions; it "
            "produces a recommendation with a rationale and a "
            "confidence score. Underwriter overrides are logged with "
            "free-text reason and feed the model improvement queue. "
            "Quarterly review by Model Risk Management examines override "
            "rate; a month with override rate above 10% triggers an "
            "immediate review and possible rollback to the prior "
            "champion."
        ),
        hitl_review_threshold=(
            "Always — every output is reviewed before any business action."
        ),
        created_by="sarah.chen@example-insurer.com",
        acting_as_role=StudioRole.BUSINESS_OWNER,
    )
    intake_id = intake["id"]

    # Requirements — captured by the business owner at intake time.
    # All draft until AI Governance reviews and the multi-role chain
    # signs off. Functional requirements drive plan generation below.
    for spec in [
        {
            "code": "BR-1",
            "kind": RequirementKind.BUSINESS,
            "statement": (
                "Reduce underwriter time-on-eligibility by at least 50% "
                "without increasing decline reversals."
            ),
            "acceptance_criteria": (
                "Measured monthly: median triage minutes < 20 (baseline 40); "
                "decline-reversal rate not above current baseline +1pp."
            ),
            "source": "PRD §3.1",
        },
        {
            "code": "FR-1",
            "kind": RequirementKind.FUNCTIONAL,
            "statement": (
                "System classifies each BOP submission's eligibility against "
                "the published appetite rules and returns one of "
                "in_appetite / out_of_appetite / needs_review."
            ),
            "acceptance_criteria": (
                "F1 ≥ 0.92 against the gold-labelled validation set; "
                "rationale string ≥ 80% rated coherent by underwriter SMEs."
            ),
            "source": "PRD §4.2",
        },
        {
            "code": "FR-2",
            "kind": RequirementKind.FUNCTIONAL,
            "statement": (
                "Validate completeness of submission data (required ACORD "
                "fields present, named insured resolves) before classification."
            ),
            "acceptance_criteria": (
                "Returns a structured 'missing' list when fields fail; "
                "no false-completes against the validation set."
            ),
            "source": "PRD §4.3",
        },
        {
            "code": "NFR-1",
            "kind": RequirementKind.NON_FUNCTIONAL,
            "statement": "P95 end-to-end latency under 5 seconds.",
            "acceptance_criteria": (
                "Measured over a 7-day rolling window in production."
            ),
            "source": "PRD §6.1",
        },
        {
            "code": "CR-1",
            "kind": RequirementKind.COMPLIANCE,
            "statement": (
                "All eligibility decisions retain a complete decision log "
                "(inputs, output, rationale, model version) for 7 years."
            ),
            "acceptance_criteria": (
                "Every production invocation produces an agent_decision_log "
                "row; sample audit confirms 100% retention."
            ),
            "source": "NAIC AI Bulletin §3.1; NYDFS Cir. Letter 7 §IV.A",
        },
    ]:
        await intake_service.add_requirement(
            intake_id,
            code=spec["code"],
            kind=spec["kind"],
            statement=spec["statement"],
            acceptance_criteria=spec["acceptance_criteria"],
            source=spec["source"],
            status=RequirementStatus.DRAFT,
            created_by="sarah.chen@example-insurer.com",
            acting_as_role=StudioRole.BUSINESS_OWNER,
            embed_now=True,
        )

    # Plan rows — auto-generated from the seeded requirements so the
    # engineer view is non-empty from page load. Status=proposed; not
    # realised. Same code path runs automatically when intake is
    # approved — calling it here is idempotent (ON CONFLICT DO NOTHING).
    await generate_plan(intake_service, intake_id)

    # Seed stops here intentionally. The demo walks through:
    #   1. AI Governance triages (sets risk tier, advances state)
    #   2. Compliance + AI Governance fill the impact assessment
    #   3. The five required roles sign off on the approval request
    #   4. The intake transitions to `approved`
    #   5. Engineer realizes plan rows into registry drafts

    final = await intake_service.get_intake_by_code(app_code, INTAKE_CODE)
    plan_rows = await intake_service.list_plan_rows(final["id"])
    requirements = await intake_service.list_requirements(final["id"])
    logger.info(
        "Seeded %s in early state — status=%s, %d requirement(s), %d plan row(s). "
        "Demo walks through triage, impact assessment, approvals, and realisation.",
        INTAKE_CODE, final["status"], len(requirements), len(plan_rows),
    )
    return final


async def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "VERITY_DATABASE_URL",
            "postgresql://verityuser:veritypass123@localhost:5432/verity_db",
        ),
    )
    args = parser.parse_args()

    verity = Verity(database_url=args.database_url, anthropic_api_key="")
    await verity.connect()
    try:
        await seed_uw_bop_eligibility(verity.intake)
    finally:
        await verity.close()


if __name__ == "__main__":
    asyncio.run(_main())
