"""Celery application. Workers run ML jobs out-of-process so the API stays async
and responsive, and GPU/torch code never blocks the event loop."""
from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "microseg",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.jobs"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_max_tasks_per_child=20,     # release GPU memory periodically
    broker_connection_retry_on_startup=True,
    task_acks_late=True,
)
