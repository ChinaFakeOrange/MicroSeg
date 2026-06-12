"""Task status, cancellation, and live progress streaming."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.core.tasks import EVENT_CHANNEL, tracker
from app.schemas.models import TaskOut

router = APIRouter()


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str):
    record = tracker.get(task_id)
    if not record:
        raise HTTPException(404, "Task not found")
    return record.to_dict()


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: str):
    record = tracker.request_cancel(task_id)
    if not record:
        raise HTTPException(404, "Task not found")
    return record.to_dict()


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def project_tasks(project_id: str):
    return [r.to_dict() for r in tracker.list_for_project(project_id)]


@router.websocket("/ws/tasks")
async def task_stream(websocket: WebSocket):
    """Push every task update to subscribed clients.

    Clients may send a project_id to filter; otherwise all events are forwarded.
    """
    await websocket.accept()
    project_filter = websocket.query_params.get("project_id")

    pubsub = tracker.client.pubsub()
    pubsub.subscribe(EVENT_CHANNEL)
    loop = asyncio.get_event_loop()

    try:
        while True:
            message = await loop.run_in_executor(
                None, lambda: pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            )
            if message and message.get("type") == "message":
                data = json.loads(message["data"])
                if project_filter and data.get("project_id") != project_filter:
                    continue
                await websocket.send_json(data)
            else:
                # keep the socket alive and let the loop yield
                await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        pass
    finally:
        pubsub.close()
