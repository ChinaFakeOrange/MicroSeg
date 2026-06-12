"""YOLO (ultralytics) detection training.

Builds an ultralytics dataset from the project's box annotations, trains, and
streams epoch progress to the task tracker via a training callback instead of
scraping subprocess stdout like the old code did.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict

import yaml
from PIL import Image

from app.config import get_settings
from app.core.storage import store
from app.core.tasks import tracker

SIZE_TO_WEIGHTS = {"light": "yolov8n.pt", "medium": "yolov8l.pt", "heavy": "yolov8x.pt"}
ALIASES = {"轻量级": "light", "中量级": "medium", "高量级": "heavy"}


def export_yolo_dataset(project_id: str) -> Path:
    """Write a YOLO-format dataset (images/ labels/ data.yaml) under exports/."""
    project = store.get(project_id)
    dataset = store.path(project_id) / "exports" / "yolo_dataset"
    for split in ("train", "val"):
        (dataset / "images" / split).mkdir(parents=True, exist_ok=True)
        (dataset / "labels" / split).mkdir(parents=True, exist_ok=True)

    entries = store.list_images(project_id)
    split_at = max(1, int(len(entries) * 0.85))
    for i, entry in enumerate(entries):
        ann = store.load_annotation(project_id, entry["id"])
        if not ann or not ann.get("boxes"):
            continue
        split = "train" if i < split_at else "val"
        img_path = store.image_path(project_id, entry["id"])
        img = Image.open(img_path)
        w, h = img.size
        shutil.copy(img_path, dataset / "images" / split / img_path.name)
        lines = []
        for box in ann["boxes"]:
            cls = box["label"]
            cx = (box["x"] + box["w"] / 2) / w
            cy = (box["y"] + box["h"] / 2) / h
            lines.append(f"{cls} {cx:.6f} {cy:.6f} {box['w']/w:.6f} {box['h']/h:.6f}")
        label_file = dataset / "labels" / split / f"{img_path.stem}.txt"
        label_file.write_text("\n".join(lines))

    names = {c.id: c.name for c in project.classes}
    data_yaml = {
        "path": str(dataset.resolve()),
        "train": "images/train",
        "val": "images/val",
        "names": names,
    }
    (dataset / "data.yaml").write_text(yaml.safe_dump(data_yaml, allow_unicode=True))
    return dataset


def train_yolo(task_id: str, project_id: str, params: Dict) -> Dict:
    from ultralytics import YOLO

    dataset = export_yolo_dataset(project_id)
    size = ALIASES.get(params.get("model_size", "medium"), params.get("model_size", "medium"))
    epochs = int(params.get("epochs", 80))
    model = YOLO(SIZE_TO_WEIGHTS.get(size, "yolov8l.pt"))

    def on_epoch_end(trainer):
        if tracker.is_cancelled(task_id):
            trainer.stop = True
        epoch = getattr(trainer, "epoch", 0) + 1
        tracker.update(task_id, progress=epoch / epochs, message=f"Epoch {epoch}/{epochs}")

    model.add_callback("on_fit_epoch_end", on_epoch_end)
    out_dir = store.path(project_id) / "models"
    results = model.train(
        data=str(dataset / "data.yaml"),
        epochs=epochs,
        batch=int(params.get("batch_size", -1)),
        project=str(out_dir),
        name=f"yolo_{task_id[:8]}",
        verbose=False,
        workers=0,  # Celery worker is a daemon process; can't spawn dataloader children
        device=0 if get_settings().resolve_device() == "cuda" else "cpu",
    )
    best = Path(results.save_dir) / "weights" / "best.pt"
    return {"checkpoint": str(best.relative_to(out_dir)) if best.exists() else None,
            "save_dir": str(results.save_dir)}
