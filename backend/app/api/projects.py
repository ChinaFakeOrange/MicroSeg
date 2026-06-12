"""Project & image management endpoints."""
from __future__ import annotations

import io

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from PIL import Image

from app.core.storage import store
from app.schemas.models import (
    AnnotationIn, ClassUpdate, MaskEdit, ProjectCreate, ProjectOut, SelectionUpdate,
)

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


# --------------------------------------------------------- tiff inspection
@router.post("/tiff/inspect")
async def inspect_tiff(file: UploadFile = File(...)):
    """Return a TIFF's effective shape so the UI can show dimensions before
    choosing a slice axis / 'every Nth'. Reads only the header, stores nothing."""
    content = await file.read()
    try:
        return store.stack_info(content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not read TIFF: {exc}")


# ------------------------------------------------------------------ images
@router.post("/projects/{project_id}/images")
async def upload_images(
    project_id: str,
    files: list[UploadFile] = File(...),
    axis: int = Form(0),
    select_every: int = Form(1),
    max_select: int = Form(0),
):
    if not store.get(project_id):
        raise HTTPException(404, "Project not found")
    added = []
    for f in files:
        content = await f.read()
        is_tiff = (f.filename or "").lower().endswith((".tif", ".tiff"))
        if is_tiff:
            try:
                sliced = store.add_stack(project_id, f.filename, content,
                                         axis=axis, select_every=select_every, max_select=max_select)
                if len(sliced) > 1:
                    added.extend(sliced)
                    continue
                # single-page tiff: fall through to a normal single image
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(400, f"Could not read TIFF stack: {exc}")
        added.append(store.add_image(project_id, f.filename, content))
    return {"added": added}


@router.get("/projects/{project_id}/images")
def list_images(project_id: str):
    imgs = store.list_images(project_id)
    for e in imgs:
        e["has_mask"] = store.mask_path(project_id, e["id"]).exists()
    return imgs


@router.get("/projects/{project_id}/images/{image_id}/raw")
def get_image(project_id: str, image_id: str):
    path = store.image_path(project_id, image_id)
    if not path or not path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(path)


# ------------------------------------------------------------- test images
@router.post("/projects/{project_id}/test-images")
async def upload_test_images(project_id: str, files: list[UploadFile] = File(...)):
    if not store.get(project_id):
        raise HTTPException(404, "Project not found")
    added = [store.add_test_image(project_id, f.filename, await f.read()) for f in files]
    return {"added": added}


@router.get("/projects/{project_id}/test-images")
def list_test_images(project_id: str):
    return store.list_test_images(project_id)


@router.post("/projects/{project_id}/train-pairs")
async def upload_train_pairs(project_id: str,
                             images: list[UploadFile] = File(...),
                             masks: list[UploadFile] = File(...)):
    """Upload external (image, label-mask) pairs for training. The i-th image is
    paired with the i-th mask, so upload them in matching order."""
    if not store.get(project_id):
        raise HTTPException(404, "Project not found")
    if len(images) != len(masks):
        raise HTTPException(400, f"Got {len(images)} images but {len(masks)} masks — counts must match.")
    added = []
    for img, msk in zip(images, masks):
        added.append(store.add_extra_pair(project_id, img.filename, await img.read(),
                                          msk.filename, await msk.read()))
    return {"added": added, "total": len(store.list_extra_pairs(project_id))}


@router.get("/projects/{project_id}/train-pairs")
def list_train_pairs(project_id: str):
    return store.list_extra_pairs(project_id)


@router.delete("/projects/{project_id}/train-pairs/{pair_id}")
def delete_train_pair(project_id: str, pair_id: str):
    ok = store.delete_extra_pair(project_id, pair_id)
    if not ok:
        raise HTTPException(404, "Pair not found")
    return {"deleted": pair_id}


@router.get("/projects/{project_id}/test-images/{image_id}/raw")
def get_test_image(project_id: str, image_id: str):
    path = store.test_image_path(project_id, image_id)
    if not path or not path.exists():
        raise HTTPException(404, "Test image not found")
    return FileResponse(path)


@router.get("/projects/{project_id}/test-images/{image_id}/result")
def get_test_result(project_id: str, image_id: str, colorized: bool = True):
    path = store.result_mask_path(project_id, image_id)
    if not path.exists():
        raise HTTPException(404, "No result for this test image")
    if not colorized:
        return FileResponse(path)
    import numpy as np
    from PIL import Image
    from app.ml.inference import _colorize, _palette
    labels = np.asarray(Image.open(path))
    rgb = _colorize(labels, _palette(project_id))
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")



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


# ----------------------------------------------------------------- classes
@router.put("/projects/{project_id}/classes", response_model=ProjectOut)
def update_classes(project_id: str, body: ClassUpdate):
    project = store.update_classes(project_id, [c.model_dump() for c in body.classes])
    if project is None:
        raise HTTPException(404, "Project not found")
    return ProjectOut(**project.to_dict())


# --------------------------------------------------------- manual mask edit
@router.put("/projects/{project_id}/images/{image_id}/mask")
def save_mask(project_id: str, image_id: str, body: MaskEdit):
    """Persist a manually edited label mask (base64-encoded PNG, label ids)."""
    import base64

    raw = body.png_base64.split(",", 1)[-1]   # tolerate data: URL prefix
    try:
        png = base64.b64decode(raw)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Invalid base64 PNG")
    store.save_mask(project_id, image_id, png)
    return {"saved": True}


# --------------------------------------------------- image selection toggle
@router.patch("/projects/{project_id}/images/{image_id}")
def patch_image(project_id: str, image_id: str, selected: bool = Body(..., embed=True)):
    if not store.set_selected(project_id, image_id, selected):
        raise HTTPException(404, "Image not found")
    return {"id": image_id, "selected": selected}


@router.post("/projects/{project_id}/images/select")
def select_images(project_id: str, body: SelectionUpdate):
    """Batch select / deselect images for annotation (select-all, clear, every-Nth)."""
    n = store.set_selected_many(project_id, body.ids, body.selected)
    return {"updated": n, "selected": body.selected}


@router.get("/projects/{project_id}/models")
def list_models(project_id: str):
    """Trained models available in this project (interactive, segmentation, detection)."""
    return store.list_models(project_id)


@router.get("/projects/{project_id}/volume-info")
def volume_info(project_id: str):
    """Summary of the stacked 3D mask: how many slices have masks, and a
    representative (middle) masked slice to preview."""
    all_imgs = store.list_images(project_id)
    masked = [e for e in all_imgs if store.mask_path(project_id, e["id"]).exists()]
    masked.sort(key=lambda e: (e.get("group") or "", e.get("index") if e.get("index") is not None else 0))
    preview = masked[len(masked) // 2]["id"] if masked else None
    return {"n_slices": len(all_imgs), "n_with_mask": len(masked), "preview_image_id": preview}


@router.get("/projects/{project_id}/exports/{name}")
def download_export(project_id: str, name: str):
    path = store.path(project_id) / "exports" / name
    if not path.exists():
        raise HTTPException(404, "Export not found")
    return FileResponse(path, filename=name)
