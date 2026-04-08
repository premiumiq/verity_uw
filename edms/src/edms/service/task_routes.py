"""EDMS Task API routes - document task monitoring and management."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from edms.core.db import EdmsDatabase


def create_task_routes(db: EdmsDatabase) -> APIRouter:
    """Create the task API router."""

    router = APIRouter(prefix="/tasks", tags=["tasks"])

    @router.get("")
    async def list_tasks(
        status: Optional[str] = Query(None, description="Filter by status: pending, running, complete, failed"),
        task_type: Optional[str] = Query(None, description="Filter by task type: text_extraction, ocr, etc."),
        limit: int = Query(100, description="Max results"),
    ):
        """List all tasks across all documents with optional filters."""
        tasks = await db.list_all_tasks(status=status, task_type=task_type, limit=limit)
        return {"count": len(tasks), "tasks": tasks}

    @router.get("/{task_id}")
    async def get_task(task_id: UUID):
        """Get a task by ID."""
        task = await db.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        return task

    @router.get("/document/{document_id}")
    async def list_document_tasks(document_id: UUID):
        """List all tasks for a specific document."""
        tasks = await db.list_tasks_for_document(document_id)
        return {"document_id": str(document_id), "count": len(tasks), "tasks": tasks}

    return router
