# API reference

Base path: `/api` (configurable via `MICROSEG_API_PREFIX`). All request/response bodies are JSON unless noted. Interactive docs are available at `/docs` (Swagger) when the API is running.

## Health

```
GET /health → { status, device, app }
```

## Projects

```
POST   /api/projects                 create a project
GET    /api/projects                 list projects
GET    /api/projects/{id}            get one project (with classes + image manifest)
DELETE /api/projects/{id}            delete a project and all its data
```

**Create body**

```json
{
  "name": "sandstone-thin-sections",
  "task_type": "segmentation",        // or "detection"
  "classes": [
    { "id": 1, "name": "particle", "color": "#2fe6cf" },
    { "id": 2, "name": "pore", "color": "#f0519e" }
  ],
  "pixel_size_um": 1.0,
  "is_stack": false,
  "description": ""
}
```

## Images & annotations

```
POST /api/projects/{id}/images                         multipart upload (field: files[])
GET  /api/projects/{id}/images                          list images
GET  /api/projects/{id}/images/{image_id}/raw           raw image bytes
GET  /api/projects/{id}/images/{image_id}/mask          predicted mask (?colorized=true)
PUT  /api/projects/{id}/images/{image_id}/annotation    save { boxes, scribbles }
GET  /api/projects/{id}/images/{image_id}/annotation    load annotation
GET  /api/projects/{id}/exports/{name}                  download an export artifact
```

**Annotation shape**

```json
{
  "boxes":     [{ "label": 1, "x": 10, "y": 12, "w": 40, "h": 30 }],
  "scribbles": [{ "label": 2, "points": [[5,5],[6,6],[7,8]] }]
}
```

## Jobs

Every job endpoint creates a task, enqueues it, and returns `{ "task_id": "t_..." }` immediately.

```
POST /api/projects/{id}/segment        interactive (LightGBM) segmentation
POST /api/projects/{id}/morphometry    particle measurement
POST /api/projects/{id}/percolation    invasion percolation
POST /api/projects/{id}/mesh           3D isosurface
POST /api/projects/{id}/train          model training
POST /api/projects/{id}/inference      neural inference
```

**Selected bodies**

```jsonc
// segment
{ "image_ids": ["img_1"], "strokes_by_image": { "img_1": [{ "label": 1, "points": [[..]] }] } }

// morphometry
{ "image_ids": ["img_1"], "spacing": 1.0, "watershed": true, "watershed_level": 0.1, "min_area": 0 }

// percolation
{ "image_id": "img_1", "pore_label": 2, "inlet_axis": 0, "inlet_side": "low", "n_frames": 120 }

// mesh
{ "source": "masks", "label": 1, "downsample": 2, "step_size": 1, "spacing": [1,1,1] }

// train
{ "task_type": "segmentation", "model_size": "medium", "epochs": 50, "batch_size": 8, "lr": 0.001, "input_size": 512 }

// inference
{ "kind": "segmentation", "model": "best", "image_ids": null, "conf": 0.25, "tta": true }
```

## Tasks

```
GET  /api/tasks/{task_id}              task status
POST /api/tasks/{task_id}/cancel       request cooperative cancellation
GET  /api/projects/{id}/tasks          all tasks for a project
WS   /api/ws/tasks?project_id={id}     live stream of task updates
```

**Task object**

```json
{
  "id": "t_ab12", "type": "percolation", "state": "running",
  "progress": 0.3, "message": "Running invasion percolation",
  "project_id": "p_xx", "result": null, "error": null,
  "created_at": 1718200000.0, "updated_at": 1718200005.0
}
```

States: `queued → running → done | error | cancelled`.

## Notable result payloads

**percolation** — `result` contains `shape`, `n_steps`, `breakthrough_step`, `saturation_curve`, `percolates`, `porosity`, and `time_map_b64` (base64 int16 time-of-invasion map, `-1` = never invaded). The frontend decodes it and animates by revealing voxels with `0 ≤ time ≤ t`.

**mesh** — `result` contains flat `vertices`, `normals`, `indices` arrays (ready for a Three.js `BufferGeometry`), `vertex_count`, `triangle_count`, and `bounds { min, max }`, centered at the origin.

**morphometry** — `result` contains `rows` (one object per row: area, ed, esp, perimeter, rugosity, cpc, centroid, elongation, roundness, feret_diameter) and a `summary` of per-column means/stds plus `count` and `total_area`.
