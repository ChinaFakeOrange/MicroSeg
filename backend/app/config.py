"""Application configuration via environment variables (pydantic-settings)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MICROSEG_", env_file=".env", extra="ignore")

    # --- general ---
    app_name: str = "MicroSeg"
    debug: bool = False
    api_prefix: str = "/api"

    # --- storage ---
    data_dir: Path = Path("./data")          # projects, images, models, exports
    max_upload_mb: int = 256

    # --- task queue / cache ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    task_ttl_seconds: int = 60 * 60 * 24 * 7  # keep task records 7 days

    # --- compute ---
    device: str = "auto"                      # auto | cpu | cuda
    train_subprocess: bool = True             # isolate training in its own process

    # --- security / cors ---
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.projects_dir, self.models_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
