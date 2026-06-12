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
        for sub in ("images", "annotations", "masks", "models", "exports"):
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

    def add_image(self, project_id: str, filename: str, content: bytes) -> Dict[str, Any]:
        img_id = new_id("img_")
        ext = Path(filename).suffix.lower() or ".png"
        dest = self.images_dir(project_id) / f"{img_id}{ext}"
        dest.write_bytes(content)
        manifest_path = self.images_dir(project_id) / "_manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
        entry = {"id": img_id, "filename": filename, "path": dest.name, "order": len(manifest)}
        manifest.append(entry)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return entry

    def image_path(self, project_id: str, image_id: str) -> Optional[Path]:
        for entry in self.list_images(project_id):
            if entry["id"] == image_id:
                return self.images_dir(project_id) / entry["path"]
        return None

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
