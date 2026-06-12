"""Batch inference with a trained model.

Supports three model kinds:
  * ``interactive`` - the saved LightGBM scribble classifier (CPU)
  * ``segmentation`` - an EfficientNet-U-Net checkpoint (with flip TTA, mirroring
                       the original ``DLPred``)
  * ``detection``    - an ultralytics YOLO checkpoint
Predicted masks are saved to ``masks/`` so morphometry/percolation/3D can use
them directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np
from PIL import Image

from app.config import get_settings
from app.core.storage import store
from app.core.tasks import tracker


def _image_ids(project_id: str, requested: List[str] | None) -> List[str]:
    if requested:
        return requested
    return [e["id"] for e in store.list_images(project_id)]


def run_batch_inference(task_id: str, project_id: str, params: Dict) -> Dict:
    kind = params.get("kind", "segmentation")
    image_ids = _image_ids(project_id, params.get("image_ids"))
    if kind == "interactive":
        return _infer_interactive(task_id, project_id, image_ids, params)
    if kind == "detection":
        return _infer_detection(task_id, project_id, image_ids, params)
    return _infer_segmentation(task_id, project_id, image_ids, params)


def _infer_interactive(task_id, project_id, image_ids, params) -> Dict:
    from app.ml.interactive import InteractiveSegmenter

    model_path = store.path(project_id) / "models" / params.get("model", "interactive.joblib")
    seg = InteractiveSegmenter.loads(model_path.read_bytes())
    done = 0
    for i, img_id in enumerate(image_ids):
        if tracker.is_cancelled(task_id):
            raise InterruptedError
        img = np.asarray(Image.open(store.image_path(project_id, img_id)).convert("RGB"))
        labels = seg.predict(img)
        Image.fromarray(labels).save(store.mask_path(project_id, img_id))
        done += 1
        tracker.update(task_id, progress=(i + 1) / len(image_ids))
    return {"masks_written": done}


def _infer_segmentation(task_id, project_id, image_ids, params) -> Dict:
    import torch
    import torch.nn.functional as F

    from app.ml.models.efficientnet_unet import build_segmentation_model

    device = torch.device(get_settings().resolve_device())
    ckpt = torch.load(store.path(project_id) / "models" / params["model"], map_location=device)
    model = build_segmentation_model(ckpt["num_classes"], size=ckpt.get("size", "medium")).to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    input_size = ckpt.get("input_size", 512)
    tta = params.get("tta", True)

    done = 0
    with torch.no_grad():
        for i, img_id in enumerate(image_ids):
            if tracker.is_cancelled(task_id):
                raise InterruptedError
            pil = Image.open(store.image_path(project_id, img_id)).convert("RGB")
            w0, h0 = pil.size
            x = torch.from_numpy(
                np.asarray(pil.resize((input_size, input_size)), np.float32) / 255.0
            ).permute(2, 0, 1).unsqueeze(0).to(device)

            logits = model(x)
            if tta:  # horizontal + vertical flip averaging
                logits = (logits + model(x.flip(-1)).flip(-1) + model(x.flip(-2)).flip(-2)) / 3
            pred = logits.argmax(1).squeeze(0).byte().cpu().numpy()
            mask = np.asarray(Image.fromarray(pred).resize((w0, h0), Image.NEAREST))
            Image.fromarray(mask).save(store.mask_path(project_id, img_id))
            done += 1
            tracker.update(task_id, progress=(i + 1) / len(image_ids))
    return {"masks_written": done}


def _infer_detection(task_id, project_id, image_ids, params) -> Dict:
    from ultralytics import YOLO

    model = YOLO(str(store.path(project_id) / "models" / params["model"]))
    conf = float(params.get("conf", 0.25))
    detections: Dict[str, list] = {}
    for i, img_id in enumerate(image_ids):
        if tracker.is_cancelled(task_id):
            raise InterruptedError
        path = store.image_path(project_id, img_id)
        res = model(str(path), conf=conf, verbose=False)[0]
        boxes = []
        for b in res.boxes:
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            boxes.append({"label": int(b.cls.item()), "conf": float(b.conf.item()),
                          "x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1})
        detections[img_id] = boxes
        tracker.update(task_id, progress=(i + 1) / len(image_ids))
    return {"detections": detections}
