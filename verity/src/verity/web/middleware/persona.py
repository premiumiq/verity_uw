"""Persona middleware — session-scoped Studio role.

The demo has no real auth. Instead, every Studio user picks a persona
from a switcher in the nav (the 10 ``StudioRole`` values). The chosen
persona is stored in a session cookie and read here on every request.
Templates and route handlers branch on it for nav tailoring; write
paths capture it as ``acting_as_role`` for audit.

When real auth lands (Phase C), this module becomes the only place
that needs to change — replace cookie-read with a real identity-to-role
lookup and the rest of the codebase is unaffected.

Exports:
  - PersonaMiddleware  — Starlette middleware
  - get_persona(request) -> StudioRole | None
  - persona_cookie_response(role)  — sets the cookie on a Response
  - PERSONA_COOKIE_NAME
  - DEFAULT_PERSONA  — viewer (least-privileged read-only)
  - role_actions     — mapping persona -> set of allowed action codes
  - is_action_allowed(role, action)
"""

from __future__ import annotations

from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from verity.models.intake import StudioRole


# Cookie name for the persona. Short prefix because lots of cookies
# under /studio/ may sit alongside it later.
PERSONA_COOKIE_NAME = "vty_persona"

# Until the user picks one, treat them as a read-only viewer. Choosing
# an authoritative default is safer than guessing they're an engineer.
DEFAULT_PERSONA = StudioRole.VIEWER


# ── ROLE × ACTION MATRIX ──────────────────────────────────────
# Action codes used across Studio + API to gate writes. Keep them
# stable strings — Studio templates check membership, the API gates
# call ``is_action_allowed(role, action)`` before executing a write.

# Action vocabulary (matches docs/architecture/governance-intake.md § 5.2):
ACTION_CREATE_INTAKE = "create_intake"
ACTION_EDIT_INTAKE = "edit_intake"
ACTION_TRIAGE_INTAKE = "triage_intake"
ACTION_RECLASSIFY_RISK = "reclassify_risk"
ACTION_EDIT_REQUIREMENT = "edit_requirement"
ACTION_EDIT_IMPACT_ASSESSMENT = "edit_impact_assessment"
ACTION_SIGNOFF = "signoff"
ACTION_WITHDRAW_APPROVAL = "withdraw_approval"
ACTION_GENERATE_PLAN = "generate_plan"
ACTION_EDIT_PLAN = "edit_plan"
ACTION_REALIZE_PLAN = "realize_plan"
ACTION_AUTHOR_REGISTRY = "author_registry"
ACTION_PROMOTE_REGISTRY = "promote_registry"
ACTION_VIEW = "view"
ACTION_EXPORT_YAML = "export_yaml"
ACTION_IMPORT_YAML = "import_yaml"
ACTION_VIEW_REPORTS = "view_reports"


# Action -> roles allowed. Mirrors § 5.2 of the design doc. Anyone
# (every persona) gets ACTION_VIEW. ACTION_EXPORT_YAML excludes only
# ``viewer`` per the matrix.
_ACTION_ROLES: dict[str, set[StudioRole]] = {
    ACTION_CREATE_INTAKE: {
        StudioRole.BUSINESS_OWNER, StudioRole.AI_GOVERNANCE,
    },
    ACTION_EDIT_INTAKE: {
        StudioRole.BUSINESS_OWNER, StudioRole.AI_GOVERNANCE,
    },
    ACTION_TRIAGE_INTAKE: {StudioRole.AI_GOVERNANCE},
    ACTION_RECLASSIFY_RISK: {StudioRole.AI_GOVERNANCE},
    ACTION_EDIT_REQUIREMENT: {
        StudioRole.BUSINESS_OWNER, StudioRole.AI_GOVERNANCE, StudioRole.ENGINEER,
    },
    ACTION_EDIT_IMPACT_ASSESSMENT: {
        StudioRole.COMPLIANCE, StudioRole.MODEL_RISK,
        StudioRole.AI_GOVERNANCE, StudioRole.SECURITY, StudioRole.PRIVACY,
    },
    ACTION_SIGNOFF: {
        StudioRole.BUSINESS_OWNER, StudioRole.COMPLIANCE, StudioRole.LEGAL,
        StudioRole.MODEL_RISK, StudioRole.AI_GOVERNANCE,
        StudioRole.SECURITY, StudioRole.PRIVACY,
    },
    ACTION_WITHDRAW_APPROVAL: {
        StudioRole.BUSINESS_OWNER, StudioRole.COMPLIANCE, StudioRole.LEGAL,
        StudioRole.MODEL_RISK, StudioRole.AI_GOVERNANCE,
    },
    ACTION_GENERATE_PLAN: {StudioRole.AI_GOVERNANCE},
    ACTION_EDIT_PLAN: {StudioRole.AI_GOVERNANCE, StudioRole.ENGINEER},
    ACTION_REALIZE_PLAN: {StudioRole.ENGINEER},
    ACTION_AUTHOR_REGISTRY: {StudioRole.ENGINEER},
    ACTION_PROMOTE_REGISTRY: {StudioRole.AI_GOVERNANCE},
    ACTION_VIEW: set(StudioRole),
    ACTION_EXPORT_YAML: set(StudioRole) - {StudioRole.VIEWER},
    ACTION_IMPORT_YAML: {StudioRole.AI_GOVERNANCE, StudioRole.ENGINEER},
    ACTION_VIEW_REPORTS: set(StudioRole) - {StudioRole.ENGINEER, StudioRole.VIEWER},
}


def is_action_allowed(role: Optional[StudioRole], action: str) -> bool:
    """Return True when ``role`` is allowed to perform ``action``.

    None role (no persona selected) defaults to DEFAULT_PERSONA.
    Unknown actions return False — fail closed.
    """
    effective = role or DEFAULT_PERSONA
    allowed = _ACTION_ROLES.get(action)
    if allowed is None:
        return False
    return effective in allowed


# ── PROFILE-PAGE METADATA ─────────────────────────────────────
# Human-readable strings for the profile page and role help popup.
# Keeping these alongside the action constants means new actions
# always come with a label; the profile UI stays self-describing.

ACTION_LABELS: dict[str, str] = {
    ACTION_CREATE_INTAKE:          "Create intake",
    ACTION_EDIT_INTAKE:            "Edit intake",
    ACTION_TRIAGE_INTAKE:          "Triage intake (set risk tier)",
    ACTION_RECLASSIFY_RISK:        "Reclassify risk tier",
    ACTION_EDIT_REQUIREMENT:       "Edit requirements",
    ACTION_EDIT_IMPACT_ASSESSMENT: "Edit impact assessment",
    ACTION_SIGNOFF:                "Sign off on approval",
    ACTION_WITHDRAW_APPROVAL:      "Withdraw approval",
    ACTION_GENERATE_PLAN:          "Auto-generate artifact plan",
    ACTION_EDIT_PLAN:              "Edit plan rows",
    ACTION_REALIZE_PLAN:           "Realize plan → registry draft",
    ACTION_AUTHOR_REGISTRY:        "Author agent / task / prompt",
    ACTION_PROMOTE_REGISTRY:       "Promote registry artifact",
    ACTION_VIEW:                   "View intakes / requirements / plans",
    ACTION_EXPORT_YAML:            "Export YAML",
    ACTION_IMPORT_YAML:            "Import YAML",
    ACTION_VIEW_REPORTS:           "View compliance reports",
}

# Stable display order for the matrix (groups related actions). The
# profile page and role-help modal both iterate this — never the dict
# key order — so column / row layout is predictable.
ACTION_ORDER: list[str] = [
    ACTION_CREATE_INTAKE,
    ACTION_EDIT_INTAKE,
    ACTION_TRIAGE_INTAKE,
    ACTION_RECLASSIFY_RISK,
    ACTION_EDIT_REQUIREMENT,
    ACTION_EDIT_IMPACT_ASSESSMENT,
    ACTION_SIGNOFF,
    ACTION_WITHDRAW_APPROVAL,
    ACTION_GENERATE_PLAN,
    ACTION_EDIT_PLAN,
    ACTION_REALIZE_PLAN,
    ACTION_AUTHOR_REGISTRY,
    ACTION_PROMOTE_REGISTRY,
    ACTION_VIEW,
    ACTION_EXPORT_YAML,
    ACTION_IMPORT_YAML,
    ACTION_VIEW_REPORTS,
]

# One-sentence role purpose. Lifted from the design doc so the help
# popup explains *what each role is for*, not just what it can do.
ROLE_DESCRIPTIONS: dict[StudioRole, str] = {
    StudioRole.BUSINESS_OWNER:
        "Sponsors a use case. Submits the intake; signs off as the "
        "requesting business; owns the success criteria.",
    StudioRole.AI_GOVERNANCE:
        "Triages intakes, sets the risk tier, runs plan generation, "
        "and gates promotions. The accountable owner of the AI program.",
    StudioRole.COMPLIANCE:
        "Reviews use cases against regulatory obligations. Co-owns "
        "the impact assessment; required signoff on limited+ tiers.",
    StudioRole.LEGAL:
        "Reviews legal exposure. Required signoff on high-risk intakes.",
    StudioRole.MODEL_RISK:
        "Reviews validation, drift, and recertification. Co-owns "
        "the impact assessment; required signoff on high-risk intakes.",
    StudioRole.SECURITY:
        "Reviews data classification and access. Co-owns the impact "
        "assessment; signoff is optional unless the intake involves "
        "sensitive data.",
    StudioRole.PRIVACY:
        "Reviews PII and consent posture. Co-owns the impact "
        "assessment; signoff is optional unless the intake involves "
        "personal data.",
    StudioRole.ENGINEER:
        "Builds the agents, tasks, prompts, and tools. Realizes plan "
        "rows into registry drafts and develops them through the "
        "lifecycle.",
    StudioRole.AUDITOR:
        "Read-only across all artifacts including compliance reports. "
        "Cannot author, edit, or sign off.",
    StudioRole.VIEWER:
        "Read-only default for an unauthenticated session. Can view "
        "intakes and registry artifacts but cannot export, import, or "
        "modify anything.",
}


def actions_allowed_for(role: Optional[StudioRole]) -> list[str]:
    """Return the ordered list of action codes ``role`` can perform.

    Order matches ACTION_ORDER so the profile UI is stable.
    """
    effective = role or DEFAULT_PERSONA
    return [
        a for a in ACTION_ORDER
        if effective in _ACTION_ROLES.get(a, set())
    ]


def role_action_matrix() -> list[tuple[str, str, dict[StudioRole, bool]]]:
    """Return rows for the role × action matrix as a list of tuples.

    Each tuple is ``(action_code, action_label, {role: bool})``.
    Used by the role-help popup to render the same matrix shown in
    the design doc, sourced from a single truth (``_ACTION_ROLES``).
    """
    rows: list[tuple[str, str, dict[StudioRole, bool]]] = []
    for action in ACTION_ORDER:
        allowed = _ACTION_ROLES.get(action, set())
        rows.append((
            action,
            ACTION_LABELS.get(action, action),
            {role: (role in allowed) for role in StudioRole},
        ))
    return rows


def get_persona(request: Request) -> Optional[StudioRole]:
    """Read the current persona off the request.

    The middleware below stores it on ``request.state.persona``;
    this helper just provides a typed accessor so route handlers
    don't need to know how it was set.
    """
    return getattr(request.state, "persona", None)


def persona_cookie_response(response: Response, role: StudioRole) -> Response:
    """Attach the persona cookie to a response.

    The cookie is HttpOnly and lasts 30 days. SameSite=Lax so navigation
    from the Admin app preserves the persona.
    """
    response.set_cookie(
        key=PERSONA_COOKIE_NAME,
        value=role.value,
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


class PersonaMiddleware(BaseHTTPMiddleware):
    """Read the persona cookie and stash the parsed StudioRole on request.state.

    Mounted on the Studio sub-app. The Admin sub-app and the JSON API
    don't (yet) consult personas, so they don't need this middleware.

    The cookie value is whitelisted against the StudioRole enum;
    anything unknown reverts silently to DEFAULT_PERSONA.
    """

    async def dispatch(self, request: Request, call_next):
        raw = request.cookies.get(PERSONA_COOKIE_NAME)
        try:
            request.state.persona = StudioRole(raw) if raw else DEFAULT_PERSONA
        except ValueError:
            # Unknown / tampered value — fail closed to viewer.
            request.state.persona = DEFAULT_PERSONA
        return await call_next(request)
