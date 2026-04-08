"""EDMS Collection API routes - governed storage domain management."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException

from edms.core.db import EdmsDatabase


def create_collection_routes(db: EdmsDatabase) -> APIRouter:
    router = APIRouter(prefix="/collections", tags=["collections"])

    @router.get("")
    async def list_collections():
        collections = await db.list_collections()
        return {"count": len(collections), "collections": collections}

    @router.get("/{collection_id}")
    async def get_collection(collection_id: UUID):
        coll = await db.get_collection(collection_id)
        if not coll:
            raise HTTPException(status_code=404, detail="Collection not found")
        return coll

    @router.post("")
    async def create_collection(
        name: str = Form(...), display_name: str = Form(...),
        storage_container: str = Form(...), owner_name: str = Form(...),
        created_by: str = Form("system"), description: str = Form(None),
    ):
        existing = await db.get_collection_by_name(name)
        if existing:
            raise HTTPException(status_code=409, detail=f"Collection '{name}' already exists")
        return await db.insert_collection(
            name=name, display_name=display_name, storage_container=storage_container,
            owner_name=owner_name, created_by=created_by, description=description,
        )

    @router.put("/{collection_id}")
    async def update_collection(
        collection_id: UUID, display_name: str = Form(None),
        description: str = Form(None), status: str = Form(None), owner_name: str = Form(None),
    ):
        kwargs = {k: v for k, v in {"display_name": display_name, "description": description,
                  "status": status, "owner_name": owner_name}.items() if v is not None}
        return await db.update_collection(collection_id, **kwargs)

    @router.delete("/{collection_id}")
    async def delete_collection(collection_id: UUID):
        deleted = await db.delete_collection(collection_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Collection not found")
        return {"deleted": True}

    @router.get("/{collection_id}/folders")
    async def list_collection_folders(collection_id: UUID):
        tree = await db.get_folder_tree(collection_id)
        return {"collection_id": str(collection_id), "tree": tree}

    @router.get("/{collection_id}/documents")
    async def list_collection_documents(collection_id: UUID, folder_id: Optional[str] = None):
        fid = UUID(folder_id) if folder_id else None
        docs = await db.list_documents_in_collection(collection_id, fid)
        return {"count": len(docs), "documents": docs}

    return router
