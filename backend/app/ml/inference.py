"""Batch inference with a trained model.

Runs a saved model over a set of images and writes the predicted label maps at
the ORIGINAL image resolution, then bundles them into a downloadable zip.

Model kinds:
  * ``interactive`` - the saved LightGBM scribble classifier (CPU). Predicts at
                      native resolution, so output is already original-size.
  * ``segmentation`` - an EfficientNet-U-Net checkpoint (flip TTA), the network
                       runs at a fixed input size and the mask is resized back to
                       the original size with nearest-neighbour (mirrors the
                       original ``DLPred``).
  * ``detection``    - an ultralytics YOLO checkpoint (boxes in original coords).

Source:
  * ``test``   - separately uploaded test images; results go to ``results/``.
  * ``images`` - the project's own images; results go to ``masks/`` so the
                 analysis tools can pick them up.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

from app.config import get_settings
from app.core.storage import store
from app.core.tasks import tracker


def _resolve(project_id: str, source: str, requested) -> List[Tuple[str, Path, str]]:
    """Return [(image_id, path, filename)] for the chosen source."""
    if source == "test":
        entries = store.list_test_images(project_id)
        out = []
        for e in entries:
            if requested and e["id"] not in requested:
                continue
            out.append((e["id"], store.test_image_path(project_id, e["id"]), e.get("filename", e["id"])))
        return out
    entries = store.list_images(project_id)
    out = []
    for e in entries:
        if requested and e["id"] not in requested:
            continue
        out.append((e["id"], store.image_path(project_id, e["id"]), e.get("filename", e["id"])))
    return out


def _palette(project_id: str) -> Dict[int, Tuple[int, int, int]]:
    """Build a label->RGB map from the project's class colours."""
    project = store.get(project_id)
    palette: Dict[int, Tuple[int, int, int]] = {}
    for c in getattr(project, "classes", []) or []:
        hex_ = (getattr(c, "color", None) or "#2fe6cf").lstrip("#")
        try:
            palette[int(getattr(c, "id"))] = tuple(int(hex_[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:  # noqa: BLE001
            palette[int(getattr(c, "id"))] = (47, 230, 207)
    return palette


def _colorize(labels: np.ndarray, palette: Dict[int, Tuple[int, int, int]]) -> np.ndarray:
    mx = int(labels.max())
    lut = np.zeros((mx + 1, 3), dtype=np.uint8)
    for k, v in palette.items():
        if 0 <= k <= mx:
            lut[k] = v
    return lut[labels]


def _result_target(project_id: str, source: str, img_id: str) -> Path:
    # Keep test predictions separate; for project images write into masks/ so
    # morphometry / percolation / 3D can consume them.
    return store.result_mask_path(project_id, img_id) if source == "test" \
        else store.mask_path(project_id, img_id)


def run_batch_inference(task_id: str, project_id: str, params: Dict) -> Dict:
    kind = params.get("kind", "interactive")
    source = params.get("source", "test")
    items = _resolve(project_id, source, params.get("image_ids"))
    if not items:
        raise ValueError(
            "No images to run on. Upload test images first." if source == "test"
            else "No project images found.")

    if kind == "detection":
        return _infer_detection(task_id, project_id, source, items, params)
    if kind == "segmentation":
        predictor = _make_dl_predictor(project_id, params)
    else:
        predictor = _make_interactive_predictor(project_id, params)

    palette = _palette(project_id)
    results: List[Dict] = []
    label_pngs: List[Tuple[str, bytes]] = []
    overlay_pngs: List[Tuple[str, bytes]] = []

    for i, (img_id, path, filename) in enumerate(items):
        if tracker.is_cancelled(task_id):
            raise InterruptedError
        pil = Image.open(path).convert("RGB")
        w0, h0 = pil.size
        labels = predictor(pil)                      # (H, W) uint8 at ORIGINAL size
        Image.fromarray(labels).save(_result_target(project_id, source, img_id))

        stem = Path(filename).stem
        buf = io.BytesIO(); Image.fromarray(labels).save(buf, "PNG")
        label_pngs.append((f"labels/{stem}.png", buf.getvalue()))
        ov = io.BytesIO(); Image.fromarray(_colorize(labels, palette)).save(ov, "PNG")
        overlay_pngs.append((f"overlays/{stem}.png", ov.getvalue()))

        results.append({"image_id": img_id, "filename": filename,
                        "width": w0, "height": h0})
        tracker.update(task_id, progress=(i + 1) / len(items))

    out: Dict = {"source": source, "kind": kind, "n_images": len(results), "results": results}

    if params.get("export", True):
        export_name = f"inference_{task_id[:8]}.zip"
        export_path = store.export_path(project_id, export_name)
        with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in label_pngs + overlay_pngs:
                zf.writestr(name, data)
            index = io.StringIO()
            writer = csv.writer(index)
            writer.writerow(["filename", "width", "height", "label_png"])
            for r in results:
                writer.writerow([r["filename"], r["width"], r["height"],
                                 f"labels/{Path(r['filename']).stem}.png"])
            zf.writestr("index.csv", index.getvalue())
        out["export"] = export_name

    return out


def _make_interactive_predictor(project_id: str, params: Dict):
    from app.ml.interactive import InteractiveSegmenter

    model_path = store.path(project_id) / "models" / params.get("model", "interactive.joblib")
    if not model_path.exists():
        raise FileNotFoundError(
            "No interactive model found. Run segmentation on the annotated images first.")
    seg = InteractiveSegmenter.loads(model_path.read_bytes())

    def predict(pil: Image.Image) -> np.ndarray:
        return seg.predict(np.asarray(pil))          # native resolution

    return predict


def _make_dl_predictor(project_id: str, params: Dict):
    import torch

    from app.ml.models.efficientnet_unet import build_segmentation_model

    device = torch.device(get_settings().resolve_device())
    ckpt = torch.load(store.path(project_id) / "models" / params["model"], map_location=device)
    model = build_segmentation_model(ckpt["num_classes"], size=ckpt.get("size", "medium")).to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    input_size = ckpt.get("input_size", 512)
    tta = params.get("tta", True)

    def predict(pil: Image.Image) -> np.ndarray:
        w0, h0 = pil.size
        x = torch.from_numpy(
            np.asarray(pil.resize((input_size, input_size)), np.float32) / 255.0
        ).permute(2, 0, 1).unsqueeze(0).to(device)
        with torch.no_grad():
            logits = model(x)
            if tta:
                logits = (logits + model(x.flip(-1)).flip(-1) + model(x.flip(-2)).flip(-2)) / 3
        pred = logits.argmax(1).squeeze(0).byte().cpu().numpy()
        # resize the label map back to the ORIGINAL size (nearest neighbour)
        return np.asarray(Image.fromarray(pred).resize((w0, h0), Image.NEAREST))

    return predict


def _infer_detection(task_id, project_id, source, items, params) -> Dict:
    from ultralytics import YOLO

    model = YOLO(str(store.path(project_id) / "models" / params["model"]))
    conf = float(params.get("conf", 0.25))
    detections: Dict[str, list] = {}
    rows = [["filename", "label", "conf", "x", "y", "w", "h"]]
    for i, (img_id, path, filename) in enumerate(items):
        if tracker.is_cancelled(task_id):
            raise InterruptedError
        res = model(str(path), conf=conf, verbose=False)[0]
        boxes = []
        for b in res.boxes:
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            box = {"label": int(b.cls.item()), "conf": float(b.conf.item()),
                   "x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
            boxes.append(box)
            rows.append([filename, box["label"], round(box["conf"], 4),
                         round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)])
        detections[img_id] = boxes
        tracker.update(task_id, progress=(i + 1) / len(items))

    out: Dict = {"source": source, "kind": "detection",
                 "n_images": len(items), "detections": detections}
    if params.get("export", True):
        export_name = f"inference_{task_id[:8]}.zip"
        with zipfile.ZipFile(store.export_path(project_id, export_name), "w", zipfile.ZIP_DEFLATED) as zf:
            buf = io.StringIO(); csv.writer(buf).writerows(rows)
            zf.writestr("detections.csv", buf.getvalue())
        out["export"] = export_name
    return out
