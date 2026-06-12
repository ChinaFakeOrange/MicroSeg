# Architecture

MicroSeg is a four-service system: a Vue SPA, a FastAPI API, a Celery worker, and Redis. The guiding principle is that **the API stays async and never blocks**, so anything heavy — feature extraction, watershed, percolation, marching cubes, and especially GPU training — runs in the worker process and reports back through Redis.

## Components

### Frontend (Vue 3 + Vite)
A single-page app served as static files by nginx in production, or by the Vite dev server during development. State lives in two Pinia stores:

- `projects` — the project list, the open project, its classes and images.
- `tasks` — a live registry of every dispatched job, kept current by a single shared WebSocket with a polling fallback.

Views map to the workflow: **Projects → Annotate → Analyze → Volume → Train**. Four components carry the weight: `AnnotationCanvas` (zoomable box/scribble drawing on a canvas overlay), `TaskMonitor` (the live instrument log), `VolumeViewer3D` (Three.js isosurface viewer), and `PercolationSim` (canvas animation of the invasion front).

### API (FastAPI)
Three routers under `/api`:

- **projects** — CRUD, image upload/raw/mask, annotation save/load, export download.
- **jobs** — one dispatch endpoint per job type. Each creates a `TaskRecord`, enqueues a Celery task, and returns `{ task_id }` immediately.
- **tasks** — status, cancellation, per-project listing, and the `/ws/tasks` WebSocket that streams every task update.

The API is intentionally thin: it validates with pydantic schemas, talks to the on-disk `ProjectStore` for project data, and to the Redis-backed `TaskTracker` for job state. It imports no torch, so the API image is small and starts fast.

### Worker (Celery)
The worker consumes jobs from Redis. Each job:

1. moves the task to `RUNNING` and updates progress as it goes,
2. checks `tracker.is_cancelled(...)` at safe points for cooperative cancellation,
3. writes its result back into the task record on success, or the traceback on failure.

ML imports (`torch`, `ultralytics`, `segmentation-models-pytorch`) are **lazy** — done inside the job functions, not at module load — so a CPU worker can still run the numpy/LightGBM/SimpleITK jobs even when torch isn't installed.

Celery (rather than an in-process async queue) was chosen specifically because training is long-running and GPU-bound: isolating it in a separate process keeps the event loop free, lets `worker_max_tasks_per_child` reclaim GPU memory, and allows the GPU worker to be a different container/image from the API.

### Redis
Plays three roles: Celery broker (db 1), Celery result backend (db 2), and the application's own task store + pub/sub event channel (db 0). The API subscribes to `microseg:task-events` and forwards messages to WebSocket clients (optionally filtered by project).

## Data flow: a segmentation job

```
1. User scribbles in AnnotationCanvas; annotation saved via PUT .../annotation
2. "Run segmentation" → POST /api/projects/{id}/segment
3. API: tracker.create(task) ; jobs.interactive_segment.delay(...) ; returns {task_id}
4. Frontend: tasks.register(task_id) → shows "queued" instantly
5. Worker: extract features → fit LightGBM on scribbles → predict full frame
          → write mask to disk → tracker.update(SUCCESS, result)
6. Each tracker.update publishes to Redis → API forwards over WS → TaskMonitor updates
7. AnnotateView sees the done event → reloads the colorized mask overlay
```

## Storage layout

Projects live under `MICROSEG_DATA_DIR` (a mounted volume in Docker):

```
data/projects/{project_id}/
├── project.json            name, classes, task type, pixel size, image manifest
├── images/                 uploaded source images
├── annotations/            {image_id}.json  → { boxes, scribbles }
├── masks/                  predicted/label masks (PNG)
├── models/                 trained checkpoints
└── exports/                YOLO datasets, CSVs
```

## Async + task tracking

A `TaskRecord` carries `id, type, state, progress, message, project_id, result, error, created_at, updated_at`. States are `queued → running → (done | error | cancelled)`. The frontend never has to know whether an update arrived by WebSocket or by poll — both flow through `taskStore.ingest()`, which merges partial updates so a sparse event never clobbers a fuller record.

## Why this shape

The original desktop tool ran algorithms on Qt `QThread`s inside the GUI process and shelled out to Windows subprocesses for training, scraping stdout for progress. That works for one user on one machine but can't be deployed, shared, or scaled, and a crash in an algorithm could take down the UI. Splitting API/worker/queue gives process isolation, horizontal scaling of workers, a language-agnostic HTTP surface, and a UI that stays responsive no matter how heavy the job.
