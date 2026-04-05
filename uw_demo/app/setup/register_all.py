"""Seed Script — Register all demo entities in Verity.

This script populates the Verity database with demo-ready data:
- 5 inference configs
- 8 tools
- 2 agents (triage, appetite) with 2 versions each
- 2 tasks (classifier, extractor) with 2 versions each
- 8 prompts with versioned content
- 1 pipeline with 4 steps
- Test suites, approval records, model cards, validation runs
- Pre-seeded decision logs and overrides for UI browsing

IDEMPOTENT: Drops all tables and re-creates from scratch on every run.
USES SDK: All registrations go through verity.registry.* and verity.lifecycle.*
          to prove the SDK works end-to-end.

Usage:
    cd ~/verity_uw
    source .venv/bin/activate
    python -m uw_demo.app.setup.register_all
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from uuid import uuid4

from verity import Verity
from verity.db.migrate import apply_schema


# ── DATABASE URL ──────────────────────────────────────────────
DB_URL = "postgresql://verityuser:veritypass123@localhost:5432/verity_db"


async def main():
    """Run the full seed process."""

    # ── STEP 0: Reset database ────────────────────────────────
    print("Step 0: Resetting database (drop + recreate schema)...")
    await apply_schema(DB_URL, drop_existing=True)

    # ── Connect Verity SDK ────────────────────────────────────
    verity = Verity(database_url=DB_URL)
    await verity.connect()

    try:
        # ── STEP 1: Inference Configs ─────────────────────────
        print("Step 1: Registering inference configs...")
        configs = await seed_inference_configs(verity)

        # ── STEP 2: Tools ─────────────────────────────────────
        print("Step 2: Registering tools...")
        tools = await seed_tools(verity)

        # ── STEP 3: Agents + Tasks + Prompts ──────────────────
        print("Step 3: Registering agents, tasks, and prompts...")
        agents = await seed_agents(verity)
        tasks = await seed_tasks(verity)
        prompts = await seed_prompts(verity, agents, tasks)

        # ── STEP 4: Agent Versions + Task Versions ────────────
        print("Step 4: Registering entity versions...")
        agent_versions = await seed_agent_versions(verity, agents, configs)
        task_versions = await seed_task_versions(verity, tasks, configs)

        # ── STEP 5-6: Prompt Versions + Assignments ───────────
        print("Step 5-6: Registering prompt versions and assignments...")
        prompt_versions = await seed_prompt_versions(verity, prompts)
        await seed_prompt_assignments(verity, agent_versions, task_versions, prompt_versions)

        # ── STEP 7: Tool Authorizations ───────────────────────
        print("Step 7: Authorizing tools for agent versions...")
        await seed_tool_authorizations(verity, agent_versions, tools)

        # ── STEP 8: Pipeline ──────────────────────────────────
        print("Step 8: Registering pipeline...")
        pipeline = await seed_pipeline(verity)

        # ── STEP 9-10: Test Suites + Cases ────────────────────
        print("Step 9-10: Registering test suites and cases...")
        test_suites = await seed_test_suites(verity, agents, tasks)

        # ── STEP 11-12: Promote to Champion ───────────────────
        print("Step 11-12: Promoting versions to champion...")
        await promote_to_champion(verity, agent_versions, task_versions, agents, tasks)

        # ── STEP 13-16: Validation, Model Cards, Thresholds ──
        print("Step 13-16: Seeding validation runs, model cards, thresholds...")
        await seed_governance_artifacts(verity, agents, tasks, agent_versions, task_versions)

        # ── STEP 17: Test Execution Logs ──────────────────────
        print("Step 17: Seeding test execution logs...")
        await seed_test_results(verity, test_suites, agent_versions, task_versions)

        # ── STEP 18-19: Decision Logs + Overrides ─────────────
        print("Step 18-19: Seeding decision logs and overrides...")
        await seed_decisions(verity, agent_versions, task_versions)

        print("\n✓ Seed complete. All demo data loaded.")
        print("  Open http://localhost:8000/verity/admin/ to see the data.")

    finally:
        await verity.close()


# ══════════════════════════════════════════════════════════════
# STEP 1: INFERENCE CONFIGS
# ══════════════════════════════════════════════════════════════

async def seed_inference_configs(verity: Verity) -> dict:
    """Register 5 named inference configs. Returns {name: id}."""
    configs_data = [
        {
            "name": "classification_strict",
            "description": "Fully deterministic for classification tasks",
            "intended_use": "Document classification, appetite classification, routing decisions",
            "model_name": "claude-sonnet-4-20250514",
            "temperature": 0.0,
            "max_tokens": 512,
            "top_p": None, "top_k": None, "stop_sequences": None,
            "extended_params": "{}",
        },
        {
            "name": "extraction_deterministic",
            "description": "Deterministic for field extraction",
            "intended_use": "ACORD form extraction, loss run parsing, entity matching",
            "model_name": "claude-sonnet-4-20250514",
            "temperature": 0.0,
            "max_tokens": 2048,
            "top_p": None, "top_k": None, "stop_sequences": None,
            "extended_params": "{}",
        },
        {
            "name": "triage_balanced",
            "description": "Low temperature for consistent risk assessment",
            "intended_use": "Triage agent, appetite agent — requires consistency not creativity",
            "model_name": "claude-sonnet-4-20250514",
            "temperature": 0.2,
            "max_tokens": 4096,
            "top_p": None, "top_k": None, "stop_sequences": None,
            "extended_params": "{}",
        },
        {
            "name": "generation_narrative",
            "description": "Moderate temperature for professional narrative generation",
            "intended_use": "Quote letters, referral memos, renewal analysis narratives",
            "model_name": "claude-sonnet-4-20250514",
            "temperature": 0.4,
            "max_tokens": 8192,
            "top_p": None, "top_k": None, "stop_sequences": None,
            "extended_params": "{}",
        },
        {
            "name": "renewal_analytical",
            "description": "Low temperature for comparative analysis",
            "intended_use": "Renewal agent — structured comparison of prior vs current",
            "model_name": "claude-sonnet-4-20250514",
            "temperature": 0.1,
            "max_tokens": 4096,
            "top_p": None, "top_k": None, "stop_sequences": None,
            "extended_params": "{}",
        },
    ]

    result = {}
    for cfg in configs_data:
        r = await verity.registry.register_inference_config(**cfg)
        result[cfg["name"]] = r["id"]
        print(f"  + inference_config: {cfg['name']}")
    return result


# ══════════════════════════════════════════════════════════════
# STEP 2: TOOLS
# ══════════════════════════════════════════════════════════════

async def seed_tools(verity: Verity) -> dict:
    """Register 8 tools. Returns {name: id}."""
    tools_data = [
        {
            "name": "get_submission_context",
            "display_name": "Get Submission Context",
            "description": "Retrieves full submission data including account details, coverage information, and associated loss history for a given submission ID.",
            "input_schema": {"type": "object", "properties": {"submission_id": {"type": "string"}}, "required": ["submission_id"]},
            "output_schema": {"type": "object", "properties": {"account": {"type": "object"}, "submission": {"type": "object"}, "loss_history": {"type": "array"}}},
            "implementation_path": "uw_demo.app.tools.submission_tools.get_submission_context",
            "mock_mode_enabled": True, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "submission"],
        },
        {
            "name": "get_underwriting_guidelines",
            "display_name": "Get UW Guidelines",
            "description": "Retrieves the underwriting guidelines document for a given line of business (D&O or GL). Returns guideline text with section references.",
            "input_schema": {"type": "object", "properties": {"lob": {"type": "string", "enum": ["DO", "GL"]}}, "required": ["lob"]},
            "output_schema": {"type": "object", "properties": {"guidelines_text": {"type": "string"}, "sections": {"type": "array"}}},
            "implementation_path": "uw_demo.app.tools.guidelines_tools.get_underwriting_guidelines",
            "mock_mode_enabled": True, "mock_response_key": "default",
            "data_classification_max": "tier2_internal",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "guidelines"],
        },
        {
            "name": "get_documents_for_submission",
            "display_name": "Get Documents",
            "description": "Lists all documents uploaded for a submission from MinIO storage. Returns document metadata including filenames, types, and upload dates.",
            "input_schema": {"type": "object", "properties": {"submission_id": {"type": "string"}}, "required": ["submission_id"]},
            "output_schema": {"type": "object", "properties": {"documents": {"type": "array"}}},
            "implementation_path": "uw_demo.app.tools.document_tools.get_documents_for_submission",
            "mock_mode_enabled": True, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "documents"],
        },
        {
            "name": "get_loss_history",
            "display_name": "Get Loss History",
            "description": "Retrieves historical loss run data for the submission's account. Returns annual loss records with claim counts, incurred, paid, and reserves.",
            "input_schema": {"type": "object", "properties": {"account_id": {"type": "string"}}, "required": ["account_id"]},
            "output_schema": {"type": "object", "properties": {"years": {"type": "array"}, "total_incurred": {"type": "number"}}},
            "implementation_path": "uw_demo.app.tools.submission_tools.get_loss_history",
            "mock_mode_enabled": True, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "losses"],
        },
        {
            "name": "get_enrichment_data",
            "display_name": "Get Enrichment Data",
            "description": "Retrieves mock enrichment data simulating LexisNexis, D&B, and Pitchbook lookups. Returns litigation history, financial indicators, and company profile.",
            "input_schema": {"type": "object", "properties": {"company_name": {"type": "string"}}, "required": ["company_name"]},
            "output_schema": {"type": "object", "properties": {"lexisnexis": {"type": "object"}, "dnb": {"type": "object"}, "pitchbook": {"type": "object"}}},
            "implementation_path": "uw_demo.app.tools.mock_enrichment.get_enrichment_data",
            "mock_mode_enabled": True, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "enrichment"],
        },
        {
            "name": "update_submission_event",
            "display_name": "Update Event Log",
            "description": "Logs a workflow event for a submission (e.g., 'triage_complete', 'appetite_assessed'). Used for tracking pipeline progress.",
            "input_schema": {"type": "object", "properties": {"submission_id": {"type": "string"}, "event_type": {"type": "string"}, "details": {"type": "object"}}, "required": ["submission_id", "event_type"]},
            "output_schema": {"type": "object", "properties": {"event_id": {"type": "string"}, "logged_at": {"type": "string"}}},
            "implementation_path": "uw_demo.app.tools.submission_tools.update_submission_event",
            "mock_mode_enabled": True, "mock_response_key": "default",
            "data_classification_max": "tier2_internal",
            "is_write_operation": True, "requires_confirmation": False, "tags": ["write", "events"],
        },
        {
            "name": "store_triage_result",
            "display_name": "Store Triage Result",
            "description": "Stores the triage agent's risk assessment output (risk score, routing, narrative) to the submission record.",
            "input_schema": {"type": "object", "properties": {"submission_id": {"type": "string"}, "risk_score": {"type": "string"}, "routing": {"type": "string"}, "reasoning": {"type": "string"}}, "required": ["submission_id", "risk_score"]},
            "output_schema": {"type": "object", "properties": {"stored": {"type": "boolean"}}},
            "implementation_path": "uw_demo.app.tools.submission_tools.store_triage_result",
            "mock_mode_enabled": True, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": True, "requires_confirmation": False, "tags": ["write", "triage"],
        },
        {
            "name": "update_appetite_status",
            "display_name": "Update Appetite Status",
            "description": "Stores the appetite agent's determination (within_appetite, borderline, outside_appetite) and guideline citations.",
            "input_schema": {"type": "object", "properties": {"submission_id": {"type": "string"}, "determination": {"type": "string"}, "citations": {"type": "array"}}, "required": ["submission_id", "determination"]},
            "output_schema": {"type": "object", "properties": {"stored": {"type": "boolean"}}},
            "implementation_path": "uw_demo.app.tools.submission_tools.update_appetite_status",
            "mock_mode_enabled": True, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": True, "requires_confirmation": False, "tags": ["write", "appetite"],
        },
    ]

    result = {}
    for t in tools_data:
        r = await verity.registry.register_tool(**t)
        result[t["name"]] = r["id"]
        print(f"  + tool: {t['name']}")
    return result


# ══════════════════════════════════════════════════════════════
# STEP 3: AGENTS + TASKS + PROMPTS
# ══════════════════════════════════════════════════════════════

async def seed_agents(verity: Verity) -> dict:
    """Register 2 agents. Returns {name: {id, ...}}."""
    agents_data = [
        {
            "name": "triage_agent",
            "display_name": "Submission Risk Triage Agent",
            "description": "Synthesises extracted submission data, account enrichment, and loss history into a structured risk assessment for commercial lines D&O and GL submissions. Produces a risk score (Green/Amber/Red), routing recommendation, and plain-language risk narrative by reasoning across multiple competing risk factors. Calls tools to retrieve all relevant context before assessment.",
            "purpose": "Assist underwriters by providing a structured first-pass risk assessment before human review, reducing data-gathering time and improving routing consistency.",
            "domain": "underwriting",
            "materiality_tier": "high",
            "owner_name": "Sarah Chen",
            "owner_email": "sarah.chen@premiumiq.com",
            "business_context": "Used in the submission triage workflow to provide initial risk scoring before an underwriter reviews the submission.",
            "known_limitations": "Sensitive to prompt phrasing; limited to D&O and GL lines; requires complete submission data for accurate assessment; may over-weight recent loss history.",
            "regulatory_notes": "SR 11-7 High materiality model. Requires HITL for premiums above $500K.",
        },
        {
            "name": "appetite_agent",
            "display_name": "Underwriting Appetite Assessment Agent",
            "description": "Assesses whether a commercial lines D&O or GL submission is within underwriting appetite by reasoning across the submission's characteristics and the relevant underwriting guidelines document. Cites specific guideline sections for each determination. Distinct from triage_agent: appetite_agent focuses exclusively on guidelines compliance, not overall risk scoring.",
            "purpose": "Provide a structured guidelines-based appetite determination with specific section citations, enabling consistent appetite decisions and regulatory defensibility.",
            "domain": "underwriting",
            "materiality_tier": "high",
            "owner_name": "Sarah Chen",
            "owner_email": "sarah.chen@premiumiq.com",
            "business_context": "Evaluates submissions against published underwriting guidelines to determine if the risk falls within the company's appetite.",
            "known_limitations": "Dependent on guidelines document completeness and currency; cannot assess risks not covered by guidelines; may miss nuanced appetite exceptions approved verbally.",
            "regulatory_notes": "SR 11-7 High materiality. Appetite determinations may influence adverse action decisions.",
        },
    ]

    result = {}
    for a in agents_data:
        r = await verity.registry.register_agent(**a)
        result[a["name"]] = {"id": r["id"], **a}
        print(f"  + agent: {a['name']}")
    return result


async def seed_tasks(verity: Verity) -> dict:
    """Register 2 tasks. Returns {name: {id, ...}}."""
    tasks_data = [
        {
            "name": "document_classifier",
            "display_name": "Insurance Document Classification Task",
            "description": "Classifies a single insurance document into one of the defined document types based on its text content. Returns document type and confidence score. Processes one document per invocation.",
            "capability_type": "classification",
            "purpose": "Identify document types to route to appropriate extraction tasks.",
            "domain": "underwriting",
            "materiality_tier": "medium",
            "input_schema": {"document_text": "string", "document_filename": "string"},
            "output_schema": {"document_type": "string", "confidence": "number", "classification_notes": "string"},
            "owner_name": "James Okafor",
            "owner_email": "james.okafor@premiumiq.com",
            "business_context": "First step in document processing pipeline — identifies what type of insurance document was submitted.",
            "known_limitations": "Accuracy degrades on scanned documents with OCR errors; may confuse supplemental forms with similar structure.",
            "regulatory_notes": "Medium materiality. Classification errors can route documents to wrong extraction pipeline.",
        },
        {
            "name": "field_extractor",
            "display_name": "D&O ACORD 855 Field Extraction Task",
            "description": "Extracts structured data fields from a D&O Directors and Officers liability ACORD 855 application form. Returns field values with per-field confidence scores. Does not extract from GL forms, loss runs, or supplementals.",
            "capability_type": "extraction",
            "purpose": "Populate submission detail records from ACORD 855 application text.",
            "domain": "underwriting",
            "materiality_tier": "medium",
            "input_schema": {"document_text": "string", "submission_id": "string"},
            "output_schema": {"fields": "object", "low_confidence_fields": "array", "unextractable_fields": "array", "extraction_complete": "boolean"},
            "owner_name": "James Okafor",
            "owner_email": "james.okafor@premiumiq.com",
            "business_context": "Extracts key application fields from ACORD 855 forms to populate the submission record automatically.",
            "known_limitations": "Requires text-based input (not scanned images); field accuracy varies by form layout; may miss fields in non-standard form versions.",
            "regulatory_notes": "Medium materiality. Extracted values feed into risk assessment; errors propagate downstream.",
        },
    ]

    result = {}
    for t in tasks_data:
        r = await verity.registry.register_task(**t)
        result[t["name"]] = {"id": r["id"], **t}
        print(f"  + task: {t['name']}")
    return result


async def seed_prompts(verity: Verity, agents: dict, tasks: dict) -> dict:
    """Register 8 prompt entities (no versions yet). Returns {name: id}."""
    prompts_data = [
        # Agent prompts
        {"name": "triage_agent_system", "description": "System prompt for the triage agent defining risk assessment behaviour",
         "primary_entity_type": "agent", "primary_entity_id": agents["triage_agent"]["id"]},
        {"name": "triage_agent_context", "description": "User message template for triage agent with submission context variables",
         "primary_entity_type": "agent", "primary_entity_id": agents["triage_agent"]["id"]},
        {"name": "appetite_agent_system", "description": "System prompt for appetite agent defining guidelines assessment behaviour",
         "primary_entity_type": "agent", "primary_entity_id": agents["appetite_agent"]["id"]},
        {"name": "appetite_agent_context", "description": "User message template for appetite agent with submission and guidelines variables",
         "primary_entity_type": "agent", "primary_entity_id": agents["appetite_agent"]["id"]},
        # Task prompts
        {"name": "doc_classifier_instruction", "description": "System instruction for document classification task",
         "primary_entity_type": "task", "primary_entity_id": tasks["document_classifier"]["id"]},
        {"name": "doc_classifier_input", "description": "User message template for document classifier input",
         "primary_entity_type": "task", "primary_entity_id": tasks["document_classifier"]["id"]},
        {"name": "field_extractor_instruction", "description": "System instruction for ACORD 855 field extraction task",
         "primary_entity_type": "task", "primary_entity_id": tasks["field_extractor"]["id"]},
        {"name": "field_extractor_input", "description": "User message template for field extractor input",
         "primary_entity_type": "task", "primary_entity_id": tasks["field_extractor"]["id"]},
    ]

    result = {}
    for p in prompts_data:
        r = await verity.registry.register_prompt(**p)
        result[p["name"]] = r["id"]
        print(f"  + prompt: {p['name']}")
    return result


# ══════════════════════════════════════════════════════════════
# STEP 4: ENTITY VERSIONS
# ══════════════════════════════════════════════════════════════

async def seed_agent_versions(verity: Verity, agents: dict, configs: dict) -> dict:
    """Register agent versions. Returns {(name, version_label): id}."""
    versions = {}

    # Triage agent v0.9.0 (deprecated) — gives version history
    r = await verity.registry.register_agent_version(
        agent_id=agents["triage_agent"]["id"],
        major_version=0, minor_version=9, patch_version=0,
        lifecycle_state="deprecated", channel="production",
        inference_config_id=configs["triage_balanced"],
        output_schema=None, authority_thresholds=json.dumps({"requires_hitl_above_premium": 500000}),
        mock_mode_enabled=False,
        developer_name="Dev Team", change_summary="Initial prototype with basic risk scoring",
        change_type="major_redesign",
    )
    versions[("triage_agent", "0.9.0")] = r["id"]
    print(f"  + triage_agent v0.9.0 (deprecated)")

    # Triage agent v1.0.0 (will be promoted to champion)
    r = await verity.registry.register_agent_version(
        agent_id=agents["triage_agent"]["id"],
        major_version=1, minor_version=0, patch_version=0,
        lifecycle_state="draft", channel="development",
        inference_config_id=configs["triage_balanced"],
        output_schema=json.dumps({"risk_score": "string", "routing": "string", "reasoning": "string", "risk_factors": "array", "confidence": "number"}),
        authority_thresholds=json.dumps({"requires_hitl_above_premium": 500000, "low_confidence_threshold": 0.70, "auto_decline_red": False}),
        mock_mode_enabled=False,
        developer_name="Dev Team", change_summary="Added multi-factor risk assessment with guideline citations and structured risk factors",
        change_type="new_capability",
    )
    versions[("triage_agent", "1.0.0")] = r["id"]
    print(f"  + triage_agent v1.0.0 (draft → will promote)")

    # Appetite agent v1.0.0
    r = await verity.registry.register_agent_version(
        agent_id=agents["appetite_agent"]["id"],
        major_version=1, minor_version=0, patch_version=0,
        lifecycle_state="draft", channel="development",
        inference_config_id=configs["triage_balanced"],
        output_schema=json.dumps({"determination": "string", "confidence": "number", "guideline_citations": "array", "reasoning": "string"}),
        authority_thresholds=json.dumps({}),
        mock_mode_enabled=False,
        developer_name="Dev Team", change_summary="Initial release with guidelines-based appetite assessment",
        change_type="major_redesign",
    )
    versions[("appetite_agent", "1.0.0")] = r["id"]
    print(f"  + appetite_agent v1.0.0 (draft → will promote)")

    return versions


async def seed_task_versions(verity: Verity, tasks: dict, configs: dict) -> dict:
    """Register task versions. Returns {(name, version_label): id}."""
    versions = {}

    # Document classifier v0.9.0 (deprecated)
    r = await verity.registry.register_task_version(
        task_id=tasks["document_classifier"]["id"],
        major_version=0, minor_version=9, patch_version=0,
        lifecycle_state="deprecated", channel="production",
        inference_config_id=configs["classification_strict"],
        output_schema=None, mock_mode_enabled=False,
        developer_name="Dev Team", change_summary="Initial classifier with 6 document types",
        change_type="major_redesign",
    )
    versions[("document_classifier", "0.9.0")] = r["id"]
    print(f"  + document_classifier v0.9.0 (deprecated)")

    # Document classifier v1.0.0
    r = await verity.registry.register_task_version(
        task_id=tasks["document_classifier"]["id"],
        major_version=1, minor_version=0, patch_version=0,
        lifecycle_state="draft", channel="development",
        inference_config_id=configs["classification_strict"],
        output_schema=json.dumps({"document_type": "string", "confidence": "number", "classification_notes": "string"}),
        mock_mode_enabled=False,
        developer_name="Dev Team", change_summary="Added board_resolution and other types, improved prompt for accuracy",
        change_type="new_capability",
    )
    versions[("document_classifier", "1.0.0")] = r["id"]
    print(f"  + document_classifier v1.0.0 (draft → will promote)")

    # Field extractor v1.0.0
    r = await verity.registry.register_task_version(
        task_id=tasks["field_extractor"]["id"],
        major_version=1, minor_version=0, patch_version=0,
        lifecycle_state="draft", channel="development",
        inference_config_id=configs["extraction_deterministic"],
        output_schema=json.dumps({"fields": "object", "low_confidence_fields": "array", "unextractable_fields": "array", "extraction_complete": "boolean"}),
        mock_mode_enabled=False,
        developer_name="Dev Team", change_summary="Initial release with 20-field ACORD 855 extraction",
        change_type="major_redesign",
    )
    versions[("field_extractor", "1.0.0")] = r["id"]
    print(f"  + field_extractor v1.0.0 (draft → will promote)")

    return versions


# ══════════════════════════════════════════════════════════════
# STEPS 5-7: PROMPT VERSIONS, ASSIGNMENTS, TOOL AUTH
# ══════════════════════════════════════════════════════════════

async def seed_prompt_versions(verity: Verity, prompts: dict) -> dict:
    """Register prompt versions. Returns {(prompt_name, version_number): id}."""
    pv = {}

    # ── Triage agent system prompt — 2 versions (deprecated + current)
    r = await verity.registry.register_prompt_version(
        prompt_id=prompts["triage_agent_system"], version_number=1,
        content="You are a risk assessment assistant. Given a submission, evaluate the risk level and provide a Green/Amber/Red score with brief reasoning.",
        api_role="system", governance_tier="behavioural", lifecycle_state="deprecated",
        change_summary="Initial basic system prompt", sensitivity_level="high", author_name="Dev Team",
    )
    pv[("triage_agent_system", 1)] = r["id"]

    r = await verity.registry.register_prompt_version(
        prompt_id=prompts["triage_agent_system"], version_number=2,
        content="""You are a specialist underwriting risk triage agent for commercial lines insurance (D&O and GL). Your role is to synthesise submission data, account enrichment, loss history, and underwriting guidelines into a structured risk assessment.

You MUST call the available tools to retrieve all relevant context before making your assessment. Do not assess based on partial information.

Your output must be valid JSON with these fields:
- risk_score: "Green" (accept), "Amber" (review), or "Red" (decline/refer)
- routing: "assign_to_uw", "assign_to_senior_uw", "decline_without_review", or "refer_to_management"
- confidence: 0.0 to 1.0
- reasoning: Plain language explanation of your assessment (2-3 paragraphs)
- risk_factors: Array of identified risk factors, each with {factor, severity, detail}
- mitigating_factors: Array of positive indicators

Consider these dimensions:
1. Financial stability (revenue trends, going concern opinions)
2. Claims and litigation history (frequency, severity, trends)
3. Industry risk profile (SIC code risk classification)
4. Corporate governance (board composition, D&O history)
5. Regulatory exposure (investigations, enforcement actions)
6. Market conditions (competitive landscape, rate adequacy)""",
        api_role="system", governance_tier="behavioural", lifecycle_state="champion",
        change_summary="Comprehensive system prompt with multi-factor assessment framework, structured output schema, and tool-use instructions",
        sensitivity_level="high", author_name="Sarah Chen",
    )
    pv[("triage_agent_system", 2)] = r["id"]

    # ── Triage agent context template
    r = await verity.registry.register_prompt_version(
        prompt_id=prompts["triage_agent_context"], version_number=1,
        content="Please assess the following submission. Use the available tools to retrieve full context before making your assessment.\n\nSubmission ID: {{submission_id}}\nLine of Business: {{lob}}\nNamed Insured: {{named_insured}}",
        api_role="user", governance_tier="contextual", lifecycle_state="champion",
        change_summary="Initial context template with submission identifiers", sensitivity_level="medium", author_name="Dev Team",
    )
    pv[("triage_agent_context", 1)] = r["id"]

    # ── Appetite agent system prompt
    r = await verity.registry.register_prompt_version(
        prompt_id=prompts["appetite_agent_system"], version_number=1,
        content="""You are an underwriting appetite assessment agent. Your role is to determine whether a submission falls within the company's underwriting appetite by comparing the submission's characteristics against the relevant underwriting guidelines document.

You MUST:
1. Call get_underwriting_guidelines to retrieve the relevant guidelines
2. Call get_submission_context to retrieve the submission details
3. Compare each guideline criterion against the submission data
4. Cite specific guideline sections for each determination

Your output must be valid JSON with these fields:
- determination: "within_appetite", "borderline", or "outside_appetite"
- confidence: 0.0 to 1.0
- reasoning: Plain language explanation
- guideline_citations: Array of {section, criterion, submission_value, meets_criterion}
- exceptions_needed: Array of guideline exceptions that would need approval""",
        api_role="system", governance_tier="behavioural", lifecycle_state="champion",
        change_summary="Initial system prompt with guidelines citation framework", sensitivity_level="high", author_name="Sarah Chen",
    )
    pv[("appetite_agent_system", 1)] = r["id"]

    # ── Appetite agent context template
    r = await verity.registry.register_prompt_version(
        prompt_id=prompts["appetite_agent_context"], version_number=1,
        content="Please assess the appetite for the following submission.\n\nSubmission ID: {{submission_id}}\nLine of Business: {{lob}}\nNamed Insured: {{named_insured}}",
        api_role="user", governance_tier="contextual", lifecycle_state="champion",
        change_summary="Initial context template", sensitivity_level="medium", author_name="Dev Team",
    )
    pv[("appetite_agent_context", 1)] = r["id"]

    # ── Document classifier system prompt — 2 versions
    r = await verity.registry.register_prompt_version(
        prompt_id=prompts["doc_classifier_instruction"], version_number=1,
        content="Classify the document into one of: acord_855, acord_125, loss_runs, supplemental_do, supplemental_gl, other. Return JSON with document_type and confidence.",
        api_role="system", governance_tier="behavioural", lifecycle_state="deprecated",
        change_summary="Initial simple classifier instruction", sensitivity_level="high", author_name="Dev Team",
    )
    pv[("doc_classifier_instruction", 1)] = r["id"]

    r = await verity.registry.register_prompt_version(
        prompt_id=prompts["doc_classifier_instruction"], version_number=2,
        content="You are an insurance document classifier. Classify the provided document into exactly one of these types: acord_855, acord_125, loss_runs, supplemental_do, supplemental_gl, financial_statements, board_resolution, other. Return only valid JSON with document_type, confidence (0.0-1.0), and classification_notes. Base classification only on document content — never on filename.",
        api_role="system", governance_tier="behavioural", lifecycle_state="champion",
        change_summary="Added financial_statements and board_resolution types, explicit instruction to ignore filename, added classification_notes field",
        sensitivity_level="high", author_name="James Okafor",
    )
    pv[("doc_classifier_instruction", 2)] = r["id"]

    # ── Document classifier input template
    r = await verity.registry.register_prompt_version(
        prompt_id=prompts["doc_classifier_input"], version_number=1,
        content="Document text:\n{{document_text}}",
        api_role="user", governance_tier="formatting", lifecycle_state="champion",
        change_summary="Simple document text input wrapper", sensitivity_level="low", author_name="Dev Team",
    )
    pv[("doc_classifier_input", 1)] = r["id"]

    # ── Field extractor system prompt
    r = await verity.registry.register_prompt_version(
        prompt_id=prompts["field_extractor_instruction"], version_number=1,
        content="You are a specialist extraction system for D&O insurance applications (ACORD 855 form). Extract the following fields: named_insured, fein, entity_type, state_of_incorporation, annual_revenue, employee_count, board_size, independent_directors, effective_date, expiration_date, limits_requested, retention_requested, prior_carrier, prior_premium, securities_class_action_history, regulatory_investigation_history, merger_acquisition_activity, ipo_planned, going_concern_opinion, non_renewed_by_carrier. For each field: extract the value exactly as stated, assign confidence (0.0-1.0), and if not found, set to null with confidence 0.0. Never invent values. Return only valid JSON.",
        api_role="system", governance_tier="behavioural", lifecycle_state="champion",
        change_summary="Initial extraction instruction with 20-field schema", sensitivity_level="high", author_name="James Okafor",
    )
    pv[("field_extractor_instruction", 1)] = r["id"]

    # ── Field extractor input template
    r = await verity.registry.register_prompt_version(
        prompt_id=prompts["field_extractor_input"], version_number=1,
        content="ACORD 855 document text:\n{{document_text}}",
        api_role="user", governance_tier="formatting", lifecycle_state="champion",
        change_summary="Simple ACORD 855 text input wrapper", sensitivity_level="low", author_name="Dev Team",
    )
    pv[("field_extractor_input", 1)] = r["id"]

    print(f"  + {len(pv)} prompt versions registered")
    return pv


async def seed_prompt_assignments(verity, agent_versions, task_versions, prompt_versions):
    """Link current prompt versions to champion entity versions."""

    assignments = [
        # Triage agent v1.0.0 gets system prompt v2 + context template v1
        ("agent", agent_versions[("triage_agent", "1.0.0")],
         prompt_versions[("triage_agent_system", 2)], "system", "behavioural", 1, True),
        ("agent", agent_versions[("triage_agent", "1.0.0")],
         prompt_versions[("triage_agent_context", 1)], "user", "contextual", 2, True),

        # Appetite agent v1.0.0
        ("agent", agent_versions[("appetite_agent", "1.0.0")],
         prompt_versions[("appetite_agent_system", 1)], "system", "behavioural", 1, True),
        ("agent", agent_versions[("appetite_agent", "1.0.0")],
         prompt_versions[("appetite_agent_context", 1)], "user", "contextual", 2, True),

        # Document classifier v1.0.0 gets instruction v2 + input v1
        ("task", task_versions[("document_classifier", "1.0.0")],
         prompt_versions[("doc_classifier_instruction", 2)], "system", "behavioural", 1, True),
        ("task", task_versions[("document_classifier", "1.0.0")],
         prompt_versions[("doc_classifier_input", 1)], "user", "formatting", 2, True),

        # Field extractor v1.0.0
        ("task", task_versions[("field_extractor", "1.0.0")],
         prompt_versions[("field_extractor_instruction", 1)], "system", "behavioural", 1, True),
        ("task", task_versions[("field_extractor", "1.0.0")],
         prompt_versions[("field_extractor_input", 1)], "user", "formatting", 2, True),
    ]

    for entity_type, version_id, pv_id, api_role, gov_tier, order, required in assignments:
        await verity.registry.assign_prompt(
            entity_type=entity_type, entity_version_id=version_id,
            prompt_version_id=pv_id, api_role=api_role, governance_tier=gov_tier,
            execution_order=order, is_required=required, condition_logic=None,
        )
    print(f"  + {len(assignments)} prompt assignments created")


async def seed_tool_authorizations(verity, agent_versions, tools):
    """Authorize tools for agent versions."""
    auth = [
        # Triage agent tools
        (agent_versions[("triage_agent", "1.0.0")], tools["get_submission_context"]),
        (agent_versions[("triage_agent", "1.0.0")], tools["get_underwriting_guidelines"]),
        (agent_versions[("triage_agent", "1.0.0")], tools["get_loss_history"]),
        (agent_versions[("triage_agent", "1.0.0")], tools["get_enrichment_data"]),
        (agent_versions[("triage_agent", "1.0.0")], tools["store_triage_result"]),
        # Appetite agent tools
        (agent_versions[("appetite_agent", "1.0.0")], tools["get_submission_context"]),
        (agent_versions[("appetite_agent", "1.0.0")], tools["get_underwriting_guidelines"]),
        (agent_versions[("appetite_agent", "1.0.0")], tools["update_appetite_status"]),
    ]

    for av_id, tool_id in auth:
        await verity.registry.authorize_agent_tool(
            agent_version_id=av_id, tool_id=tool_id, authorized=True, notes=None,
        )
    print(f"  + {len(auth)} tool authorizations created")


# ══════════════════════════════════════════════════════════════
# STEP 8: PIPELINE
# ══════════════════════════════════════════════════════════════

async def seed_pipeline(verity: Verity) -> dict:
    """Register the UW submission pipeline."""
    r = await verity.registry.register_pipeline(
        name="uw_submission_pipeline",
        display_name="Underwriting Submission Processing Pipeline",
        description="Full submission processing pipeline from document classification through risk triage and appetite assessment. Orchestrates tasks and agents in dependency order.",
    )
    pipeline_id = r["id"]

    steps = [
        {"step_order": 1, "step_name": "classify_documents", "entity_type": "task",
         "entity_name": "document_classifier", "depends_on": [], "parallel_group": None,
         "error_policy": "fail_pipeline"},
        {"step_order": 2, "step_name": "extract_fields", "entity_type": "task",
         "entity_name": "field_extractor", "depends_on": ["classify_documents"], "parallel_group": None,
         "error_policy": "continue_with_flag"},
        {"step_order": 3, "step_name": "triage_submission", "entity_type": "agent",
         "entity_name": "triage_agent", "depends_on": ["extract_fields"], "parallel_group": None,
         "error_policy": "fail_pipeline"},
        {"step_order": 4, "step_name": "assess_appetite", "entity_type": "agent",
         "entity_name": "appetite_agent", "depends_on": ["triage_submission"], "parallel_group": None,
         "error_policy": "continue_with_flag"},
    ]

    pv = await verity.registry.register_pipeline_version(
        pipeline_id=pipeline_id, version_number=1, lifecycle_state="champion",
        steps=steps, change_summary="Initial 4-step pipeline: classify → extract → triage → appetite",
        developer_name="Dev Team",
    )

    # Set the champion pointer on the pipeline so get_pipeline_by_name() resolves steps
    await verity.db.execute_raw(
        "UPDATE pipeline SET current_champion_version_id = %(version_id)s WHERE id = %(pipeline_id)s",
        {"version_id": str(pv["id"]), "pipeline_id": str(pipeline_id)},
    )

    print(f"  + pipeline: uw_submission_pipeline (4 steps)")
    return {"id": pipeline_id}


# ══════════════════════════════════════════════════════════════
# STEPS 9-10: TEST SUITES + CASES
# ══════════════════════════════════════════════════════════════

async def seed_test_suites(verity, agents, tasks) -> dict:
    """Register test suites and cases. Returns {suite_name: {suite_id, cases: [...]}}."""
    suites = {}

    suite_defs = [
        {
            "name": "document_classifier_unit",
            "description": "Unit tests for document classification task",
            "entity_type": "task", "entity_id": tasks["document_classifier"]["id"],
            "suite_type": "unit", "created_by": "Dev Team",
            "cases": [
                {"name": "classify_acord_855", "description": "Should classify ACORD 855 form correctly",
                 "input_data": {"document_text": "ACORD 855 DIRECTORS AND OFFICERS LIABILITY APPLICATION Named Insured: Acme Corp...", "document_filename": "test.pdf"},
                 "expected_output": {"document_type": "acord_855", "confidence": 0.95},
                 "metric_type": "classification_f1", "metric_config": {"classes": ["acord_855", "acord_125", "loss_runs", "other"]}},
                {"name": "classify_loss_runs", "description": "Should classify loss run document correctly",
                 "input_data": {"document_text": "LOSS RUN REPORT Policy Period: 2022-2023 Claims Summary...", "document_filename": "losses.pdf"},
                 "expected_output": {"document_type": "loss_runs", "confidence": 0.92},
                 "metric_type": "classification_f1", "metric_config": None},
                {"name": "classify_supplemental", "description": "Should classify supplemental D&O application",
                 "input_data": {"document_text": "SUPPLEMENTAL D&O APPLICATION Additional Information: Board composition...", "document_filename": "supp.pdf"},
                 "expected_output": {"document_type": "supplemental_do", "confidence": 0.88},
                 "metric_type": "classification_f1", "metric_config": None},
            ],
        },
        {
            "name": "field_extractor_unit",
            "description": "Unit tests for ACORD 855 field extraction",
            "entity_type": "task", "entity_id": tasks["field_extractor"]["id"],
            "suite_type": "unit", "created_by": "Dev Team",
            "cases": [
                {"name": "extract_complete_form", "description": "Extract all fields from a complete ACORD 855",
                 "input_data": {"document_text": "Named Insured: Acme Dynamics LLC FEIN: 12-3456789 Revenue: $50,000,000...", "submission_id": "test-001"},
                 "expected_output": {"fields": {"named_insured": "Acme Dynamics LLC", "fein": "12-3456789", "annual_revenue": 50000000}, "extraction_complete": True},
                 "metric_type": "field_accuracy", "metric_config": {"required_fields": ["named_insured", "fein", "annual_revenue"], "tolerance": 0.90}},
                {"name": "extract_partial_form", "description": "Handle partial form with missing fields",
                 "input_data": {"document_text": "Named Insured: TechFlow Inc Revenue: Not provided...", "submission_id": "test-002"},
                 "expected_output": {"fields": {"named_insured": "TechFlow Inc"}, "low_confidence_fields": ["annual_revenue"], "extraction_complete": False},
                 "metric_type": "field_accuracy", "metric_config": None},
                {"name": "extract_empty_form", "description": "Handle empty/unreadable document gracefully",
                 "input_data": {"document_text": "[illegible scan]", "submission_id": "test-003"},
                 "expected_output": {"fields": {}, "extraction_complete": False},
                 "metric_type": "field_accuracy", "metric_config": None},
            ],
        },
        {
            "name": "triage_agent_unit",
            "description": "Unit tests for submission risk triage agent",
            "entity_type": "agent", "entity_id": agents["triage_agent"]["id"],
            "suite_type": "unit", "created_by": "Dev Team",
            "cases": [
                {"name": "triage_green_risk", "description": "Clean submission should score Green",
                 "input_data": {"submission_id": "test-green", "lob": "DO", "named_insured": "SafeCorp LLC"},
                 "expected_output": {"risk_score": "Green", "routing": "assign_to_uw"},
                 "metric_type": "classification_f1", "metric_config": {"classes": ["Green", "Amber", "Red"]}},
                {"name": "triage_amber_risk", "description": "Borderline submission should score Amber",
                 "input_data": {"submission_id": "test-amber", "lob": "DO", "named_insured": "RiskyCorp Inc"},
                 "expected_output": {"risk_score": "Amber", "routing": "assign_to_senior_uw"},
                 "metric_type": "classification_f1", "metric_config": None},
                {"name": "triage_red_risk", "description": "High-risk submission should score Red",
                 "input_data": {"submission_id": "test-red", "lob": "GL", "named_insured": "DangerCo LLC"},
                 "expected_output": {"risk_score": "Red", "routing": "refer_to_management"},
                 "metric_type": "classification_f1", "metric_config": None},
            ],
        },
        {
            "name": "appetite_agent_unit",
            "description": "Unit tests for appetite assessment agent",
            "entity_type": "agent", "entity_id": agents["appetite_agent"]["id"],
            "suite_type": "unit", "created_by": "Dev Team",
            "cases": [
                {"name": "appetite_within", "description": "Standard submission within appetite",
                 "input_data": {"submission_id": "test-in", "lob": "DO", "named_insured": "StandardCorp"},
                 "expected_output": {"determination": "within_appetite"},
                 "metric_type": "classification_f1", "metric_config": {"classes": ["within_appetite", "borderline", "outside_appetite"]}},
                {"name": "appetite_borderline", "description": "Submission on appetite boundary",
                 "input_data": {"submission_id": "test-border", "lob": "GL", "named_insured": "EdgeCase LLC"},
                 "expected_output": {"determination": "borderline"},
                 "metric_type": "classification_f1", "metric_config": None},
                {"name": "appetite_outside", "description": "Submission clearly outside appetite",
                 "input_data": {"submission_id": "test-out", "lob": "DO", "named_insured": "CryptoCoin Inc"},
                 "expected_output": {"determination": "outside_appetite"},
                 "metric_type": "classification_f1", "metric_config": None},
            ],
        },
    ]

    for sd in suite_defs:
        cases_data = sd.pop("cases")
        sr = await verity.registry.register_test_suite(**sd)
        suite_id = sr["id"]
        case_ids = []
        for c in cases_data:
            c["suite_id"] = suite_id
            c["is_adversarial"] = False
            c["tags"] = []
            cr = await verity.registry.register_test_case(**c)
            case_ids.append({"id": cr["id"], **c})
        suites[sd["name"]] = {"suite_id": suite_id, "entity_type": sd["entity_type"],
                               "entity_id": sd["entity_id"], "cases": case_ids}
        print(f"  + test_suite: {sd['name']} ({len(case_ids)} cases)")

    return suites


# ══════════════════════════════════════════════════════════════
# STEPS 11-12: PROMOTE TO CHAMPION
# ══════════════════════════════════════════════════════════════

async def promote_to_champion(verity, agent_versions, task_versions, agents, tasks):
    """Promote all v1.0.0 versions: draft → candidate → champion."""
    promotions = [
        ("agent", agent_versions[("triage_agent", "1.0.0")], "triage_agent"),
        ("agent", agent_versions[("appetite_agent", "1.0.0")], "appetite_agent"),
        ("task", task_versions[("document_classifier", "1.0.0")], "document_classifier"),
        ("task", task_versions[("field_extractor", "1.0.0")], "field_extractor"),
    ]

    for entity_type, version_id, name in promotions:
        # Draft → Candidate
        await verity.promote(
            entity_type=entity_type, entity_version_id=version_id,
            target_state="candidate", approver_name="Dev Team",
            rationale=f"Development complete for {name}",
        )
        # Candidate → Champion (fast-track for demo seeding)
        await verity.promote(
            entity_type=entity_type, entity_version_id=version_id,
            target_state="champion", approver_name="Sarah Chen, Chief Actuary",
            rationale=f"Ground truth validation passed for {name}. Model card approved.",
            ground_truth_reviewed=True, model_card_reviewed=True,
        )
        print(f"  + promoted {name} v1.0.0 → champion")


# ══════════════════════════════════════════════════════════════
# STEPS 13-16: VALIDATION, MODEL CARDS, THRESHOLDS
# ══════════════════════════════════════════════════════════════

async def seed_governance_artifacts(verity, agents, tasks, agent_versions, task_versions):
    """Seed ground truth datasets, validation runs, model cards, and metric thresholds."""

    # Ground truth datasets
    gt_classifier = await verity.registry.register_ground_truth_dataset(
        entity_type="task", entity_id=tasks["document_classifier"]["id"],
        name="classifier_ground_truth_v1", version=1,
        description="200 SME-labeled insurance documents (50 per major type)",
        lob=None, record_count=200, minio_bucket="ground-truth-datasets",
        minio_key="document_classifier/v1/dataset.json",
        labeled_by_sme="Maria Santos, Senior UW", reviewed_by="James Okafor, Model Risk",
    )

    gt_triage = await verity.registry.register_ground_truth_dataset(
        entity_type="agent", entity_id=agents["triage_agent"]["id"],
        name="triage_ground_truth_v1", version=1,
        description="20 SME-labeled submissions with risk scores and routing decisions",
        lob=None, record_count=20, minio_bucket="ground-truth-datasets",
        minio_key="triage_agent/v1/dataset.json",
        labeled_by_sme="James Okafor, Model Risk", reviewed_by="Sarah Chen, Chief Actuary",
    )

    # Validation runs
    await verity.registry.register_validation_run(
        entity_type="task", entity_version_id=task_versions[("document_classifier", "1.0.0")],
        dataset_id=gt_classifier["id"], run_by="James Okafor",
        precision_score=0.9600, recall_score=0.9400, f1_score=0.9500,
        cohens_kappa=None, confusion_matrix={"acord_855": {"acord_855": 48, "other": 2}, "loss_runs": {"loss_runs": 47, "other": 3}},
        field_accuracy=None, overall_extraction_rate=None, low_confidence_rate=None,
        fairness_metrics=None, fairness_passed=None, fairness_notes=None,
        thresholds_met=True, threshold_details={"f1": {"required": 0.92, "achieved": 0.95, "passed": True}},
        inference_config_snapshot={"config_name": "classification_strict", "model_name": "claude-sonnet-4-20250514", "temperature": 0.0},
        passed=True, notes="All metric thresholds met. 200 documents validated.",
    )

    await verity.registry.register_validation_run(
        entity_type="agent", entity_version_id=agent_versions[("triage_agent", "1.0.0")],
        dataset_id=gt_triage["id"], run_by="Sarah Chen",
        precision_score=0.8800, recall_score=0.8500, f1_score=0.8600,
        cohens_kappa=0.7800, confusion_matrix={"Green": {"Green": 8, "Amber": 1}, "Amber": {"Amber": 6, "Red": 1}, "Red": {"Red": 4}},
        field_accuracy=None, overall_extraction_rate=None, low_confidence_rate=None,
        fairness_metrics={"sic_parity": 0.02, "geo_parity": 0.01}, fairness_passed=True, fairness_notes="No significant disparate impact detected",
        thresholds_met=True, threshold_details={"f1": {"required": 0.83, "achieved": 0.86, "passed": True}, "kappa": {"required": 0.75, "achieved": 0.78, "passed": True}},
        inference_config_snapshot={"config_name": "triage_balanced", "model_name": "claude-sonnet-4-20250514", "temperature": 0.2},
        passed=True, notes="All thresholds met. Fairness analysis passed. 20 submissions validated.",
    )
    print(f"  + 2 ground truth datasets, 2 validation runs")

    # Model cards (high materiality agents only)
    await verity.registry.register_model_card(
        entity_type="agent", entity_version_id=agent_versions[("triage_agent", "1.0.0")], card_version=1,
        purpose="First-pass risk assessment for commercial insurance submissions, scoring Green/Amber/Red with routing recommendations.",
        design_rationale="LLM-based multi-factor synthesis chosen because risk triage requires reasoning across competing factors from heterogeneous data sources. Rule-based approaches cannot capture the nuanced interactions between financial, litigation, and governance risk indicators.",
        inputs_description="Submission data, account enrichment (LexisNexis, D&B), loss history, underwriting guidelines. All retrieved via governed tool calls.",
        outputs_description="Structured JSON with risk_score (G/A/R), routing recommendation, confidence, reasoning narrative, and itemized risk/mitigating factors.",
        known_limitations="Sensitive to system prompt phrasing; limited to D&O and GL lines; may over-weight recent loss history; requires complete submission data for accurate assessment.",
        conditions_of_use="Must be used with HITL review for premiums above $500K. Not approved for auto-decline. Triage output is advisory — underwriter makes final decision.",
        lm_specific_limitations="Output quality depends on Claude model version; temperature 0.2 provides consistency but may miss edge cases at extremes.",
        prompt_sensitivity_notes="v2 system prompt tested against 5 paraphrasings with <3% variance in risk score distribution.",
        validated_by="Sarah Chen, Chief Actuary", validation_run_id=None,
        validation_notes="Validated against 20 SME-labeled submissions. F1=0.86, Kappa=0.78.",
        regulatory_notes="SR 11-7 High materiality model. ASOP 56 §3.8 limitations disclosed.",
        materiality_classification="High — directly influences underwriting accept/decline decisions.",
        approved_by="Sarah Chen", approved_at=datetime.now().isoformat(), lifecycle_state="approved",
    )

    await verity.registry.register_model_card(
        entity_type="agent", entity_version_id=agent_versions[("appetite_agent", "1.0.0")], card_version=1,
        purpose="Determine whether a submission falls within underwriting appetite based on published guidelines.",
        design_rationale="LLM retrieval-and-reasoning approach chosen because appetite assessment requires comparing submission characteristics against complex guideline documents with section-specific criteria.",
        inputs_description="Submission details and underwriting guidelines document. Retrieved via governed tool calls.",
        outputs_description="Structured JSON with determination (within/borderline/outside), confidence, reasoning, and specific guideline section citations.",
        known_limitations="Dependent on guidelines document completeness; cannot assess risks not covered by guidelines; may miss nuanced appetite exceptions approved verbally.",
        conditions_of_use="Appetite determination is advisory. Exceptions require senior underwriter approval.",
        lm_specific_limitations=None, prompt_sensitivity_notes=None,
        validated_by="James Okafor, Model Risk", validation_run_id=None,
        validation_notes="Qualitative review against 10 historical appetite decisions. Agreement rate 90%.",
        regulatory_notes="SR 11-7 High materiality. May influence adverse action decisions.",
        materiality_classification="High — appetite determination can lead to submission decline.",
        approved_by="Sarah Chen", approved_at=datetime.now().isoformat(), lifecycle_state="approved",
    )
    print(f"  + 2 model cards")

    # Metric thresholds
    thresholds = [
        ("agent", agents["triage_agent"]["id"], "high", "f1_score", 0.8300, 0.8800),
        ("agent", agents["appetite_agent"]["id"], "high", "f1_score", 0.8600, 0.9000),
        ("task", tasks["document_classifier"]["id"], "medium", "f1_score", 0.9200, 0.9600),
        ("task", tasks["field_extractor"]["id"], "medium", "field_accuracy", 0.9000, 0.9500),
    ]
    for et, eid, tier, metric, min_val, target in thresholds:
        await verity.registry.register_metric_threshold(
            entity_type=et, entity_id=eid, materiality_tier=tier,
            metric_name=metric, minimum_acceptable=min_val, target_champion=target,
        )
    print(f"  + 4 metric thresholds")


# ══════════════════════════════════════════════════════════════
# STEP 17: TEST EXECUTION LOGS
# ══════════════════════════════════════════════════════════════

async def seed_test_results(verity, test_suites, agent_versions, task_versions):
    """Pre-seed passing test results for champion versions."""
    version_map = {
        "document_classifier": ("task", task_versions[("document_classifier", "1.0.0")]),
        "field_extractor": ("task", task_versions[("field_extractor", "1.0.0")]),
        "triage_agent": ("agent", agent_versions[("triage_agent", "1.0.0")]),
        "appetite_agent": ("agent", agent_versions[("appetite_agent", "1.0.0")]),
    }

    count = 0
    for suite_name, suite_data in test_suites.items():
        # Determine which entity version this suite targets
        entity_name = suite_name.replace("_unit", "")
        if entity_name not in version_map:
            continue
        entity_type, version_id = version_map[entity_name]

        for case in suite_data["cases"]:
            await verity.testing.log_test_result(
                suite_id=suite_data["suite_id"],
                entity_type=entity_type,
                entity_version_id=version_id,
                test_case_id=case["id"],
                mock_mode=True, channel="staging",
                input_used=case["input_data"],
                actual_output=case["expected_output"],  # Pre-seeded as passing
                expected_output=case["expected_output"],
                metric_type=case["metric_type"],
                metric_result={"passed": True, "score": 0.95},
                passed=True, failure_reason=None,
                duration_ms=1200,
                inference_config_snapshot={"config_name": "test_run", "temperature": 0.0},
            )
            count += 1
    print(f"  + {count} test execution logs (all passing)")


# ══════════════════════════════════════════════════════════════
# STEPS 18-19: DECISION LOGS + OVERRIDES
# ══════════════════════════════════════════════════════════════

async def seed_decisions(verity, agent_versions, task_versions):
    """Pre-seed 16 decision logs (4 submissions × 4 steps) + 2 overrides."""

    # Submission IDs — fixed UUIDs for consistency
    submissions = [
        {"id": "00000001-0001-0001-0001-000000000001", "name": "Acme Dynamics D&O", "lob": "DO",
         "classifier_output": {"document_type": "acord_855", "confidence": 0.97, "classification_notes": "Clear ACORD 855 D&O application header"},
         "extractor_output": {"fields": {"named_insured": "Acme Dynamics LLC", "annual_revenue": 50000000, "employee_count": 250, "board_size": 7}, "low_confidence_fields": [], "extraction_complete": True},
         "triage_output": {"risk_score": "Green", "routing": "assign_to_uw", "confidence": 0.89, "reasoning": "Strong financials, clean loss history, experienced board. Standard D&O risk profile.", "risk_factors": [{"factor": "Revenue concentration", "severity": "low", "detail": "Single market segment"}]},
         "appetite_output": {"determination": "within_appetite", "confidence": 0.92, "reasoning": "Meets all D&O guidelines criteria per §2.1-2.4.", "guideline_citations": [{"section": "§2.1", "criterion": "Revenue > $10M", "meets": True}]}},

        {"id": "00000002-0002-0002-0002-000000000002", "name": "TechFlow Industries D&O", "lob": "DO",
         "classifier_output": {"document_type": "acord_855", "confidence": 0.94, "classification_notes": "ACORD 855 with some non-standard formatting"},
         "extractor_output": {"fields": {"named_insured": "TechFlow Industries Inc", "annual_revenue": 120000000, "employee_count": 800, "board_size": 9}, "low_confidence_fields": ["regulatory_investigation_history"], "extraction_complete": True},
         "triage_output": {"risk_score": "Amber", "routing": "assign_to_senior_uw", "confidence": 0.72, "reasoning": "Mixed profile. Strong revenue but pending regulatory investigation and recent board turnover raise concerns.", "risk_factors": [{"factor": "Regulatory investigation", "severity": "medium", "detail": "SEC inquiry pending"}, {"factor": "Board turnover", "severity": "low", "detail": "3 directors replaced in 12 months"}]},
         "appetite_output": {"determination": "borderline", "confidence": 0.65, "reasoning": "Meets most criteria but §3.2 flags pending regulatory matters.", "guideline_citations": [{"section": "§3.2", "criterion": "No pending regulatory investigations", "meets": False}]}},

        {"id": "00000003-0003-0003-0003-000000000003", "name": "Meridian Holdings GL", "lob": "GL",
         "classifier_output": {"document_type": "acord_125", "confidence": 0.91, "classification_notes": "General liability application form"},
         "extractor_output": {"fields": {"named_insured": "Meridian Holdings Corp", "annual_revenue": 25000000, "employee_count": 150}, "low_confidence_fields": ["prior_premium"], "extraction_complete": True},
         "triage_output": {"risk_score": "Red", "routing": "refer_to_management", "confidence": 0.85, "reasoning": "High claims frequency, going concern qualification, and industry in excluded SIC codes.", "risk_factors": [{"factor": "Claims frequency", "severity": "high", "detail": "12 claims in 3 years"}, {"factor": "Going concern", "severity": "critical", "detail": "Auditor qualified opinion"}]},
         "appetite_output": {"determination": "outside_appetite", "confidence": 0.94, "reasoning": "Multiple guideline violations: §4.1 excluded SIC code, §4.3 going concern disqualification.", "guideline_citations": [{"section": "§4.1", "criterion": "SIC code not excluded", "meets": False}, {"section": "§4.3", "criterion": "No going concern opinion", "meets": False}]}},

        {"id": "00000004-0004-0004-0004-000000000004", "name": "Acme Dynamics GL", "lob": "GL",
         "classifier_output": {"document_type": "acord_125", "confidence": 0.93, "classification_notes": "Standard GL application"},
         "extractor_output": {"fields": {"named_insured": "Acme Dynamics LLC", "annual_revenue": 50000000, "employee_count": 250}, "low_confidence_fields": [], "extraction_complete": True},
         "triage_output": {"risk_score": "Amber", "routing": "assign_to_senior_uw", "confidence": 0.74, "reasoning": "Adequate financials but GL exposure from manufacturing operations and moderate claims history.", "risk_factors": [{"factor": "Manufacturing operations", "severity": "medium", "detail": "Products liability exposure"}, {"factor": "Claims trend", "severity": "low", "detail": "Increasing frequency, stable severity"}]},
         "appetite_output": {"determination": "within_appetite", "confidence": 0.81, "reasoning": "Meets GL criteria. Manufacturing operations within acceptable risk classes per §5.2.", "guideline_citations": [{"section": "§5.2", "criterion": "Manufacturing SIC codes allowed", "meets": True}]}},
    ]

    step_configs = [
        ("classify_documents", "task", task_versions[("document_classifier", "1.0.0")], "classifier_output",
         "classification_strict", "claude-sonnet-4-20250514", 0.0, 512),
        ("extract_fields", "task", task_versions[("field_extractor", "1.0.0")], "extractor_output",
         "extraction_deterministic", "claude-sonnet-4-20250514", 0.0, 2048),
        ("triage_submission", "agent", agent_versions[("triage_agent", "1.0.0")], "triage_output",
         "triage_balanced", "claude-sonnet-4-20250514", 0.2, 4096),
        ("assess_appetite", "agent", agent_versions[("appetite_agent", "1.0.0")], "appetite_output",
         "triage_balanced", "claude-sonnet-4-20250514", 0.2, 4096),
    ]

    # Fixed pipeline_run_id per submission — predictable so the UW app
    # can reference them in SUBMISSIONS list for "View in Verity" links.
    # These are Verity-owned IDs, not business keys.
    PIPELINE_RUN_IDS = {
        "00000001-0001-0001-0001-000000000001": "aaaa0001-0001-0001-0001-000000000001",
        "00000002-0002-0002-0002-000000000002": "aaaa0002-0002-0002-0002-000000000002",
        "00000003-0003-0003-0003-000000000003": "aaaa0003-0003-0003-0003-000000000003",
        "00000004-0004-0004-0004-000000000004": "aaaa0004-0004-0004-0004-000000000004",
    }

    decision_count = 0
    override_decisions = []

    for sub in submissions:
        pipeline_run_id = PIPELINE_RUN_IDS[sub["id"]]
        for step_name, entity_type, version_id, output_key, config_name, model, temp, max_tok in step_configs:
            output = sub[output_key]

            from verity.models.decision import DecisionLogCreate
            from verity.models.lifecycle import DeploymentChannel, EntityType as ET

            log_result = await verity.decisions.log_decision(DecisionLogCreate(
                entity_type=ET(entity_type),
                entity_version_id=version_id,
                prompt_version_ids=[],
                inference_config_snapshot={"config_name": config_name, "model_name": model, "temperature": temp, "max_tokens": max_tok},
                submission_id=sub["id"],
                channel=DeploymentChannel.PRODUCTION,
                pipeline_run_id=pipeline_run_id,
                parent_decision_id=None,
                decision_depth=0,
                step_name=step_name,
                input_summary=f"{sub['name']} — {sub['lob']}",
                input_json={"submission_id": sub["id"], "lob": sub["lob"], "named_insured": sub["name"]},
                output_json=output,
                output_summary=json.dumps(output)[:300],
                reasoning_text=output.get("reasoning", ""),
                risk_factors={"factors": output.get("risk_factors", [])} if "risk_factors" in output else None,
                confidence_score=output.get("confidence"),
                model_used=model,
                input_tokens=1500 + (decision_count * 100),
                output_tokens=800 + (decision_count * 50),
                duration_ms=2000 + (decision_count * 300),
                status="complete",
            ))

            # Track triage decisions for SUB-002 and appetite for SUB-003 (will override)
            if sub["id"] == submissions[1]["id"] and step_name == "triage_submission":
                override_decisions.append(("triage", log_result["decision_log_id"], version_id, sub["id"]))
            if sub["id"] == submissions[2]["id"] and step_name == "assess_appetite":
                override_decisions.append(("appetite", log_result["decision_log_id"], version_id, sub["id"]))

            decision_count += 1

    print(f"  + {decision_count} decision logs (4 submissions × 4 steps)")

    # Seed overrides
    from verity.models.decision import OverrideLogCreate
    from verity.models.lifecycle import EntityType as ET

    for override_type, decision_id, version_id, sub_id in override_decisions:
        if override_type == "triage":
            await verity.decisions.record_override(OverrideLogCreate(
                decision_log_id=decision_id,
                entity_type=ET.AGENT, entity_version_id=version_id,
                overrider_name="David Park", overrider_role="Senior Underwriter",
                override_reason_code="risk_assessment_disagree",
                override_notes="Regulatory investigation is routine SEC review, not enforcement action. Downgrading risk assessment from Amber to Green based on direct discussion with insured's counsel.",
                ai_recommendation={"risk_score": "Amber", "routing": "assign_to_senior_uw"},
                human_decision={"risk_score": "Green", "routing": "assign_to_uw"},
                submission_id=sub_id,
            ))
        elif override_type == "appetite":
            await verity.decisions.record_override(OverrideLogCreate(
                decision_log_id=decision_id,
                entity_type=ET.AGENT, entity_version_id=version_id,
                overrider_name="Lisa Wong", overrider_role="VP Underwriting",
                override_reason_code="client_relationship",
                override_notes="Long-standing client relationship with strong premium history. Accepting despite guideline §4.1 SIC code exclusion per management exception protocol.",
                ai_recommendation={"determination": "outside_appetite"},
                human_decision={"determination": "within_appetite", "exception_approved": True},
                submission_id=sub_id,
            ))

    print(f"  + {len(override_decisions)} override logs")


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(main())
