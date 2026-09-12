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


@lru_cache
def get_settings() -> Settings:
    return Settings()
