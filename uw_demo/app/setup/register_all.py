"""Seed Script — Register all demo entities in Verity.

This script populates the Verity database with demo-ready data:
- 5 inference configs
- 11 tools (8 UW + 2 EDMS + 1 extraction storage)
- 2 agents (triage, appetite) with 2 versions each
- 2 tasks (classifier, extractor) with 2 versions each
- 8 prompts with versioned content
- 2 multi-step workflows (orchestrated in uw_demo/app/workflows.py, not registered as Verity entities)
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
# Reads from VERITY_DB_URL environment variable (set in docker-compose.yml).
# Falls back to localhost for running outside Docker (local development).
import os
DB_URL = os.environ.get("VERITY_DB_URL", "postgresql://verityuser:veritypass123@localhost:5432/verity_db")


async def main():
    """Run the full seed process."""

    # ── STEP 0: Reset database ────────────────────────────────
    print("Step 0: Resetting database (drop + recreate schema)...")
    await apply_schema(DB_URL, drop_existing=True)

    # ── Connect Verity SDK ────────────────────────────────────
    verity = Verity(database_url=DB_URL, application="uw_demo")
    await verity.connect()

    try:
        # ── STEP 0b: Model catalog + current prices ───────────
        # Must come before inference_configs so the backfill can
        # resolve inference_config.model_id from the text model_name.
        print("Step 0b: Registering model catalog + prices...")
        await seed_models(verity)

        # ── STEP 1: Inference Configs ─────────────────────────
        print("Step 1: Registering inference configs...")
        configs = await seed_inference_configs(verity)

        # Backfill inference_config.model_id from the text model_name.
        updated = await verity.models.backfill_inference_config_model_id()
        print(f"  + backfilled inference_config.model_id on {len(updated)} rows")

        # ── STEP 1b: MCP servers ──────────────────────────────
        # Must come before tools — tool.mcp_server_name has a FK to
        # mcp_server(name).
        print("Step 1b: Registering MCP servers...")
        await seed_mcp_servers(verity)

        # ── Data connectors ───────────────────────────────────
        # Register the EDMS connector row. task_version_source rows
        # reference this by connector_id, so it must exist before task
        # versions declare their sources below. The in-process provider
        # binding happens in uw_demo/app/main.py at app startup; this
        # step only creates the governance row.
        print("Registering data connectors...")
        await seed_data_connectors(verity)

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

        # ── Task version data sources ─────────────────────────
        # Declare which task versions pull inputs from which connectors.
        # Example: document_classifier's {{document_text}} can come from
        # EDMS when the caller passes a document_ref. Declared optional —
        # callers can still pass document_text directly.
        print("Declaring task version data sources...")
        await seed_task_version_sources(verity, task_versions)

        # ── STEP 5-6: Prompt Versions + Assignments ───────────
        print("Step 5-6: Registering prompt versions and assignments...")
        prompt_versions = await seed_prompt_versions(verity, prompts)
        await seed_prompt_assignments(verity, agent_versions, task_versions, prompt_versions)

        # ── STEP 7: Tool Authorizations ───────────────────────
        print("Step 7: Authorizing tools for agent versions...")
        await seed_tool_authorizations(verity, agent_versions, tools)

        # ── STEP 7b: Sub-agent Delegation Authorizations ──────
        # FC-1: Which parent agent_versions can delegate to which
        # sub-agents. Governed separately from tool authorizations —
        # granting the delegate_to_agent tool enables the CAPABILITY,
        # this table specifies the allowed targets.
        print("Step 7b: Registering delegation authorizations...")
        await seed_delegations(verity, agent_versions)

        # ── STEP 8: Application Registration ─────────────────
        # Multi-step workflows are orchestrated in
        # uw_demo/app/workflows.py (descoped from Verity), so there's
        # no pipeline to register at the governance plane.
        print("Step 8: Registering application and mapping entities...")
        await seed_application(verity, agents, tasks, tools, prompts)

        # ── STEP 9-10: Test Suites + Cases ────────────────────
        print("Step 9-10: Registering test suites and cases...")
        test_suites = await seed_test_suites(verity, agents, tasks)

        # ── STEP 11-12: Promote to Champion ───────────────────
        print("Step 11-12: Promoting versions to champion...")
        await promote_to_champion(verity, agent_versions, task_versions, agents, tasks)

        # ── STEP 13: Governance artifacts (datasets, validation runs, model cards, thresholds)
        print("Step 13: Seeding governance artifacts...")
        gt_datasets = await seed_governance_artifacts(verity, agents, tasks, agent_versions, task_versions)

        # ── STEP 14: Upload documents to EDMS (before GT records — need doc IDs)
        print("Step 14: Uploading documents to EDMS...")
        from uw_demo.app.setup.seed_edms import seed_edms
        edms_doc_ids = await seed_edms()

        # ── STEP 15: Ground Truth Records + Annotations (uses EDMS doc IDs)
        print("Step 15: Populating ground truth records with EDMS document references...")
        await seed_ground_truth_records(verity, gt_datasets, tasks, agents, edms_doc_ids)

        # Step 16 removed: test execution logs are no longer pre-seeded.
        # Test results should come from actual test runs via the UI, not fake data.

        # ── STEP 17: Decision Logs + Overrides ────────────────
        print("Step 17: Seeding decision logs and overrides...")
        await seed_decisions(verity, agent_versions, task_versions)

        # ── STEP 18: Seed Verity platform settings ────────────
        print("Step 18: Seeding Verity platform settings...")
        await seed_platform_settings(verity)

        # ── STEP 19: Seed UW database ─────────────────────────
        print("Step 19: Seeding UW database (submissions + loss history)...")
        from uw_demo.app.setup.seed_uw import seed_uw_db
        await seed_uw_db()

        print("\n✓ Seed complete. All demo data loaded.")
        print("  Verity:  http://localhost:8000/admin/")
        print("  UW Demo: http://localhost:8001/")
        print("  EDMS:    http://localhost:8002/ui/")

    finally:
        await verity.close()


# ══════════════════════════════════════════════════════════════
# STEP 1: INFERENCE CONFIGS
# ══════════════════════════════════════════════════════════════

async def seed_models(verity: Verity) -> dict:
    """Register the models + currently-active prices Verity knows about.

    Prices are the published Anthropic API list prices as of early 2026
    (per 1M tokens). Cache-read is 10% of base input; cache-write is
    125% of base input (Anthropic's documented multipliers for prompt
    caching). Update by inserting a new model_price row via
    verity.models.set_price(...) — which sets valid_to on the prior
    row so the historical cost view stays correct.

    Returns {model_id_string: verity_model_row_id}.
    """
    models_data = [
        {
            "provider": "anthropic",
            "model_id": "claude-sonnet-4-20250514",
            "display_name": "Claude Sonnet 4",
            "context_window": 200_000,
            "description": "Balanced model — default for most Verity-governed agents and tasks.",
            "prices": {
                "input_price_per_1m": 3.00,
                "output_price_per_1m": 15.00,
                "cache_read_price_per_1m": 0.30,
                "cache_write_price_per_1m": 3.75,
            },
        },
        {
            "provider": "anthropic",
            "model_id": "claude-opus-4-20250514",
            "display_name": "Claude Opus 4",
            "context_window": 200_000,
            "description": "Highest-capability model — for complex reasoning tasks.",
            "prices": {
                "input_price_per_1m": 15.00,
                "output_price_per_1m": 75.00,
                "cache_read_price_per_1m": 1.50,
                "cache_write_price_per_1m": 18.75,
            },
        },
        {
            "provider": "anthropic",
            "model_id": "claude-haiku-4-5-20251001",
            "display_name": "Claude Haiku 4.5",
            "context_window": 200_000,
            "description": "Fast + inexpensive model — for high-volume classification tasks.",
            "prices": {
                "input_price_per_1m": 0.80,
                "output_price_per_1m": 4.00,
                "cache_read_price_per_1m": 0.08,
                "cache_write_price_per_1m": 1.00,
            },
        },
    ]

    result: dict[str, str] = {}
    for m in models_data:
        prices = m.pop("prices")
        row = await verity.models.register_model(**m)
        await verity.models.set_price(
            model_pk=row["id"],
            notes="Seeded at platform setup — public Anthropic list price",
            **prices,
        )
        result[m["model_id"]] = row["id"]
        print(f"  + model: {m['provider']}/{m['model_id']}  (${prices['input_price_per_1m']:.2f} in / ${prices['output_price_per_1m']:.2f} out per 1M)")
    return result


async def seed_inference_configs(verity: Verity) -> dict:
    """Register 5 named inference configs. Returns {name: id}."""
    configs_data = [
        {
            "name": "classification_strict",
            "display_name": "Classification Strict",
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
            "display_name": "Extraction Deterministic",
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
            "display_name": "Triage Balanced",
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
            "display_name": "Generation Narrative",
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
            "display_name": "Renewal Analytical",
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
# STEP 1b: MCP SERVERS
# Register the in-repo MCP servers Verity knows about. Tools registered
# with transport='mcp_stdio' reference these by name via mcp_server_name.
# MCP servers must be seeded BEFORE tools because the tool table has a
# foreign key to mcp_server(name).
# ══════════════════════════════════════════════════════════════

async def seed_mcp_servers(verity: Verity) -> dict:
    """Register the demo MCP servers. Returns {name: id}."""
    servers = [
        {
            "name": "duckduckgo",
            "display_name": "DuckDuckGo Web Search",
            "description": (
                "DuckDuckGo web search via the ddgs Python package. No API "
                "key, no account — uses the free HTML search endpoint. "
                "Spawned as a stdio subprocess on first tool call; kept "
                "alive for the process lifetime and terminated on "
                "Verity.close()."
            ),
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "mcp_servers.duckduckgo.server"],
            "env": {},
            "auth_config": {},
        },
        {
            "name": "enrichment",
            "display_name": "Company Enrichment Data Providers",
            "description": (
                "Simulated third-party enrichment data for UW triage: "
                "LexisNexis, Dun & Bradstreet, PitchBook, FactSet. "
                "Curated profiles for the demo's four seeded insureds "
                "plus deterministic synthetic fallback for any other "
                "company name. In production this server would be "
                "replaced by real API integrations; the tool contract "
                "would be unchanged."
            ),
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "mcp_servers.enrichment.server"],
            "env": {},
            "auth_config": {},
        },
    ]
    result = {}
    for s in servers:
        r = await verity.registry.register_mcp_server(**s)
        result[s["name"]] = r["id"]
    print(f"  + {len(result)} MCP servers registered")
    return result


# ══════════════════════════════════════════════════════════════
# DATA CONNECTORS
# Register the integrations Tasks can declare sources/targets against.
# One row per connector name. The matching in-process provider (e.g.
# EdmsProvider) is registered at app startup in uw_demo/app/main.py.
# ══════════════════════════════════════════════════════════════

async def seed_data_connectors(verity: Verity) -> dict:
    """Register UW's data connectors. Returns {name: id}.

    Called during initial seed. Idempotent via upsert_data_connector so
    re-running the seed is safe. Secrets (API keys, auth tokens) are NOT
    stored here — providers read them from env vars at startup.
    """
    import json as _json
    connectors = [
        {
            "name": "edms",
            "connector_type": "edms",
            "display_name": "EDMS — Enterprise Document Management",
            "description": (
                "HTTP integration with the EDMS service. Provides "
                "document text, metadata, and lineage for Tasks that "
                "declare document sources. Base URL comes from EDMS_URL "
                "env var on the consuming app's process."
            ),
            "config": {},   # non-secret tuning only; empty for now
            "owner_name": "Platform Team",
        },
    ]
    result = {}
    for c in connectors:
        row = await verity.db.execute_returning("upsert_data_connector", {
            **c,
            "config": _json.dumps(c["config"]),
        })
        result[c["name"]] = row["id"]
        print(f"  + data connector: {c['name']}")
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
            "mock_mode_enabled": False, "mock_response_key": "default",
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
            "mock_mode_enabled": False, "mock_response_key": "default",
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
            "mock_mode_enabled": False, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "documents"],
        },
        {
            "name": "get_loss_history",
            "display_name": "Get Loss History",
            "description": "Retrieves historical loss run data for the given submission. Takes the submission UUID (the same value passed in the pipeline context as submission_id). Returns annual loss records with claim counts, incurred, paid, and reserves.",
            "input_schema": {"type": "object", "properties": {"submission_id": {"type": "string", "description": "The submission UUID — the same value available in the pipeline context."}}, "required": ["submission_id"]},
            "output_schema": {"type": "object", "properties": {"years": {"type": "array"}, "total_incurred": {"type": "number"}}},
            "implementation_path": "uw_demo.app.tools.submission_tools.get_loss_history",
            "mock_mode_enabled": False, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "losses"],
        },
        # ── MCP-sourced tools ─────────────────────────────────
        # These dispatch through verity.runtime.mcp_client.MCPClient to
        # the stdio subprocesses registered in mcp_server. Their Verity
        # registry shape is identical to python_inprocess tools except
        # for transport, mcp_server_name, and mcp_tool_name. Each call
        # logs to agent_decision_log.tool_calls_made with the transport
        # preserved, so the audit trail shows clearly which calls went
        # through MCP vs in-process Python.
        {
            "name": "web_search",
            "display_name": "Web Search (DuckDuckGo)",
            "description": "Search the public web via DuckDuckGo. Returns up to max_results text results (title, URL, snippet). Use for current events, public records, regulatory filings, news about companies, and anything not already in the agent's context.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
            "output_schema": {"type": "object", "properties": {"content": {"type": "array"}, "text": {"type": "string"}}},
            "transport": "mcp_stdio",
            "mcp_server_name": "duckduckgo",
            "mcp_tool_name": "web_search",
            "implementation_path": "mcp://duckduckgo/web_search",
            "mock_mode_enabled": False, "mock_response_key": None,
            "data_classification_max": "tier2_internal",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "mcp", "web"],
        },
        {
            "name": "lexisnexis_lookup",
            "display_name": "LexisNexis Risk Lookup",
            "description": "LexisNexis Risk — litigation history, regulatory actions, bankruptcy filings, OFAC sanctions check, adverse media hit count. Use for legal/regulatory risk assessment.",
            "input_schema": {"type": "object", "properties": {"company_name": {"type": "string"}}, "required": ["company_name"]},
            "output_schema": {"type": "object", "properties": {"content": {"type": "array"}, "text": {"type": "string"}}},
            "transport": "mcp_stdio",
            "mcp_server_name": "enrichment",
            "mcp_tool_name": "lexisnexis_lookup",
            "implementation_path": "mcp://enrichment/lexisnexis_lookup",
            "mock_mode_enabled": False, "mock_response_key": None,
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "mcp", "enrichment", "legal"],
        },
        {
            "name": "dnb_lookup",
            "display_name": "Dun & Bradstreet Lookup",
            "description": "Dun & Bradstreet — DUNS number, Financial Stress Score, Paydex score, payment performance, years in business, SIC/NAICS industry codes, verified employee count and revenue. Use for financial stability and firmographic verification.",
            "input_schema": {"type": "object", "properties": {"company_name": {"type": "string"}}, "required": ["company_name"]},
            "output_schema": {"type": "object", "properties": {"content": {"type": "array"}, "text": {"type": "string"}}},
            "transport": "mcp_stdio",
            "mcp_server_name": "enrichment",
            "mcp_tool_name": "dnb_lookup",
            "implementation_path": "mcp://enrichment/dnb_lookup",
            "mock_mode_enabled": False, "mock_response_key": None,
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "mcp", "enrichment", "credit"],
        },
        {
            "name": "pitchbook_lookup",
            "display_name": "PitchBook Lookup",
            "description": "PitchBook — company type (Private/Public), industry, founding year, total funding raised, last funding round, investor list, latest valuation, and exit history. Use for growth-stage and investor profile on private companies.",
            "input_schema": {"type": "object", "properties": {"company_name": {"type": "string"}}, "required": ["company_name"]},
            "output_schema": {"type": "object", "properties": {"content": {"type": "array"}, "text": {"type": "string"}}},
            "transport": "mcp_stdio",
            "mcp_server_name": "enrichment",
            "mcp_tool_name": "pitchbook_lookup",
            "implementation_path": "mcp://enrichment/pitchbook_lookup",
            "mock_mode_enabled": False, "mock_response_key": None,
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "mcp", "enrichment", "funding"],
        },
        {
            "name": "factset_lookup",
            "display_name": "FactSet Fundamentals Lookup",
            "description": "FactSet — ticker and exchange (if public), trailing twelve-month revenue, EBITDA margin, net debt to EBITDA, current ratio, credit rating and agency, and going-concern opinion flag. Use for financial fundamentals analysis.",
            "input_schema": {"type": "object", "properties": {"company_name": {"type": "string"}}, "required": ["company_name"]},
            "output_schema": {"type": "object", "properties": {"content": {"type": "array"}, "text": {"type": "string"}}},
            "transport": "mcp_stdio",
            "mcp_server_name": "enrichment",
            "mcp_tool_name": "factset_lookup",
            "implementation_path": "mcp://enrichment/factset_lookup",
            "mock_mode_enabled": False, "mock_response_key": None,
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "mcp", "enrichment", "financials"],
        },
        # ── Verity-builtin meta-tool ──────────────────────────
        # delegate_to_agent is the FC-1 sub-agent delegation primitive.
        # Granting this tool authorization to an agent version lets that
        # agent CALL delegate_to_agent at runtime; WHICH specific sub-agents
        # it may target is governed separately by the agent_version_delegation
        # table (seeded in seed_delegations).
        {
            "name": "delegate_to_agent",
            "display_name": "Delegate to Sub-Agent",
            "description": (
                "Verity meta-tool. Invoke another governed agent as a "
                "sub-agent during your own reasoning. Pass the target "
                "agent_name, a context dict for the sub-agent, and a short "
                "reason string. Authorized targets are governed by the "
                "agent_version_delegation registry — calls to unauthorized "
                "agents return an error listing the agents you ARE "
                "authorized to delegate to. The sub-agent's structured "
                "output is returned in the tool result for you to "
                "incorporate into your final answer. Use sparingly — only "
                "delegate when a specialist sub-agent will produce a "
                "materially better analysis than you can produce directly."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Registered Verity agent name of the sub-agent to invoke.",
                    },
                    "context": {
                        "type": "object",
                        "description": "Input context dict passed to the sub-agent (e.g., {submission_id, lob, named_insured}).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "One-sentence rationale for why delegating is appropriate here. Stored in the audit trail.",
                    },
                },
                "required": ["agent_name", "context"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "sub_decision_log_id": {"type": "string"},
                    "sub_entity_name": {"type": "string"},
                    "sub_version_label": {"type": "string"},
                    "sub_status": {"type": "string"},
                    "output": {"type": "object"},
                    "reasoning_text": {"type": "string"},
                },
            },
            "transport": "verity_builtin",
            "mcp_server_name": None,
            "mcp_tool_name": None,
            "implementation_path": "verity.runtime.engine.ExecutionEngine._delegate_to_agent",
            "mock_mode_enabled": False, "mock_response_key": None,
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False,
            "tags": ["meta", "delegation", "verity_builtin"],
        },
        {
            "name": "update_submission_event",
            "display_name": "Update Event Log",
            "description": "Logs a workflow event for a submission (e.g., 'triage_complete', 'appetite_assessed'). Used for tracking pipeline progress.",
            "input_schema": {"type": "object", "properties": {"submission_id": {"type": "string"}, "event_type": {"type": "string"}, "details": {"type": "object"}}, "required": ["submission_id", "event_type"]},
            "output_schema": {"type": "object", "properties": {"event_id": {"type": "string"}, "logged_at": {"type": "string"}}},
            "implementation_path": "uw_demo.app.tools.submission_tools.update_submission_event",
            "mock_mode_enabled": False, "mock_response_key": "default",
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
            "mock_mode_enabled": False, "mock_response_key": "default",
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
            "mock_mode_enabled": False, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": True, "requires_confirmation": False, "tags": ["write", "appetite"],
        },
        # ── EDMS document tools ──────────────────────────────────
        {
            "name": "list_documents",
            "display_name": "List Documents (EDMS)",
            "description": "Lists documents from EDMS for a business context. Returns metadata including IDs, filenames, types, and upload dates. Supports optional filtering by document type and context type.",
            "input_schema": {"type": "object", "properties": {
                "context_ref": {"type": "string", "description": "Business context reference, e.g. 'submission:00000001-0001-0001-0001-000000000001'"},
                "document_type": {"type": "string", "description": "Optional filter by document type (do_application, gl_application, loss_run, etc.)"},
                "context_type": {"type": "string", "description": "Optional filter by context type (submission, policy, claim)"},
            }, "required": ["context_ref"]},
            "output_schema": {"type": "object", "properties": {"documents": {"type": "array"}}},
            "implementation_path": "uw_demo.app.tools.edms_tools.list_documents",
            "mock_mode_enabled": False, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "documents", "edms"],
        },
        {
            "name": "get_document_text",
            "display_name": "Get Document Text (EDMS)",
            "description": "Returns the extracted text content of a specific document from EDMS by its document ID. The document must have been previously uploaded and text-extracted.",
            "input_schema": {"type": "object", "properties": {
                "document_id": {"type": "string", "description": "UUID of the document to retrieve text for"},
            }, "required": ["document_id"]},
            "output_schema": {"type": "object", "properties": {"text": {"type": "string"}, "char_count": {"type": "integer"}}},
            "implementation_path": "uw_demo.app.tools.edms_tools.get_document_text",
            "mock_mode_enabled": False, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "documents", "edms"],
        },
        # ── Extraction storage tool ──────────────────────────────
        {
            "name": "store_extraction_result",
            "display_name": "Store Extraction Result",
            "description": "Writes extracted field values from the field extraction task to uw_db. Stores per-field confidence scores and flags low-confidence or missing fields for HITL review.",
            "input_schema": {"type": "object", "properties": {
                "submission_id": {"type": "string"},
                "fields": {"type": "object", "description": "Dict of field_name -> {value, confidence, note}"},
                "low_confidence_fields": {"type": "array", "items": {"type": "string"}},
                "unextractable_fields": {"type": "array", "items": {"type": "string"}},
                "source_document_id": {"type": "string", "description": "EDMS document ID the fields were extracted from"},
            }, "required": ["submission_id", "fields"]},
            "output_schema": {"type": "object", "properties": {"stored": {"type": "boolean"}, "fields_stored": {"type": "integer"}, "fields_flagged": {"type": "integer"}}},
            "implementation_path": "uw_demo.app.tools.submission_tools.store_extraction_result",
            "mock_mode_enabled": False, "mock_response_key": "default",
            "data_classification_max": "tier3_confidential",
            "is_write_operation": True, "requires_confirmation": False, "tags": ["write", "extraction"],
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
            "display_name": "D&O Application Field Extraction Task",
            "description": "Extracts structured data fields from a D&O Directors and Officers liability D&O liability application form. Returns field values with per-field confidence scores. Does not extract from GL forms, loss runs, or supplementals.",
            "capability_type": "extraction",
            "purpose": "Populate submission detail records from D&O application text.",
            "domain": "underwriting",
            "materiality_tier": "medium",
            "input_schema": {"document_text": "string", "submission_id": "string"},
            "output_schema": {"fields": "object", "low_confidence_fields": "array", "unextractable_fields": "array", "extraction_complete": "boolean"},
            "owner_name": "James Okafor",
            "owner_email": "james.okafor@premiumiq.com",
            "business_context": "Extracts key application fields from D&O application forms to populate the submission record automatically.",
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
        {"name": "triage_agent_system", "display_name": "Triage Agent System Prompt",
         "description": "System prompt for the triage agent defining risk assessment behaviour",
         "primary_entity_type": "agent", "primary_entity_id": agents["triage_agent"]["id"]},
        {"name": "triage_agent_context", "display_name": "Triage Agent Context Template",
         "description": "User message template for triage agent with submission context variables",
         "primary_entity_type": "agent", "primary_entity_id": agents["triage_agent"]["id"]},
        {"name": "appetite_agent_system", "display_name": "Appetite Agent System Prompt",
         "description": "System prompt for appetite agent defining guidelines assessment behaviour",
         "primary_entity_type": "agent", "primary_entity_id": agents["appetite_agent"]["id"]},
        {"name": "appetite_agent_context", "display_name": "Appetite Agent Context Template",
         "description": "User message template for appetite agent with submission and guidelines variables",
         "primary_entity_type": "agent", "primary_entity_id": agents["appetite_agent"]["id"]},
        # Task prompts
        {"name": "doc_classifier_instruction", "display_name": "Document Classifier Instruction",
         "description": "System instruction for document classification task",
         "primary_entity_type": "task", "primary_entity_id": tasks["document_classifier"]["id"]},
        {"name": "doc_classifier_input", "display_name": "Document Classifier Input Template",
         "description": "User message template for document classifier input",
         "primary_entity_type": "task", "primary_entity_id": tasks["document_classifier"]["id"]},
        {"name": "field_extractor_instruction", "display_name": "Field Extractor Instruction",
         "description": "System instruction for D&O application field extraction task",
         "primary_entity_type": "task", "primary_entity_id": tasks["field_extractor"]["id"]},
        {"name": "field_extractor_input", "display_name": "Field Extractor Input Template",
         "description": "User message template for field extractor input",
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
    """Register agent versions. Returns {(name, version_label): id}.

    All versions start as draft. Promotions go through lifecycle functions.
    v0.9.0 is promoted to champion first, then v1.0.0 is promoted which
    auto-deprecates v0.9.0 (setting its valid_to via lifecycle).
    No hardcoded dates. No raw SQL. All temporal fields managed by lifecycle.
    """
    versions = {}

    # ── Triage agent v0.9.0 — created as draft, will be promoted then superseded
    r = await verity.registry.register_agent_version(
        agent_id=agents["triage_agent"]["id"],
        major_version=0, minor_version=9, patch_version=0,
        lifecycle_state="draft", channel="development",
        inference_config_id=configs["triage_balanced"],
        output_schema=None, authority_thresholds=json.dumps({"requires_hitl_above_premium": 500000}),
        mock_mode_enabled=False, decision_log_detail="full",
        developer_name="Dev Team", change_summary="Initial prototype with basic risk scoring",
        change_type="major_redesign",
    )
    versions[("triage_agent", "0.9.0")] = r["id"]
    print(f"  + triage_agent v0.9.0 (draft)")

    # Promote v0.9.0: draft → candidate → champion (lifecycle sets valid_from, valid_to=2999)
    await verity.promote(entity_type="agent", entity_version_id=versions[("triage_agent", "0.9.0")],
        target_state="candidate", approver_name="Dev Team", rationale="Development complete")
    await verity.promote(entity_type="agent", entity_version_id=versions[("triage_agent", "0.9.0")],
        target_state="champion", approver_name="Dev Team", rationale="Initial champion")
    print(f"  + triage_agent v0.9.0 → champion")

    # ── Triage agent v1.0.0 — will supersede v0.9.0
    r = await verity.registry.register_agent_version(
        agent_id=agents["triage_agent"]["id"],
        major_version=1, minor_version=0, patch_version=0,
        lifecycle_state="draft", channel="development",
        inference_config_id=configs["triage_balanced"],
        output_schema=json.dumps({"risk_score": "string", "routing": "string", "reasoning": "string", "risk_factors": "array", "confidence": "number"}),
        authority_thresholds=json.dumps({"requires_hitl_above_premium": 500000, "low_confidence_threshold": 0.70, "auto_decline_red": False}),
        mock_mode_enabled=False, decision_log_detail="full",
        developer_name="Dev Team", change_summary="Added multi-factor risk assessment with guideline citations and structured risk factors",
        change_type="new_capability",
    )
    versions[("triage_agent", "1.0.0")] = r["id"]
    print(f"  + triage_agent v1.0.0 (draft)")

    # ── Appetite agent v1.0.0
    r = await verity.registry.register_agent_version(
        agent_id=agents["appetite_agent"]["id"],
        major_version=1, minor_version=0, patch_version=0,
        lifecycle_state="draft", channel="development",
        inference_config_id=configs["triage_balanced"],
        output_schema=json.dumps({"determination": "string", "confidence": "number", "guideline_citations": "array", "reasoning": "string"}),
        authority_thresholds=json.dumps({}),
        mock_mode_enabled=False, decision_log_detail="full",
        developer_name="Dev Team", change_summary="Initial release with guidelines-based appetite assessment",
        change_type="major_redesign",
    )
    versions[("appetite_agent", "1.0.0")] = r["id"]
    print(f"  + appetite_agent v1.0.0 (draft)")

    # ── Triage agent v2.0.0 — draft, NOT promoted (demonstrates lifecycle gate)
    r = await verity.registry.register_agent_version(
        agent_id=agents["triage_agent"]["id"],
        major_version=2, minor_version=0, patch_version=0,
        lifecycle_state="draft", channel="development",
        inference_config_id=configs["triage_balanced"],
        output_schema=json.dumps({"risk_score": "string", "routing": "string", "reasoning": "string", "risk_factors": "array", "confidence": "number"}),
        authority_thresholds=json.dumps({"requires_hitl_above_premium": 500000}),
        mock_mode_enabled=False, decision_log_detail="full",
        developer_name="Dev Team",
        change_summary="Experimental: enhanced risk factor weighting with industry-specific adjustments",
        change_type="new_capability",
    )
    versions[("triage_agent", "2.0.0")] = r["id"]
    print(f"  + triage_agent v2.0.0 (draft — pre-champion, demonstrates lifecycle gate)")

    return versions


async def seed_task_versions(verity: Verity, tasks: dict, configs: dict) -> dict:
    """Register task versions. Same pattern: v0.9.0 promoted first, then v1.0.0 supersedes it."""
    versions = {}

    # ── Document classifier v0.9.0 — draft, then promoted to champion
    r = await verity.registry.register_task_version(
        task_id=tasks["document_classifier"]["id"],
        major_version=0, minor_version=9, patch_version=0,
        lifecycle_state="draft", channel="development",
        inference_config_id=configs["classification_strict"],
        output_schema=None, mock_mode_enabled=False, decision_log_detail="standard",
        developer_name="Dev Team", change_summary="Initial classifier with 6 document types",
        change_type="major_redesign",
    )
    versions[("document_classifier", "0.9.0")] = r["id"]
    print(f"  + document_classifier v0.9.0 (draft)")

    # Promote v0.9.0 to champion
    await verity.promote(entity_type="task", entity_version_id=versions[("document_classifier", "0.9.0")],
        target_state="candidate", approver_name="Dev Team", rationale="Development complete")
    await verity.promote(entity_type="task", entity_version_id=versions[("document_classifier", "0.9.0")],
        target_state="champion", approver_name="Dev Team", rationale="Initial champion")
    print(f"  + document_classifier v0.9.0 → champion")

    # ── Document classifier v1.0.0 — will supersede v0.9.0
    r = await verity.registry.register_task_version(
        task_id=tasks["document_classifier"]["id"],
        major_version=1, minor_version=0, patch_version=0,
        lifecycle_state="draft", channel="development",
        inference_config_id=configs["classification_strict"],
        output_schema=json.dumps({"document_type": "string", "confidence": "number", "classification_notes": "string"}),
        mock_mode_enabled=False, decision_log_detail="standard",
        developer_name="Dev Team", change_summary="Added board_resolution and other types, improved prompt for accuracy",
        change_type="new_capability",
    )
    versions[("document_classifier", "1.0.0")] = r["id"]
    print(f"  + document_classifier v1.0.0 (draft)")

    # ── Field extractor v1.0.0
    r = await verity.registry.register_task_version(
        task_id=tasks["field_extractor"]["id"],
        major_version=1, minor_version=0, patch_version=0,
        lifecycle_state="draft", channel="development",
        inference_config_id=configs["extraction_deterministic"],
        output_schema=json.dumps({"fields": "object", "low_confidence_fields": "array", "unextractable_fields": "array", "extraction_complete": "boolean"}),
        mock_mode_enabled=False, decision_log_detail="standard",
        developer_name="Dev Team", change_summary="Initial release with 20-field D&O application extraction",
        change_type="major_redesign",
    )
    versions[("field_extractor", "1.0.0")] = r["id"]
    print(f"  + field_extractor v1.0.0 (draft)")

    return versions


async def seed_task_version_sources(verity: Verity, task_versions: dict) -> None:
    """Declare data sources on task versions.

    A source says: "when the caller passes `input_field_name` in
    input_data, resolve it via the named connector and bind the result
    to the prompt template variable `maps_to_template_var`."

    Declared required=False — UW's production flow still passes
    `document_text` directly, which bypasses source resolution. Validation
    runs (and any caller that prefers to pass an EDMS ref) get the fetch
    for free.
    """
    edms = await verity.db.fetch_one("get_data_connector_by_name", {"name": "edms"})
    if not edms:
        print("  ! edms data connector not registered; skipping source declarations")
        return
    edms_id = edms["id"]

    # Every registered task version (both 0.9.0 and 1.0.0) gets the same
    # declaration so a promotion/rollback doesn't lose the source contract.
    declarations = [
        ("document_classifier", "0.9.0"),
        ("document_classifier", "1.0.0"),
        ("field_extractor",      "1.0.0"),
    ]
    for task_name, version in declarations:
        tv_id = task_versions.get((task_name, version))
        if not tv_id:
            continue
        await verity.db.execute_returning("insert_task_version_source", {
            "task_version_id": str(tv_id),
            "input_field_name": "document_ref",
            "connector_id": str(edms_id),
            "fetch_method": "get_document_text",
            "maps_to_template_var": "document_text",
            "required": False,
            "execution_order": 1,
            "description": "When caller passes document_ref (an EDMS document id), fetch the extracted text and bind it to {{document_text}}.",
        })
        print(f"  + source declared: {task_name} {version} (document_ref → document_text via edms)")


# ══════════════════════════════════════════════════════════════
# STEPS 5-7: PROMPT VERSIONS, ASSIGNMENTS, TOOL AUTH
# ══════════════════════════════════════════════════════════════

async def seed_prompt_versions(verity: Verity, prompts: dict) -> dict:
    """Register prompt versions and promote through lifecycle.

    All versions start as draft. Promotions go through lifecycle functions.
    For prompts with 2 versions: v1 is promoted to champion first, then v2
    is promoted which auto-deprecates v1.
    """
    pv = {}

    async def _register_and_promote(prompt_id, major, minor, patch, content, api_role, governance_tier,
                                     change_summary, sensitivity_level, author_name, key):
        """Helper: register a prompt version as draft, then promote to champion."""
        r = await verity.registry.register_prompt_version(
            prompt_id=prompt_id,
            major_version=major, minor_version=minor, patch_version=patch,
            content=content, api_role=api_role, governance_tier=governance_tier,
            lifecycle_state="draft",
            change_summary=change_summary, sensitivity_level=sensitivity_level,
            author_name=author_name,
        )
        version_id = r["id"]
        pv[key] = version_id
        # Promote: draft → candidate → champion
        await verity.promote(entity_type="prompt", entity_version_id=version_id,
            target_state="candidate", approver_name="Dev Team", rationale="Development complete")
        await verity.promote(entity_type="prompt", entity_version_id=version_id,
            target_state="champion", approver_name=author_name, rationale=change_summary)
        return version_id

    # Prompt content is defined in uw_demo/app/prompts.py for readability.
    # Each prompt is a named constant (e.g., TRIAGE_SYSTEM_V2).
    from uw_demo.app.prompts import (
        TRIAGE_SYSTEM_V1, TRIAGE_SYSTEM_V2, TRIAGE_CONTEXT_V1,
        APPETITE_SYSTEM_V1, APPETITE_CONTEXT_V1,
        CLASSIFIER_SYSTEM_V1, CLASSIFIER_SYSTEM_V2, CLASSIFIER_SYSTEM_V3,
        CLASSIFIER_INPUT_V1, CLASSIFIER_INPUT_V2,
        EXTRACTOR_SYSTEM_V1, EXTRACTOR_INPUT_V1, EXTRACTOR_INPUT_V2,
    )

    # ── Triage agent system prompt — v1 promoted then superseded by v2
    await _register_and_promote(
        prompts["triage_agent_system"], 1, 0, 0,
        TRIAGE_SYSTEM_V1,
        "system", "behavioural",
        "Initial basic system prompt", "high", "Dev Team",
        ("triage_agent_system", 1),
    )
    # v2 promotion auto-deprecates v1
    await _register_and_promote(
        prompts["triage_agent_system"], 2, 0, 0,
        TRIAGE_SYSTEM_V2,
        "system", "behavioural",
        "Production-grade prompt with scoring criteria, confidence calibration, and critical distinctions", "high", "Sarah Chen",
        ("triage_agent_system", 2),
    )

    # ── Triage agent context template
    await _register_and_promote(
        prompts["triage_agent_context"], 1, 0, 0,
        TRIAGE_CONTEXT_V1,
        "user", "contextual",
        "Context template with tool call instructions and submission identifiers", "medium", "Dev Team",
        ("triage_agent_context", 1),
    )

    # ── Appetite agent system prompt
    await _register_and_promote(
        prompts["appetite_agent_system"], 1, 0, 0,
        APPETITE_SYSTEM_V1,
        "system", "behavioural",
        "Production-grade prompt with systematic guideline evaluation and determination rules", "high", "Sarah Chen",
        ("appetite_agent_system", 1),
    )

    # ── Appetite agent context template
    await _register_and_promote(
        prompts["appetite_agent_context"], 1, 0, 0,
        APPETITE_CONTEXT_V1,
        "user", "contextual",
        "Context template with tool call instructions and LOB-specific guidance", "medium", "Dev Team",
        ("appetite_agent_context", 1),
    )

    # ── Document classifier instruction — v1 promoted then superseded by v2
    await _register_and_promote(
        prompts["doc_classifier_instruction"], 1, 0, 0,
        CLASSIFIER_SYSTEM_V1,
        "system", "behavioural",
        "Initial simple classifier instruction", "high", "Dev Team",
        ("doc_classifier_instruction", 1),
    )
    await _register_and_promote(
        prompts["doc_classifier_instruction"], 2, 0, 0,
        CLASSIFIER_SYSTEM_V2,
        "system", "behavioural",
        "Production-grade prompt with document type descriptions, recognition markers, and confidence calibration", "high", "James Okafor",
        ("doc_classifier_instruction", 2),
    )

    # ── Document classifier input template — v1 then superseded by v2
    await _register_and_promote(
        prompts["doc_classifier_input"], 1, 0, 0,
        CLASSIFIER_INPUT_V1,
        "user", "formatting",
        "Document text input with classification instruction", "low", "Dev Team",
        ("doc_classifier_input", 1),
    )

    # v3 system: handles PDF content blocks (multi-document classification)
    await _register_and_promote(
        prompts["doc_classifier_instruction"], 3, 0, 0,
        CLASSIFIER_SYSTEM_V3,
        "system", "behavioural",
        "Multi-document classifier with PDF content block support", "high", "James Okafor",
        ("doc_classifier_instruction", 3),
    )

    # v2 input: for EDMS-integrated pipeline (no document_text, uses content blocks)
    await _register_and_promote(
        prompts["doc_classifier_input"], 2, 0, 0,
        CLASSIFIER_INPUT_V2,
        "user", "contextual",
        "Multi-document classification input for EDMS-integrated pipeline", "medium", "James Okafor",
        ("doc_classifier_input", 2),
    )

    # ── Field extractor system prompt
    await _register_and_promote(
        prompts["field_extractor_instruction"], 1, 0, 0,
        EXTRACTOR_SYSTEM_V1,
        "system", "behavioural",
        "Production-grade prompt with 20-field schema, type definitions, confidence calibration, and extraction rules", "high", "James Okafor",
        ("field_extractor_instruction", 1),
    )

    # ── Field extractor input template — v1 then superseded by v2
    await _register_and_promote(
        prompts["field_extractor_input"], 1, 0, 0,
        EXTRACTOR_INPUT_V1,
        "user", "formatting",
        "D&O application text input with extraction instruction", "low", "Dev Team",
        ("field_extractor_input", 1),
    )

    # v2 input: includes submission context alongside document text
    await _register_and_promote(
        prompts["field_extractor_input"], 2, 0, 0,
        EXTRACTOR_INPUT_V2,
        "user", "contextual",
        "Extraction input with submission context for EDMS-integrated pipeline", "medium", "James Okafor",
        ("field_extractor_input", 2),
    )

    print(f"  + {len(pv)} prompt versions registered and promoted via lifecycle")
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

        # Document classifier v1.0.0 gets instruction v3 + input v2 (EDMS-integrated)
        ("task", task_versions[("document_classifier", "1.0.0")],
         prompt_versions[("doc_classifier_instruction", 3)], "system", "behavioural", 1, True),
        ("task", task_versions[("document_classifier", "1.0.0")],
         prompt_versions[("doc_classifier_input", 2)], "user", "contextual", 2, True),

        # Field extractor v1.0.0 gets instruction v1 + input v2 (EDMS-integrated)
        ("task", task_versions[("field_extractor", "1.0.0")],
         prompt_versions[("field_extractor_instruction", 1)], "system", "behavioural", 1, True),
        ("task", task_versions[("field_extractor", "1.0.0")],
         prompt_versions[("field_extractor_input", 2)], "user", "contextual", 2, True),
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
        # Triage agent tools — in-process Python tools
        (agent_versions[("triage_agent", "1.0.0")], tools["get_submission_context"]),
        (agent_versions[("triage_agent", "1.0.0")], tools["get_underwriting_guidelines"]),
        (agent_versions[("triage_agent", "1.0.0")], tools["get_loss_history"]),
        (agent_versions[("triage_agent", "1.0.0")], tools["store_triage_result"]),
        # Triage agent tools — MCP-sourced (replaces the old
        # get_enrichment_data Python tool with four provider-native tools
        # plus DuckDuckGo web search for current news/regulatory filings)
        (agent_versions[("triage_agent", "1.0.0")], tools["web_search"]),
        (agent_versions[("triage_agent", "1.0.0")], tools["lexisnexis_lookup"]),
        (agent_versions[("triage_agent", "1.0.0")], tools["dnb_lookup"]),
        (agent_versions[("triage_agent", "1.0.0")], tools["pitchbook_lookup"]),
        (agent_versions[("triage_agent", "1.0.0")], tools["factset_lookup"]),
        # Triage agent tool — Verity-builtin meta-tool for sub-agent
        # delegation (FC-1). Granting the tool authorizes the CAPABILITY;
        # which specific sub-agents triage can target is governed by the
        # agent_version_delegation rows seeded in seed_delegations.
        (agent_versions[("triage_agent", "1.0.0")], tools["delegate_to_agent"]),
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
# STEP 7b: SUB-AGENT DELEGATION AUTHORIZATIONS (FC-1)
# Governs which parent agent versions can delegate to which specific
# sub-agents via the delegate_to_agent meta-tool. Distinct from the
# agent_version_tool junction (which only grants the CAPABILITY to call
# the meta-tool at all). See agent_version_delegation table docs.
# ══════════════════════════════════════════════════════════════

async def seed_delegations(verity: Verity, agent_versions: dict) -> None:
    """Register authorized parent→child delegation relationships.

    Each row authorizes ONE specific parent agent_version to delegate to
    ONE specific child agent. Champion-tracking (child_agent_name) means
    the delegation follows whichever version of the child agent is
    currently promoted to champion — newer champions light up automatically
    without re-authorizing.
    """
    delegations = [
        {
            "parent_agent_version_id": agent_versions[("triage_agent", "1.0.0")],
            "child_agent_name": "appetite_agent",  # champion-tracking
            "scope": {},
            "rationale": (
                "Triage delegates detailed guideline-compliance analysis to "
                "the appetite specialist agent when the submission's "
                "regulatory or policy fit is ambiguous (pending SEC inquiry, "
                "edge-case SIC code, borderline revenue, etc.). The "
                "sub-agent's determination is then factored into triage's "
                "final risk score and routing."
            ),
            "notes": "FC-1 demo delegation (seeded 2026-04).",
        },
    ]

    for d in delegations:
        await verity.registry.register_delegation(**d)

    print(f"  + {len(delegations)} delegation authorization(s) registered")


# ══════════════════════════════════════════════════════════════
# STEP 8: PIPELINE
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# STEP 8: APPLICATION REGISTRATION
# ══════════════════════════════════════════════════════════════
# Multi-step workflows (doc-processing, risk-assessment) are
# orchestrated in uw_demo/app/workflows.py now that pipelines are
# descoped from Verity. No pipeline entity gets registered with the
# governance plane; the app still maps its own agents / tasks /
# prompts / tools.

async def seed_application(verity, agents, tasks, tools, prompts):
    """Register the UW Demo application and map all entities to it."""

    # Register the application
    app = await verity.register_application(
        name="uw_demo",
        display_name="Underwriting Demo",
        description="Commercial underwriting platform for D&O and GL lines, powered by Verity.",
    )
    app_id = app["id"]
    print(f"  + application: uw_demo")

    # Map all agents to the application
    for name, data in agents.items():
        await verity.registry.map_entity_to_application(app_id, "agent", data["id"])
    print(f"  + mapped {len(agents)} agents")

    # Map all tasks
    for name, data in tasks.items():
        await verity.registry.map_entity_to_application(app_id, "task", data["id"])
    print(f"  + mapped {len(tasks)} tasks")

    # Map all tools
    for name, tool_id in tools.items():
        await verity.registry.map_entity_to_application(app_id, "tool", tool_id)
    print(f"  + mapped {len(tools)} tools")

    # Create execution contexts for the 4 seeded submissions
    submission_ids = [
        "00000001-0001-0001-0001-000000000001",
        "00000002-0002-0002-0002-000000000002",
        "00000003-0003-0003-0003-000000000003",
        "00000004-0004-0004-0004-000000000004",
    ]
    for sub_id in submission_ids:
        await verity.registry.create_execution_context(
            application_id=app_id,
            context_ref=f"submission:{sub_id}",
            context_type="submission",
            metadata={"submission_id": sub_id},
        )
    print(f"  + created {len(submission_ids)} execution contexts")


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
                {"name": "classify_do_application", "description": "Should classify D&O application form correctly",
                 "input_data": {"document_text": "DIRECTORS AND OFFICERS LIABILITY APPLICATION Named Insured: Acme Corp...", "document_filename": "test.pdf"},
                 "expected_output": {"document_type": "do_application", "confidence": 0.95},
                 "metric_type": "classification_f1", "metric_config": {"classes": ["do_application", "gl_application", "loss_runs", "other"]}},
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
            "description": "Unit tests for D&O application field extraction",
            "entity_type": "task", "entity_id": tasks["field_extractor"]["id"],
            "suite_type": "unit", "created_by": "Dev Team",
            "cases": [
                {"name": "extract_complete_form", "description": "Extract all fields from a complete D&O application",
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
                 "metric_type": "classification_f1", "metric_config": {"classes": ["Green", "Amber", "Red"]},
                 "tool_mocks": [
                     {"tool_name": "get_submission_context", "mock_response": {"account": {"name": "SafeCorp LLC", "sic_code": "7372", "years_in_business": 15}, "submission": {"lob": "DO", "annual_revenue": 50000000, "employee_count": 250, "board_size": 7, "independent_directors": 4}, "loss_history": [{"year": 2023, "claims": 0}, {"year": 2024, "claims": 0}, {"year": 2025, "claims": 0}]}, "description": "Clean D&O submission - no risk factors"},
                     {"tool_name": "get_loss_history", "mock_response": {"total_claims": 0, "total_incurred": 0, "years": [{"year": 2023, "claims": 0}, {"year": 2024, "claims": 0}, {"year": 2025, "claims": 0}]}, "description": "Clean loss history"},
                 ]},
                {"name": "triage_amber_risk", "description": "Borderline submission should score Amber",
                 "input_data": {"submission_id": "test-amber", "lob": "DO", "named_insured": "RiskyCorp Inc"},
                 "expected_output": {"risk_score": "Amber", "routing": "assign_to_senior_uw"},
                 "metric_type": "classification_f1", "metric_config": None,
                 "tool_mocks": [
                     {"tool_name": "get_submission_context", "mock_response": {"account": {"name": "RiskyCorp Inc", "sic_code": "7372", "years_in_business": 8}, "submission": {"lob": "DO", "annual_revenue": 120000000, "board_size": 9, "independent_directors": 5, "regulatory_investigation": "SEC routine inquiry"}, "loss_history": [{"year": 2023, "claims": 1}, {"year": 2024, "claims": 0}, {"year": 2025, "claims": 1}]}, "description": "D&O with SEC inquiry and 2 claims at threshold"},
                     {"tool_name": "get_loss_history", "mock_response": {"total_claims": 2, "total_incurred": 225000, "years": [{"year": 2023, "claims": 1, "incurred": 75000}, {"year": 2024, "claims": 0}, {"year": 2025, "claims": 1, "incurred": 150000}]}, "description": "2 claims in 5 years at maximum threshold"},
                 ]},
                {"name": "triage_red_risk", "description": "High-risk submission should score Red",
                 "input_data": {"submission_id": "test-red", "lob": "GL", "named_insured": "DangerCo LLC"},
                 "expected_output": {"risk_score": "Red", "routing": "refer_to_management"},
                 "metric_type": "classification_f1", "metric_config": None,
                 "tool_mocks": [
                     {"tool_name": "get_submission_context", "mock_response": {"account": {"name": "DangerCo LLC", "sic_code": "6159", "years_in_business": 22}, "submission": {"lob": "GL", "annual_revenue": 25000000, "going_concern_opinion": True}, "loss_history": [{"year": 2023, "claims": 5}, {"year": 2024, "claims": 4}, {"year": 2025, "claims": 3}]}, "description": "GL with going concern, excluded SIC, excessive claims"},
                     {"tool_name": "get_loss_history", "mock_response": {"total_claims": 12, "total_incurred": 600000, "years": [{"year": 2023, "claims": 5, "incurred": 220000}, {"year": 2024, "claims": 4, "incurred": 190000}, {"year": 2025, "claims": 3, "incurred": 190000}]}, "description": "12 claims in 3 years, way above threshold"},
                 ]},
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
                 "metric_type": "classification_f1", "metric_config": {"classes": ["within_appetite", "borderline", "outside_appetite"]},
                 "tool_mocks": [
                     {"tool_name": "get_underwriting_guidelines", "mock_response": {"lob": "DO", "guidelines_text": "§1 GENERAL ELIGIBILITY\n1.1 Entity must be US incorporated.\n1.2 Min 3 years.\n1.3 Revenue $10M-$500M.\n§2 FINANCIAL\n2.1 Revenue > $10M.\n§3 GOVERNANCE\n3.1 Board >= 5.\n3.3 Majority independent."}, "description": "D&O guidelines"},
                     {"tool_name": "get_submission_context", "mock_response": {"account": {"name": "StandardCorp", "years_in_business": 12}, "submission": {"lob": "DO", "annual_revenue": 85000000, "board_size": 8, "independent_directors": 5}}, "description": "Clean D&O submission meeting all criteria"},
                 ]},
                {"name": "appetite_borderline", "description": "Submission on appetite boundary",
                 "input_data": {"submission_id": "test-border", "lob": "GL", "named_insured": "EdgeCase LLC"},
                 "expected_output": {"determination": "borderline"},
                 "metric_type": "classification_f1", "metric_config": None,
                 "tool_mocks": [
                     {"tool_name": "get_underwriting_guidelines", "mock_response": {"lob": "GL", "guidelines_text": "§1 ELIGIBILITY\n1.2 Min 2 years.\n1.3 Revenue $5M-$250M.\n§5 MANUFACTURING\n5.2 Heavy mfg (SIC 3300-3399) requires senior UW.\n§6 CLAIMS\n6.1 Max 5 GL claims in 3 years."}, "description": "GL guidelines"},
                     {"tool_name": "get_submission_context", "mock_response": {"account": {"name": "EdgeCase LLC", "sic_code": "3312", "years_in_business": 10}, "submission": {"lob": "GL", "annual_revenue": 90000000, "manufacturing_operations": True}}, "description": "Heavy manufacturing - requires senior UW approval"},
                 ]},
                {"name": "appetite_outside", "description": "Submission clearly outside appetite",
                 "input_data": {"submission_id": "test-out", "lob": "DO", "named_insured": "CryptoCoin Inc"},
                 "expected_output": {"determination": "outside_appetite"},
                 "metric_type": "classification_f1", "metric_config": None,
                 "tool_mocks": [
                     {"tool_name": "get_underwriting_guidelines", "mock_response": {"lob": "DO", "guidelines_text": "§2 FINANCIAL\n2.1 Revenue > $10M.\n2.2 No going concern.\n§4 EXCLUSIONS\n4.2 Cannabis excluded.\n4.4 Bankruptcy in last 5 years excluded."}, "description": "D&O guidelines with exclusions"},
                     {"tool_name": "get_submission_context", "mock_response": {"account": {"name": "CryptoCoin Inc", "years_in_business": 2}, "submission": {"lob": "DO", "annual_revenue": 8000000, "board_size": 3}}, "description": "Below revenue minimum, below board minimum, too young"},
                 ]},
            ],
        },
    ]

    mock_count = 0
    for sd in suite_defs:
        cases_data = sd.pop("cases")
        sr = await verity.registry.register_test_suite(**sd)
        suite_id = sr["id"]
        case_ids = []
        for c in cases_data:
            # Extract tool_mocks before passing to register_test_case
            # (tool_mocks is not a column on test_case - it goes to test_case_mock)
            tool_mocks = c.pop("tool_mocks", [])
            c["suite_id"] = suite_id
            c["is_adversarial"] = False
            c["tags"] = []
            cr = await verity.registry.register_test_case(**c)
            case_id = cr["id"]
            case_ids.append({"id": case_id, **c})

            # Insert tool mocks into test_case_mock table
            for tm in tool_mocks:
                await verity.db.execute_returning("insert_test_case_mock", {
                    "test_case_id": str(case_id),
                    "tool_name": tm["tool_name"],
                    "call_order": tm.get("call_order", 1),
                    "mock_response": json.dumps(tm["mock_response"]),
                    "description": tm.get("description"),
                })
                mock_count += 1

        suites[sd["name"]] = {"suite_id": suite_id, "entity_type": sd["entity_type"],
                               "entity_id": sd["entity_id"], "cases": case_ids}
        print(f"  + test_suite: {sd['name']} ({len(case_ids)} cases)")
    print(f"  + {mock_count} test case mocks (tool scenario data)")

    return suites


# ══════════════════════════════════════════════════════════════
# STEPS 11-12: PROMOTE TO CHAMPION
# ══════════════════════════════════════════════════════════════

async def promote_to_champion(verity, agent_versions, task_versions, agents, tasks):
    """Promote all v1.0.0 versions: draft → candidate → champion.

    This auto-deprecates the v0.9.0 champions (which were promoted earlier
    in seed_agent_versions/seed_task_versions). The lifecycle functions
    handle all valid_from/valid_to fields — no hardcoded dates.

    After this step:
    - v0.9.0 versions: lifecycle_state='deprecated', valid_to=NOW()
    - v1.0.0 versions: lifecycle_state='champion', valid_from=NOW(), valid_to=2999-12-31
    """
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
        # Candidate → Champion (auto-deprecates prior champion v0.9.0 if exists)
        await verity.promote(
            entity_type=entity_type, entity_version_id=version_id,
            target_state="champion", approver_name="Sarah Chen, Chief Actuary",
            rationale=f"Ground truth validation passed for {name}. Model card approved.",
            ground_truth_reviewed=True, model_card_reviewed=True,
        )
        print(f"  + promoted {name} v1.0.0 → champion (v0.9.0 auto-deprecated)")


# ══════════════════════════════════════════════════════════════
# STEPS 13-16: VALIDATION, MODEL CARDS, THRESHOLDS
# ══════════════════════════════════════════════════════════════

async def seed_governance_artifacts(verity, agents, tasks, agent_versions, task_versions):
    """Seed ground truth datasets, validation runs, model cards, and metric thresholds."""

    # Clean up existing GT data so re-running the seed is safe.
    # CASCADE handles child records (annotations, mocks, validation results).
    await verity.db.execute_raw("DELETE FROM validation_record_result WHERE validation_run_id IN (SELECT id FROM validation_run)", {})
    await verity.db.execute_raw("DELETE FROM validation_run", {})
    await verity.db.execute_raw("DELETE FROM ground_truth_record_mock WHERE record_id IN (SELECT id FROM ground_truth_record)", {})
    await verity.db.execute_raw("DELETE FROM ground_truth_annotation", {})
    await verity.db.execute_raw("DELETE FROM ground_truth_record", {})
    await verity.db.execute_raw("DELETE FROM ground_truth_dataset", {})
    await verity.db.execute_raw("DELETE FROM metric_threshold", {})
    print("  (cleaned existing GT data for re-seed)")

    # Ground truth datasets (three-table design: dataset -> record -> annotation)
    # 4 datasets: classifier (54 docs), extractor (10 D&O apps), triage (4 subs), appetite (4 subs)
    gt_classifier = await verity.registry.register_ground_truth_dataset(
        entity_type="task", entity_id=tasks["document_classifier"]["id"],
        name="classifier_ground_truth_v1", version="1.0",
        description="54 SME-labeled insurance documents across 6 document types",
        purpose="Validate document classification accuracy before champion promotion",
        quality_tier="silver", status="ready",
        owner_name="Maria Santos, Senior UW", created_by="Maria Santos, Senior UW",
        record_count=54, designed_for_version_id=None,
        coverage_notes="10 D&O apps, 10 GL apps, 20 loss runs, 7 financials, 2 board resolutions, 5 GL supplementals.",
    )

    gt_extractor = await verity.registry.register_ground_truth_dataset(
        entity_type="task", entity_id=tasks["field_extractor"]["id"],
        name="extractor_ground_truth_v1", version="1.0",
        description="10 D&O applications with hand-verified field values",
        purpose="Validate field extraction accuracy before champion promotion",
        quality_tier="silver", status="ready",
        owner_name="Maria Santos, Senior UW", created_by="Maria Santos, Senior UW",
        record_count=10, designed_for_version_id=None,
        coverage_notes="All 10 D&O application PDFs with 20 fields each verified against source documents.",
    )

    gt_triage = await verity.registry.register_ground_truth_dataset(
        entity_type="agent", entity_id=agents["triage_agent"]["id"],
        name="triage_ground_truth_v1", version="1.0",
        description="4 SME-labeled submissions with risk scores and routing decisions",
        purpose="Validate triage risk scoring accuracy before champion promotion",
        quality_tier="silver", status="ready",
        owner_name="James Okafor, Model Risk", created_by="James Okafor, Model Risk",
        record_count=4, designed_for_version_id=None,
        coverage_notes="1 Green, 1 Amber (D&O), 1 Red (GL), 1 Amber (GL).",
    )

    gt_appetite = await verity.registry.register_ground_truth_dataset(
        entity_type="agent", entity_id=agents["appetite_agent"]["id"],
        name="appetite_ground_truth_v1", version="1.0",
        description="4 SME-labeled submissions with appetite determinations",
        purpose="Validate appetite assessment accuracy before champion promotion",
        quality_tier="silver", status="ready",
        owner_name="James Okafor, Model Risk", created_by="James Okafor, Model Risk",
        record_count=4, designed_for_version_id=None,
        coverage_notes="1 within appetite, 1 borderline, 1 outside appetite, 1 within appetite (GL).",
    )

    # Ground truth records, annotations, and tool mocks are created
    # by seed_ground_truth_records() called separately in main().
    # This function only creates datasets, validation runs, model cards, and thresholds.

    # Validation runs
    await verity.registry.register_validation_run(
        entity_type="task", entity_version_id=task_versions[("document_classifier", "1.0.0")],
        dataset_id=gt_classifier["id"], dataset_version="1.0", run_by="James Okafor",
        precision_score=0.9600, recall_score=0.9400, f1_score=0.9500,
        cohens_kappa=None, confusion_matrix={"do_application": {"do_application": 48, "other": 2}, "loss_runs": {"loss_runs": 47, "other": 3}},
        field_accuracy=None, overall_extraction_rate=None, low_confidence_rate=None,
        fairness_metrics=None, fairness_passed=None, fairness_notes=None,
        thresholds_met=True, threshold_details={"f1": {"required": 0.92, "achieved": 0.95, "passed": True}},
        inference_config_snapshot={"config_name": "classification_strict", "model_name": "claude-sonnet-4-20250514", "temperature": 0.0},
        status="complete", passed=True, notes="[SEED DATA] Synthetic validation result for demo. Not from a real validation run.",
    )

    await verity.registry.register_validation_run(
        entity_type="agent", entity_version_id=agent_versions[("triage_agent", "1.0.0")],
        dataset_id=gt_triage["id"], dataset_version="1.0", run_by="Sarah Chen",
        precision_score=0.8800, recall_score=0.8500, f1_score=0.8600,
        cohens_kappa=0.7800, confusion_matrix={"Green": {"Green": 8, "Amber": 1}, "Amber": {"Amber": 6, "Red": 1}, "Red": {"Red": 4}},
        field_accuracy=None, overall_extraction_rate=None, low_confidence_rate=None,
        fairness_metrics={"sic_parity": 0.02, "geo_parity": 0.01}, fairness_passed=True, fairness_notes="No significant disparate impact detected",
        thresholds_met=True, threshold_details={"f1": {"required": 0.83, "achieved": 0.86, "passed": True}, "kappa": {"required": 0.75, "achieved": 0.78, "passed": True}},
        inference_config_snapshot={"config_name": "triage_balanced", "model_name": "claude-sonnet-4-20250514", "temperature": 0.2},
        status="complete", passed=True, notes="[SEED DATA] Synthetic validation result for demo. Not from a real validation run.",
    )
    print(f"  + 4 ground truth datasets, 8 GT records with mocks, 2 synthetic validation runs")

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
    # Metric names MUST match what classification_metrics() and field_accuracy() return:
    #   "f1", "precision", "recall", "cohens_kappa", "overall_accuracy"
    # NOT "f1_score" or "precision_score" - those are column names in validation_run, not metric keys.
    thresholds = [
        ("agent", agents["triage_agent"]["id"], "high", "f1", 0.8300, 0.8800),
        ("agent", agents["appetite_agent"]["id"], "high", "f1", 0.8600, 0.9000),
        ("task", tasks["document_classifier"]["id"], "medium", "f1", 0.9200, 0.9600),
        ("task", tasks["field_extractor"]["id"], "medium", "overall_accuracy", 0.9000, 0.9500),
    ]
    for et, eid, tier, metric, min_val, target in thresholds:
        await verity.registry.register_metric_threshold(
            entity_type=et, entity_id=eid, materiality_tier=tier,
            metric_name=metric, field_name=None, minimum_acceptable=min_val, target_champion=target,
        )
    print(f"  + 4 metric thresholds")

    return {
        "gt_classifier": gt_classifier, "gt_extractor": gt_extractor,
        "gt_triage": gt_triage, "gt_appetite": gt_appetite,
    }


# ══════════════════════════════════════════════════════════════
# STEP 13b: GROUND TRUTH RECORDS + ANNOTATIONS
# ══════════════════════════════════════════════════════════════

async def seed_ground_truth_records(verity, gt_datasets, tasks, agents, edms_doc_ids=None):
    """Populate ground truth records with EDMS document references.

    Ground truth records reference EDMS documents by their document UUID.
    The edms_doc_ids mapping (filename → EDMS document ID) comes from
    seed_edms() which runs before this function.

    Args:
        edms_doc_ids: Dict of filename → EDMS document UUID string.
                      If None or empty, falls back to local file references.
    """
    from pathlib import Path
    import json

    edms_doc_ids = edms_doc_ids or {}

    # ── 1. CLASSIFIER GROUND TRUTH (54 documents) ────────────
    # Each seed document becomes a ground truth record.
    # Source references point to EDMS documents (not local files).
    gt_cls_id = gt_datasets["gt_classifier"]["id"]
    doc_dir = Path("/app/uw_demo/seed_docs/filled")
    if not doc_dir.exists():
        doc_dir = Path(__file__).parents[2] / "seed_docs" / "filled"

    type_map = {
        "do_app_": "do_application",
        "gl_app_": "gl_application",
        "loss_run_": "loss_run",
        "financial_stmt_": "financial_statement",
        "board_resolution_": "board_resolution",
        "supplemental_gl_": "supplemental_gl",
    }

    record_idx = 0
    if doc_dir.exists():
        for filepath in sorted(doc_dir.iterdir()):
            doc_type = None
            for prefix, dtype in type_map.items():
                if filepath.name.startswith(prefix):
                    doc_type = dtype
                    break
            if not doc_type:
                continue

            # Source reference must point to EDMS - never local files
            edms_id = edms_doc_ids.get(filepath.name)
            if not edms_id:
                print(f"    ! Skipping {filepath.name}: not found in EDMS (upload may have failed)")
                continue
            source_provider = "edms"
            source_container = "submissions"
            source_key = edms_id  # EDMS document UUID

            # Input data carries only the EDMS document reference. At
            # validation time, the classifier's declared source resolves
            # this ref to the extracted text via the edms connector and
            # binds it to the prompt's {{document_text}} variable.
            input_data = {
                "document_ref": edms_id,
                "document_filename": filepath.name,
            }

            record = await verity.registry.register_ground_truth_record(
                dataset_id=str(gt_cls_id), record_index=record_idx,
                source_type="document",
                source_provider=source_provider,
                source_container=source_container,
                source_key=source_key,
                source_description=f"{doc_type} document: {filepath.name}",
                input_data=input_data,
                tags=[doc_type, filepath.suffix.lstrip(".")],
                difficulty="standard",
                record_notes=None,
            )

            # Authoritative annotation: the correct document type
            await verity.registry.register_ground_truth_annotation(
                record_id=str(record["id"]), dataset_id=str(gt_cls_id),
                annotator_type="human_sme",
                labeled_by="Maria Santos, Senior UW",
                label_confidence=0.99,
                label_notes=f"Document type determined from filename and content review",
                judge_model=None, judge_prompt_version_id=None, judge_reasoning=None,
                expected_output={"document_type": doc_type, "confidence": 0.95},
                is_authoritative=True,
            )
            record_idx += 1

    print(f"  + classifier ground truth: {record_idx} records with annotations")

    # ── 2. EXTRACTOR GROUND TRUTH (10 D&O applications) ──────
    # Expected field values from the seed submission data
    gt_ext_id = gt_datasets["gt_extractor"]["id"]

    # D&O company data for the 10 applications
    do_companies = [
        {"name": "Acme Dynamics LLC", "fein": "12-3456789", "entity_type": "LLC",
         "state": "Delaware", "revenue": 50000000, "employees": 250,
         "board_size": 7, "independent": 4, "filename": "do_app_acme_dynamics.pdf"},
        {"name": "TechFlow Industries Inc", "fein": "98-7654321", "entity_type": "Corporation",
         "state": "California", "revenue": 120000000, "employees": 800,
         "board_size": 9, "independent": 5, "filename": "do_app_techflow_industries.pdf"},
        {"name": "Brightline Analytics Corp", "fein": "45-6789012", "entity_type": "Corporation",
         "state": "Massachusetts", "revenue": 35000000, "employees": 180,
         "board_size": 7, "independent": 4, "filename": "do_app_brightline_analytics.pdf"},
        {"name": "Continental Services Group", "fein": "67-8901234", "entity_type": "Corporation",
         "state": "Illinois", "revenue": 85000000, "employees": 500,
         "board_size": 8, "independent": 5, "filename": "do_app_continental_services.pdf"},
        {"name": "Horizon Capital Partners", "fein": "23-4567890", "entity_type": "LLC",
         "state": "New York", "revenue": 200000000, "employees": 120,
         "board_size": 6, "independent": 3, "filename": "do_app_horizon_capital.pdf"},
        {"name": "NovaTech Holdings Inc", "fein": "34-5678901", "entity_type": "Corporation",
         "state": "Texas", "revenue": 75000000, "employees": 350,
         "board_size": 7, "independent": 4, "filename": "do_app_novatech_holdings.pdf"},
        {"name": "Pacific Ventures LLC", "fein": "56-7890123", "entity_type": "LLC",
         "state": "Oregon", "revenue": 45000000, "employees": 200,
         "board_size": 5, "independent": 3, "filename": "do_app_pacific_ventures.pdf"},
        {"name": "Pinnacle Software Inc", "fein": "78-9012345", "entity_type": "Corporation",
         "state": "Washington", "revenue": 60000000, "employees": 280,
         "board_size": 7, "independent": 4, "filename": "do_app_pinnacle_software.pdf"},
        {"name": "Sterling Advisory Group", "fein": "89-0123456", "entity_type": "Corporation",
         "state": "Connecticut", "revenue": 95000000, "employees": 150,
         "board_size": 8, "independent": 5, "filename": "do_app_sterling_advisory.pdf"},
        {"name": "Westfield Manufacturing Corp", "fein": "01-2345678", "entity_type": "Corporation",
         "state": "Ohio", "revenue": 110000000, "employees": 700,
         "board_size": 9, "independent": 5, "filename": "do_app_westfield_manufacturing.pdf"},
    ]

    ext_idx = 0
    for company in do_companies:
        edms_id = edms_doc_ids.get(company["filename"])
        if not edms_id:
            print(f"    ! Skipping extractor GT for {company['filename']}: not in EDMS")
            continue
        input_data = {"document_filename": company["filename"], "document_type": "do_application", "edms_document_id": edms_id}

        record = await verity.registry.register_ground_truth_record(
            dataset_id=str(gt_ext_id), record_index=ext_idx,
            source_type="document",
            source_provider="edms",
            source_container="submissions",
            source_key=edms_id,
            source_description=f"D&O application for {company['name']}",
            input_data=input_data,
            tags=["do_application", "extraction"],
            difficulty="standard",
            record_notes=None,
        )

        await verity.registry.register_ground_truth_annotation(
            record_id=str(record["id"]), dataset_id=str(gt_ext_id),
            annotator_type="human_sme",
            labeled_by="Maria Santos, Senior UW",
            label_confidence=0.98,
            label_notes="Field values verified against source PDF",
            judge_model=None, judge_prompt_version_id=None, judge_reasoning=None,
            expected_output={
                "fields": {
                    "named_insured": {"value": company["name"], "confidence": 0.98},
                    "fein": {"value": company["fein"], "confidence": 0.97},
                    "entity_type": {"value": company["entity_type"], "confidence": 0.95},
                    "state_of_incorporation": {"value": company["state"], "confidence": 0.96},
                    "annual_revenue": {"value": company["revenue"], "confidence": 0.95},
                    "employee_count": {"value": company["employees"], "confidence": 0.94},
                    "board_size": {"value": company["board_size"], "confidence": 0.92},
                    "independent_directors": {"value": company["independent"], "confidence": 0.90},
                },
                "extraction_complete": True,
            },
            is_authoritative=True,
        )
        ext_idx += 1

    print(f"  + extractor ground truth: {ext_idx} records with annotations")

    # ── 3. TRIAGE GROUND TRUTH (4 submissions) ───────────────
    gt_tri_id = gt_datasets["gt_triage"]["id"]

    triage_cases = [
        {"sub_id": "00000001-0001-0001-0001-000000000001", "name": "Acme D&O",
         "lob": "DO", "named_insured": "Acme Dynamics LLC",
         "expected": {"risk_score": "Green", "routing": "assign_to_uw", "confidence": 0.89},
         "difficulty": "easy",
         "tool_mocks": [
             ("get_submission_context", {"account": {"name": "Acme Dynamics LLC", "sic_code": "3599", "years_in_business": 15}, "submission": {"lob": "DO", "annual_revenue": 50000000, "employee_count": 250, "board_size": 7, "independent_directors": 4}, "loss_history": [{"year": 2023, "claims": 0}, {"year": 2024, "claims": 0}, {"year": 2025, "claims": 0}]}),
             ("get_loss_history", {"total_claims": 0, "total_incurred": 0, "years": [{"year": 2023, "claims": 0}, {"year": 2024, "claims": 0}, {"year": 2025, "claims": 0}]}),
         ]},
        {"sub_id": "00000002-0002-0002-0002-000000000002", "name": "TechFlow D&O",
         "lob": "DO", "named_insured": "TechFlow Industries Inc",
         "expected": {"risk_score": "Amber", "routing": "assign_to_senior_uw", "confidence": 0.72},
         "difficulty": "medium",
         "tool_mocks": [
             ("get_submission_context", {"account": {"name": "TechFlow Industries Inc", "sic_code": "7372", "years_in_business": 8}, "submission": {"lob": "DO", "annual_revenue": 120000000, "board_size": 9, "independent_directors": 5, "regulatory_investigation": "SEC routine inquiry"}, "loss_history": [{"year": 2023, "claims": 1, "incurred": 75000}, {"year": 2024, "claims": 0}, {"year": 2025, "claims": 1, "incurred": 150000}]}),
             ("get_loss_history", {"total_claims": 2, "total_incurred": 225000, "years": [{"year": 2023, "claims": 1}, {"year": 2024, "claims": 0}, {"year": 2025, "claims": 1}]}),
         ]},
        {"sub_id": "00000003-0003-0003-0003-000000000003", "name": "Meridian GL",
         "lob": "GL", "named_insured": "Meridian Holdings Corp",
         "expected": {"risk_score": "Red", "routing": "refer_to_management", "confidence": 0.85},
         "difficulty": "easy",
         "tool_mocks": [
             ("get_submission_context", {"account": {"name": "Meridian Holdings Corp", "sic_code": "6159", "years_in_business": 22}, "submission": {"lob": "GL", "annual_revenue": 25000000, "going_concern_opinion": True}, "loss_history": [{"year": 2023, "claims": 5, "incurred": 220000}, {"year": 2024, "claims": 4, "incurred": 190000}, {"year": 2025, "claims": 3, "incurred": 190000}]}),
             ("get_loss_history", {"total_claims": 12, "total_incurred": 600000, "years": [{"year": 2023, "claims": 5}, {"year": 2024, "claims": 4}, {"year": 2025, "claims": 3}]}),
         ]},
        {"sub_id": "00000004-0004-0004-0004-000000000004", "name": "Acme GL",
         "lob": "GL", "named_insured": "Acme Dynamics LLC",
         "expected": {"risk_score": "Amber", "routing": "assign_to_senior_uw", "confidence": 0.74},
         "difficulty": "medium",
         "tool_mocks": [
             ("get_submission_context", {"account": {"name": "Acme Dynamics LLC", "sic_code": "3599", "years_in_business": 15}, "submission": {"lob": "GL", "annual_revenue": 50000000, "manufacturing_operations": True}, "loss_history": [{"year": 2023, "claims": 2, "incurred": 65000}, {"year": 2024, "claims": 1, "incurred": 45000}, {"year": 2025, "claims": 2, "incurred": 80000}]}),
             ("get_loss_history", {"total_claims": 5, "total_incurred": 190000, "years": [{"year": 2023, "claims": 2}, {"year": 2024, "claims": 1}, {"year": 2025, "claims": 2}]}),
         ]},
    ]

    for idx, tc in enumerate(triage_cases):
        record = await verity.registry.register_ground_truth_record(
            dataset_id=str(gt_tri_id), record_index=idx,
            source_type="submission",
            source_provider=None, source_container=None, source_key=None,
            source_description=f"Submission: {tc['name']}",
            input_data={"submission_id": tc["sub_id"], "lob": tc["lob"], "named_insured": tc["named_insured"]},
            tags=[tc["lob"], tc["expected"]["risk_score"].lower()],
            difficulty=tc["difficulty"],
            record_notes=None,
        )

        await verity.registry.register_ground_truth_annotation(
            record_id=str(record["id"]), dataset_id=str(gt_tri_id),
            annotator_type="human_sme",
            labeled_by="James Okafor, Model Risk",
            label_confidence=0.95,
            label_notes=f"Risk score determined by senior underwriter review of full submission",
            judge_model=None, judge_prompt_version_id=None, judge_reasoning=None,
            expected_output=tc["expected"],
            is_authoritative=True,
        )

        # Insert tool mocks for this agent record
        for tool_name, mock_response in tc.get("tool_mocks", []):
            await verity.db.execute_returning("insert_ground_truth_record_mock", {
                "record_id": str(record["id"]), "tool_name": tool_name,
                "call_order": 1, "mock_response": json.dumps(mock_response),
                "description": f"Scenario data for {tc['named_insured']}",
            })

    print(f"  + triage ground truth: {len(triage_cases)} records with annotations and tool mocks")

    # ── 4. APPETITE GROUND TRUTH (4 submissions) ─────────────
    gt_app_id = gt_datasets["gt_appetite"]["id"]

    appetite_cases = [
        {"sub_id": "00000001-0001-0001-0001-000000000001", "name": "Acme D&O",
         "lob": "DO", "named_insured": "Acme Dynamics LLC",
         "expected": {"determination": "within_appetite", "confidence": 0.92},
         "difficulty": "easy",
         "tool_mocks": [
             ("get_underwriting_guidelines", {"lob": "DO", "guidelines_text": "§1 GENERAL ELIGIBILITY\n1.2 Min 3 years in business.\n1.3 Revenue $10M-$500M.\n§2 FINANCIAL\n2.1 Revenue > $10M.\n2.2 No going concern.\n2.4 D/E < 3:1.\n§3 GOVERNANCE\n3.1 Board >= 5.\n3.3 Majority independent.\n§4 EXCLUSIONS\n4.1 SIC 6000-6199 requires special approval.\n§5 CLAIMS\n5.1 Max 2 D&O claims in 5 years."}),
             ("get_submission_context", {"account": {"name": "Acme Dynamics LLC", "sic_code": "3599", "years_in_business": 15}, "submission": {"lob": "DO", "annual_revenue": 50000000, "board_size": 7, "independent_directors": 4}}),
         ]},
        {"sub_id": "00000002-0002-0002-0002-000000000002", "name": "TechFlow D&O",
         "lob": "DO", "named_insured": "TechFlow Industries Inc",
         "expected": {"determination": "borderline", "confidence": 0.65},
         "difficulty": "hard",
         "tool_mocks": [
             ("get_underwriting_guidelines", {"lob": "DO", "guidelines_text": "§1 GENERAL ELIGIBILITY\n1.2 Min 3 years.\n1.3 Revenue $10M-$500M.\n§2 FINANCIAL\n2.1 Revenue > $10M.\n§3 GOVERNANCE\n3.1 Board >= 5.\n3.2 No pending SEC enforcement. Routine inquiries acceptable.\n3.3 Majority independent.\n§5 CLAIMS\n5.1 Max 2 D&O claims in 5 years."}),
             ("get_submission_context", {"account": {"name": "TechFlow Industries Inc", "sic_code": "7372", "years_in_business": 8}, "submission": {"lob": "DO", "annual_revenue": 120000000, "board_size": 9, "independent_directors": 5, "regulatory_investigation": "SEC routine inquiry"}}),
         ]},
        {"sub_id": "00000003-0003-0003-0003-000000000003", "name": "Meridian GL",
         "lob": "GL", "named_insured": "Meridian Holdings Corp",
         "expected": {"determination": "outside_appetite", "confidence": 0.94},
         "difficulty": "easy",
         "tool_mocks": [
             ("get_underwriting_guidelines", {"lob": "GL", "guidelines_text": "§1 ELIGIBILITY\n1.2 Min 2 years.\n1.3 Revenue $5M-$250M.\n§4 EXCLUSIONS\n4.1 SIC 6000-6199 excluded.\n4.3 Going concern excluded.\n§6 CLAIMS\n6.1 Max 5 GL claims in 3 years."}),
             ("get_submission_context", {"account": {"name": "Meridian Holdings Corp", "sic_code": "6159", "years_in_business": 22}, "submission": {"lob": "GL", "annual_revenue": 25000000, "going_concern_opinion": True}}),
         ]},
        {"sub_id": "00000004-0004-0004-0004-000000000004", "name": "Acme GL",
         "lob": "GL", "named_insured": "Acme Dynamics LLC",
         "expected": {"determination": "within_appetite", "confidence": 0.81},
         "difficulty": "medium",
         "tool_mocks": [
             ("get_underwriting_guidelines", {"lob": "GL", "guidelines_text": "§1 ELIGIBILITY\n1.2 Min 2 years.\n1.3 Revenue $5M-$250M.\n§5 MANUFACTURING\n5.1 Light mfg (3400-3599) standard.\n§6 CLAIMS\n6.1 Max 5 GL claims in 3 years."}),
             ("get_submission_context", {"account": {"name": "Acme Dynamics LLC", "sic_code": "3599", "years_in_business": 15}, "submission": {"lob": "GL", "annual_revenue": 50000000, "manufacturing_operations": True}}),
         ]},
    ]

    for idx, tc in enumerate(appetite_cases):
        record = await verity.registry.register_ground_truth_record(
            dataset_id=str(gt_app_id), record_index=idx,
            source_type="submission",
            source_provider=None, source_container=None, source_key=None,
            source_description=f"Submission: {tc['name']}",
            input_data={"submission_id": tc["sub_id"], "lob": tc["lob"], "named_insured": tc["named_insured"]},
            tags=[tc["lob"], tc["expected"]["determination"]],
            difficulty=tc["difficulty"],
            record_notes=None,
        )

        await verity.registry.register_ground_truth_annotation(
            record_id=str(record["id"]), dataset_id=str(gt_app_id),
            annotator_type="human_sme",
            labeled_by="James Okafor, Model Risk",
            label_confidence=0.95,
            label_notes=f"Appetite determination based on guideline review by senior underwriter",
            judge_model=None, judge_prompt_version_id=None, judge_reasoning=None,
            expected_output=tc["expected"],
            is_authoritative=True,
        )

        for tool_name, mock_response in tc.get("tool_mocks", []):
            await verity.db.execute_returning("insert_ground_truth_record_mock", {
                "record_id": str(record["id"]), "tool_name": tool_name,
                "call_order": 1, "mock_response": json.dumps(mock_response),
                "description": f"Scenario data for {tc['named_insured']}",
            })

    print(f"  + appetite ground truth: {len(appetite_cases)} records with annotations and tool mocks")


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
         "classifier_output": {"document_type": "do_application", "confidence": 0.97, "classification_notes": "Clear D&O liability application header"},
         "extractor_output": {"fields": {"named_insured": "Acme Dynamics LLC", "annual_revenue": 50000000, "employee_count": 250, "board_size": 7}, "low_confidence_fields": [], "extraction_complete": True},
         "triage_output": {"risk_score": "Green", "routing": "assign_to_uw", "confidence": 0.89, "reasoning": "Strong financials, clean loss history, experienced board. Standard D&O risk profile.", "risk_factors": [{"factor": "Revenue concentration", "severity": "low", "detail": "Single market segment"}]},
         "appetite_output": {"determination": "within_appetite", "confidence": 0.92, "reasoning": "Meets all D&O guidelines criteria per §2.1-2.4.", "guideline_citations": [{"section": "§2.1", "criterion": "Revenue > $10M", "meets": True}]}},

        {"id": "00000002-0002-0002-0002-000000000002", "name": "TechFlow Industries D&O", "lob": "DO",
         "classifier_output": {"document_type": "do_application", "confidence": 0.94, "classification_notes": "D&O application with some non-standard formatting"},
         "extractor_output": {"fields": {"named_insured": "TechFlow Industries Inc", "annual_revenue": 120000000, "employee_count": 800, "board_size": 9}, "low_confidence_fields": ["regulatory_investigation_history"], "extraction_complete": True},
         "triage_output": {"risk_score": "Amber", "routing": "assign_to_senior_uw", "confidence": 0.72, "reasoning": "Mixed profile. Strong revenue but pending regulatory investigation and recent board turnover raise concerns.", "risk_factors": [{"factor": "Regulatory investigation", "severity": "medium", "detail": "SEC inquiry pending"}, {"factor": "Board turnover", "severity": "low", "detail": "3 directors replaced in 12 months"}]},
         "appetite_output": {"determination": "borderline", "confidence": 0.65, "reasoning": "Meets most criteria but §3.2 flags pending regulatory matters.", "guideline_citations": [{"section": "§3.2", "criterion": "No pending regulatory investigations", "meets": False}]}},

        {"id": "00000003-0003-0003-0003-000000000003", "name": "Meridian Holdings GL", "lob": "GL",
         "classifier_output": {"document_type": "gl_application", "confidence": 0.91, "classification_notes": "General liability application form"},
         "extractor_output": {"fields": {"named_insured": "Meridian Holdings Corp", "annual_revenue": 25000000, "employee_count": 150}, "low_confidence_fields": ["prior_premium"], "extraction_complete": True},
         "triage_output": {"risk_score": "Red", "routing": "refer_to_management", "confidence": 0.85, "reasoning": "High claims frequency, going concern qualification, and industry in excluded SIC codes.", "risk_factors": [{"factor": "Claims frequency", "severity": "high", "detail": "12 claims in 3 years"}, {"factor": "Going concern", "severity": "critical", "detail": "Auditor qualified opinion"}]},
         "appetite_output": {"determination": "outside_appetite", "confidence": 0.94, "reasoning": "Multiple guideline violations: §4.1 excluded SIC code, §4.3 going concern disqualification.", "guideline_citations": [{"section": "§4.1", "criterion": "SIC code not excluded", "meets": False}, {"section": "§4.3", "criterion": "No going concern opinion", "meets": False}]}},

        {"id": "00000004-0004-0004-0004-000000000004", "name": "Acme Dynamics GL", "lob": "GL",
         "classifier_output": {"document_type": "gl_application", "confidence": 0.93, "classification_notes": "Standard GL application"},
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

    # Fixed workflow_run_id per submission — predictable so the UW app
    # can reference them in SUBMISSIONS list for "View in Verity" links.
    # These are caller-supplied correlation ids grouping the demo's
    # classify+extract step decisions, not Verity-owned pipeline runs.
    WORKFLOW_RUN_IDS = {
        "00000001-0001-0001-0001-000000000001": "aaaa0001-0001-0001-0001-000000000001",
        "00000002-0002-0002-0002-000000000002": "aaaa0002-0002-0002-0002-000000000002",
        "00000003-0003-0003-0003-000000000003": "aaaa0003-0003-0003-0003-000000000003",
        "00000004-0004-0004-0004-000000000004": "aaaa0004-0004-0004-0004-000000000004",
    }
    from datetime import datetime, timezone
    seed_started_at = datetime.now(timezone.utc)

    decision_count = 0
    override_decisions = []

    for sub in submissions:
        workflow_run_id = WORKFLOW_RUN_IDS[sub["id"]]
        for step_name, entity_type, version_id, output_key, config_name, model, temp, max_tok in step_configs:
            output = sub[output_key]

            from verity.models.decision import DecisionLogCreate
            from verity.models.lifecycle import DeploymentChannel, EntityType as ET

            log_result = await verity.decisions.log_decision(DecisionLogCreate(
                entity_type=ET(entity_type),
                entity_version_id=version_id,
                prompt_version_ids=[],
                inference_config_snapshot={"config_name": config_name, "model_name": model, "temperature": temp, "max_tokens": max_tok},
                channel=DeploymentChannel.PRODUCTION,
                workflow_run_id=workflow_run_id,
                parent_decision_id=None,
                decision_depth=0,
                step_name=step_name,
                input_summary=f"{sub['name']} — {sub['lob']}",
                input_json={"submission_id": sub["id"], "lob": sub["lob"], "named_insured": sub["name"]},
                output_json=output,
                output_summary=json.dumps(output)[:300],
                reasoning_text=output.get("reasoning", ""),
                risk_factors=output.get("risk_factors"),
                confidence_score=output.get("confidence"),
                model_used=model,
                input_tokens=1500 + (decision_count * 100),
                output_tokens=800 + (decision_count * 50),
                duration_ms=2000 + (decision_count * 300),
                application="uw_demo",
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
            ))

    print(f"  + {len(override_decisions)} override logs")


# ══════════════════════════════════════════════════════════════
# STEP 20: PLATFORM SETTINGS
# ══════════════════════════════════════════════════════════════

async def seed_platform_settings(verity: Verity):
    """Seed Verity platform settings (decision logging levels, thresholds).

    These live in verity_db.platform_settings and control governance
    behavior across all consuming applications.
    """
    settings_data = [
        # Decision Logging
        ("decision_log_detail", "standard", "decision_logging", "Default Detail Level",
         "Controls how much data is stored in the decision log for each AI invocation. "
         "FULL=complete payloads (for audit/replay). STANDARD=redact binary/large content. "
         "SUMMARY=first 500 chars only. METADATA=status/tokens/duration only. NONE=no log entry.",
         "select", "full,standard,summary,metadata,none", 1),

        ("redact_input_threshold", "10000", "decision_logging", "Input Redaction Threshold (chars)",
         "Text fields in input_json longer than this are truncated at STANDARD level. "
         "Base64 content and fields starting with _ are always redacted at STANDARD.",
         "number", None, 2),

        ("redact_output_threshold", "10000", "decision_logging", "Output Redaction Threshold (chars)",
         "Text fields in output_json longer than this are truncated at STANDARD level.",
         "number", None, 3),

        ("redact_message_threshold", "5000", "decision_logging", "Message Block Threshold (chars)",
         "Individual message content blocks in message_history longer than this are truncated. "
         "Document/image content blocks are always removed at STANDARD level.",
         "number", None, 4),

        ("redact_tool_payload_threshold", "1000", "decision_logging", "Tool Payload Threshold (chars)",
         "Tool call input_data and output_data payloads longer than this are truncated at STANDARD level.",
         "number", None, 5),
    ]

    # Write to verity_db using the SDK's execute_raw (named params)
    for key, value, category, display_name, desc, input_type, options, sort_order in settings_data:
        await verity.db.execute_raw(
            """INSERT INTO platform_settings (key, value, category, display_name, description, input_type, options, sort_order)
            VALUES (%(key)s, %(value)s, %(category)s, %(display_name)s, %(description)s, %(input_type)s, %(options)s, %(sort_order)s)
            ON CONFLICT (key) DO NOTHING""",
            {"key": key, "value": value, "category": category, "display_name": display_name,
             "description": desc, "input_type": input_type, "options": options, "sort_order": sort_order},
        )
    print(f"  + {len(settings_data)} platform settings seeded")


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(main())
