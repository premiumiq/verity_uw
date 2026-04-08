# EDMS Collection & Folder Metamodel Design

## Design Principles

1. **Collections are governed storage domains** - not just folders with buckets.
   They carry policies, defaults, ownership, and lifecycle state.
2. **Folders are organizational structure** - lightweight, virtual, hierarchical.
   They exist to help humans navigate documents, not to control storage or security.
3. **Every document belongs to exactly one collection** - this is mandatory.
   The collection determines where the file physically lives (MinIO bucket).
4. **Folders are optional** - a document can live at the collection root.
5. **Security will be at the collection level** (future) - not folder level.
   Collections are the unit of access control.
6. **Properties cascade** - a collection can define default tags that apply to
   all documents placed in it. Folders can override with their own defaults.

## Data Model

### Collection

A collection is a governed storage domain. Think of it as a filing cabinet
with specific rules about what goes in it and who can access it.

```sql
CREATE TABLE IF NOT EXISTS collection (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identity
    name                VARCHAR(100) UNIQUE NOT NULL,
    -- Machine name (e.g., "submissions", "uw_guidelines", "ground_truth")
    display_name        VARCHAR(200) NOT NULL,
    -- Human name (e.g., "Insurance Submissions", "Underwriting Guidelines")
    description         TEXT,
    -- Purpose of this collection

    -- Storage mapping
    storage_provider    VARCHAR(50) NOT NULL DEFAULT 'minio',
    storage_container   VARCHAR(200) NOT NULL,
    -- MinIO bucket name (e.g., "submissions"). One bucket per collection.
    storage_prefix      VARCHAR(500) DEFAULT '',
    -- Optional prefix within the bucket. Empty string = root of bucket.

    -- Lifecycle
    status              VARCHAR(50) NOT NULL DEFAULT 'active',
    -- 'active'    = accepting new documents, full read/write
    -- 'readonly'  = no new uploads, existing docs accessible
    -- 'archived'  = no access without explicit unarchive
    -- 'locked'    = regulatory hold, no modifications allowed

    -- Governance defaults
    -- Tags that automatically apply to every document placed in this collection.
    -- Documents can add more tags but cannot remove collection-level defaults.
    -- e.g., {"sensitivity": ["confidential"], "lob": ["do"]}
    default_tags        JSONB DEFAULT '{}',

    -- Ownership
    owner_name          VARCHAR(200) NOT NULL,
    created_by          VARCHAR(200) NOT NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);
```

### Folder

A folder is a virtual directory within a collection. Hierarchical via
self-referencing parent_folder_id. Paths are computed, not stored.

```sql
CREATE TABLE IF NOT EXISTS folder (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    collection_id       UUID NOT NULL REFERENCES collection(id) ON DELETE CASCADE,
    -- Every folder belongs to exactly one collection.

    parent_folder_id    UUID REFERENCES folder(id),
    -- NULL = direct child of the collection root.
    -- Set  = nested under another folder in the same collection.

    name                VARCHAR(200) NOT NULL,
    description         TEXT,

    -- Folder-level tag defaults (merge with collection defaults)
    default_tags        JSONB DEFAULT '{}',

    created_by          VARCHAR(200) NOT NULL DEFAULT 'system',
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),

    -- No two siblings in the same collection can have the same name
    CONSTRAINT uq_folder_in_collection UNIQUE (collection_id, parent_folder_id, name)
);
```

### Document (Modified)

Replace the single `folder_id` with `collection_id` (mandatory) + `folder_id` (optional).

```sql
-- On the document table:
    collection_id       UUID NOT NULL REFERENCES collection(id),
    -- Mandatory: every document lives in a collection.
    folder_id           UUID REFERENCES folder(id),
    -- Optional: document can be at collection root (folder_id = NULL)
    --           or in a folder within the collection.
```

The `storage_container` on document becomes derived from the collection.
The `storage_key` includes the folder path for organization.

## UI Flow

### Collection Setup Page (/ui/collections)

Dedicated page for managing collections. Separate from folder management.

Each collection card shows:
- Name, display name, description
- MinIO bucket mapping
- Status badge (active/readonly/archived/locked)
- Default tags
- Document count
- Created by / when

Actions: Create, Edit, Archive, Lock, Delete (only if empty)

### Folder Management (/ui/collections/{id}/folders)

Per-collection folder management. Shows tree view of folders within
the selected collection.

Tree is expandable/collapsible. Each node shows:
- Folder name
- Document count
- Default tags (if any)

Actions: Create (with tree position picker), Rename, Move, Delete

### Folder Picker (Modal Component)

Reusable across Upload and Document Detail pages.

Step 1: Select collection (dropdown or card selector)
Step 2: Select folder within collection (expandable tree, click to select)

Shows selected path: Collection > Folder > Subfolder

### Document Browser

Each row shows breadcrumb:
- If <= 3 levels: Collection > Folder > Subfolder
- If > 3 levels: Collection > ... > Leaf Folder

Left sidebar: Collection list (click to filter). Within selected collection,
show folder tree.

### Upload Form

Two-step location selector:
1. Collection dropdown (required)
2. Folder tree within selected collection (optional, uses HTMX to load
   the tree when collection is selected)

## Path Computation

Folder paths are computed by walking the parent chain. For display:

```
Full path:    Submissions / 2026 / Q1 / Acme Dynamics
Short path:   Submissions / ... / Acme Dynamics  (when > 3 levels)
```

A helper function computes the path from folder_id by walking parent_folder_id
up to NULL (collection root).

## Seed Data

Initial collections for the demo:

| Name | Display Name | Bucket | Purpose |
|------|-------------|--------|---------|
| submissions | Insurance Submissions | submissions | Application packages for UW review |
| uw_guidelines | Underwriting Guidelines | uw-guidelines | Guideline documents by LOB |
| ground_truth | Ground Truth Datasets | ground-truth-datasets | Labeled data for AI validation |

Initial folders within "submissions":
- 2026/
  - Q1/
  - Q2/
- By Insured/
  - Acme Dynamics/
  - TechFlow Industries/
  - Meridian Holdings/

## Implementation Changes

### Schema
- CREATE `collection` table (new)
- ALTER `folder`: add `collection_id` FK, remove `storage_container`/`storage_prefix`
- ALTER `document`: add `collection_id` FK (NOT NULL), keep `folder_id`
- Remove `storage_container` from document (derived from collection)

### DB Operations
- Collection CRUD
- Folder CRUD scoped to collection
- Path computation helper
- Update insert_document to require collection_id

### API Routes
- /collections (CRUD)
- /collections/{id}/folders (tree within collection)
- /collections/{id}/documents (docs in collection)

### UI
- Collection management page
- Per-collection folder tree page
- Collection+folder picker component (for upload and document detail)
- Updated browser with collection/folder breadcrumbs
