from datetime import date, timedelta
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
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
    review_web_reviewer_identifier: str = Field(
        default="local-review-ui", min_length=1, max_length=255
    )
    master_publisher_batch_size: int = Field(default=100, ge=1, le=10_000)
    verification_batch_size: int = Field(default=100, ge=1, le=10_000)
    raw_storage_root: str = "data/raw"
    discovery_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    discovery_read_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    discovery_http_retries: int = Field(default=2, ge=0, le=5)
    history_lookback_months: int = Field(default=12, ge=1, le=60)
    discovery_max_response_bytes: int = Field(default=10_000_000, ge=1024)
    monitor_running_stale_minutes: int = Field(default=60, ge=1, le=10_080)
    monitor_success_stale_hours: int = Field(default=26, ge=1, le=8_760)
    monitor_trend_run_limit: int = Field(default=20, ge=1, le=500)
    monitor_notification_channels: str = "LOG"
    monitor_notification_file: str | None = None
    public_allowed_hosts: str = "localhost,127.0.0.1,testserver"
    public_forwarded_allow_ips: str = "127.0.0.1"
    public_rate_limit_requests: int = Field(default=120, ge=1, le=100_000)
    public_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3_600)
    public_cache_max_age_seconds: int = Field(default=60, ge=0, le=3_600)
    public_max_request_target_bytes: int = Field(default=4_096, ge=512, le=65_536)

    def history_cutoff(self, today: date) -> date:
        month_index = today.year * 12 + today.month - 1 - self.history_lookback_months
        year, month_zero = divmod(month_index, 12)
        first_next = date(year + (month_zero == 11), (month_zero + 1) % 12 + 1, 1)
        last_day = (first_next - timedelta(days=1)).day
        return date(year, month_zero + 1, min(today.day, last_day))

    @property
    def public_allowed_host_list(self) -> list[str]:
        hosts = [host.strip() for host in self.public_allowed_hosts.split(",") if host.strip()]
        if not hosts:
            raise ValueError("AJI_PUBLIC_ALLOWED_HOSTS must contain at least one host")
        return hosts

    @model_validator(mode="after")
    def reject_unbounded_production_proxy_trust(self) -> "Settings":
        if self.app_env == "production":
            if "*" in self.public_allowed_host_list:
                raise ValueError("AJI_PUBLIC_ALLOWED_HOSTS cannot contain '*' in production")
            if self.public_forwarded_allow_ips.strip() == "*":
                raise ValueError("AJI_PUBLIC_FORWARDED_ALLOW_IPS cannot be '*' in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
