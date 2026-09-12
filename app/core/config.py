from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AJI_",
        extra="ignore",
    )

    app_name: str = "Assam Job Intelligence"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = Field(
        default="postgresql+psycopg://assam_admin:assam_dev_password@localhost:5432/assam_job_intelligence",
        min_length=1,
    )
    confidence_standard_threshold: int = Field(default=80, ge=0, le=100)
    confidence_critical_threshold: int = Field(default=90, ge=0, le=100)
    confidence_revision_threshold: int = Field(default=85, ge=0, le=100)
    master_publisher_batch_size: int = Field(default=100, ge=1, le=10_000)
    verification_batch_size: int = Field(default=100, ge=1, le=10_000)
    raw_storage_root: str = "data/raw"
    discovery_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    discovery_read_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    discovery_http_retries: int = Field(default=2, ge=0, le=5)
    discovery_max_response_bytes: int = Field(default=10_000_000, ge=1024)
    monitor_running_stale_minutes: int = Field(default=60, ge=1, le=10_080)
    monitor_success_stale_hours: int = Field(default=26, ge=1, le=8_760)
    monitor_trend_run_limit: int = Field(default=20, ge=1, le=500)
    monitor_notification_channels: str = "LOG"
    monitor_notification_file: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
