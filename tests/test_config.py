import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_load_defaults(monkeypatch) -> None:
    monkeypatch.delenv("AJI_APP_ENV", raising=False)
    settings = Settings(_env_file=None)

    assert settings.app_name == "Assam Job Intelligence"
    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.confidence_standard_threshold == 80
    assert settings.confidence_critical_threshold == 90
    assert settings.confidence_revision_threshold == 85
    assert settings.master_publisher_batch_size == 100
    assert settings.public_allowed_host_list == ["localhost", "127.0.0.1", "testserver"]
    assert settings.public_rate_limit_requests == 120
    assert settings.public_cache_max_age_seconds == 60


def test_settings_load_environment(monkeypatch) -> None:
    monkeypatch.setenv("AJI_APP_ENV", "test")
    monkeypatch.setenv("AJI_DEBUG", "true")
    monkeypatch.setenv("AJI_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("AJI_CONFIDENCE_STANDARD_THRESHOLD", "75")
    monkeypatch.setenv("AJI_CONFIDENCE_CRITICAL_THRESHOLD", "88")
    monkeypatch.setenv("AJI_CONFIDENCE_REVISION_THRESHOLD", "82")
    monkeypatch.setenv("AJI_MASTER_PUBLISHER_BATCH_SIZE", "25")
    monkeypatch.setenv("AJI_PUBLIC_ALLOWED_HOSTS", "jobs.example.test,localhost")
    monkeypatch.setenv("AJI_PUBLIC_RATE_LIMIT_REQUESTS", "50")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.debug is True
    assert settings.database_url == "sqlite+pysqlite:///:memory:"
    assert settings.confidence_standard_threshold == 75
    assert settings.confidence_critical_threshold == 88
    assert settings.confidence_revision_threshold == 82
    assert settings.master_publisher_batch_size == 25
    assert settings.public_allowed_host_list == ["jobs.example.test", "localhost"]
    assert settings.public_rate_limit_requests == 50


@pytest.mark.parametrize(
    ("setting", "value"),
    [("public_allowed_hosts", "*"), ("public_forwarded_allow_ips", "*")],
)
def test_production_settings_reject_unbounded_trust(setting, value) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", **{setting: value})
