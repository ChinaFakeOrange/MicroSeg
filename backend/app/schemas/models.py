"""API request/response schemas."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ------------------------------------------------------------------ projects
class ClassDef(BaseModel):
    id: int
    name: str
    color: str = "#e67e22"


class ProjectCreate(BaseModel):
    name: str
    task_type: str = Field("segmentation", pattern="^(segmentation|detection)$")
    classes: List[ClassDef] = []
    pixel_size_um: float = 1.0
    is_stack: bool = False
    description: str = ""


class ProjectOut(BaseModel):
    id: str
    name: str
    task_type: str
    classes: List[ClassDef]
    pixel_size_um: float
    is_stack: bool
    description: str
    created_at: str
    updated_at: str


# --------------------------------------------------------------- annotations
class Box(BaseModel):
    label: int
    x: float
    y: float
    w: float
    h: float


class Scribble(BaseModel):
    label: int
    points: List[List[float]]   # [[x, y], ...]
    width: Optional[float] = None  # brush width when drawn (rendering only)


class AnnotationIn(BaseModel):
    boxes: List[Box] = []
    scribbles: List[Scribble] = []


# --------------------------------------------------------------------- jobs
class SegmentJob(BaseModel):
    # Defaults reproduce the original "label every uploaded image from all
    # existing scribbles": image_ids=None -> all images; empty strokes ->
    # the saved annotations on disk are used as training data.
    image_ids: Optional[List[str]] = None
    strokes_by_image: Dict[str, List[Scribble]] = {}
    use_saved: bool = True
    # scope = "all" labels every image; "rest" labels only the unselected
    # images (the ones not used for annotation). export bundles a results zip.
    scope: str = Field("all", pattern="^(all|rest|selected|current)$")
    export: bool = False


class ClassUpdate(BaseModel):
    classes: List[ClassDef]


class MaskEdit(BaseModel):
    png_base64: str


class SelectionUpdate(BaseModel):
    ids: List[str]
    selected: bool


class MorphometryJob(BaseModel):
    image_ids: List[str] = []
    source: str = Field("image", pattern="^(image|volume)$")
    spacing: float = 1.0
    watershed: bool = True
    watershed_level: float = 0.1
    min_area: float = 0.0
    target_label: Optional[int] = None


class PercolationJob(BaseModel):
    image_id: Optional[str] = None
    source: str = Field("image", pattern="^(image|volume)$")
    pore_label: Optional[int] = None
    inlet_axis: int = 0
    inlet_side: str = Field("low", pattern="^(low|high)$")
    n_frames: int = 120


class MeshJob(BaseModel):
    source: str = Field("masks", pattern="^(masks|images)$")
    label: Optional[int] = None
    threshold: Optional[float] = None
    spacing: List[float] = [1.0, 1.0, 1.0]
    downsample: int = 2
    step_size: int = 1


class TrainJob(BaseModel):
    task_type: str = Field("segmentation", pattern="^(segmentation|detection)$")
    model_size: str = "medium"
    epochs: int = 50
    batch_size: int = 8
    lr: float = 1e-3
    input_size: int = 512
    resume_model: Optional[str] = None   # continue training from this checkpoint
    # dataset customization
    image_ids: Optional[List[str]] = None    # hand-picked training subset (None = all masked)
    include_extra: bool = True               # also use uploaded external image+mask pairs
    val_fraction: float = 0.15
    seed: int = 42
    augment: Optional[Dict[str, bool]] = None  # {hflip, vflip, rot90, brightness}


class InferenceJob(BaseModel):
    kind: str = Field("interactive", pattern="^(segmentation|detection|interactive)$")
    model: str = "interactive.joblib"
    # "test" runs on separately uploaded test images; "images" on project images.
    source: str = Field("test", pattern="^(images|test)$")
    image_ids: Optional[List[str]] = None
    conf: float = 0.25
    tta: bool = True
    export: bool = True            # bundle predicted masks into a downloadable zip


class TaskOut(BaseModel):
    id: str
    type: str
    state: str
    progress: float
    message: str
    project_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float
    updated_at: float
