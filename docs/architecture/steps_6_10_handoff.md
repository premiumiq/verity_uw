# Steps 6-10: Verity-EDMS Integration - Detailed Handoff

## READ THIS FIRST. Do not explore the codebase. Everything you need is here.

## Context

EDMS is a FastAPI service running in its own Docker container on port 8002.
It has REST APIs for document management. Verity is the AI governance platform
on port 8000. UW Demo is the business app on port 8001.

The UW pipeline has 4 steps: classify_documents, extract_fields, triage_submission,
assess_appetite. Steps 1-2 (classify, extract) currently fail because they have
no document content. The prompts use `{{document_text}}` but nobody provides it.

The fix: classify and extract become AGENTS (not tasks) so they can call EDMS
tools to fetch document content themselves.

## Step 6: Register EDMS tools in Verity

### What to do
Add two new tool registrations in `uw_demo/app/setup/register_all.py` inside
the `seed_tools()` function. These go in the `tools` list alongside the existing
8 tools (get_submission_context, get_loss_history, etc.).

### Exact tools to add

```python
{
    "name": "list_documents",
    "display_name": "List Documents",
    "description": "Returns metadata for all documents in the EDMS for a given business context. Called by classifier and extractor agents to discover what documents are available.",
    "input_schema": {"type": "object", "properties": {"context_ref": {"type": "string"}}, "required": ["context_ref"]},
    "output_schema": {"type": "object", "properties": {"documents": {"type": "array"}}},
    "implementation_path": "edms.client.EdmsClient.list_documents",
    "mock_mode_enabled": True, "mock_response_key": "default",
    "data_classification_max": "tier3_confidential",
    "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "documents", "edms"],
},
{
    "name": "get_document_text",
    "display_name": "Get Document Text",
    "description": "Returns the extracted text content of a document from the EDMS. The document must have been previously uploaded and text-extracted. Called by classifier and extractor agents.",
    "input_schema": {"type": "object", "properties": {"document_id": {"type": "string"}}, "required": ["document_id"]},
    "output_schema": {"type": "object", "properties": {"text": {"type": "string"}, "char_count": {"type": "integer"}}},
    "implementation_path": "edms.client.EdmsClient.get_document_text",
    "mock_mode_enabled": True, "mock_response_key": "default",
    "data_classification_max": "tier3_confidential",
    "is_write_operation": False, "requires_confirmation": False, "tags": ["read", "documents", "edms"],
},
```

### File to modify
`uw_demo/app/setup/register_all.py` - add to the `tools` list in `seed_tools()`.

---

## Step 7: Register EDMS tool implementations in UW app

### What to do
In `uw_demo/app/main.py`, import EdmsClient and register the two EDMS tools
as tool implementations on the Verity SDK instance.

### Exact code to add

After the existing tool registrations (around line 67), add:

```python
# EDMS document tools — calls the EDMS service via HTTP
from edms import EdmsClient
edms = EdmsClient(base_url=settings.EDMS_URL)

verity.register_tool_implementation("list_documents",
    lambda context_ref: asyncio.get_event_loop().run_until_complete(edms.list_documents(context_ref)))
verity.register_tool_implementation("get_document_text",
    lambda document_id: asyncio.get_event_loop().run_until_complete(edms.get_document_text(document_id)))
```

WAIT - the execution engine calls tools with `await`, so these need to be async.
The EdmsClient methods are already async. So simpler:

```python
from edms import EdmsClient
edms = EdmsClient(base_url=settings.EDMS_URL)

verity.register_tool_implementation("list_documents", edms.list_documents)
verity.register_tool_implementation("get_document_text", edms.get_document_text)
```

### Config needed
`EDMS_URL` must be in `uw_demo/app/config.py`:
```python
EDMS_URL: str = os.getenv("EDMS_URL", "http://localhost:8002")
```

Already set in docker-compose.yml: `EDMS_URL: http://edms:8002`

### File to modify
- `uw_demo/app/main.py` - add EdmsClient import and tool registrations
- `uw_demo/app/config.py` - add EDMS_URL setting (if not already there)

---

## Step 8: Upload seed documents to EDMS during setup

### What to do
After the UW seed script runs, the 54 generated documents in `uw_demo/seed_docs/filled/`
need to be uploaded to EDMS via its HTTP API. This should be a new step in
`register_all.py` or a separate script.

### Approach
Use the EdmsClient HTTP client to upload documents. For each of the 4 demo
submissions, upload their documents to EDMS:

- SUB-001 (Acme D&O): do_app_acme_dynamics.pdf, loss_run_acme_dynamics.txt, board_resolution_acme_dynamics.txt
- SUB-002 (TechFlow D&O): do_app_techflow_industries.pdf, loss_run_techflow_industries.txt, financial_stmt_techflow_industries.txt
- SUB-003 (Meridian GL): gl_app_meridian_holdings.pdf, loss_run_meridian_holdings.txt, financial_stmt_meridian_holdings.txt
- SUB-004 (Acme GL): no GL profile exists for Acme in docgen - use atlas_building or skip

For each document:
1. Call EDMS upload-local API (documents are already on disk in the container)
2. Call EDMS extract API (trigger text extraction)

The EDMS service must be running when this executes. The UW demo container
has `depends_on: edms` in docker-compose.yml.

### Key mapping
The `context_ref` for each document should match what the pipeline uses:
`"submission:{submission_id}"` (e.g., `"submission:00000001-0001-0001-0001-000000000001"`)

### File to create or modify
Either add a new function `seed_edms_documents()` in `register_all.py` or
create a new script `uw_demo/app/setup/seed_edms.py`.

The `collection_id` must come from the EDMS "general" collection created by
the EDMS seed script. Query EDMS API to find it:
```python
edms = EdmsClient(base_url=settings.EDMS_URL)
collections = await edms.list_documents("dummy")  # No, use the collections API
# Actually EdmsClient doesn't have a list_collections method yet.
# Need to add one, or use httpx directly.
```

---

## Step 9: Convert classifier and extractor from tasks to agents

### What to do
Currently `document_classifier` and `field_extractor` are registered as TASKS
in `register_all.py`. Tasks are single-turn: prompt in, output out. They cannot
call tools.

They need to become AGENTS so they can call `list_documents` and `get_document_text`
to fetch document content from EDMS before classifying/extracting.

### Changes in register_all.py

In `seed_entities()`, change:
```python
# FROM:
"document_classifier": {
    "entity_type": "task",
    ...
}
# TO:
"document_classifier": {
    "entity_type": "agent",
    ...
}
```

Same for `field_extractor`.

This affects:
- Entity registration (agent vs task table)
- Version registration (agent_version vs task_version table)
- Tool authorization (agents can have tools, tasks currently can too)
- Prompt assignment (same API, different entity_type parameter)
- Pipeline step definition (entity_type in the step)

### Prompt changes needed
The classifier and extractor prompts (in `uw_demo/app/prompts.py`) need to
include tool-calling instructions:

Classifier system prompt needs:
```
You have access to these tools:
1. list_documents(context_ref) - returns list of documents for a submission
2. get_document_text(document_id) - returns extracted text of a document

For each document, call get_document_text to retrieve its content, then classify.
```

Extractor system prompt needs similar tool instructions.

### Pipeline step changes
In `register_all.py` where pipeline steps are defined, change entity_type
from "task" to "agent" for classify_documents and extract_fields steps.

---

## Step 10: Update pipeline and test end-to-end

### What to do
1. Ensure the Dockerfile installs the `edms` package (for EdmsClient import)
2. Rebuild all containers
3. Run the full seed: EDMS seeds automatically, then run UW seed, then seed EDMS docs
4. Test: run a mock pipeline from UW demo, verify classifier gets real document text

### Dockerfile change
In the root `Dockerfile`, add:
```
COPY edms/ /app/edms/
RUN pip install --no-cache-dir /app/edms/
```
(Only the client part is needed - the service runs in its own container)

### Test sequence
```bash
docker compose down -v
docker compose up -d --build
# EDMS auto-seeds governance data + test collection
docker compose exec uw-demo python -m uw_demo.app.setup.register_all
# Upload documents to EDMS
docker compose exec uw-demo python -m uw_demo.app.setup.seed_edms
# Test pipeline
# Go to http://localhost:8001, pick a submission, run pipeline in mock mode
# Then try live mode - classifier should get real text from EDMS
```

---

## Architecture Reminders

- **Verity NEVER imports EDMS.** The UW app imports both.
- **EdmsClient is an HTTP client** at `edms/src/edms/client.py`. It makes HTTP
  requests to the EDMS service. No direct DB access.
- **Tool implementations are function pointers** registered at app startup.
  `verity.register_tool_implementation("name", async_function)`.
  The execution engine calls these when Claude requests a tool.
- **submission_id was REMOVED from all Verity tables.** Business context is
  linked via `execution_context_id` only.
- **Prompt template variables** (`{{document_text}}`) are auto-extracted on
  registration and validated at execution time. Missing variables raise a
  clear error. Since classifier/extractor will now be agents that fetch their
  own content via tools, their prompts should NOT use `{{document_text}}` anymore.

## Key Files

| File | What it does |
|------|-------------|
| `uw_demo/app/setup/register_all.py` | Seeds all Verity entities. Modify for Steps 6, 8, 9 |
| `uw_demo/app/main.py` | UW app startup. Modify for Step 7 |
| `uw_demo/app/config.py` | UW app config. Has EDMS_URL |
| `uw_demo/app/prompts.py` | All prompt content. Modify for Step 9 |
| `edms/src/edms/client.py` | EdmsClient HTTP client (for UW app) |
| `edms/src/edms/service/routes.py` | EDMS REST API endpoints |
| `Dockerfile` | Root Dockerfile for verity + uw-demo containers |
| `docker-compose.yml` | All 5 containers defined here |
| `verity/src/verity/core/execution.py` | Execution engine - runs agents/tasks, calls tools |
