"""Project & image management endpoints."""
from __future__ import annotations

import io

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from PIL import Image

from app.core.storage import store
from app.schemas.models import AnnotationIn, ProjectCreate, ProjectOut

router = APIRouter()


# ---------------------------------------------------------------- projects
@router.post("/projects", response_model=ProjectOut)
def create_project(body: ProjectCreate):
    project = store.create(
        name=body.name,
        task_type=body.task_type,
        classes=[c.model_dump() for c in body.classes],
        pixel_size_um=body.pixel_size_um,
        is_stack=body.is_stack,
        description=body.description,
    )
    return project.to_dict()


@router.get("/projects", response_model=list[ProjectOut])
def list_projects():
    return [p.to_dict() for p in store.list()]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str):
    project = store.get(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project.to_dict()


@router.delete("/projects/{project_id}")
def delete_project(project_id: str):
    if not store.delete(project_id):
        raise HTTPException(404, "Project not found")
    return {"deleted": project_id}


# ------------------------------------------------------------------ images
@router.post("/projects/{project_id}/images")
async def upload_images(project_id: str, files: list[UploadFile] = File(...)):
    if not store.get(project_id):
        raise HTTPException(404, "Project not found")
    added = []
    for f in files:
        content = await f.read()
        added.append(store.add_image(project_id, f.filename, content))
    return {"added": added}


@router.get("/projects/{project_id}/images")
def list_images(project_id: str):
    return store.list_images(project_id)


@router.get("/projects/{project_id}/images/{image_id}/raw")
def get_image(project_id: str, image_id: str):
    path = store.image_path(project_id, image_id)
    if not path or not path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(path)


@router.get("/projects/{project_id}/images/{image_id}/mask")
def get_mask(project_id: str, image_id: str, colorized: bool = True):
    path = store.mask_path(project_id, image_id)
    if not path.exists():
        raise HTTPException(404, "No mask for this image")
    if not colorized:
        return FileResponse(path)
    import numpy as np
    from app.ml.interactive import colorize

    labels = np.asarray(Image.open(path))
    rgb = colorize(labels)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


# ------------------------------------------------------------- annotations
@router.put("/projects/{project_id}/images/{image_id}/annotation")
def save_annotation(project_id: str, image_id: str, body: AnnotationIn):
    store.save_annotation(project_id, image_id, body.model_dump())
    return {"saved": True}


@router.get("/projects/{project_id}/images/{image_id}/annotation")
def get_annotation(project_id: str, image_id: str):
    return store.load_annotation(project_id, image_id) or {"boxes": [], "scribbles": []}


@router.get("/projects/{project_id}/exports/{name}")
def download_export(project_id: str, name: str):
    path = store.path(project_id) / "exports" / name
    if not path.exists():
        raise HTTPException(404, "Export not found")
    return FileResponse(path, filename=name)
