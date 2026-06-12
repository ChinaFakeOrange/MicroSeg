"""API smoke tests.

These exercise the HTTP surface without Redis or Celery: project CRUD, image
upload and annotation round-trips. Job dispatch endpoints are covered
separately (they require a broker), so here we only assert the synchronous
parts of the API behave.
"""
from __future__ import annotations

import io
import os
import tempfile

import numpy as np
import pytest
from PIL import Image

# Point the data dir at a temp location BEFORE importing the app/settings.
_TMP = tempfile.mkdtemp(prefix="microseg-test-")
os.environ["MICROSEG_DATA_DIR"] = _TMP

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _png_bytes(w=32, h=32) -> bytes:
    arr = (np.random.default_rng(0).random((h, w, 3)) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "device" in body


def test_project_lifecycle_and_image_upload():
    # Create.
    r = client.post("/api/projects", json={
        "name": "demo",
        "description": "test project",
        "classes": [
            {"id": 1, "name": "particle", "color": "#ff0000"},
            {"id": 2, "name": "pore", "color": "#0000ff"},
        ],
    })
    assert r.status_code in (200, 201), r.text
    project = r.json()
    pid = project["id"]

    # List shows it.
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert any(p["id"] == pid for p in r.json())

    # Upload an image.
    r = client.post(
        f"/api/projects/{pid}/images",
        files={"files": ("a.png", _png_bytes(), "image/png")},
    )
    assert r.status_code in (200, 201), r.text
    images = client.get(f"/api/projects/{pid}/images").json()
    assert len(images) == 1
    image_id = images[0]["id"]

    # Save and reload an annotation.
    ann = {
        "boxes": [{"label": 1, "x": 2, "y": 3, "w": 10, "h": 12}],
        "scribbles": [{"label": 2, "points": [[1, 1], [2, 2], [3, 3]]}],
    }
    r = client.put(f"/api/projects/{pid}/images/{image_id}/annotation", json=ann)
    assert r.status_code in (200, 204), r.text

    r = client.get(f"/api/projects/{pid}/images/{image_id}/annotation")
    assert r.status_code == 200
    got = r.json()
    assert got["boxes"][0]["label"] == 1
    assert got["scribbles"][0]["label"] == 2

    # Raw image bytes are served.
    r = client.get(f"/api/projects/{pid}/images/{image_id}/raw")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")

    # Delete.
    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code in (200, 204)
    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 404
