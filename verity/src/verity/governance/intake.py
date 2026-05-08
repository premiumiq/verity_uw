"""IntakeService — the governance intake layer.

Operates on the seven new tables defined in
``verity/src/verity/db/schema_intake.sql``:

  - intake                  -- the business-approved AI use case header
  - intake_impact_assessment-- required for risk tier in (limited, high)
  - intake_requirement      -- BR/FR/NFR/compliance reqs (with embeddings)
  - intake_entity_link      -- bridge to agents/tasks/prompts/tools
  - intake_artifact_plan    -- proposed registry entities to build
  - approval_request        -- per gating event (intake / promote / retire)
  - approval_signoff        -- one row per role per request

This service is intentionally a thin wrapper over the named queries in
``intake.sql`` plus a handful of higher-level workflows
(triage_intake, signoff, check_promotion_gate). All write paths capture
``acting_as_role`` for audit. See docs/architecture/governance-intake.md
for the full contract.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from verity.db.connection import Database
from verity.models.intake import (
    AIRiskTier,
    ApprovalDecision,
    ApprovalRequestKind,
    ApprovalRole,
    ArtifactPlanStatus,
    IntakeStatus,
    LinkedEntityKind,
    PromotionGateResult,
    REQUIRED_ROLES_BY_RISK_TIER,
    RequirementKind,
    RequirementRelationship,
    RequirementStatus,
    StudioRole,
)


logger = logging.getLogger(__name__)


# ── EMBEDDING PROVIDER (lazy import) ───────────────────────────
# fastembed is a moderately heavy import (ONNX runtime). Defer it
# until a caller actually requests an embedding so unit tests of the
# rest of IntakeService don't pay the cost.

_EMBEDDER = None


def _get_embedder():
    """Lazily load the BGE-small embedder used for intake_requirement."""
    global _EMBEDDER
    if _EMBEDDER is None:
        # Imported inline so a missing fastembed install only breaks
        # embedding-dependent flows, not the rest of the service.
        from fastembed import TextEmbedding

        _EMBEDDER = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _EMBEDDER


def _embed_text(text: str) -> list[float]:
    """Embed a single string into a 384-dim float list.

    Returns an empty list when the input is blank — callers should
    treat that as "no embedding".
    """
    if not text or not text.strip():
        return []
    embedder = _get_embedder()
    # fastembed yields generators; we want one vector per call.
    vectors = list(embedder.embed([text]))
    if not vectors:
        return []
    return [float(x) for x in vectors[0]]


def _embedding_input(statement: str, acceptance_criteria: Optional[str]) -> str:
    """The text we feed into the embedder for a requirement."""
    if acceptance_criteria:
        return f"{statement}\n\n{acceptance_criteria}"
    return statement


def _hash_input(text: str) -> bytes:
    """SHA-256 of the embedder input — staleness sentinel."""
    return hashlib.sha256(text.encode("utf-8")).digest()


def _vec_to_pgvector_literal(vec: list[float]) -> str:
    """Format a list[float] as a pgvector input literal: '[0.1,0.2,...]'.

    psycopg passes this string through; pgvector parses it.
    """
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


def _to_str(value: Any) -> Optional[str]:
    """Coerce UUIDs / Enums / None to plain strings for SQL params."""
    if value is None:
        return None
    if hasattr(value, "value") and hasattr(value, "name"):  # Enum
        return value.value
    return str(value)


def _json_param(value: Any) -> str:
    """Serialise a Python value to JSON for a JSONB column."""
    return json.dumps(value)


# ── SERVICE ────────────────────────────────────────────────────


class IntakeService:
    """Business-process layer above the registry.

    Constructed alongside Registry / Lifecycle inside the Verity SDK
    and exposed as ``verity.intake``.
    """

    def __init__(self, db: Database):
        self.db = db

    # ── INTAKE CRUD ────────────────────────────────────────────

    @staticmethod
    def _slugify_title(title: str) -> str:
        """Derive a URL/YAML-friendly slug from an intake title.

        Business owners type free-form titles ("BOP Submission Eligibility
        Classification"); the slug ("bop-submission-eligibility-classification")
        is what shows up in URLs and YAML exports. Capped at 80 chars so
        the column constraint (varchar 120) is comfortably under-utilised.
        """
        s = title.lower()
        s = re.sub(r"['’‘]", "", s)
        s = re.sub(r"[^a-z0-9\s-]+", " ", s)
        s = re.sub(r"\s+", "-", s.strip())
        s = re.sub(r"-+", "-", s).strip("-")
        return s[:80] or "intake"

    async def _next_unique_code(
        self, base: str, *, application_id: str, max_attempts: int = 50,
    ) -> str:
        """Return ``base`` if free WITHIN the given application, otherwise
        ``base-2``, ``base-3``, ... .

        The DB's composite UNIQUE (application_id, code) is the actual
        guard against duplicates — this helper is the ergonomic probe
        that picks a free suffix before insert. Both probe and insert
        share the same transaction in ``create_intake``; if a concurrent
        creator wins the race, the INSERT raises UniqueViolation and
        the surrounding retry loop bumps to the next candidate.
        """
        candidate = base
        for n in range(2, max_attempts + 2):
            row = await self.db.fetch_one(
                "probe_intake_code_in_app",
                {"application_id": application_id, "code": candidate},
            )
            if not row:
                return candidate
            candidate = f"{base}-{n}"
        raise RuntimeError(
            f"Could not find a unique intake code for base '{base}' "
            f"in application {application_id} after {max_attempts} attempts."
        )

    async def create_intake(
        self,
        *,
        code: Optional[str] = None,
        title: str,
        problem_statement: str,
        expected_benefit: str,
        business_owner_name: str,
        created_by: str,
        # Owning application is REQUIRED. Pass either application_code
        # (preferred — resolved against governance.application by name)
        # or application_id directly. ValueError if neither resolves.
        application_code: Optional[str] = None,
        application_id: Optional[UUID] = None,
        in_scope_decisions: Optional[str] = None,
        out_of_scope_decisions: Optional[str] = None,
        affected_populations: Optional[list[str]] = None,
        business_owner_email: Optional[str] = None,
        requesting_team: Optional[str] = None,
        ai_risk_tier: AIRiskTier = AIRiskTier.LIMITED,
        risk_classification_rationale: str = "(pending triage)",
        naic_materiality: str = "non_material",
        notes: Optional[str] = None,
        acting_as_role: Optional[StudioRole] = None,
        hitl_strategy: Optional[str] = None,
        hitl_review_threshold: Optional[str] = None,
    ) -> dict:
        """Create a new intake (status='proposed').

        Auto-opens the kind='intake' approval request with
        required_roles=[business_owner, ai_governance] so the triage /
        approval flow has somewhere to land.
        """
        # Resolve the owning application. Code path preferred for ergonomics;
        # passing an explicit application_id skips the lookup.
        resolved_app_id: Optional[str] = None
        if application_id is not None:
            resolved_app_id = str(application_id)
        elif application_code:
            app_row = await self.db.fetch_one(
                "get_application_by_name", {"app_name": application_code},
            )
            if not app_row:
                raise ValueError(
                    f"Application '{application_code}' is not registered. "
                    f"Register it before submitting intakes for it."
                )
            resolved_app_id = str(app_row["id"])
        else:
            raise ValueError(
                "create_intake requires application_code or application_id."
            )

        # Code is auto-derived from title when not supplied — business
        # users typing free-form titles get a stable URL slug without
        # having to invent one. Collisions get a numeric suffix WITHIN
        # the owning application (UNIQUE is (application_id, code)).
        if not code:
            code = await self._next_unique_code(
                self._slugify_title(title),
                application_id=resolved_app_id,
            )

        params = {
            "application_id": resolved_app_id,
            "code": code,
            "title": title,
            "problem_statement": problem_statement,
            "expected_benefit": expected_benefit,
            "in_scope_decisions": in_scope_decisions,
            "out_of_scope_decisions": out_of_scope_decisions,
            "affected_populations": _json_param(affected_populations or []),
            "business_owner_name": business_owner_name,
            "business_owner_email": business_owner_email,
            "requesting_team": requesting_team,
            "ai_risk_tier": _to_str(ai_risk_tier),
            "risk_classification_rationale": risk_classification_rationale,
            "naic_materiality": naic_materiality,
            "status": IntakeStatus.PROPOSED.value,
            "created_by": created_by,
            "acting_as_role": _to_str(acting_as_role),
            "notes": notes,
            "hitl_strategy": hitl_strategy,
            "hitl_review_threshold": hitl_review_threshold,
        }
        async with self.db.transaction() as tx:
            row = await tx.execute_returning("insert_intake", params)
            if not row:
                raise RuntimeError("insert_intake returned no row")

            # Open the kind='intake' approval request alongside.
            initial_roles = [
                ApprovalRole.BUSINESS_OWNER.value,
                ApprovalRole.AI_GOVERNANCE.value,
            ]
            await tx.execute_returning(
                "insert_approval_request",
                {
                    "intake_id": str(row["id"]),
                    "kind": ApprovalRequestKind.INTAKE.value,
                    "target_entity_type": None,
                    "target_entity_id": None,
                    "required_roles": _json_param(initial_roles),
                    "opened_by": created_by,
                    "opened_by_role": _to_str(acting_as_role),
                    "summary": f"Intake approval for '{code}'",
                    "notes": None,
                },
            )
        return row

    async def get_intake_by_code(
        self, application_code: str, code: str,
    ) -> Optional[dict]:
        """Resolve an intake by its (application_code, code) natural key.

        Path-scoped lookup — both segments are required because two
        applications may each have their own intake with the same code
        slug. Returns None when no row matches; callers turn None into
        404 at the API layer.
        """
        return await self.db.fetch_one(
            "get_intake_by_code",
            {"application_code": application_code, "code": code},
        )

    async def get_intake_by_id(self, intake_id) -> Optional[dict]:
        return await self.db.fetch_one("get_intake_by_id", {"id": str(intake_id)})

    async def list_intakes(
        self,
        *,
        status: Optional[IntakeStatus] = None,
        ai_risk_tier: Optional[AIRiskTier] = None,
        business_owner_email: Optional[str] = None,
        application_code: Optional[str] = None,
    ) -> list[dict]:
        if (
            status is None
            and ai_risk_tier is None
            and business_owner_email is None
            and application_code is None
        ):
            return await self.db.fetch_all("list_intakes")
        return await self.db.fetch_all(
            "list_intakes_filtered",
            {
                "status": _to_str(status),
                "ai_risk_tier": _to_str(ai_risk_tier),
                "business_owner_email": business_owner_email,
                "application_code": application_code,
            },
        )

    async def update_intake(
        self, intake_id, **fields,
    ) -> Optional[dict]:
        """Update mutable fields on an intake. None = leave unchanged."""
        params: dict[str, Any] = {"id": str(intake_id)}
        # Pre-fill all COALESCE keys with None so missing kwargs become NULL.
        for key in (
            "title", "problem_statement", "expected_benefit",
            "in_scope_decisions", "out_of_scope_decisions",
            "business_owner_name", "business_owner_email",
            "requesting_team", "notes",
            "hitl_strategy", "hitl_review_threshold",
        ):
            params[key] = fields.get(key)
        ap = fields.get("affected_populations")
        params["affected_populations"] = _json_param(ap) if ap is not None else None
        return await self.db.execute_returning("update_intake_mutable", params)

    # ── TRIAGE / RISK CLASSIFICATION ───────────────────────────

    async def triage_intake(
        self,
        intake_id,
        *,
        ai_risk_tier: AIRiskTier,
        naic_materiality: str,
        risk_classification_rationale: str,
        acting_as_role: Optional[StudioRole] = None,
    ) -> dict:
        """Set risk tier + materiality and advance the intake.

        Side-effects:
          - Status moves to 'in_review' (or 'impact_assessment' if tier
            is limited/high).
          - The open intake-approval request's required_roles is updated
            to match the tier (§ 4.2 of governance-intake.md).
          - 'unacceptable' tier rejects the intake.
        """
        # Apply DB-level transition first; the SQL handles the simple
        # status moves. Approval-request bookkeeping happens after.
        async with self.db.transaction() as tx:
            row = await tx.execute_returning(
                "triage_intake",
                {
                    "id": str(intake_id),
                    "ai_risk_tier": ai_risk_tier.value,
                    "naic_materiality": naic_materiality,
                    "risk_classification_rationale": risk_classification_rationale,
                },
            )
            if not row:
                raise ValueError(f"Intake {intake_id} not found")

            # If unacceptable, reject and stop.
            if ai_risk_tier == AIRiskTier.UNACCEPTABLE:
                rejected = await tx.execute_returning(
                    "reject_intake",
                    {
                        "id": str(intake_id),
                        "notes": (
                            "Auto-rejected: AI risk tier 'unacceptable' under "
                            "EU AI Act framing — prohibited use case."
                        ),
                    },
                )
                return rejected or row

            # Otherwise, refresh the open intake-approval request's required_roles
            # to match the new tier. We update the most recent open request.
            open_reqs = await tx.fetch_all(
                "list_open_intake_approvals",
                {"intake_id": str(intake_id)},
            )
            if open_reqs:
                # Tier -> required roles mapping centralised in the model layer.
                required = REQUIRED_ROLES_BY_RISK_TIER.get(ai_risk_tier, [])
                role_values = [r.value for r in required]
                # Update each open intake-approval to broaden its roles.
                for req in open_reqs:
                    await tx.execute_returning(
                        "update_approval_request_required_roles",
                        {
                            "required_roles": _json_param(role_values),
                            "id": str(req["id"]),
                        },
                    )
        return row

    async def reject_intake(
        self, intake_id, *, notes: Optional[str] = None,
    ) -> dict:
        return await self.db.execute_returning(
            "reject_intake", {"id": str(intake_id), "notes": notes},
        ) or {}

    async def retire_intake(self, intake_id) -> Optional[dict]:
        return await self.db.execute_returning(
            "retire_intake", {"id": str(intake_id)},
        )

    # ── REQUIREMENTS ───────────────────────────────────────────

    async def add_requirement(
        self,
        intake_id,
        *,
        code: str,
        kind: RequirementKind,
        statement: str,
        created_by: str,
        acceptance_criteria: Optional[str] = None,
        source: Optional[str] = None,
        status: RequirementStatus = RequirementStatus.DRAFT,
        parent_requirement_id: Optional[UUID] = None,
        acting_as_role: Optional[StudioRole] = None,
        embed_now: bool = True,
    ) -> dict:
        """Add a requirement under an intake. Embeds the text by default.

        ``embed_now=False`` skips the fastembed import — useful in unit
        tests and bulk seeders that prefer to call ``reembed_requirements``
        afterwards.
        """
        row = await self.db.execute_returning(
            "insert_intake_requirement",
            {
                "intake_id": str(intake_id),
                "code": code,
                "kind": kind.value,
                "statement": statement,
                "acceptance_criteria": acceptance_criteria,
                "source": source,
                "status": status.value,
                "parent_requirement_id": _to_str(parent_requirement_id),
                "created_by": created_by,
                "acting_as_role": _to_str(acting_as_role),
            },
        )
        if not row:
            raise RuntimeError("insert_intake_requirement returned no row")
        if embed_now:
            try:
                await self._embed_requirement_row(row["id"], statement, acceptance_criteria)
            except Exception as exc:
                # Don't fail the create if embedding fails — log and move on.
                # The reembed CLI will pick the row up later.
                logger.warning(
                    "Embedding failed for requirement %s: %s", row["id"], exc,
                )
        return row

    async def list_requirements(self, intake_id) -> list[dict]:
        return await self.db.fetch_all(
            "list_requirements_for_intake",
            {"intake_id": str(intake_id)},
        )

    async def update_requirement(
        self, requirement_id, **fields,
    ) -> Optional[dict]:
        """Update a requirement; re-embed if statement / acceptance changed."""
        params: dict[str, Any] = {"id": str(requirement_id)}
        for key in ("statement", "acceptance_criteria", "source"):
            params[key] = fields.get(key)
        params["status"] = _to_str(fields.get("status"))
        params["parent_requirement_id"] = _to_str(fields.get("parent_requirement_id"))
        row = await self.db.execute_returning("update_requirement", params)
        if not row:
            return None
        # Re-embed if the embedded text changed.
        if fields.get("statement") is not None or fields.get("acceptance_criteria") is not None:
            try:
                await self._embed_requirement_row(
                    row["id"], row.get("statement"), row.get("acceptance_criteria"),
                )
            except Exception as exc:
                logger.warning("Re-embedding failed for %s: %s", row["id"], exc)
        return row

    async def _embed_requirement_row(
        self,
        requirement_id,
        statement: Optional[str],
        acceptance_criteria: Optional[str],
    ) -> None:
        """Compute + write the embedding + model FK + hash for one row."""
        if not statement:
            return
        text = _embedding_input(statement, acceptance_criteria)
        vec = _embed_text(text)
        if not vec:
            return
        # Resolve the current embedding model FK. Inline SQL via fetch_one_raw
        # because there is no value in adding a named query for a one-line
        # registry lookup.
        cfg_row = await self.db.fetch_one_raw(
            "SELECT id FROM compliance.embedding_config WHERE is_current = true LIMIT 1",
        )
        model_id = cfg_row["id"] if cfg_row else None
        await self.db.execute_returning(
            "update_requirement_embedding",
            {
                "id": str(requirement_id),
                "embedding": _vec_to_pgvector_literal(vec),
                "embedding_model_id": str(model_id) if model_id else None,
                "embedding_input_hash": _hash_input(text),
            },
        )

    async def search_similar_requirements(
        self,
        statement: str,
        acceptance_criteria: Optional[str] = None,
        *,
        top_n: int = 5,
        # 0.78 chosen empirically — BGE-small on insurance-domain
        # requirement text scores genuine paraphrases at 0.80–0.92
        # and unrelated requirements below 0.70. The Studio UX
        # treats anything ≥ 0.78 as "consider linking instead".
        min_similarity: float = 0.78,
        exclude_id: Optional[UUID] = None,
    ) -> list[dict]:
        """Embed the input and return the top-N most-similar requirements.

        Used by Studio's redundancy-check HTMX endpoint.
        """
        text = _embedding_input(statement, acceptance_criteria)
        vec = _embed_text(text)
        if not vec:
            return []
        return await self.db.fetch_all(
            "search_similar_requirements",
            {
                "query_embedding": _vec_to_pgvector_literal(vec),
                "exclude_id": _to_str(exclude_id),
                "min_similarity": min_similarity,
                "top_n": top_n,
            },
        )

    async def reembed_requirements(self) -> int:
        """Re-embed all stale rows. Returns the count re-embedded."""
        cfg_row = await self.db.fetch_one_raw(
            "SELECT id FROM compliance.embedding_config WHERE is_current = true LIMIT 1",
        )
        model_id = cfg_row["id"] if cfg_row else None
        if not model_id:
            logger.warning("No current embedding_config row — skipping reembed.")
            return 0
        rows = await self.db.fetch_all(
            "list_stale_requirement_embeddings",
            {"current_model_id": str(model_id)},
        )
        # Also include rows whose hash no longer matches their text.
        # We computed the SHA256 in Python; check it explicitly here.
        count = 0
        for r in rows:
            text = _embedding_input(r["statement"], r.get("acceptance_criteria"))
            current_hash = _hash_input(text)
            stored = r.get("embedding_input_hash")
            if stored is not None and bytes(stored) == current_hash and r.get("embedding_model_id"):
                continue
            await self._embed_requirement_row(r["id"], r["statement"], r.get("acceptance_criteria"))
            count += 1
        return count

    # ── ENTITY LINKS ───────────────────────────────────────────

    async def link_entity(
        self,
        intake_id,
        *,
        entity_type: LinkedEntityKind,
        entity_id: UUID,
        created_by: str,
        requirement_id: Optional[UUID] = None,
        relationship: RequirementRelationship = RequirementRelationship.IMPLEMENTS,
        acting_as_role: Optional[StudioRole] = None,
    ) -> Optional[dict]:
        return await self.db.execute_returning(
            "insert_intake_entity_link",
            {
                "intake_id": str(intake_id),
                "requirement_id": _to_str(requirement_id),
                "entity_type": entity_type.value,
                "entity_id": str(entity_id),
                "relationship": relationship.value,
                "created_by": created_by,
                "acting_as_role": _to_str(acting_as_role),
            },
        )

    async def list_entity_links(self, intake_id) -> list[dict]:
        return await self.db.fetch_all(
            "list_entity_links_for_intake",
            {"intake_id": str(intake_id)},
        )

    async def delete_entity_link(self, link_id) -> Optional[dict]:
        return await self.db.execute_returning(
            "delete_intake_entity_link", {"id": str(link_id)},
        )

    async def list_intakes_for_entity(
        self, entity_type: LinkedEntityKind, entity_id: UUID,
    ) -> list[dict]:
        return await self.db.fetch_all(
            "list_intakes_for_entity",
            {
                "entity_type": entity_type.value,
                "entity_id": str(entity_id),
            },
        )

    # ── ARTIFACT PLAN ──────────────────────────────────────────

    async def list_plan_rows(self, intake_id) -> list[dict]:
        return await self.db.fetch_all(
            "list_artifact_plan_rows", {"intake_id": str(intake_id)},
        )

    async def add_plan_row(
        self,
        intake_id,
        *,
        proposed_kind: LinkedEntityKind,
        proposed_name: str,
        proposed_display_name: str,
        proposed_materiality_tier: str,
        created_by: str,
        proposed_description: Optional[str] = None,
        proposed_purpose: Optional[str] = None,
        proposed_inputs: Optional[dict] = None,
        proposed_outputs: Optional[dict] = None,
        proposed_capability_type: Optional[str] = None,
        requirement_id: Optional[UUID] = None,
        auto_generated: bool = False,
        acting_as_role: Optional[StudioRole] = None,
    ) -> Optional[dict]:
        return await self.db.execute_returning(
            "insert_artifact_plan_row",
            {
                "intake_id": str(intake_id),
                "requirement_id": _to_str(requirement_id),
                "proposed_kind": proposed_kind.value,
                "proposed_name": proposed_name,
                "proposed_display_name": proposed_display_name,
                "proposed_description": proposed_description,
                "proposed_purpose": proposed_purpose,
                "proposed_inputs": _json_param(proposed_inputs or {}),
                "proposed_outputs": _json_param(proposed_outputs or {}),
                "proposed_capability_type": proposed_capability_type,
                "proposed_materiality_tier": proposed_materiality_tier,
                "auto_generated": auto_generated,
                "created_by": created_by,
                "acting_as_role": _to_str(acting_as_role),
            },
        )

    async def update_plan_row(self, plan_id, **fields) -> Optional[dict]:
        params: dict[str, Any] = {"id": str(plan_id)}
        for key in (
            "proposed_name", "proposed_display_name",
            "proposed_description", "proposed_purpose",
        ):
            params[key] = fields.get(key)
        for jkey in ("proposed_inputs", "proposed_outputs"):
            v = fields.get(jkey)
            params[jkey] = _json_param(v) if v is not None else None
        params["status"] = _to_str(fields.get("status"))
        return await self.db.execute_returning("update_artifact_plan_row", params)

    async def realize_plan_row(
        self, plan_id, realized_entity_id: UUID,
    ) -> Optional[dict]:
        """Mark a plan row as realised and link the registry entity to
        the intake's owning application.

        Two writes:
          1. ``intake_artifact_plan.realized_entity_id`` set; status →
             realized.
          2. A row in ``application_entity`` mapping the new registry
             entity (agent / task / prompt / tool) to the same
             application that owns the parent intake. If the mapping
             already exists, the underlying upsert is a no-op.

        Without step 2, an engineer who realises a plan into an agent
        would have to remember to register that agent against the
        application separately — error-prone, and the agent wouldn't
        appear in the application's asset views.
        """
        row = await self.db.execute_returning(
            "realize_artifact_plan_row",
            {
                "id": str(plan_id),
                "realized_entity_id": str(realized_entity_id),
            },
        )
        if not row:
            return None

        # Look up the parent intake to find its application; only entity
        # kinds that the application_entity polymorphic FK accepts get
        # a mapping (agent / task / prompt / tool / pipeline).
        parent = await self.db.fetch_one_raw(
            """
            SELECT i.application_id
            FROM governance.intake_artifact_plan p
            JOIN governance.intake i ON i.id = p.intake_id
            WHERE p.id = %(plan_id)s
            """,
            {"plan_id": str(plan_id)},
        )
        registry_kinds = {"agent", "task", "prompt", "tool"}
        kind = row.get("proposed_kind")
        if parent and kind in registry_kinds:
            try:
                # Idempotent — application_entity has UNIQUE on
                # (application_id, entity_type, entity_id).
                await self.db.execute_returning(
                    "insert_application_entity",
                    {
                        "application_id": str(parent["application_id"]),
                        "entity_type": kind,
                        "entity_id": str(realized_entity_id),
                    },
                )
            except Exception as exc:
                # Already-mapped duplicate is the expected non-fatal
                # case; log and proceed. Anything else also doesn't
                # block plan realisation — surface it for diagnosis.
                logger.warning(
                    "application_entity link failed for plan=%s entity=%s: %s",
                    plan_id, realized_entity_id, exc,
                )
        return row

    async def delete_plan_row(self, plan_id) -> Optional[dict]:
        return await self.db.execute_returning(
            "delete_artifact_plan_row", {"id": str(plan_id)},
        )

    # ── IMPACT ASSESSMENT ──────────────────────────────────────

    async def upsert_impact_assessment(
        self,
        intake_id,
        *,
        completed_by: Optional[str] = None,
        completed: bool = False,
        data_sources: Optional[list[dict]] = None,
        potential_harms: Optional[list[dict]] = None,
        mitigations: Optional[list[dict]] = None,
        fairness_considerations: Optional[str] = None,
        privacy_considerations: Optional[str] = None,
        human_oversight_plan: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        completed_at = datetime.now(timezone.utc) if completed else None
        return await self.db.execute_returning(
            "upsert_impact_assessment",
            {
                "intake_id": str(intake_id),
                "data_sources": _json_param(data_sources or []),
                "potential_harms": _json_param(potential_harms or []),
                "mitigations": _json_param(mitigations or []),
                "fairness_considerations": fairness_considerations,
                "privacy_considerations": privacy_considerations,
                "human_oversight_plan": human_oversight_plan,
                "completed_at": completed_at,
                "completed_by": completed_by,
                "notes": notes,
            },
        ) or {}

    async def get_impact_assessment(self, intake_id) -> Optional[dict]:
        return await self.db.fetch_one(
            "get_impact_assessment", {"intake_id": str(intake_id)},
        )

    # ── APPROVALS ──────────────────────────────────────────────

    async def list_approval_requests(self, intake_id) -> list[dict]:
        return await self.db.fetch_all(
            "list_approval_requests_for_intake",
            {"intake_id": str(intake_id)},
        )

    async def open_approval_request(
        self,
        intake_id,
        *,
        kind: ApprovalRequestKind,
        opened_by: str,
        summary: str,
        required_roles: list[ApprovalRole],
        target_entity_type: Optional[LinkedEntityKind] = None,
        target_entity_id: Optional[UUID] = None,
        opened_by_role: Optional[StudioRole] = None,
        notes: Optional[str] = None,
    ) -> dict:
        return await self.db.execute_returning(
            "insert_approval_request",
            {
                "intake_id": str(intake_id),
                "kind": kind.value,
                "target_entity_type": target_entity_type.value if target_entity_type else None,
                "target_entity_id": _to_str(target_entity_id),
                "required_roles": _json_param([r.value for r in required_roles]),
                "opened_by": opened_by,
                "opened_by_role": _to_str(opened_by_role),
                "summary": summary,
                "notes": notes,
            },
        ) or {}

    async def list_signoffs(self, approval_request_id) -> list[dict]:
        return await self.db.fetch_all(
            "list_signoffs_for_request",
            {"approval_request_id": str(approval_request_id)},
        )

    async def signoff(
        self,
        approval_request_id,
        *,
        role: ApprovalRole,
        approver_name: str,
        decision: ApprovalDecision,
        approver_email: Optional[str] = None,
        comment: Optional[str] = None,
        evidence_url: Optional[str] = None,
    ) -> dict:
        """Record a signoff. Recomputes the parent request's status and,
        if it transitions to 'approved', advances the parent intake and
        triggers artifact-plan auto-generation (for kind='intake' only).
        """
        intake_just_approved = False
        approved_intake_id = None
        async with self.db.transaction() as tx:
            signoff_row = await tx.execute_returning(
                "insert_approval_signoff",
                {
                    "approval_request_id": str(approval_request_id),
                    "role": role.value,
                    "approver_name": approver_name,
                    "approver_email": approver_email,
                    "decision": decision.value,
                    "comment": comment,
                    "evidence_url": evidence_url,
                },
            )
            request = await tx.fetch_one(
                "get_approval_request", {"id": str(approval_request_id)},
            )
            if not request:
                raise ValueError(f"Approval request {approval_request_id} not found")

            new_status = await self._recompute_request_status(tx, request)
            if new_status and new_status != request["status"]:
                await tx.execute_returning(
                    "update_approval_request_status",
                    {"id": str(approval_request_id), "status": new_status},
                )
            # If this is the kind='intake' approval and it just turned
            # 'approved', flip the intake to 'approved' too. Plan
            # auto-generation runs OUTSIDE the transaction below.
            if (
                new_status == "approved"
                and request["kind"] == ApprovalRequestKind.INTAKE.value
            ):
                await tx.execute_returning(
                    "approve_intake", {"id": str(request["intake_id"])},
                )
                intake_just_approved = True
                approved_intake_id = request["intake_id"]

        # Plan generation deliberately runs AFTER the transaction commits.
        # The plan is logically separate from the approval state — if
        # generation fails the intake is still approved and the engineer
        # can run plan generation manually from Studio.
        if intake_just_approved and approved_intake_id is not None:
            try:
                # Lazy import: plan_generator imports IntakeService, which
                # imports this module. Top-level import would cycle.
                from verity.governance.plan_generator import generate_plan
                await generate_plan(self, approved_intake_id)
            except Exception as exc:
                logger.warning(
                    "Plan auto-generation failed for intake %s: %s",
                    approved_intake_id, exc,
                )
        return signoff_row

    async def _recompute_request_status(
        self, tx, request: dict,
    ) -> Optional[str]:
        """Roll up the parent request's status from its signoffs.

        Rules (matches § 4.3 of governance-intake.md):
          - Any signoff with decision='rejected'  -> request 'rejected'.
          - Every required role has at least one 'approved' signoff
            AND no 'rejected' anywhere -> request 'approved'.
          - Otherwise -> 'pending'.
        """
        signoffs = await tx.fetch_all(
            "list_signoffs_for_request",
            {"approval_request_id": str(request["id"])},
        )
        if any(s["decision"] == "rejected" for s in signoffs):
            return "rejected"
        required = request["required_roles"]
        if isinstance(required, str):
            # Defensive: psycopg may surface JSONB as a parsed list or as
            # a JSON string depending on adapter config. Coerce.
            required = json.loads(required)
        if not required:
            # Nothing required (e.g. unacceptable tier wiped roles); leave pending.
            return "pending"
        approved_roles = {s["role"] for s in signoffs if s["decision"] == "approved"}
        if all(r in approved_roles for r in required):
            return "approved"
        return "pending"

    # ── PROMOTION GATE (lifecycle hook) ────────────────────────

    async def check_promotion_gate(
        self,
        entity_type: LinkedEntityKind,
        entity_id: UUID,
        target_state: str,
    ) -> PromotionGateResult:
        """Lifecycle calls this before promote()-ing a registry artifact.

        Returns ``allowed=False`` with reasons when:
          - any linked intake is in {proposed, in_review, impact_assessment,
            rejected, retired}
          - any linked intake has an open kind='intake' or
            'risk_reclassification' request
          - target_state='champion' AND the intake is high-risk AND no
            approved kind='promote_champion' request exists for this entity
          - any linked functional/compliance requirement is not in
            ('verified','approved','implemented')

        Unlinked entities (no intake_entity_link rows) are allowed —
        backward-compat with legacy seed data.
        """
        rows = await self.list_intakes_for_entity(entity_type, entity_id)
        if not rows:
            return PromotionGateResult(allowed=True, reasons=[], linked_intakes=[])

        reasons: list[str] = []
        linked_ids: list[UUID] = []

        for r in rows:
            linked_ids.append(r["id"])
            i_status = r["status"]
            i_tier = r["ai_risk_tier"]

            if i_status not in ("approved", "in_build", "live"):
                reasons.append(
                    f"Linked intake '{r['code']}' is in status='{i_status}' "
                    f"(must be approved/in_build/live)."
                )

            # Open intake or reclassification approvals block promotion.
            open_intake = await self.db.fetch_all(
                "list_open_intake_approvals", {"intake_id": str(r["id"])},
            )
            if open_intake:
                reasons.append(
                    f"Linked intake '{r['code']}' has {len(open_intake)} pending "
                    f"intake/risk approval(s)."
                )

            # promote_champion approval required for high-risk intakes.
            if target_state == "champion" and i_tier == "high":
                approved = await self.db.fetch_all(
                    "list_decided_promote_champion_approvals",
                    {
                        "intake_id": str(r["id"]),
                        "entity_type": entity_type.value,
                        "entity_id": str(entity_id),
                    },
                )
                # Need at least one with status='approved'.
                if not any(a["status"] == "approved" for a in approved):
                    reasons.append(
                        f"High-risk intake '{r['code']}' requires an approved "
                        f"promote_champion request for this {entity_type.value}."
                    )

            # All linked functional/compliance reqs must be verified or approved.
            reqs = await self.db.fetch_all(
                "list_requirements_for_intake", {"intake_id": str(r["id"])},
            )
            blocking_reqs = [
                req for req in reqs
                if req["kind"] in ("functional", "compliance")
                and req["status"] not in ("approved", "implemented", "verified")
            ]
            if blocking_reqs:
                codes = ", ".join(b["code"] for b in blocking_reqs)
                reasons.append(
                    f"Linked intake '{r['code']}' has unverified "
                    f"{len(blocking_reqs)} requirement(s): {codes}."
                )

        return PromotionGateResult(
            allowed=not reasons, reasons=reasons, linked_intakes=linked_ids,
        )

    # ── DASHBOARD ──────────────────────────────────────────────

    async def dashboard_counts(self) -> dict[str, Any]:
        status_rows = await self.db.fetch_all("dashboard_intake_counts_by_status")
        tier_rows = await self.db.fetch_all("dashboard_intake_counts_by_tier")
        pending = await self.db.fetch_all("dashboard_pending_approvals")
        unlinked = await self.db.fetch_all("dashboard_unlinked_entity_counts")
        return {
            "by_status": {r["status"]: r["n"] for r in status_rows},
            "by_risk_tier": {r["ai_risk_tier"]: r["n"] for r in tier_rows},
            "pending_approvals": pending,
            "unlinked_entities": {r["entity_type"]: r["n"] for r in unlinked},
        }
