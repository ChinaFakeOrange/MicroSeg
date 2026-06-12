"""Celery jobs.

Each job updates the shared :class:`TaskTracker` as it runs so the frontend can
display live progress and so jobs survive a browser refresh. Jobs check
``tracker.is_cancelled`` at safe points to support cooperative cancellation.
"""
from __future__ import annotations

import traceback
from typing import Dict, List

import numpy as np
from PIL import Image

from app.config import get_settings
from app.core.storage import store
from app.core.tasks import TaskState, tracker
from app.workers.celery_app import celery_app


def _load_rgb(path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def _guard(task_id: str) -> None:
    if tracker.is_cancelled(task_id):
        raise InterruptedError("cancelled")


# --------------------------------------------------------------------------- #
# Interactive segmentation (LightGBM scribbles -> full-frame labels)
# --------------------------------------------------------------------------- #
@celery_app.task(bind=True)
def interactive_segment(self, task_id: str, project_id: str, image_ids: List[str], strokes_by_image: Dict[str, list]):
    from app.ml.interactive import InteractiveSegmenter, Stroke

    try:
        tracker.update(task_id, state=TaskState.RUNNING, message="Extracting features", progress=0.05)

        # Train on every image that has scribbles, then predict all requested.
        all_strokes: List[Stroke] = []
        ref_image = None
        train_strokes_per_img = []
        for img_id, strokes in strokes_by_image.items():
            path = store.image_path(project_id, img_id)
            if path is None or not strokes:
                continue
            img = _load_rgb(path)
            ref_image = ref_image if ref_image is not None else img
            train_strokes_per_img.append((img, [Stroke(s["label"], s["points"]) for s in strokes]))

        if not train_strokes_per_img:
            raise ValueError("No scribbles provided")

        # Fit on the first scribbled image (multi-image fit could concatenate features).
        seg = InteractiveSegmenter()
        base_img, base_strokes = train_strokes_per_img[0]
        seg.fit(base_img, base_strokes)
        _guard(task_id)
        tracker.update(task_id, message="Predicting", progress=0.4)

        results = {}
        for i, img_id in enumerate(image_ids):
            _guard(task_id)
            path = store.image_path(project_id, img_id)
            if path is None:
                continue
            labels = seg.predict(_load_rgb(path))
            Image.fromarray(labels).save(store.mask_path(project_id, img_id))
            results[img_id] = {"mask": store.mask_path(project_id, img_id).name}
            tracker.update(task_id, progress=0.4 + 0.6 * (i + 1) / len(image_ids))

        # Persist the model for reuse.
        model_path = store.path(project_id) / "models" / "interactive.joblib"
        model_path.write_bytes(seg.dumps())

        tracker.update(task_id, state=TaskState.SUCCESS, progress=1.0,
                       message=f"Segmented {len(results)} image(s)",
                       result={"images": results, "model": model_path.name})
    except InterruptedError:
        tracker.update(task_id, state=TaskState.CANCELLED, message="Cancelled by user")
    except Exception as exc:  # noqa: BLE001
        tracker.update(task_id, state=TaskState.FAILED, error=f"{exc}\n{traceback.format_exc()}")


# --------------------------------------------------------------------------- #
# Particle morphometry
# --------------------------------------------------------------------------- #
@celery_app.task(bind=True)
def run_morphometry(self, task_id: str, project_id: str, image_ids: List[str], config: dict):
    from app.ml.morphometry import MorphometryConfig, analyze

    try:
        tracker.update(task_id, state=TaskState.RUNNING, progress=0.0, message="Measuring particles")
        cfg = MorphometryConfig(**config)
        rows_all, per_image = [], {}
        for i, img_id in enumerate(image_ids):
            _guard(task_id)
            mask_path = store.mask_path(project_id, img_id)
            if not mask_path.exists():
                continue
            labels = np.asarray(Image.open(mask_path))
            res = analyze(labels, cfg)
            for r in res.rows:
                r["image_id"] = img_id
            rows_all.extend(res.rows)
            per_image[img_id] = res.summary
            tracker.update(task_id, progress=(i + 1) / len(image_ids))

        # Write a CSV export.
        import csv
        export = store.path(project_id) / "exports" / f"morphometry_{task_id[:8]}.csv"
        if rows_all:
            with export.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows_all[0].keys()))
                writer.writeheader()
                writer.writerows(rows_all)

        tracker.update(task_id, state=TaskState.SUCCESS, progress=1.0,
                       message=f"Measured {len(rows_all)} objects",
                       result={"n_objects": len(rows_all), "per_image": per_image,
                               "export": export.name if rows_all else None})
    except InterruptedError:
        tracker.update(task_id, state=TaskState.CANCELLED)
    except Exception as exc:  # noqa: BLE001
        tracker.update(task_id, state=TaskState.FAILED, error=f"{exc}\n{traceback.format_exc()}")


# --------------------------------------------------------------------------- #
# Percolation simulation
# --------------------------------------------------------------------------- #
@celery_app.task(bind=True)
def run_percolation(self, task_id: str, project_id: str, image_id: str, params: dict):
    from app.ml.percolation import invasion_percolation, spanning_clusters

    try:
        tracker.update(task_id, state=TaskState.RUNNING, progress=0.1, message="Building pore mask")
        mask_path = store.mask_path(project_id, image_id)
        labels = np.asarray(Image.open(mask_path))
        pore_label = params.get("pore_label")
        mask = (labels == pore_label) if pore_label is not None else (labels > 0)

        report = spanning_clusters(mask, axis=params.get("inlet_axis", 0))
        tracker.update(task_id, progress=0.3, message="Running invasion percolation")
        inv = invasion_percolation(
            mask,
            inlet_axis=params.get("inlet_axis", 0),
            inlet_side=params.get("inlet_side", "low"),
            n_frames=params.get("n_frames", 120),
        )

        # Downsample the time map for transport to the browser (RLE per frame is
        # done client-side; here we ship the raw int16 map base64-encoded).
        import base64
        tm = inv.time_map.astype(np.int16)
        payload = base64.b64encode(tm.tobytes()).decode()

        tracker.update(task_id, state=TaskState.SUCCESS, progress=1.0, message="Percolation complete",
                       result={
                           "shape": list(tm.shape),
                           "n_steps": inv.n_steps,
                           "breakthrough_step": inv.breakthrough_step,
                           "saturation_curve": inv.saturation_curve,
                           "percolates": report.percolates,
                           "porosity": report.porosity,
                           "time_map_b64": payload,
                           "dtype": "int16",
                       })
    except Exception as exc:  # noqa: BLE001
        tracker.update(task_id, state=TaskState.FAILED, error=f"{exc}\n{traceback.format_exc()}")


# --------------------------------------------------------------------------- #
# 3D volume meshing
# --------------------------------------------------------------------------- #
@celery_app.task(bind=True)
def build_mesh(self, task_id: str, project_id: str, params: dict):
    from app.ml.volume import build_volume, isosurface_mesh

    try:
        tracker.update(task_id, state=TaskState.RUNNING, progress=0.1, message="Stacking slices")
        use_masks = params.get("source", "masks") == "masks"
        slices = []
        for entry in store.list_images(project_id):
            if use_masks:
                mp = store.mask_path(project_id, entry["id"])
                if mp.exists():
                    slices.append(np.asarray(Image.open(mp)))
            else:
                p = store.image_path(project_id, entry["id"])
                slices.append(np.asarray(Image.open(p).convert("L")))
        if not slices:
            raise ValueError("No slices available to build a volume")

        vol = build_volume(
            slices,
            spacing=tuple(params.get("spacing", [1.0, 1.0, 1.0])),
            is_labels=use_masks,
            downsample=params.get("downsample", 2),
        )
        tracker.update(task_id, progress=0.6, message="Extracting isosurface")
        mesh = isosurface_mesh(
            vol,
            label=params.get("label"),
            threshold=params.get("threshold"),
            step_size=params.get("step_size", 1),
        )
        tracker.update(task_id, state=TaskState.SUCCESS, progress=1.0,
                       message=f"Mesh: {mesh['triangle_count']} triangles", result=mesh)
    except Exception as exc:  # noqa: BLE001
        tracker.update(task_id, state=TaskState.FAILED, error=f"{exc}\n{traceback.format_exc()}")


# --------------------------------------------------------------------------- #
# Model training (delegates to app.ml.train_* which report epoch progress)
# --------------------------------------------------------------------------- #
@celery_app.task(bind=True)
def train_model(self, task_id: str, project_id: str, params: dict):
    try:
        tracker.update(task_id, state=TaskState.RUNNING, progress=0.0, message="Preparing dataset")
        task_type = params.get("task_type", "segmentation")
        if task_type == "detection":
            from app.ml.train_yolo import train_yolo
            result = train_yolo(task_id, project_id, params)
        else:
            from app.ml.train_seg import train_segmentation
            result = train_segmentation(task_id, project_id, params)
        tracker.update(task_id, state=TaskState.SUCCESS, progress=1.0,
                       message="Training finished", result=result)
    except InterruptedError:
        tracker.update(task_id, state=TaskState.CANCELLED)
    except Exception as exc:  # noqa: BLE001
        tracker.update(task_id, state=TaskState.FAILED, error=f"{exc}\n{traceback.format_exc()}")


# --------------------------------------------------------------------------- #
# Batch inference with a trained model
# --------------------------------------------------------------------------- #
@celery_app.task(bind=True)
def run_inference(self, task_id: str, project_id: str, params: dict):
    try:
        from app.ml.inference import run_batch_inference
        tracker.update(task_id, state=TaskState.RUNNING, progress=0.0, message="Loading model")
        result = run_batch_inference(task_id, project_id, params)
        tracker.update(task_id, state=TaskState.SUCCESS, progress=1.0,
                       message="Inference complete", result=result)
    except InterruptedError:
        tracker.update(task_id, state=TaskState.CANCELLED)
    except Exception as exc:  # noqa: BLE001
        tracker.update(task_id, state=TaskState.FAILED, error=f"{exc}\n{traceback.format_exc()}")
