"""Authoring endpoints — POST wrappers over every `register_*` SDK method.

Organized into four groups matching the plan:
    1. Headers          — agent, task, prompt, tool, pipeline, inference-config, mcp-server
    2. Versions         — agent_version, task_version, prompt_version, pipeline_version
    3. Associations     — prompt assignments, tool authorizations, sub-agent delegations
    4. Governance       — ground-truth datasets/records/annotations, validation runs,
                          model cards, metric thresholds, test suites, test cases

Every endpoint accepts an arbitrary `dict[str, Any]` body and forwards it
to the corresponding SDK method as `**body`. The expected field shapes
live in the docstring of each endpoint so they render in the Swagger UI
at /docs. Required/optional breakdown is also captured there.

Scoping by name in URLs:
    /api/v1/agents/{name}/versions                      — resolves name → agent_id
    /api/v1/agents/{name}/versions/{version_id}/prompts — also uses version_id from URL
Not every SDK method is reachable via a name-scoped URL (governance
artifacts receive entity_type/entity_id in the body instead) — the
choice is driven by what a notebook caller finds easiest to type.

Error mapping:
    ValueError       → 400 (semantic misuse, e.g. delegation child target mis-specified)
    psycopg errors   → 400 (missing required column, foreign-key violation, etc.)
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from psycopg.errors import Error as PsycopgError


def _as_400(exc: Exception) -> HTTPException:
    """Convert a domain error (ValueError or psycopg error) into a 400.

    Anything else bubbles up untouched, so real 500s (bugs) keep showing
    their traceback. That split keeps the "bad input" signal honest.
    """
    return HTTPException(status_code=400, detail=str(exc))


def build_authoring_router(verity) -> APIRouter:
    """Build the full POST surface for creating registered entities."""
    router = APIRouter(tags=["authoring"])

    # ══════════════════════════════════════════════════════════════
    # 1. HEADERS — entity anchors, created once per named entity
    # ══════════════════════════════════════════════════════════════

    @router.post("/agents")
    async def register_agent(body: dict[str, Any]) -> dict:
        """Register an agent header (no version yet).

        Expected fields: name, display_name, description, purpose,
        domain, materiality_tier, owner_name (optional owner_email,
        business_context, known_limitations, regulatory_notes).
        """
        try:
            return await verity.registry.register_agent(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/tasks")
    async def register_task(body: dict[str, Any]) -> dict:
        """Register a task header (no version yet).

        Expected fields: name, display_name, description,
        capability_type, purpose, domain, materiality_tier,
        input_schema, output_schema, owner_name (optional
        owner_email, business_context, known_limitations,
        regulatory_notes).
        """
        try:
            return await verity.registry.register_task(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/prompts")
    async def register_prompt(body: dict[str, Any]) -> dict:
        """Register a prompt header.

        Expected fields: name, display_name, description,
        primary_entity_type (agent/task), primary_entity_id.
        """
        try:
            return await verity.registry.register_prompt(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/tools")
    async def register_tool(body: dict[str, Any]) -> dict:
        """Register a tool.

        Expected: name, display_name, description, input_schema,
        output_schema. Defaults: transport='python_inprocess',
        mcp_server_name=None, mcp_tool_name=None. Optional:
        implementation_path, mock_mode_enabled, mock_response_key,
        data_classification_max, is_write_operation,
        requires_confirmation, tags.
        """
        try:
            return await verity.registry.register_tool(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/inference-configs")
    async def register_inference_config(body: dict[str, Any]) -> dict:
        """Register an inference config.

        Expected: name, display_name, description, intended_use,
        model_name, temperature, max_tokens. Optional: top_p, top_k,
        stop_sequences, extended_params.
        """
        try:
            return await verity.registry.register_inference_config(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/mcp-servers")
    async def register_mcp_server(body: dict[str, Any]) -> dict:
        """Register an MCP server.

        Required: name, display_name, transport.
        Transport-dependent:
          - transport='stdio': command (required), args (optional list[str])
          - transport='sse' | 'http': url (required)
        Optional: env (dict), auth_config (dict), description, active.
        """
        try:
            return await verity.registry.register_mcp_server(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    # ══════════════════════════════════════════════════════════════
    # 2. VERSIONS — always created in 'draft' state
    # ══════════════════════════════════════════════════════════════
    # URLs scope by the header name; endpoint resolves name → id so
    # callers never need to copy UUIDs from a prior response.

    @router.post("/agents/{name}/versions")
    async def register_agent_version(name: str, body: dict[str, Any]) -> dict:
        """Register an agent_version (draft).

        Body fields: major_version, minor_version, patch_version,
        lifecycle_state (default 'draft'), channel, inference_config_id,
        output_schema, authority_thresholds, mock_mode_enabled,
        decision_log_detail, developer_name, change_summary, change_type.
        """
        header = await verity.registry.get_agent_by_name(name)
        if not header:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        try:
            return await verity.registry.register_agent_version(
                agent_id=header["id"], **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/tasks/{name}/versions")
    async def register_task_version(name: str, body: dict[str, Any]) -> dict:
        """Register a task_version (draft).

        Body fields: major_version, minor_version, patch_version,
        lifecycle_state (default 'draft'), channel, inference_config_id,
        output_schema, mock_mode_enabled, decision_log_detail,
        developer_name, change_summary, change_type.
        """
        header = await verity.registry.get_task_by_name(name)
        if not header:
            raise HTTPException(status_code=404, detail=f"Task '{name}' not found")
        try:
            return await verity.registry.register_task_version(
                task_id=header["id"], **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/prompts/{name}/versions")
    async def register_prompt_version(name: str, body: dict[str, Any]) -> dict:
        """Register a prompt_version (draft).

        Body fields: major_version, minor_version, patch_version,
        content, api_role ('system'/'user'/'assistant'),
        governance_tier ('behavioural'/'critical'/'regulatory'),
        lifecycle_state (default 'draft'), change_summary,
        sensitivity_level, author_name. Template variables are
        auto-extracted from {{var}} placeholders in content.
        """
        header = await verity.registry.get_prompt_by_name(name)
        if not header:
            raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")
        try:
            return await verity.registry.register_prompt_version(
                prompt_id=header["id"], **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    # ══════════════════════════════════════════════════════════════
    # 3. ASSOCIATIONS — wire versions to prompts, tools, sub-agents
    # ══════════════════════════════════════════════════════════════

    @router.post("/agents/{name}/versions/{version_id}/prompts")
    async def assign_prompt_to_agent(
        name: str, version_id: str, body: dict[str, Any],
    ) -> dict:
        """Attach a prompt_version to this agent_version.

        Body fields: prompt_version_id, api_role, governance_tier,
        execution_order (int), is_required (bool, default true),
        condition_logic (optional dict for conditional inclusion).
        """
        try:
            return await verity.registry.assign_prompt(
                entity_type="agent",
                entity_version_id=version_id,
                **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/tasks/{name}/versions/{version_id}/prompts")
    async def assign_prompt_to_task(
        name: str, version_id: str, body: dict[str, Any],
    ) -> dict:
        """Attach a prompt_version to this task_version.

        Body fields: prompt_version_id, api_role, governance_tier,
        execution_order, is_required, condition_logic.
        """
        try:
            return await verity.registry.assign_prompt(
                entity_type="task",
                entity_version_id=version_id,
                **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/agents/{name}/versions/{version_id}/tools")
    async def authorize_agent_tool(
        name: str, version_id: str, body: dict[str, Any],
    ) -> dict:
        """Authorize a tool for this agent_version.

        Body fields: tool_id, authorized (bool, default true),
        notes (optional).
        """
        try:
            return await verity.registry.authorize_agent_tool(
                agent_version_id=version_id, **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/tasks/{name}/versions/{version_id}/tools")
    async def authorize_task_tool(
        name: str, version_id: str, body: dict[str, Any],
    ) -> dict:
        """Authorize a tool for this task_version.

        Body fields: tool_id, authorized (bool, default true),
        notes (optional).
        """
        try:
            return await verity.registry.authorize_task_tool(
                task_version_id=version_id, **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/agents/{name}/versions/{version_id}/delegations")
    async def register_delegation(
        name: str, version_id: str, body: dict[str, Any],
    ) -> dict:
        """Register a sub-agent delegation from this agent_version.

        Required (EXACTLY ONE): child_agent_name (champion-tracking) OR
        child_agent_version_id (version-pinned). The other must be null.
        Optional: scope (dict, per-relationship constraints), authorized
        (bool, default true), rationale, notes.
        """
        try:
            return await verity.registry.register_delegation(
                parent_agent_version_id=version_id, **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    # ══════════════════════════════════════════════════════════════
    # 4. GOVERNANCE ARTIFACTS
    # ══════════════════════════════════════════════════════════════

    @router.post("/ground-truth/datasets")
    async def register_ground_truth_dataset(body: dict[str, Any]) -> dict:
        """Register a ground-truth dataset.

        Expected: entity_type, entity_id, name, version, description,
        purpose, quality_tier, status, owner_name. Optional: created_by,
        record_count, designed_for_version_id, coverage_notes.
        """
        try:
            return await verity.registry.register_ground_truth_dataset(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/ground-truth/datasets/{dataset_id}/records")
    async def register_ground_truth_record(
        dataset_id: str, body: dict[str, Any],
    ) -> dict:
        """Register one input record in a dataset.

        Body: record_index, source_type, source_provider,
        source_container, source_key, source_description,
        input_data (dict, stored as JSONB), tags (list[str]),
        difficulty, record_notes.
        """
        try:
            return await verity.registry.register_ground_truth_record(
                dataset_id=dataset_id, **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/ground-truth/records/{record_id}/annotations")
    async def register_ground_truth_annotation(
        record_id: str, body: dict[str, Any],
    ) -> dict:
        """Register one annotator's label for a record.

        Body: dataset_id, annotator_type ('human'/'judge'/'source'),
        labeled_by, label_confidence, label_notes, judge_model,
        judge_prompt_version_id, judge_reasoning, expected_output (dict,
        stored as JSONB), is_authoritative (bool).
        """
        try:
            return await verity.registry.register_ground_truth_annotation(
                record_id=record_id, **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/validation-runs")
    async def register_validation_run(body: dict[str, Any]) -> dict:
        """Register a validation run against a dataset.

        Expected: entity_type, entity_version_id, dataset_id,
        dataset_version, run_by, precision_score, recall_score,
        f1_score, cohens_kappa, confusion_matrix (dict), field_accuracy
        (dict), overall_extraction_rate, low_confidence_rate,
        fairness_metrics (dict), fairness_passed, fairness_notes,
        thresholds_met, threshold_details (dict),
        inference_config_snapshot (dict), status, passed, notes.
        """
        try:
            return await verity.registry.register_validation_run(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/model-cards")
    async def register_model_card(body: dict[str, Any]) -> dict:
        """Register a model card.

        Expected: entity_type, entity_version_id, card_version,
        purpose, design_rationale, inputs_description,
        outputs_description, known_limitations, conditions_of_use,
        lm_specific_limitations, prompt_sensitivity_notes, validated_by,
        validation_run_id, validation_notes, regulatory_notes,
        materiality_classification, approved_by, approved_at,
        lifecycle_state.
        """
        try:
            return await verity.registry.register_model_card(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/metric-thresholds")
    async def register_metric_threshold(body: dict[str, Any]) -> dict:
        """Register a metric threshold.

        Expected: entity_type, entity_id, materiality_tier, metric_name,
        field_name (optional, for per-field thresholds),
        minimum_acceptable, target_champion.
        """
        try:
            return await verity.registry.register_metric_threshold(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/test-suites")
    async def register_test_suite(body: dict[str, Any]) -> dict:
        """Register a test suite.

        Expected: name, description, entity_type, entity_id, suite_type
        ('regression'/'acceptance'/'adversarial'/...), created_by.
        """
        try:
            return await verity.registry.register_test_suite(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/test-suites/{suite_id}/cases")
    async def register_test_case(
        suite_id: str, body: dict[str, Any],
    ) -> dict:
        """Register a test case inside a suite.

        Body: name, description, input_data (dict, JSONB),
        expected_output (dict, JSONB), metric_type, metric_config
        (dict), is_adversarial (bool), tags (list[str]).
        """
        try:
            return await verity.registry.register_test_case(
                suite_id=suite_id, **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    return router
