"""EDMS Folder API routes - virtual folders within collections."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException

from edms.core.db import EdmsDatabase


def create_folder_routes(db: EdmsDatabase) -> APIRouter:
    router = APIRouter(prefix="/folders", tags=["folders"])

    @router.post("")
    async def create_folder(
        collection_id: str = Form(...), name: str = Form(...),
        parent_folder_id: str = Form(None), description: str = Form(None),
        created_by: str = Form("system"),
    ):
        pid = UUID(parent_folder_id) if parent_folder_id else None
        return await db.insert_folder(
            collection_id=UUID(collection_id), name=name,
            parent_folder_id=pid, description=description, created_by=created_by,
        )

    @router.get("/{folder_id}")
    async def get_folder(folder_id: UUID):
        folder = await db.get_folder(folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder

    @router.get("/{folder_id}/path")
    async def get_folder_path(folder_id: UUID):
        path = await db.get_folder_path(folder_id)
        return {"path": path}

    @router.delete("/{folder_id}")
    async def delete_folder(folder_id: UUID):
        deleted = await db.delete_folder(folder_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Folder not found")
        return {"deleted": True}

    return router
