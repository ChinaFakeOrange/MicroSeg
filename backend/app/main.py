"""MicroSeg API — FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import jobs, projects, tasks
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="MicroSeg API",
    version="1.0.0",
    description="Browser-based microscopic image annotation, training, inference, "
                "particle morphometry, 3D reconstruction and percolation simulation.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = settings.api_prefix
app.include_router(projects.router, prefix=api, tags=["projects"])
app.include_router(jobs.router, prefix=api, tags=["jobs"])
app.include_router(tasks.router, prefix=api, tags=["tasks"])


@app.get("/health")
def health():
    return {"status": "ok", "device": settings.resolve_device(), "app": settings.app_name}
