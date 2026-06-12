"""Unified async task tracking.

Every long-running operation (interactive segmentation, training, batch
inference, percolation, meshing) is dispatched to a Celery worker and tracked
through a single :class:`TaskRecord` stored in Redis. The frontend polls
``GET /api/tasks/{id}`` or subscribes to the WebSocket stream for live updates,
so closing the browser never loses a running job — a core gap in the old desktop
app where state lived only in Qt threads.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import redis

from app.config import get_settings


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    id: str
    type: str
    state: TaskState = TaskState.PENDING
    progress: float = 0.0                  # 0..1
    message: str = ""
    project_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


_KEY = "microseg:task:{id}"
_CHANNEL = "microseg:task-events"


class TaskTracker:
    """Thin Redis wrapper used by both the API and the workers."""

    def __init__(self, url: Optional[str] = None):
        self._url = url or get_settings().redis_url
        self._client: Optional[redis.Redis] = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(self._url, decode_responses=True)
        return self._client

    def create(self, task_id: str, task_type: str, project_id: Optional[str] = None) -> TaskRecord:
        record = TaskRecord(id=task_id, type=task_type, project_id=project_id)
        self._save(record)
        return record

    def get(self, task_id: str) -> Optional[TaskRecord]:
        raw = self.client.get(_KEY.format(id=task_id))
        if not raw:
            return None
        data = json.loads(raw)
        data["state"] = TaskState(data["state"])
        return TaskRecord(**data)

    def update(
        self,
        task_id: str,
        *,
        state: Optional[TaskState] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[TaskRecord]:
        record = self.get(task_id)
        if record is None:
            return None
        if state is not None:
            record.state = state
        if progress is not None:
            record.progress = max(0.0, min(1.0, progress))
        if message is not None:
            record.message = message
        if result is not None:
            record.result = result
        if error is not None:
            record.error = error
        record.updated_at = time.time()
        self._save(record)
        self.client.publish(_CHANNEL, json.dumps(record.to_dict()))
        return record

    def is_cancelled(self, task_id: str) -> bool:
        record = self.get(task_id)
        return bool(record and record.state == TaskState.CANCELLED)

    def request_cancel(self, task_id: str) -> Optional[TaskRecord]:
        return self.update(task_id, state=TaskState.CANCELLED, message="Cancellation requested")

    def list_for_project(self, project_id: str) -> list[TaskRecord]:
        out = []
        for key in self.client.scan_iter(_KEY.format(id="*")):
            raw = self.client.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if data.get("project_id") == project_id:
                data["state"] = TaskState(data["state"])
                out.append(TaskRecord(**data))
        return sorted(out, key=lambda r: r.created_at, reverse=True)

    def _save(self, record: TaskRecord) -> None:
        self.client.set(
            _KEY.format(id=record.id),
            json.dumps(record.to_dict()),
            ex=get_settings().task_ttl_seconds,
        )


tracker = TaskTracker()
EVENT_CHANNEL = _CHANNEL
