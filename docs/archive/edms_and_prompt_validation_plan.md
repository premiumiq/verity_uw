# EDMS Package + Prompt Placeholder Validation

## Context

The UW pipeline's classifier and extractor tasks receive `{{document_text}}`
literally because no document content flows through the system. We need:

1. An EDMS (Enterprise Document Management System) that handles document
   storage, text extraction, and metadata - as its own service/package.
2. Prompt placeholder validation so missing variables are caught at execution
   time, not silently passed to Claude.

## Architecture Decisions

### EDMS is a separate system

- **Own database:** `edms_db` (third database alongside `verity_db` and `pas_db`)
- **Own package:** `edms/` at the project root (pip-installable, like verity/ and insurance_docgen/)
- **Verity does not touch MinIO or EDMS directly.** All access is through registered tools.
- **Extracted text** saved back to MinIO as `.txt` alongside the original PDF, tracked in metadata.

### Tool-based integration

Agents and tasks access documents through Verity-governed tool calls:
- `list_documents(execution_context_id)` - returns metadata for all documents in a context
- `get_document_text(document_id)` - returns extracted text for a document
- `get_document_metadata(document_id)` - returns metadata (type, size, upload date, etc.)
- `upload_document(context_id, file, metadata)` - upload a new document (write tool)

These tools are:
- Registered in Verity with input/output schemas, data classification, write flags
- Implemented by the consuming app (UW demo) by wrapping the EDMS package
- Governed: every call is logged, authorized, mockable

---

## Part A: EDMS Package

### Package structure

```
edms/
    pyproject.toml
    src/
        edms/
            __init__.py
            client.py           # EdmsClient - main entry point
            storage.py          # MinIO/S3 storage operations
            text_extractor.py   # PDF text extraction (PyMuPDF)
            models.py           # Pydantic models for document metadata
            db.py               # Database operations for metadata
```

### Database: edms_db

```sql
-- Single table for document metadata
CREATE TABLE document (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Business context (opaque to EDMS - caller defines meaning)
    context_ref         VARCHAR(500) NOT NULL,
    -- e.g., "submission:00000001-...", "policy:POL-2026-001"
    context_type        VARCHAR(100),
    -- e.g., "submission", "policy", "claim"

    -- File identity
    filename            VARCHAR(500) NOT NULL,
    content_type        VARCHAR(100),
    -- MIME type: "application/pdf", "text/plain", etc.
    file_size_bytes     INTEGER,

    -- Storage location (abstracted - works with MinIO, S3, Azure Blob)
    storage_provider    VARCHAR(50) NOT NULL DEFAULT 'minio',
    storage_container   VARCHAR(200) NOT NULL,
    -- bucket name
    storage_key         VARCHAR(500) NOT NULL,
    -- object key within bucket

    -- Classification (set after classifier task runs)
    document_type       VARCHAR(100),
    -- "do_application", "gl_application", "loss_run", etc.
    -- NULL until classified

    -- Text extraction
    extracted_text_key  VARCHAR(500),
    -- MinIO key for the extracted .txt file (NULL until extracted)
    extraction_status   VARCHAR(50) NOT NULL DEFAULT 'pending',
    -- 'pending', 'complete', 'failed', 'not_applicable'
    extraction_error    TEXT,
    extracted_at        TIMESTAMP,

    -- Lineage
    uploaded_by         VARCHAR(200) NOT NULL,
    uploaded_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    tags                TEXT[] DEFAULT '{}',
    notes               TEXT,

    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_doc_context ON document(context_ref);
CREATE INDEX idx_doc_type ON document(document_type);
CREATE INDEX idx_doc_extraction ON document(extraction_status);
```

### EdmsClient API

```python
from edms import EdmsClient

client = EdmsClient(
    db_url="postgresql://...@.../edms_db",
    minio_endpoint="minio:9000",
    minio_access_key="minioadmin",
    minio_secret_key="minioadmin123",
)

# Upload a document
doc = await client.upload(
    context_ref="submission:00000001-...",
    context_type="submission",
    file_path="/path/to/acord_855_acme.pdf",
    uploaded_by="system",
)
# Returns: document metadata dict with id, storage_key, etc.

# Extract text from a document (PDF -> text via PyMuPDF)
# Saves extracted text to MinIO as {storage_key}.txt
# Updates metadata: extracted_text_key, extraction_status
await client.extract_text(document_id=doc["id"])

# Get document text (reads the extracted .txt from MinIO)
text = await client.get_text(document_id=doc["id"])
# Returns: string of extracted text

# List documents for a business context
docs = await client.list_documents(context_ref="submission:00000001-...")
# Returns: list of document metadata dicts

# Get metadata
meta = await client.get_metadata(document_id=doc["id"])
```

### Text extraction approach

- Use PyMuPDF (already installed) to extract text from PDFs
- For fillable PDFs: extract both form field values AND page text
- Save extracted text to MinIO at `{original_key}.extracted.txt`
- For text files (.txt): no extraction needed, copy content directly

### Docker: add edms_db

Add to docker-compose.yml postgres init script:
```
POSTGRES_MULTIPLE_DATABASES: verity_db,pas_db,edms_db
```

---

## Part B: Tool Registration in Verity

### New tools to register (in the seed script or UW app setup)

```python
# Tool: list_documents
# Returns document metadata for a given execution context
{
    "name": "list_documents",
    "display_name": "List Documents",
    "description": "Returns metadata for all documents associated with the current execution context.",
    "input_schema": {"type": "object", "properties": {"context_ref": {"type": "string"}}},
    "output_schema": {"type": "array", "items": {"type": "object"}},
    "data_classification_max": "tier3_confidential",
    "is_write_operation": False,
    "mock_mode_enabled": True,
}

# Tool: get_document_text
# Returns extracted text content for a specific document
{
    "name": "get_document_text",
    "display_name": "Get Document Text",
    "description": "Returns the extracted text content of a document by its ID.",
    "input_schema": {"type": "object", "properties": {"document_id": {"type": "string"}}},
    "output_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
    "data_classification_max": "tier3_confidential",
    "is_write_operation": False,
    "mock_mode_enabled": True,
}
```

### UW app registers implementations

```python
# In uw_demo/app/main.py
from edms import EdmsClient

edms = EdmsClient(db_url=settings.EDMS_DB_URL, ...)

verity.register_tool_implementation("list_documents", edms.list_documents)
verity.register_tool_implementation("get_document_text", edms.get_text)
```

---

## Part C: Pipeline Flow After EDMS

### Before (broken):
```
Pipeline context: {submission_id, lob, named_insured}
    → Classifier receives {{document_text}} literally
    → Extractor receives {{document_text}} literally
```

### After (working):
```
Pipeline context: {submission_id, lob, named_insured}
    → Step 1: classify_documents (now an AGENT, not task)
        → Calls list_documents(context_ref) → gets document list
        → For each doc, calls get_document_text(doc_id) → gets text
        → Classifies each document
    → Step 2: extract_fields (now an AGENT, not task)
        → Calls get_document_text(doc_id) → gets D&O application text
        → Extracts 20 fields from actual content
    → Step 3: triage_submission (agent, unchanged)
    → Step 4: assess_appetite (agent, unchanged)
```

### Key change: classify and extract become AGENTS

Currently they're tasks (single-turn, no tool calling). But they need to call
tools to fetch document content. So they must be agents.

This means:
- Change entity_type from 'task' to 'agent' in the seed script
- Update prompts to include tool-calling instructions
- Update pipeline step definitions

---

## Part D: Prompt Placeholder Validation

### Schema change

Add `template_variables` column to `prompt_version` table:

```sql
ALTER TABLE prompt_version ADD COLUMN template_variables TEXT[] DEFAULT '{}';
-- e.g., ['submission_id', 'lob', 'named_insured', 'document_text']
```

This column lists all `{{variable}}` placeholders in the prompt content.

### Auto-extraction on registration

When a prompt version is registered, scan the content for `{{...}}` patterns
and populate `template_variables` automatically:

```python
# In registry.py register_prompt_version()
import re
variables = re.findall(r'\{\{(\w+)\}\}', content)
# Store unique variables: ['submission_id', 'lob', 'named_insured']
```

### Validation at execution time

In `_assemble_prompts()` (execution.py), before sending to Claude, check
that every declared template variable has a value in the context:

```python
for prompt in sorted_prompts:
    if prompt.template_variables:
        missing = [v for v in prompt.template_variables if v not in context]
        if missing:
            raise ValueError(
                f"Prompt '{prompt.name}' requires variables {missing} "
                f"but they are not in the execution context. "
                f"Available keys: {list(context.keys())}"
            )
```

This gives a clear error message instead of silently passing `{{document_text}}`
to Claude.

---

## Part E: Seed Data Updates

### Upload generated documents to EDMS

The `register_all.py` seed script needs a new step:
1. Initialize EdmsClient
2. For each demo submission, upload its documents from `seed_docs/filled/`
3. Extract text from each uploaded document
4. Document metadata is now in `edms_db`, files in MinIO

### Mapping: submission → documents

| Submission | Company | Documents |
|---|---|---|
| SUB-001 (Acme D&O) | acme_dynamics | do_app_acme_dynamics.pdf, loss_run_acme_dynamics.txt, board_resolution_acme_dynamics.txt |
| SUB-002 (TechFlow D&O) | techflow_industries | do_app_techflow_industries.pdf, loss_run_techflow_industries.txt, financial_stmt_techflow_industries.txt |
| SUB-003 (Meridian GL) | meridian_holdings | gl_app_meridian_holdings.pdf, loss_run_meridian_holdings.txt, financial_stmt_meridian_holdings.txt |
| SUB-004 (Acme GL) | acme_dynamics | Would need a GL app for Acme - not in current profiles. Use atlas_building as substitute or add GL profile for Acme. |

---

## Implementation Order

| Step | What | Package/Files |
|---|---|---|
| 1 | Add edms_db to docker postgres init | docker-compose.yml, init script |
| 2 | Create edms/ package (client, storage, text_extractor, models, db) | edms/ |
| 3 | Add template_variables to prompt_version schema | verity schema.sql |
| 4 | Auto-extract variables on prompt registration | verity registry.py |
| 5 | Add validation in _assemble_prompts() | verity execution.py |
| 6 | Register EDMS tools in Verity (list_documents, get_document_text) | uw_demo register_all.py |
| 7 | Register EDMS tool implementations in UW app | uw_demo main.py |
| 8 | Upload seed documents to EDMS during setup | uw_demo register_all.py |
| 9 | Convert classifier and extractor from tasks to agents | uw_demo register_all.py, prompts |
| 10 | Update pipeline step definitions | uw_demo register_all.py |
| 11 | Test end-to-end: run pipeline, verify documents flow through | Manual |

## Verification

1. Run seed script - documents uploaded to MinIO via EDMS, metadata in edms_db
2. Run pipeline in mock mode - document tools return mock data, classifier/extractor work
3. Run pipeline in live mode - document tools fetch from EDMS, Claude classifies real text
4. Register a prompt with `{{missing_var}}` - execution fails with clear error message
