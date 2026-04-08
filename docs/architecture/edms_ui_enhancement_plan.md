# EDMS UI Enhancement Plan

## Summary of Gaps Identified

1. No bulk actions on browse page (delete, etc.)
2. No task tracking - extraction runs with no feedback or history
3. Document type needs two-level hierarchy (type + subtype)
4. No folder hierarchy for organizing documents
5. No task monitoring/management page

---

## Schema Changes

### 1. Folder Table

Virtual folder hierarchy. Top-level folders map to MinIO buckets or prefixes.
Nested folders are metadata-only - they organize documents in the UI but don't
change MinIO storage structure. Moving a document between nested folders
changes its folder_id, not its MinIO storage_key.

```sql
CREATE TABLE IF NOT EXISTS folder (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                VARCHAR(200) NOT NULL,
    parent_folder_id    UUID REFERENCES folder(id),
    -- NULL = top-level folder (maps to MinIO bucket or prefix)

    -- MinIO mapping (only for top-level folders)
    storage_container   VARCHAR(200),
    -- e.g., "submissions", "guidelines". NULL for nested folders.
    storage_prefix      VARCHAR(500),
    -- Optional prefix within the container. NULL = root of bucket.

    description         TEXT,
    created_by          VARCHAR(200) NOT NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_folder_name UNIQUE (parent_folder_id, name)
    -- No two sibling folders can have the same name
);

CREATE INDEX IF NOT EXISTS idx_folder_parent ON folder(parent_folder_id);
```

### 2. Document Type Hierarchy

Add parent_type_id to document_type_definition for two-level hierarchy.
Type = top-level (e.g., "Application"). Subtype = child (e.g., "D&O Application").

```sql
ALTER TABLE document_type_definition
    ADD COLUMN parent_type_id UUID REFERENCES document_type_definition(id);
-- NULL = top-level type. Set = subtype of that parent.
```

Documents reference the most specific type (the subtype). The parent is
derived by joining. Example:
- Type: "application" (parent_type_id = NULL)
  - Subtype: "do_application" (parent_type_id = application.id)
  - Subtype: "gl_application" (parent_type_id = application.id)
- Type: "report"
  - Subtype: "loss_run"
  - Subtype: "financial_statement"

### 3. Document Task Table

Tracks every task performed on a document. Not just text extraction - any
EDMS operation (OCR, thumbnail, redaction, etc.) Each task has a lifecycle:
pending -> running -> complete/failed.

```sql
CREATE TABLE IF NOT EXISTS document_task (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id         UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,

    task_type           VARCHAR(100) NOT NULL,
    -- e.g., 'text_extraction', 'ocr', 'thumbnail', 'redaction'
    task_method         VARCHAR(200),
    -- e.g., 'pymupdf_get_text', 'tesseract_ocr'

    status              VARCHAR(50) NOT NULL DEFAULT 'pending',
    -- 'pending', 'running', 'complete', 'failed'
    progress_pct        INTEGER DEFAULT 0,
    -- 0-100 percentage (for long-running tasks)

    started_at          TIMESTAMP,
    completed_at        TIMESTAMP,
    duration_ms         INTEGER,

    -- Result tracking
    result_document_id  UUID REFERENCES document(id),
    -- The child document produced by this task (if any)
    result_summary      TEXT,
    -- Brief human-readable summary (e.g., "Extracted 12,500 chars from 5 pages")
    error_message       TEXT,

    -- Who/what initiated this task
    initiated_by        VARCHAR(200) NOT NULL DEFAULT 'system',
    task_metadata       JSONB DEFAULT '{}',
    -- Extra info: {"pages_processed": 5, "char_count": 12500}

    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dt_document ON document_task(document_id);
CREATE INDEX IF NOT EXISTS idx_dt_status ON document_task(status);
CREATE INDEX IF NOT EXISTS idx_dt_type ON document_task(task_type);
```

### 4. Document Table Changes

Add folder_id to link documents to the folder hierarchy.

```sql
ALTER TABLE document ADD COLUMN folder_id UUID REFERENCES folder(id);
```

---

## UI Pages

### 1. Document Browser (Enhanced)

Current: Simple table with filters.

After:
- **Left sidebar:** Folder tree (expandable). Click a folder to filter documents.
- **Table:** Add checkbox column for bulk select. Bulk actions bar appears when
  items selected: Delete, Move to Folder, Set Type.
- **Row actions:** Quick delete button per row (trash icon).
- **Extraction status column:** Shows badge (pending/complete/failed) with link to task.

### 2. Document Detail (Enhanced)

Current: Metadata, type dropdown, tag editor, extracted text, lineage.

After:
- **Folder assignment:** Dropdown to move document to a different folder.
- **Task History section:** Table of all tasks run on this document (type, status,
  duration, result). "Extract Text" button creates a task record first, then runs.
- **Extraction feedback:** When "Extract Text" is clicked, a task is created with
  status "running". The page shows a spinner/progress indicator. On completion,
  the page refreshes to show the result. Uses HTMX polling for live status.

### 3. Task Monitor Page (NEW)

`/ui/tasks` - All tasks across all documents.

- Table: Document, Task Type, Status, Progress, Duration, Initiated By, When
- Filter by: status (pending/running/complete/failed), task_type
- Clickable rows -> document detail page
- Auto-refresh when tasks are running (HTMX polling every 3s)

### 4. Document Types Page (Enhanced)

Current: Flat list of type keys.

After:
- Two-level display: Top-level types shown as expandable cards.
  Subtypes listed within each card.
- Add type: Choose whether it's a top-level type or a subtype of an existing type.
- Display as indented tree.

### 5. Folder Management Page (NEW)

`/ui/folders` - Create and manage the folder hierarchy.

- Tree view of all folders with nesting
- Create folder (specify parent or top-level)
- For top-level folders: set MinIO bucket/prefix mapping
- Rename, delete (with confirmation if folder contains documents)
- Show document count per folder

### 6. Sidebar Navigation (Updated)

```
Documents
  Browse          (document browser with folder tree)
  Upload
  Tasks           (NEW: task monitor)

Organization
  Folders         (NEW: folder management)

Governance
  Tag Definitions
  Document Types  (enhanced: two-level)
```

---

## Task Execution Flow

When a user clicks "Extract Text" on a document:

1. UI POSTs to `/ui/documents/{id}/extract`
2. Route creates a `document_task` record: status='running', started_at=now
3. Route runs text extraction synchronously (fast enough for PDFs)
4. On success: creates child document + lineage, updates task: status='complete',
   result_document_id, result_summary, duration_ms
5. On failure: updates task: status='failed', error_message
6. Redirects back to document detail - task history shows the result

For long-running tasks (future: OCR, large batch):
1. Create task with status='pending'
2. Return to UI immediately (task visible in task list as pending)
3. Background worker picks up pending tasks and runs them
4. UI polls task status via HTMX

For now (demo), all tasks run synchronously on the request thread. Background
workers are a future enhancement.

---

## Implementation Order

| Step | What |
|------|------|
| 1 | Schema: Add folder, document_task tables. Modify document_type_definition, document. |
| 2 | DB: Add CRUD operations for folders and tasks. |
| 3 | API: Add folder and task REST endpoints. |
| 4 | UI: Folder management page |
| 5 | UI: Task monitor page |
| 6 | UI: Enhanced document browser (folder tree, bulk actions, extraction status) |
| 7 | UI: Enhanced document detail (folder assignment, task history, extraction feedback) |
| 8 | UI: Enhanced document types page (two-level hierarchy) |
| 9 | UI: Updated sidebar navigation |
