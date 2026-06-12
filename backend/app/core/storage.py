"""On-disk storage for projects, images, annotations and models.

A project is a self-contained directory so the whole thing can be zipped, shared
or version-controlled. Layout::

    data/projects/<project_id>/
        project.json            metadata + class definitions
        images/                 source images (+ a z-order manifest for stacks)
        annotations/            <image_id>.json  (boxes + scribbles + masks)
        masks/                  <image_id>.png   (predicted/saved label maps)
        models/                 trained model checkpoints
        exports/                YOLO / COCO / CSV exports
"""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProjectClass:
    id: int
    name: str
    color: str = "#e67e22"


@dataclass
class Project:
    id: str
    name: str
    task_type: str = "segmentation"        # segmentation | detection
    classes: List[ProjectClass] = field(default_factory=list)
    pixel_size_um: float = 1.0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    is_stack: bool = False                 # treat images as an ordered z-stack
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["classes"] = [c.__dict__ for c in self.classes]
        return d


class ProjectStore:
    def __init__(self) -> None:
        self.root = get_settings().projects_dir

    # ---------------------------------------------------------- project CRUD
    def path(self, project_id: str) -> Path:
        return self.root / project_id

    def create(self, name: str, task_type: str, classes: List[Dict], **kwargs) -> Project:
        pid = new_id("p_")
        project = Project(
            id=pid,
            name=name,
            task_type=task_type,
            classes=[ProjectClass(**c) for c in classes],
            **kwargs,
        )
        base = self.path(pid)
        for sub in ("images", "test", "annotations", "masks", "results", "models", "exports", "extra_pairs"):
            (base / sub).mkdir(parents=True, exist_ok=True)
        self._write_meta(project)
        return project

    def get(self, project_id: str) -> Optional[Project]:
        meta = self.path(project_id) / "project.json"
        if not meta.exists():
            return None
        data = json.loads(meta.read_text())
        data["classes"] = [ProjectClass(**c) for c in data.get("classes", [])]
        return Project(**data)

    def list(self) -> List[Project]:
        out = []
        for d in self.root.iterdir():
            if d.is_dir() and (d / "project.json").exists():
                p = self.get(d.name)
                if p:
                    out.append(p)
        return sorted(out, key=lambda p: p.updated_at, reverse=True)

    def delete(self, project_id: str) -> bool:
        base = self.path(project_id)
        if base.exists():
            shutil.rmtree(base)
            return True
        return False

    def _write_meta(self, project: Project) -> None:
        project.updated_at = _now()
        (self.path(project.id) / "project.json").write_text(
            json.dumps(project.to_dict(), indent=2, ensure_ascii=False)
        )

    def touch(self, project: Project) -> None:
        self._write_meta(project)

    # ----------------------------------------------------------------- images
    def images_dir(self, project_id: str) -> Path:
        return self.path(project_id) / "images"

    def list_images(self, project_id: str) -> List[Dict[str, Any]]:
        manifest = self.path(project_id) / "images" / "_manifest.json"
        if manifest.exists():
            return json.loads(manifest.read_text())
        return []

    def _append_manifest(self, project_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
        manifest_path = self.images_dir(project_id) / "_manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
        entry.setdefault("order", len(manifest))
        manifest.append(entry)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return entry

    def add_image(self, project_id: str, filename: str, content: bytes,
                  selected: bool = True, group: Optional[str] = None,
                  axis: Optional[int] = None, index: Optional[int] = None) -> Dict[str, Any]:
        img_id = new_id("img_")
        ext = Path(filename).suffix.lower() or ".png"
        dest = self.images_dir(project_id) / f"{img_id}{ext}"
        dest.write_bytes(content)
        return self._append_manifest(project_id, {
            "id": img_id, "filename": filename, "path": dest.name,
            "selected": selected, "group": group, "axis": axis, "index": index,
        })

    @staticmethod
    def stack_info(content: bytes) -> Dict[str, Any]:
        """Read just the (effective) shape of a TIFF without loading all data.

        Applies the same normalisation as ``add_stack`` so the per-axis slice
        counts reported here match what slicing will actually produce.
        """
        import io as _io

        import tifffile

        with tifffile.TiffFile(_io.BytesIO(content)) as tf:
            shape = tuple(int(x) for x in tf.series[0].shape)
        if len(shape) == 2:
            eff = (1, shape[0], shape[1])
        elif len(shape) == 4 and shape[-1] in (3, 4):
            eff = shape[:3]
        elif len(shape) == 3:
            eff = shape
        else:
            raise ValueError(f"Unsupported TIFF shape {shape!r}")
        return {"raw_shape": list(shape), "shape": list(eff), "ndim": 3}

    def add_stack(self, project_id: str, filename: str, content: bytes,
                  axis: int = 0, select_every: int = 1, max_select: int = 0) -> List[Dict[str, Any]]:
        """Slice a multi-page / 3D TIFF along ``axis`` and add each slice.

        ``select_every`` marks every Nth slice as selected for annotation; the
        rest are stored but not selected. Slices are min-max normalised to 8-bit
        for consistent display.
        """
        import io as _io

        import numpy as np
        import tifffile
        from PIL import Image

        arr = tifffile.imread(_io.BytesIO(content))
        arr = np.asarray(arr)
        # Reduce trailing channel dims to a plain volume where possible.
        if arr.ndim == 2:
            arr = arr[None, ...]
        elif arr.ndim == 4 and arr.shape[-1] in (3, 4):
            arr = arr[..., :3].mean(axis=-1)         # collapse colour to intensity
        if arr.ndim != 3:
            raise ValueError(f"Unsupported TIFF shape {arr.shape!r}")

        axis = int(axis) % 3
        vol = np.moveaxis(arr, axis, 0)              # chosen axis -> slice index
        vmin, vmax = float(vol.min()), float(vol.max())
        scale = (255.0 / (vmax - vmin)) if vmax > vmin else 1.0

        group = new_id("stk_")
        n = vol.shape[0]
        sel_idx = set(range(0, n, max(1, select_every)))
        if max_select and len(sel_idx) > max_select:
            sel_idx = set(sorted(sel_idx)[:max_select])

        stem = Path(filename).stem
        added = []
        for i in range(n):
            sl = ((vol[i].astype(np.float32) - vmin) * scale).clip(0, 255).astype(np.uint8)
            buf = _io.BytesIO()
            Image.fromarray(sl).convert("RGB").save(buf, "PNG")
            added.append(self.add_image(
                project_id, f"{stem}_a{axis}_{i:04d}.png", buf.getvalue(),
                selected=(i in sel_idx), group=group, axis=axis, index=i))
        return added

    def set_selected(self, project_id: str, image_id: str, selected: bool) -> bool:
        manifest_path = self.images_dir(project_id) / "_manifest.json"
        if not manifest_path.exists():
            return False
        manifest = json.loads(manifest_path.read_text())
        hit = False
        for e in manifest:
            if e["id"] == image_id:
                e["selected"] = selected
                hit = True
        if hit:
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return hit

    def set_selected_many(self, project_id: str, ids: List[str], selected: bool) -> int:
        """Set the ``selected`` flag for many images at once (select-all / clear /
        every-Nth from the gallery)."""
        manifest_path = self.images_dir(project_id) / "_manifest.json"
        if not manifest_path.exists():
            return 0
        manifest = json.loads(manifest_path.read_text())
        idset = set(ids)
        n = 0
        for e in manifest:
            if e["id"] in idset:
                e["selected"] = selected
                n += 1
        if n:
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return n

    def save_mask(self, project_id: str, image_id: str, png_bytes: bytes) -> Path:
        """Persist an (edited) label mask PNG for an image."""
        path = self.mask_path(project_id, image_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes)
        return path

    def update_classes(self, project_id: str, classes: List[Dict]) -> Optional["Project"]:
        project = self.get(project_id)
        if project is None:
            return None
        project.classes = [ProjectClass(**c) for c in classes]
        self._write_meta(project)
        # Classes changed -> the saved interactive model is stale; drop it so the
        # next segmentation retrains and produces a fresh overlay.
        model = self.path(project_id) / "models" / "interactive.joblib"
        if model.exists():
            model.unlink()
        return project


    def image_path(self, project_id: str, image_id: str) -> Optional[Path]:
        for entry in self.list_images(project_id):
            if entry["id"] == image_id:
                return self.images_dir(project_id) / entry["path"]
        return None

    # ------------------------------------------------------- test images set
    # A separate set of images used only for inference, so predictions never
    # overwrite the training masks. Mirrors the original "deploy" file picker.
    def test_dir(self, project_id: str) -> Path:
        return self.path(project_id) / "test"

    def list_test_images(self, project_id: str) -> List[Dict[str, Any]]:
        manifest = self.test_dir(project_id) / "_manifest.json"
        if manifest.exists():
            return json.loads(manifest.read_text())
        return []

    def add_test_image(self, project_id: str, filename: str, content: bytes) -> Dict[str, Any]:
        self.test_dir(project_id).mkdir(parents=True, exist_ok=True)
        img_id = new_id("test_")
        ext = Path(filename).suffix.lower() or ".png"
        dest = self.test_dir(project_id) / f"{img_id}{ext}"
        dest.write_bytes(content)
        manifest_path = self.test_dir(project_id) / "_manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
        entry = {"id": img_id, "filename": filename, "path": dest.name, "order": len(manifest)}
        manifest.append(entry)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return entry

    def test_image_path(self, project_id: str, image_id: str) -> Optional[Path]:
        for entry in self.list_test_images(project_id):
            if entry["id"] == image_id:
                return self.test_dir(project_id) / entry["path"]
        return None

    # --------------------------------------------------- external train pairs
    def extra_dir(self, project_id: str) -> Path:
        d = self.path(project_id) / "extra_pairs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_extra_pairs(self, project_id: str) -> List[Dict[str, Any]]:
        manifest = self.extra_dir(project_id) / "_manifest.json"
        if manifest.exists():
            return json.loads(manifest.read_text())
        return []

    def add_extra_pair(self, project_id: str, img_name: str, img_bytes: bytes,
                       mask_name: str, mask_bytes: bytes) -> Dict[str, Any]:
        """Store an externally-supplied (image, label-mask) training pair."""
        d = self.extra_dir(project_id)
        pid = new_id("pair_")
        ie = Path(img_name).suffix.lower() or ".png"
        me = Path(mask_name).suffix.lower() or ".png"
        (d / f"{pid}_img{ie}").write_bytes(img_bytes)
        (d / f"{pid}_mask{me}").write_bytes(mask_bytes)
        mpath = d / "_manifest.json"
        manifest = json.loads(mpath.read_text()) if mpath.exists() else []
        entry = {"id": pid, "image": f"{pid}_img{ie}", "mask": f"{pid}_mask{me}",
                 "filename": img_name}
        manifest.append(entry)
        mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return entry

    def delete_extra_pair(self, project_id: str, pair_id: str) -> bool:
        d = self.extra_dir(project_id)
        mpath = d / "_manifest.json"
        if not mpath.exists():
            return False
        manifest = json.loads(mpath.read_text())
        keep, removed = [], None
        for e in manifest:
            if e["id"] == pair_id:
                removed = e
            else:
                keep.append(e)
        if removed:
            for f in (removed["image"], removed["mask"]):
                fp = d / f
                if fp.exists():
                    fp.unlink()
            mpath.write_text(json.dumps(keep, indent=2, ensure_ascii=False))
            return True
        return False

    def extra_pair_paths(self, project_id: str) -> List[tuple]:
        """[(image_path, mask_path), ...] for every stored external pair."""
        d = self.extra_dir(project_id)
        return [(d / e["image"], d / e["mask"]) for e in self.list_extra_pairs(project_id)]

    # ------------------------------------------------------------- results
    # ------------------------------------------------------------- models
    def models_dir(self, project_id: str) -> Path:
        d = self.path(project_id) / "models"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_models(self, project_id: str) -> List[Dict[str, Any]]:
        """All trained model files in the project with light metadata.

        Recognises the interactive LightGBM model, U-Net segmentation
        checkpoints (.pt) and YOLO detection weights (.pt under a run dir).
        """
        out: List[Dict[str, Any]] = []
        mdir = self.models_dir(project_id)
        for p in sorted(mdir.glob("*")):
            if p.is_dir():
                continue
            name = p.name
            if name.endswith(".joblib"):
                kind = "interactive"
                meta = {}
            elif name.endswith(".pt") or name.endswith(".pth"):
                kind = "segmentation"
                meta = {}
                try:    # peek at checkpoint metadata without loading weights to GPU
                    import torch
                    ck = torch.load(p, map_location="cpu")
                    meta = {"num_classes": ck.get("num_classes"),
                            "input_size": ck.get("input_size"), "size": ck.get("size")}
                except Exception:  # noqa: BLE001
                    meta = {}
            else:
                continue
            st = p.stat()
            out.append({"name": name, "kind": kind, "size": st.st_size,
                        "modified": st.st_mtime, **meta})
        # YOLO weights live under models/<run>/weights/best.pt
        for best in mdir.glob("*/weights/best.pt"):
            st = best.stat()
            out.append({"name": str(best.relative_to(mdir)), "kind": "detection",
                        "size": st.st_size, "modified": st.st_mtime})
        out.sort(key=lambda m: m["modified"], reverse=True)
        return out

    def results_dir(self, project_id: str) -> Path:
        d = self.path(project_id) / "results"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def result_mask_path(self, project_id: str, image_id: str) -> Path:
        return self.results_dir(project_id) / f"{image_id}.png"

    def export_path(self, project_id: str, name: str) -> Path:
        d = self.path(project_id) / "exports"
        d.mkdir(parents=True, exist_ok=True)
        return d / name

    # ------------------------------------------------------------ annotations
    def annotation_path(self, project_id: str, image_id: str) -> Path:
        return self.path(project_id) / "annotations" / f"{image_id}.json"

    def save_annotation(self, project_id: str, image_id: str, data: Dict) -> None:
        self.annotation_path(project_id, image_id).write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )

    def load_annotation(self, project_id: str, image_id: str) -> Optional[Dict]:
        p = self.annotation_path(project_id, image_id)
        return json.loads(p.read_text()) if p.exists() else None

    def mask_path(self, project_id: str, image_id: str) -> Path:
        return self.path(project_id) / "masks" / f"{image_id}.png"


store = ProjectStore()
