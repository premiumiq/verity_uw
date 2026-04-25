"""EDMS database operations — metadata CRUD for the collection-first model.

Uses psycopg v3 (async) with raw SQL. No ORM.
Connects to edms_db (separate from verity_db and pas_db).

Hierarchy: Collection -> Folder -> Document
Tag inheritance: Collection.default_tags -> Folder.default_tags -> Document.tags
"""

import json
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


_SCHEMA_FILE = Path(__file__).parent.parent / "schema.sql"


class EdmsDatabase:
    """Async database operations for EDMS."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self._conn = None

    async def connect(self):
        self._conn = await psycopg.AsyncConnection.connect(
            self.db_url, autocommit=True, row_factory=dict_row,
        )

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def apply_schema(self):
        schema_sql = _SCHEMA_FILE.read_text()
        async with await psycopg.AsyncConnection.connect(
            self.db_url, autocommit=True
        ) as conn:
            await conn.execute(schema_sql)

    # ══════════════════════════════════════════════════════════
    # COLLECTION OPERATIONS
    # ══════════════════════════════════════════════════════════

    async def insert_collection(
        self, name: str, display_name: str, storage_container: str,
        owner_name: str, created_by: str,
        description: Optional[str] = None, default_tags: Optional[dict] = None,
        status: str = "active",
    ) -> dict:
        result = await self._conn.execute(
            """INSERT INTO collection (name, display_name, description, storage_container,
                status, default_tags, owner_name, created_by)
            VALUES (%(name)s, %(display)s, %(desc)s, %(container)s,
                %(status)s, %(tags)s, %(owner)s, %(by)s)
            RETURNING *""",
            {"name": name, "display": display_name, "desc": description,
             "container": storage_container, "status": status,
             "tags": json.dumps(default_tags) if default_tags else "{}",
             "owner": owner_name, "by": created_by},
        )
        return await result.fetchone()

    async def get_collection(self, collection_id: UUID) -> Optional[dict]:
        result = await self._conn.execute(
            "SELECT * FROM collection WHERE id = %(id)s", {"id": str(collection_id)}
        )
        return await result.fetchone()

    async def get_collection_by_name(self, name: str) -> Optional[dict]:
        result = await self._conn.execute(
            "SELECT * FROM collection WHERE name = %(name)s", {"name": name}
        )
        return await result.fetchone()

    async def list_collections(self) -> list[dict]:
        result = await self._conn.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM document d WHERE d.collection_id = c.id) AS doc_count
            FROM collection c ORDER BY c.display_name"""
        )
        return await result.fetchall()

    async def update_collection(self, collection_id: UUID, **kwargs) -> dict:
        sets, params = [], {"id": str(collection_id)}
        for f in ("display_name", "description", "status", "owner_name"):
            if f in kwargs:
                sets.append(f"{f} = %({f})s")
                params[f] = kwargs[f]
        if "default_tags" in kwargs:
            sets.append("default_tags = %(default_tags)s")
            params["default_tags"] = json.dumps(kwargs["default_tags"])
        if sets:
            sets.append("updated_at = NOW()")
            sql = f"UPDATE collection SET {', '.join(sets)} WHERE id = %(id)s RETURNING *"
            result = await self._conn.execute(sql, params)
            return await result.fetchone()
        return await self.get_collection(collection_id)

    async def delete_collection(self, collection_id: UUID) -> bool:
        result = await self._conn.execute(
            "DELETE FROM collection WHERE id = %(id)s RETURNING id", {"id": str(collection_id)}
        )
        return (await result.fetchone()) is not None

    # ══════════════════════════════════════════════════════════
    # FOLDER OPERATIONS (scoped to collection)
    # ══════════════════════════════════════════════════════════

    async def insert_folder(
        self, collection_id: UUID, name: str, created_by: str = "system",
        parent_folder_id: Optional[UUID] = None,
        description: Optional[str] = None, default_tags: Optional[dict] = None,
    ) -> dict:
        result = await self._conn.execute(
            """INSERT INTO folder (collection_id, parent_folder_id, name, description, default_tags, created_by)
            VALUES (%(cid)s, %(pid)s, %(name)s, %(desc)s, %(tags)s, %(by)s)
            RETURNING *""",
            {"cid": str(collection_id), "pid": str(parent_folder_id) if parent_folder_id else None,
             "name": name, "desc": description,
             "tags": json.dumps(default_tags) if default_tags else "{}", "by": created_by},
        )
        return await result.fetchone()

    async def get_folder(self, folder_id: UUID) -> Optional[dict]:
        result = await self._conn.execute(
            "SELECT * FROM folder WHERE id = %(id)s", {"id": str(folder_id)}
        )
        return await result.fetchone()

    async def list_folders(self, collection_id: UUID, parent_folder_id: Optional[UUID] = None) -> list[dict]:
        if parent_folder_id:
            result = await self._conn.execute(
                "SELECT * FROM folder WHERE collection_id = %(cid)s AND parent_folder_id = %(pid)s ORDER BY name",
                {"cid": str(collection_id), "pid": str(parent_folder_id)},
            )
        else:
            result = await self._conn.execute(
                "SELECT * FROM folder WHERE collection_id = %(cid)s AND parent_folder_id IS NULL ORDER BY name",
                {"cid": str(collection_id)},
            )
        return await result.fetchall()

    async def get_folder_tree(self, collection_id: UUID) -> list[dict]:
        """Get the full folder tree for a collection with doc counts."""
        result = await self._conn.execute(
            "SELECT * FROM folder WHERE collection_id = %(cid)s ORDER BY name",
            {"cid": str(collection_id)},
        )
        all_folders = await result.fetchall()

        counts_result = await self._conn.execute(
            "SELECT folder_id, COUNT(*) as doc_count FROM document WHERE collection_id = %(cid)s AND folder_id IS NOT NULL GROUP BY folder_id",
            {"cid": str(collection_id)},
        )
        counts = {str(r["folder_id"]): r["doc_count"] for r in await counts_result.fetchall()}

        folders_by_id = {str(f["id"]): dict(f) for f in all_folders}
        for f in folders_by_id.values():
            f["children"] = []
            f["doc_count"] = counts.get(str(f["id"]), 0)

        roots = []
        for f in folders_by_id.values():
            pid = str(f["parent_folder_id"]) if f["parent_folder_id"] else None
            if pid and pid in folders_by_id:
                folders_by_id[pid]["children"].append(f)
            else:
                roots.append(f)
        return roots

    async def get_folder_path(self, folder_id: UUID) -> list[dict]:
        """Walk up the parent chain to build the folder path (root first)."""
        path = []
        current_id = folder_id
        while current_id:
            folder = await self.get_folder(current_id)
            if not folder:
                break
            path.insert(0, folder)
            current_id = folder.get("parent_folder_id")
        return path

    async def get_folder_breadcrumb(self, folder_id: Optional[UUID], collection_name: str) -> str:
        """Build a display breadcrumb string. >3 levels: Collection > ... > Leaf"""
        if not folder_id:
            return collection_name
        path = await self.get_folder_path(folder_id)
        names = [collection_name] + [f["name"] for f in path]
        if len(names) <= 3:
            return " > ".join(names)
        return f"{names[0]} > ... > {names[-1]}"

    async def update_folder(self, folder_id: UUID, **kwargs) -> dict:
        sets, params = [], {"id": str(folder_id)}
        for f in ("name", "description"):
            if f in kwargs:
                sets.append(f"{f} = %({f})s")
                params[f] = kwargs[f]
        if "default_tags" in kwargs:
            sets.append("default_tags = %(default_tags)s")
            params["default_tags"] = json.dumps(kwargs["default_tags"])
        if "parent_folder_id" in kwargs:
            v = kwargs["parent_folder_id"]
            sets.append("parent_folder_id = %(parent_folder_id)s")
            params["parent_folder_id"] = str(v) if v else None
        if not sets:
            return await self.get_folder(folder_id)
        sql = f"UPDATE folder SET {', '.join(sets)} WHERE id = %(id)s RETURNING *"
        result = await self._conn.execute(sql, params)
        return await result.fetchone()

    async def delete_folder(self, folder_id: UUID) -> bool:
        # Unlink documents
        await self._conn.execute(
            "UPDATE document SET folder_id = NULL WHERE folder_id = %(id)s", {"id": str(folder_id)}
        )
        # Reparent child folders
        folder = await self.get_folder(folder_id)
        if folder:
            await self._conn.execute(
                "UPDATE folder SET parent_folder_id = %(parent)s WHERE parent_folder_id = %(id)s",
                {"id": str(folder_id), "parent": str(folder["parent_folder_id"]) if folder["parent_folder_id"] else None},
            )
        result = await self._conn.execute(
            "DELETE FROM folder WHERE id = %(id)s RETURNING id", {"id": str(folder_id)}
        )
        return (await result.fetchone()) is not None

    # ══════════════════════════════════════════════════════════
    # DOCUMENT OPERATIONS
    # ══════════════════════════════════════════════════════════

    async def insert_document(
        self, collection_id: UUID, context_ref: str, filename: str,
        storage_key: str, uploaded_by: str,
        folder_id: Optional[UUID] = None, context_type: Optional[str] = None,
        content_type: Optional[str] = None, file_size_bytes: Optional[int] = None,
        document_type: Optional[str] = None, tags: Optional[dict] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Insert a document. storage_provider and storage_container come from collection."""
        result = await self._conn.execute(
            """INSERT INTO document (
                collection_id, folder_id, context_ref, context_type,
                filename, content_type, file_size_bytes,
                storage_provider, storage_key,
                document_type, tags, uploaded_by, notes
            ) VALUES (
                %(cid)s, %(fid)s, %(ctx_ref)s, %(ctx_type)s,
                %(filename)s, %(content_type)s, %(size)s,
                'minio', %(storage_key)s,
                %(doc_type)s, %(tags)s, %(uploaded_by)s, %(notes)s
            ) RETURNING *""",
            {"cid": str(collection_id), "fid": str(folder_id) if folder_id else None,
             "ctx_ref": context_ref, "ctx_type": context_type,
             "filename": filename, "content_type": content_type, "size": file_size_bytes,
             "storage_key": storage_key,
             "doc_type": document_type, "tags": json.dumps(tags) if tags else "{}",
             "uploaded_by": uploaded_by, "notes": notes},
        )
        return await result.fetchone()

    async def get_document(self, document_id: UUID) -> Optional[dict]:
        result = await self._conn.execute(
            "SELECT * FROM document WHERE id = %(id)s", {"id": str(document_id)}
        )
        return await result.fetchone()

    async def list_documents(
        self, context_ref: str, *, include_derivatives: bool = False,
    ) -> list[dict]:
        """List documents for a business context.

        By default returns only originals — documents that have no
        parent in the document_lineage table. Lineage children
        (auto-extracted text, JSON derivatives, etc.) are an internal
        consequence of upload + transformation; clients shouldn't see
        them in the catalog unless they explicitly ask.

        Set include_derivatives=True to get the full flat list.
        """
        if include_derivatives:
            result = await self._conn.execute(
                "SELECT * FROM document "
                "WHERE context_ref = %(ref)s "
                "ORDER BY uploaded_at DESC",
                {"ref": context_ref},
            )
        else:
            result = await self._conn.execute(
                "SELECT d.* FROM document d "
                "WHERE d.context_ref = %(ref)s "
                "  AND NOT EXISTS ("
                "    SELECT 1 FROM document_lineage dl "
                "    WHERE dl.child_document_id = d.id"
                "  ) "
                "ORDER BY d.uploaded_at DESC",
                {"ref": context_ref},
            )
        return await result.fetchall()

    async def list_documents_in_collection(self, collection_id: UUID, folder_id: Optional[UUID] = None) -> list[dict]:
        if folder_id:
            result = await self._conn.execute(
                "SELECT * FROM document WHERE collection_id = %(cid)s AND folder_id = %(fid)s ORDER BY uploaded_at DESC",
                {"cid": str(collection_id), "fid": str(folder_id)},
            )
        else:
            result = await self._conn.execute(
                "SELECT * FROM document WHERE collection_id = %(cid)s ORDER BY uploaded_at DESC LIMIT 200",
                {"cid": str(collection_id)},
            )
        return await result.fetchall()

    async def list_all_documents(self, limit: int = 200) -> list[dict]:
        result = await self._conn.execute(
            "SELECT * FROM document ORDER BY uploaded_at DESC LIMIT %(limit)s", {"limit": limit}
        )
        return await result.fetchall()

    async def update_document_type(self, document_id: UUID, document_type: str) -> dict:
        result = await self._conn.execute(
            "UPDATE document SET document_type = %(type)s WHERE id = %(id)s RETURNING *",
            {"id": str(document_id), "type": document_type},
        )
        return await result.fetchone()

    async def update_document_tags(self, document_id: UUID, tags: dict) -> dict:
        result = await self._conn.execute(
            "UPDATE document SET tags = %(tags)s WHERE id = %(id)s RETURNING *",
            {"id": str(document_id), "tags": json.dumps(tags)},
        )
        return await result.fetchone()

    async def move_document(self, document_id: UUID, collection_id: Optional[UUID] = None, folder_id: Optional[UUID] = None) -> dict:
        sets, params = [], {"id": str(document_id)}
        if collection_id is not None:
            sets.append("collection_id = %(cid)s")
            params["cid"] = str(collection_id)
        if folder_id is not None:
            sets.append("folder_id = %(fid)s")
            params["fid"] = str(folder_id) if folder_id else None
        if not sets:
            return await self.get_document(document_id)
        sql = f"UPDATE document SET {', '.join(sets)} WHERE id = %(id)s RETURNING *"
        result = await self._conn.execute(sql, params)
        return await result.fetchone()

    async def delete_document(self, document_id: UUID) -> bool:
        await self._conn.execute("DELETE FROM document_lineage WHERE child_document_id = %(id)s", {"id": str(document_id)})
        await self._conn.execute("DELETE FROM document_lineage WHERE parent_document_id = %(id)s", {"id": str(document_id)})
        result = await self._conn.execute("DELETE FROM document WHERE id = %(id)s RETURNING id", {"id": str(document_id)})
        return (await result.fetchone()) is not None

    # ══════════════════════════════════════════════════════════
    # TAG INHERITANCE
    # ══════════════════════════════════════════════════════════

    async def get_effective_tags(self, document_id: UUID) -> dict:
        """Compute effective tags by merging collection -> folder chain -> document.

        At each level, the level's tags override/extend the parent's.
        """
        doc = await self.get_document(document_id)
        if not doc:
            return {}

        # Start with collection defaults
        coll = await self.get_collection(doc["collection_id"])
        effective = dict(coll["default_tags"]) if coll and coll.get("default_tags") else {}

        # Merge folder chain defaults (from root folder down to leaf)
        if doc.get("folder_id"):
            folder_path = await self.get_folder_path(doc["folder_id"])
            for folder in folder_path:
                if folder.get("default_tags"):
                    for key, values in folder["default_tags"].items():
                        effective[key] = values  # override

        # Merge document's own tags (highest priority)
        if doc.get("tags"):
            doc_tags = doc["tags"] if isinstance(doc["tags"], dict) else {}
            for key, values in doc_tags.items():
                effective[key] = values  # override

        return effective

    # ══════════════════════════════════════════════════════════
    # DOCUMENT LINEAGE
    # ══════════════════════════════════════════════════════════

    async def insert_lineage(
        self, parent_document_id: UUID, child_document_id: UUID,
        transformation_type: str, transformation_method: Optional[str] = None,
        transformation_status: str = "complete", transformation_error: Optional[str] = None,
        transformation_metadata: Optional[dict] = None,
    ) -> dict:
        result = await self._conn.execute(
            """INSERT INTO document_lineage (
                parent_document_id, child_document_id, transformation_type,
                transformation_method, transformation_status, transformation_error,
                transformation_metadata
            ) VALUES (%(pid)s, %(cid)s, %(type)s, %(method)s, %(status)s, %(error)s, %(meta)s)
            RETURNING *""",
            {"pid": str(parent_document_id), "cid": str(child_document_id),
             "type": transformation_type, "method": transformation_method,
             "status": transformation_status, "error": transformation_error,
             "meta": json.dumps(transformation_metadata) if transformation_metadata else "{}"},
        )
        return await result.fetchone()

    async def get_children(self, parent_document_id: UUID) -> list[dict]:
        result = await self._conn.execute(
            """SELECT d.*, dl.transformation_type, dl.transformation_method,
                   dl.transformation_status, dl.transformation_metadata
            FROM document d JOIN document_lineage dl ON dl.child_document_id = d.id
            WHERE dl.parent_document_id = %(pid)s ORDER BY dl.created_at""",
            {"pid": str(parent_document_id)},
        )
        return await result.fetchall()

    async def get_parent(self, child_document_id: UUID) -> Optional[dict]:
        """Get the parent document that this document was derived from (if any)."""
        result = await self._conn.execute(
            """SELECT d.*, dl.transformation_type, dl.transformation_method,
                   dl.transformation_status, dl.transformation_metadata
            FROM document d JOIN document_lineage dl ON dl.parent_document_id = d.id
            WHERE dl.child_document_id = %(cid)s
            LIMIT 1""",
            {"cid": str(child_document_id)},
        )
        return await result.fetchone()

    async def get_text_child(self, parent_document_id: UUID) -> Optional[dict]:
        result = await self._conn.execute(
            """SELECT d.* FROM document d
            JOIN document_lineage dl ON dl.child_document_id = d.id
            WHERE dl.parent_document_id = %(pid)s
              AND dl.transformation_type = 'text_extraction'
              AND dl.transformation_status = 'complete'
            LIMIT 1""",
            {"pid": str(parent_document_id)},
        )
        return await result.fetchone()

    # ══════════════════════════════════════════════════════════
    # DOCUMENT TASKS
    # ══════════════════════════════════════════════════════════

    async def create_task(
        self, document_id: UUID, task_type: str,
        task_method: Optional[str] = None, initiated_by: str = "system",
        task_metadata: Optional[dict] = None,
    ) -> dict:
        result = await self._conn.execute(
            """INSERT INTO document_task (document_id, task_type, task_method, status, initiated_by, task_metadata)
            VALUES (%(did)s, %(type)s, %(method)s, 'pending', %(by)s, %(meta)s)
            RETURNING *""",
            {"did": str(document_id), "type": task_type, "method": task_method,
             "by": initiated_by, "meta": json.dumps(task_metadata) if task_metadata else "{}"},
        )
        return await result.fetchone()

    async def start_task(self, task_id: UUID) -> dict:
        result = await self._conn.execute(
            "UPDATE document_task SET status = 'running', started_at = NOW() WHERE id = %(id)s RETURNING *",
            {"id": str(task_id)},
        )
        return await result.fetchone()

    async def complete_task(
        self, task_id: UUID, result_document_id: Optional[UUID] = None,
        result_summary: Optional[str] = None, duration_ms: Optional[int] = None,
        task_metadata: Optional[dict] = None,
    ) -> dict:
        sets = ["status = 'complete'", "completed_at = NOW()", "progress_pct = 100"]
        params: dict[str, Any] = {"id": str(task_id)}
        if result_document_id:
            sets.append("result_document_id = %(rdoc)s")
            params["rdoc"] = str(result_document_id)
        if result_summary:
            sets.append("result_summary = %(summary)s")
            params["summary"] = result_summary
        if duration_ms is not None:
            sets.append("duration_ms = %(dur)s")
            params["dur"] = duration_ms
        if task_metadata:
            sets.append("task_metadata = %(meta)s")
            params["meta"] = json.dumps(task_metadata)
        result = await self._conn.execute(
            f"UPDATE document_task SET {', '.join(sets)} WHERE id = %(id)s RETURNING *", params
        )
        return await result.fetchone()

    async def fail_task(self, task_id: UUID, error_message: str) -> dict:
        result = await self._conn.execute(
            "UPDATE document_task SET status = 'failed', completed_at = NOW(), error_message = %(err)s WHERE id = %(id)s RETURNING *",
            {"id": str(task_id), "err": error_message},
        )
        return await result.fetchone()

    async def list_tasks_for_document(self, document_id: UUID) -> list[dict]:
        result = await self._conn.execute(
            "SELECT * FROM document_task WHERE document_id = %(did)s ORDER BY created_at DESC",
            {"did": str(document_id)},
        )
        return await result.fetchall()

    async def list_all_tasks(self, status: Optional[str] = None, task_type: Optional[str] = None, limit: int = 100) -> list[dict]:
        wheres, params = [], {"limit": limit}
        if status:
            wheres.append("dt.status = %(status)s")
            params["status"] = status
        if task_type:
            wheres.append("dt.task_type = %(task_type)s")
            params["task_type"] = task_type
        where_sql = f"WHERE {' AND '.join(wheres)}" if wheres else ""
        result = await self._conn.execute(
            f"""SELECT dt.*, d.filename AS document_filename, d.context_ref AS document_context
            FROM document_task dt JOIN document d ON d.id = dt.document_id
            {where_sql} ORDER BY dt.created_at DESC LIMIT %(limit)s""", params,
        )
        return await result.fetchall()

    # ══════════════════════════════════════════════════════════
    # TAG GOVERNANCE
    # ══════════════════════════════════════════════════════════

    async def list_tag_definitions(self, active_only: bool = True) -> list[dict]:
        where = "WHERE active = TRUE" if active_only else ""
        result = await self._conn.execute(f"SELECT * FROM tag_definition {where} ORDER BY sort_order, tag_key")
        return await result.fetchall()

    async def get_tag_definition(self, tag_key: str) -> Optional[dict]:
        result = await self._conn.execute("SELECT * FROM tag_definition WHERE tag_key = %(k)s", {"k": tag_key})
        return await result.fetchone()

    async def insert_tag_definition(self, tag_key: str, display_name: str, value_mode: str = "restricted",
                                     description: Optional[str] = None, is_required: bool = False, sort_order: int = 0) -> dict:
        result = await self._conn.execute(
            """INSERT INTO tag_definition (tag_key, display_name, description, value_mode, is_required, sort_order)
            VALUES (%(k)s, %(d)s, %(desc)s, %(m)s, %(r)s, %(s)s) RETURNING *""",
            {"k": tag_key, "d": display_name, "desc": description, "m": value_mode, "r": is_required, "s": sort_order},
        )
        return await result.fetchone()

    async def update_tag_definition(self, tag_key: str, **kwargs) -> dict:
        sets, params = [], {"k": tag_key}
        for f in ("display_name", "description", "value_mode", "is_required", "sort_order", "active"):
            if f in kwargs:
                sets.append(f"{f} = %({f})s")
                params[f] = kwargs[f]
        if not sets:
            return await self.get_tag_definition(tag_key)
        result = await self._conn.execute(
            f"UPDATE tag_definition SET {', '.join(sets)} WHERE tag_key = %(k)s RETURNING *", params
        )
        return await result.fetchone()

    async def delete_tag_definition(self, tag_key: str) -> bool:
        result = await self._conn.execute("DELETE FROM tag_definition WHERE tag_key = %(k)s RETURNING id", {"k": tag_key})
        return (await result.fetchone()) is not None

    async def list_tag_allowed_values(self, tag_key: str) -> list[dict]:
        result = await self._conn.execute(
            """SELECT tav.* FROM tag_allowed_value tav
            JOIN tag_definition td ON td.id = tav.tag_definition_id
            WHERE td.tag_key = %(k)s AND tav.active = TRUE ORDER BY tav.sort_order, tav.value""", {"k": tag_key},
        )
        return await result.fetchall()

    async def insert_tag_allowed_value(self, tag_key: str, value: str, display_name: str,
                                        description: Optional[str] = None, sort_order: int = 0) -> dict:
        td = await self.get_tag_definition(tag_key)
        if not td:
            raise ValueError(f"Tag definition '{tag_key}' not found")
        result = await self._conn.execute(
            """INSERT INTO tag_allowed_value (tag_definition_id, value, display_name, description, sort_order)
            VALUES (%(tid)s, %(v)s, %(d)s, %(desc)s, %(s)s) RETURNING *""",
            {"tid": str(td["id"]), "v": value, "d": display_name, "desc": description, "s": sort_order},
        )
        return await result.fetchone()

    async def delete_tag_allowed_value(self, tag_key: str, value: str) -> bool:
        result = await self._conn.execute(
            """DELETE FROM tag_allowed_value
            WHERE tag_definition_id = (SELECT id FROM tag_definition WHERE tag_key = %(k)s) AND value = %(v)s
            RETURNING id""", {"k": tag_key, "v": value},
        )
        return (await result.fetchone()) is not None

    async def validate_tags(self, tags: dict) -> list[str]:
        """Validate tags against governance tables. Returns list of errors (empty=valid)."""
        errors = []
        definitions = await self.list_tag_definitions(active_only=True)
        defined_keys = {d["tag_key"]: d for d in definitions}

        for key in tags:
            if key not in defined_keys:
                errors.append(f"Unknown tag key '{key}'. Allowed: {sorted(defined_keys.keys())}")

        for key, values in tags.items():
            defn = defined_keys.get(key)
            if not defn:
                continue
            if defn["value_mode"] == "restricted":
                allowed = await self.list_tag_allowed_values(key)
                allowed_set = {v["value"] for v in allowed}
                if not isinstance(values, list):
                    values = [values]
                for v in values:
                    if v not in allowed_set:
                        errors.append(f"Value '{v}' not allowed for tag '{key}'. Allowed: {sorted(allowed_set)}")

        for defn in definitions:
            if defn["is_required"] and defn["tag_key"] not in tags:
                errors.append(f"Required tag '{defn['tag_key']}' is missing")

        return errors

    # ══════════════════════════════════════════════════════════
    # DOCUMENT TYPE GOVERNANCE
    # ══════════════════════════════════════════════════════════

    async def list_document_type_definitions(self, active_only: bool = True) -> list[dict]:
        where = "WHERE active = TRUE" if active_only else ""
        result = await self._conn.execute(f"SELECT * FROM document_type_definition {where} ORDER BY sort_order, type_key")
        return await result.fetchall()

    async def get_document_type_definition(self, type_key: str) -> Optional[dict]:
        result = await self._conn.execute(
            "SELECT * FROM document_type_definition WHERE type_key = %(k)s", {"k": type_key}
        )
        return await result.fetchone()

    async def insert_document_type_definition(self, type_key: str, display_name: str,
                                               description: Optional[str] = None, parent_type_id: Optional[UUID] = None,
                                               sort_order: int = 0) -> dict:
        result = await self._conn.execute(
            """INSERT INTO document_type_definition (type_key, display_name, description, parent_type_id, sort_order)
            VALUES (%(k)s, %(d)s, %(desc)s, %(p)s, %(s)s) RETURNING *""",
            {"k": type_key, "d": display_name, "desc": description,
             "p": str(parent_type_id) if parent_type_id else None, "s": sort_order},
        )
        return await result.fetchone()

    async def delete_document_type_definition(self, type_key: str) -> bool:
        result = await self._conn.execute(
            "DELETE FROM document_type_definition WHERE type_key = %(k)s RETURNING id", {"k": type_key}
        )
        return (await result.fetchone()) is not None

    async def list_top_level_types(self) -> list[dict]:
        result = await self._conn.execute(
            "SELECT * FROM document_type_definition WHERE parent_type_id IS NULL AND active = TRUE ORDER BY sort_order"
        )
        return await result.fetchall()

    async def list_subtypes(self, parent_type_id: UUID) -> list[dict]:
        result = await self._conn.execute(
            "SELECT * FROM document_type_definition WHERE parent_type_id = %(p)s AND active = TRUE ORDER BY sort_order",
            {"p": str(parent_type_id)},
        )
        return await result.fetchall()

    async def get_type_hierarchy(self) -> list[dict]:
        top = await self.list_top_level_types()
        for t in top:
            t["subtypes"] = await self.list_subtypes(t["id"])
        return top

    async def validate_document_type(self, document_type: str) -> Optional[str]:
        if not document_type:
            return None
        defn = await self.get_document_type_definition(document_type)
        if not defn:
            valid = await self.list_document_type_definitions()
            return f"Unknown document type '{document_type}'. Allowed: {[t['type_key'] for t in valid]}"
        if not defn["active"]:
            return f"Document type '{document_type}' is deactivated"
        return None

    # ══════════════════════════════════════════════════════════
    # CONTEXT TYPE GOVERNANCE
    # ══════════════════════════════════════════════════════════

    async def list_context_type_definitions(self) -> list[dict]:
        result = await self._conn.execute(
            "SELECT * FROM context_type_definition WHERE active = TRUE ORDER BY sort_order, type_key"
        )
        return await result.fetchall()

    async def insert_context_type_definition(self, type_key: str, display_name: str,
                                              description: Optional[str] = None, sort_order: int = 0) -> dict:
        result = await self._conn.execute(
            """INSERT INTO context_type_definition (type_key, display_name, description, sort_order)
            VALUES (%(k)s, %(d)s, %(desc)s, %(s)s) RETURNING *""",
            {"k": type_key, "d": display_name, "desc": description, "s": sort_order},
        )
        return await result.fetchone()

    async def delete_context_type_definition(self, type_key: str) -> bool:
        result = await self._conn.execute(
            "DELETE FROM context_type_definition WHERE type_key = %(k)s RETURNING id", {"k": type_key}
        )
        return (await result.fetchone()) is not None

    async def validate_context_type(self, context_type: str) -> Optional[str]:
        if not context_type:
            return None
        result = await self._conn.execute(
            "SELECT id FROM context_type_definition WHERE type_key = %(k)s AND active = TRUE", {"k": context_type}
        )
        if not await result.fetchone():
            valid = await self.list_context_type_definitions()
            return f"Unknown context type '{context_type}'. Allowed: {[t['type_key'] for t in valid]}"
        return None
