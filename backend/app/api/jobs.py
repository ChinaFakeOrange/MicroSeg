"""Job dispatch endpoints.

Each endpoint creates a :class:`TaskRecord`, enqueues a Celery job, and returns
the task id immediately. The client then tracks progress via /tasks/{id} or the
WebSocket stream.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.storage import new_id, store
from app.core.tasks import tracker
from app.schemas.models import (
    InferenceJob,
    MeshJob,
    MorphometryJob,
    PercolationJob,
    SegmentJob,
    TrainJob,
)
from app.workers import jobs

router = APIRouter()


def _require_project(project_id: str):
    if not store.get(project_id):
        raise HTTPException(404, "Project not found")


def _enqueue(task_type: str, project_id: str, celery_task, *args) -> dict:
    task_id = new_id("t_")
    tracker.create(task_id, task_type, project_id=project_id)
    celery_task.delay(task_id, *args)
    return {"task_id": task_id}


@router.post("/projects/{project_id}/segment")
def segment(project_id: str, body: SegmentJob):
    _require_project(project_id)
    strokes = {k: [s.model_dump() for s in v] for k, v in body.strokes_by_image.items()}
    return _enqueue("interactive_segment", project_id, jobs.interactive_segment,
                    project_id, body.image_ids, strokes, body.scope, body.export)


@router.post("/projects/{project_id}/morphometry")
def morphometry(project_id: str, body: MorphometryJob):
    _require_project(project_id)
    cfg = body.model_dump(exclude={"image_ids"})
    return _enqueue("morphometry", project_id, jobs.run_morphometry,
                    project_id, body.image_ids, cfg)


@router.post("/projects/{project_id}/percolation")
def percolation(project_id: str, body: PercolationJob):
    _require_project(project_id)
    return _enqueue("percolation", project_id, jobs.run_percolation,
                    project_id, body.image_id, body.model_dump(exclude={"image_id"}))


@router.post("/projects/{project_id}/mesh")
def mesh(project_id: str, body: MeshJob):
    _require_project(project_id)
    return _enqueue("mesh", project_id, jobs.build_mesh, project_id, body.model_dump())


@router.post("/projects/{project_id}/train")
def train(project_id: str, body: TrainJob):
    _require_project(project_id)
    return _enqueue("train", project_id, jobs.train_model, project_id, body.model_dump())


@router.post("/projects/{project_id}/inference")
def inference(project_id: str, body: InferenceJob):
    _require_project(project_id)
    return _enqueue("inference", project_id, jobs.run_inference, project_id, body.model_dump())
