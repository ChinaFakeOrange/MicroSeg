# Migration notes — from the PySide desktop tool to MicroSeg

This document maps the original local application (referred to here as *ImageSeg*) onto MicroSeg, and records the deliberate changes made along the way. The goal of the migration was to keep the scientific value intact while making the tool deployable, browser-operable, async, and maintainable.

## The original tool

ImageSeg was a single-process PySide6 desktop application (~Windows-only). Its real source — setting aside the large generated Qt resource file — was a handful of modules that mixed three concerns together:

- **UI** (`interface_main.py`, `utils/graphicview.py`) — the Qt window and a hand-built annotation canvas.
- **Algorithms** (`utils/algo.py`, ~1100 lines) — the feature stack, the LightGBM interactive segmenter, watershed morphometry, a hand-rolled EfficientNetV2, an Attention-U-Net, and several loss functions.
- **Threading** (`utils/Workers.py`) — `QThread` workers, plus training launched as Windows subprocesses whose stdout was scraped for progress.

It had three workflows: **annotation** (boxes → YOLO export, and scribble-based interactive segmentation), **training** (YOLOv8 detection + custom segmentation), and **inference/deploy** (detection/segmentation on images/video/camera + SimpleITK watershed particle morphometry → CSV).

## Module-by-module mapping

| Original | MicroSeg | Notes |
|---|---|---|
| `utils/algo.py` → `GIS`, feature funcs | `app/ml/features.py` | The multi-scale feature stack (intensity, Gaussian, Sobel, DoG, neighbors, Hessian, structure tensor at scales 1/2/4), cleanly separated with a `FeatureConfig`. |
| `utils/algo.py` → `training`/`d_set`/`Pred` | `app/ml/interactive.py` | The ilastik-style LightGBM segmenter, now a serializable `InteractiveSegmenter` class with `fit`/`predict`/`predict_proba`, feature-importance selection, and joblib `dumps`/`loads`. |
| `utils/algo.py` → watershed + `LabelShapeStatisticsImageFilter` | `app/ml/morphometry.py` | SimpleITK watershed/connected-components morphometry; same columns (area, ED, ESP, perimeter, rugosity, CPC, …) plus roundness, elongation, Feret. |
| `utils/algo.py` → custom `EfficientNetV2` | `app/ml/models/efficientnet_unet.py` | **Replaced** (see below) with `segmentation-models-pytorch` U-Net + EfficientNet encoder + scSE attention. |
| `utils/algo.py` → losses (`SurfaceLoss`, `DiceLoss`, `GDL`, `FocalTverskyLoss`) | `app/ml/models/losses.py` | Ported and **fixed** (see below); added a `ComboLoss` and a `dice_score` metric. |
| `utils/Workers.py` (QThread + subprocess training) | `app/workers/jobs.py` + Celery | Training/inference/analysis become Celery tasks with structured progress, not stdout scraping. |
| YOLO box export | `app/ml/train_yolo.py` → `export_yolo_dataset` | Projects boxes to normalized YOLO format and writes `data.yaml`. |
| YOLOv8 training/inference | `app/ml/train_yolo.py`, `app/ml/inference.py` | Uses `ultralytics`, with an epoch callback for progress + cancellation. |
| Custom seg training loop | `app/ml/train_seg.py` | AdamW + OneCycleLR + AMP, best-checkpoint by validation Dice, progress to the task tracker. |
| `interface_main.py`, `graphicview.py` (Qt UI) | `frontend/` (Vue SPA) | The entire UI is reimplemented in the browser; `AnnotationCanvas.vue` replaces the Qt graphics view. |
| (none) | `app/ml/percolation.py` + `PercolationSim.vue` | **New** feature. |
| (none) | `app/ml/volume.py` + `VolumeViewer3D.vue` | **New** 3D feature. |

## Deliberate changes

### 1. Replaced the hand-rolled EfficientNetV2 with `segmentation-models-pytorch`
The original carried ~700 lines of custom EfficientNetV2 + Attention-U-Net code. That is a lot of surface area to maintain and debug for what is, today, a solved problem. MicroSeg uses `smp.Unet` with an EfficientNet encoder (`b0`/`b3`/`b5` for the light/medium/heavy sizes from the original UI) and scSE attention. This keeps the same "pick a model size" UX, gets pretrained encoders for free, and removes hundreds of lines of bespoke network code. The Chinese size labels (轻量级/中量级/高量级) are preserved as aliases.

### 2. Fixed `DiceLoss`
The original `DiceLoss` computed its intersection/union with **numpy**, which breaks autograd — gradients can't flow through a numpy detour, so the loss couldn't actually train. MicroSeg's `SoftDiceLoss` is a proper differentiable soft-Dice over torch tensors. The other losses (Generalized Dice, Focal Tversky) were ported faithfully, and a `ComboLoss` (cross-entropy + region loss) replaces the old ad-hoc `criteria` combination.

### 3. Celery instead of QThreads/subprocesses
Desktop threading doesn't survive becoming a service. Training is long and GPU-bound, so it runs in a separate Celery worker process; the API never blocks, GPU memory is reclaimed periodically, and the GPU worker can be a different image from the API. Progress is reported through structured task updates instead of scraping subprocess stdout.

### 4. Async with real task tracking
Every long operation returns a task id and streams progress over a WebSocket, with cooperative cancellation and persistence across browser refreshes — the "async operations with task status tracking" requirement that the desktop tool only approximated with per-window threads.

### 5. Robustness fixes carried over from the audit
The original had silent `try/except: pass` blocks, Windows-only backslash paths, and no persistence, tests or packaging. MicroSeg uses `pathlib` throughout, surfaces errors into the task record (with traceback), persists projects/tasks to disk and Redis, ships a pytest suite for the GPU-free core, and is fully Dockerized.

## New capabilities

- **Percolation** (`app/ml/percolation.py`) — spanning-cluster/connectivity analysis and heap-based invasion percolation ordered by distance-transform throat width, producing a time-of-invasion map the browser animates frame by frame, plus a saturation curve, porosity and breakthrough step. Validated physics: random media below the threshold don't span, above it they do; invasion on a connected medium saturates monotonically to 1.0.
- **3D reconstruction** (`app/ml/volume.py`) — stack Z-slices into a volume and extract an isosurface with marching cubes, emitting flat vertex/normal/index buffers ready for a Three.js `BufferGeometry`.

## What was intentionally dropped

- The generated Qt resource blob and all Qt dependencies.
- Live **camera/video** inference from the desktop deploy tab — out of scope for a first browser release; the batch image path covers the core need and can be extended later.
- stdout-scraping subprocess orchestration, replaced by Celery.
