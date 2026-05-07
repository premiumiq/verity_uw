"""Rule-based artifact-plan generator.

Given an approved intake's requirements, propose the registry entities
needed to implement it. Auto-generates rows in
``governance.intake_artifact_plan`` with ``auto_generated=true``;
engineers then add, edit, remove, or realize them.

Approach (Phase A — § 6 of governance-intake.md): deterministic
keyword matching. No LLM. The choice is documented in the open-questions
section of the design doc — rule-based is safer for the demo because
plan generation runs synchronously inside the approval flow.

A Phase C task is to swap in an LLM-driven generator behind the same
``generate_plan(intake_id)`` interface.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from uuid import UUID

from verity.governance.intake import IntakeService
from verity.models.intake import (
    AIRiskTier,
    LinkedEntityKind,
    RequirementKind,
    StudioRole,
)


logger = logging.getLogger(__name__)


# ── KEYWORD → CAPABILITY MAPPING ──────────────────────────────
# Order matters: the first matching pattern wins. Patterns are
# regex word-boundary matches over the requirement statement.
#
# Specific verbs (validate / extract / summarise / generate / match)
# are listed BEFORE the broad "classification" rule. Otherwise a
# requirement like "Validate completeness ... before classification"
# would match the classify pattern at the end instead of the validate
# verb at the start.

# (regex, capability_type, agent_or_task)
# capability_type only used for tasks; for agents it stays None.
_CAPABILITY_RULES: list[tuple[str, Optional[str], LinkedEntityKind]] = [
    # Multi-step / orchestration / decision verbs propose an agent.
    (r"\borchestrat", None, LinkedEntityKind.AGENT),
    (r"\bdecide\b|\bdecision\b", None, LinkedEntityKind.AGENT),
    (r"\bplan\b|\bworkflow\b", None, LinkedEntityKind.AGENT),
    (r"\binvestigat", None, LinkedEntityKind.AGENT),

    # Specific task verbs first.
    (r"\bvalidat|\bverif|\bcheck\b", "validation", LinkedEntityKind.TASK),
    (r"\bextract|\bparse\b|\bpull (?:fields|data)", "extraction", LinkedEntityKind.TASK),
    (r"\bsummar(?:ize|ise)\b|\bcondens", "summarisation", LinkedEntityKind.TASK),
    (r"\bgenerat|\bdraft\b|\bwrite\b|\bcompose\b", "generation", LinkedEntityKind.TASK),
    (r"\bmatch|\bdedup|\bresolve\b", "matching", LinkedEntityKind.TASK),
    # Catch-all classification last (broad keyword family).
    (r"\bclassif|\bcategor|\blabel\b|\bscore\b", "classification", LinkedEntityKind.TASK),
]


# Suffix that turns a description into a task identifier. Maps
# capability_type to a noun-form action, mirroring how registry
# names already read in this codebase (eligibility_classifier,
# document_classifier, etc.).
_CAPABILITY_SUFFIX: dict[str, str] = {
    "classification": "classifier",
    "extraction":     "extractor",
    "summarisation":  "summarizer",
    "generation":     "generator",
    "matching":       "matcher",
    "validation":     "validator",
}


# Words to drop when deriving a name from a requirement statement.
# Lowercase. Includes generic articles/conjunctions plus the action
# verbs that are already encoded as the capability suffix (so we
# don't double up "validate" + "validator").
_NAME_STOPWORDS: set[str] = {
    # articles / conjunctions / prepositions
    "a", "an", "the", "of", "to", "for", "and", "or", "in", "on",
    "at", "by", "with", "from", "into", "over", "per", "via",
    "as", "if", "than", "this", "that", "these", "those", "its",
    "it", "be", "is", "are", "was", "were", "been", "being",
    "must", "should", "shall", "will", "can", "may",
    "each", "every", "any", "all", "some", "one", "ones",
    "before", "after", "during", "between", "under", "above",
    "no", "not", "only",
    # filler / generic
    "system", "platform", "service", "data", "use", "case", "cases",
    "based", "required", "named", "against", "given", "such",
    "either", "etc", "set", "list", "value", "values", "kind", "kinds",
    "type", "types", "way", "ways", "manner", "form", "forms",
    # verbs already encoded as capability suffixes
    "classify", "classifies", "classified", "classifying",
    "categorize", "categorizes", "label", "labels",
    "score", "scores",
    "extract", "extracts", "extracted", "parse", "parses", "pull",
    "summarize", "summarizes", "summarise", "summarises",
    "condense", "condenses",
    "generate", "generates", "generated", "draft", "drafts",
    "write", "writes", "compose", "composes",
    "match", "matches", "dedup", "deduplicate",
    "resolve", "resolves",
    "validate", "validates", "validated", "verify", "verifies",
    "check", "checks",
    "decide", "decides", "decision",
    "plan", "plans", "workflow", "investigate", "investigates",
    "orchestrate", "orchestrates",
}


# ── MATERIALITY MAPPING ───────────────────────────────────────
# Intake risk tier -> default materiality_tier on the auto-generated
# registry entity. Engineers can override per row in Studio.

_MATERIALITY_BY_TIER: dict[str, str] = {
    AIRiskTier.HIGH.value: "high",
    AIRiskTier.LIMITED.value: "medium",
    AIRiskTier.MINIMAL.value: "low",
    # 'unacceptable' never reaches this code path (rejected at triage).
}


def _depluralize(word: str) -> str:
    """De-pluralize a word for the purpose of dedup'ing keyword lists.

    Cheap rules — not real lemmatization — but enough to keep
    "submissions" and "submission" from both showing up in a name.

    Preserves words that aren't actually plural:
      - shorter than 5 chars (avoid "loss" → "los")
      - ending in -ss / -us / -is (loss, focus, basis stay as-is)

    Handles -ies → -y (policies → policy) and -s → '' (rules → rule).
    """
    if len(word) <= 3:
        return word
    if word.endswith(("ss", "us", "is")):
        return word
    if not word.endswith("s"):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    return word[:-1]


def _propose_kind_for_statement(
    statement: str,
) -> tuple[LinkedEntityKind, Optional[str]]:
    """Return (LinkedEntityKind, capability_type-or-None) for a requirement."""
    text = statement.lower()
    for pattern, capability, kind in _CAPABILITY_RULES:
        if re.search(pattern, text):
            return kind, capability
    # No match → propose nothing; caller skips.
    return None, None  # type: ignore[return-value]


def _derive_artifact_name(
    statement: str,
    capability: Optional[str],
    kind: LinkedEntityKind,
    *,
    max_keywords: int = 3,
) -> str:
    """Derive a short, intent-revealing artifact name from a requirement.

    Pattern: ``{key-noun-1}-{key-noun-2}-{...}-{action-suffix}``

    - Action verbs and stopwords drop out (they're encoded by the
      action-suffix or are uninformative).
    - The first ``max_keywords`` non-stopword tokens become the noun
      stem so the name reads like an existing registry name
      (e.g. ``eligibility_classifier``, ``document_classifier``).
    - Tasks pick up a capability-specific suffix from
      ``_CAPABILITY_SUFFIX``; agents get ``-agent``; other kinds
      (test_suite, ground_truth_dataset) use bare keyword stems.

    Examples:
        statement = "Validate completeness of submission data..."
        capability = "validation", kind = TASK
        → "completeness-submission-data-validator"

        statement = "Underwriter decides eligibility..."
        capability = None, kind = AGENT
        → "underwriter-eligibility-agent"
    """
    # Lowercase, strip apostrophes first (so "submission's" → "submissions"
    # rather than "submission s"), then strip remaining punctuation
    # to spaces. Drop single-character tokens (stray "s" left over from
    # contractions, list-item bullets, etc.).
    text = statement.lower()
    text = re.sub(r"['’‘]", "", text)
    text = re.sub(r"[^a-z0-9\s-]+", " ", text)
    tokens = [t for t in text.split() if len(t) > 1]

    # Filter stopwords (against the original form — the stopword list
    # contains both "classify" and "classifies"). Deduplicate by a
    # de-pluralized form so "submissions" and "submission" don't both
    # contribute. Preserve order.
    seen: set[str] = set()
    keywords: list[str] = []
    for tok in tokens:
        if tok in _NAME_STOPWORDS:
            continue
        sing = _depluralize(tok)
        if sing in seen:
            continue
        seen.add(sing)
        keywords.append(sing)
        if len(keywords) >= max_keywords:
            break

    base = "-".join(keywords) or "task"
    if capability and capability in _CAPABILITY_SUFFIX:
        return f"{base}-{_CAPABILITY_SUFFIX[capability]}"
    if kind == LinkedEntityKind.AGENT:
        return f"{base}-agent"
    return base


async def generate_plan(
    intake_service: IntakeService,
    intake_id: UUID,
    *,
    created_by: str = "system:plan_generator",
    acting_as_role: Optional[StudioRole] = StudioRole.AI_GOVERNANCE,
) -> list[dict]:
    """Generate plan rows for an intake's requirements.

    - Iterates functional requirements; proposes an agent or task per
      matched verb pattern.
    - For high-risk intakes, also proposes a ground_truth_dataset and
      a test_suite once (intake-level, requirement_id NULL).
    - Existing plan rows are not duplicated (handled by the SQL
      ON CONFLICT).

    Returns the list of newly created plan rows. Empty list when nothing
    matched (e.g. only business / non-functional reqs).
    """
    intake = await intake_service.get_intake_by_id(intake_id)
    if not intake:
        raise ValueError(f"Intake {intake_id} not found")

    if intake["ai_risk_tier"] == AIRiskTier.UNACCEPTABLE.value:
        # Defensive: never auto-generate plan for prohibited use cases.
        return []

    materiality = _MATERIALITY_BY_TIER.get(intake["ai_risk_tier"], "medium")

    requirements = await intake_service.list_requirements(intake_id)
    intake_code = intake["code"]
    created_rows: list[dict] = []

    for req in requirements:
        if req["kind"] != RequirementKind.FUNCTIONAL.value:
            continue
        kind, capability = _propose_kind_for_statement(req["statement"])
        if kind is None:
            logger.info(
                "plan_generator: no rule matched req %s (%s) — skipped",
                req["code"], intake_code,
            )
            continue

        # Name describes WHAT the artifact does (action verb + key
        # nouns), not which requirement drove it. Reads like the
        # existing registry names (eligibility_classifier, etc.).
        proposed_name = _derive_artifact_name(req["statement"], capability, kind)
        display = req["statement"][:120]
        purpose = (
            f"Implements {req['code']} for intake {intake_code}: "
            f"{req['statement']}"
        )

        row = await intake_service.add_plan_row(
            intake_id,
            proposed_kind=kind,
            proposed_name=proposed_name,
            proposed_display_name=display,
            proposed_description=req.get("acceptance_criteria") or req["statement"],
            proposed_purpose=purpose,
            proposed_capability_type=capability,
            proposed_materiality_tier=materiality,
            requirement_id=req["id"],
            auto_generated=True,
            created_by=created_by,
            acting_as_role=acting_as_role,
        )
        if row:
            created_rows.append(row)

    # Phase B: also propose ground-truth + test_suite for high-risk
    # intakes. We do this even when no functional req matched, because
    # high-risk intakes always need validation infrastructure.
    if intake["ai_risk_tier"] == AIRiskTier.HIGH.value:
        # Stem comes from intake title — same naming convention as
        # task names above (no intake_code prefix; the engineer can
        # rename freely on realisation).
        stem = _derive_artifact_name(
            intake.get("title") or intake_code,
            capability=None,
            kind=LinkedEntityKind.TEST_SUITE,
            max_keywords=2,
        )
        for kind, suffix, display in [
            (LinkedEntityKind.GROUND_TRUTH_DATASET, "ground-truth",
             "Ground-truth dataset for production validation"),
            (LinkedEntityKind.TEST_SUITE, "tests",
             "Integration test suite"),
        ]:
            row = await intake_service.add_plan_row(
                intake_id,
                proposed_kind=kind,
                proposed_name=f"{stem}-{suffix}",
                proposed_display_name=display,
                proposed_description=(
                    f"Auto-proposed for high-risk intake {intake_code}; "
                    f"engineer to flesh out coverage."
                ),
                proposed_purpose=display,
                proposed_capability_type=None,
                proposed_materiality_tier=materiality,
                requirement_id=None,
                auto_generated=True,
                created_by=created_by,
                acting_as_role=acting_as_role,
            )
            if row:
                created_rows.append(row)

    return created_rows
