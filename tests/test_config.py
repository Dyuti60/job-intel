import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_DEVELOPMENT_DATABASE_URL, Settings


def test_settings_load_defaults(monkeypatch) -> None:
    monkeypatch.delenv("AJI_APP_ENV", raising=False)
    settings = Settings(_env_file=None)

    assert settings.app_name == "Assam Job Intelligence"
    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.confidence_standard_threshold == 80
    assert settings.confidence_critical_threshold == 90
    assert settings.confidence_revision_threshold == 85
    assert settings.review_web_reviewer_identifier == "local-review-ui"
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
    monkeypatch.setenv("AJI_REVIEW_WEB_REVIEWER_IDENTIFIER", "local-operator")
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
    assert settings.review_web_reviewer_identifier == "local-operator"
    assert settings.public_allowed_host_list == ["jobs.example.test", "localhost"]
    assert settings.public_rate_limit_requests == 50


@pytest.mark.parametrize(
    ("setting", "value"),
    [("public_allowed_hosts", "*"), ("public_forwarded_allow_ips", "*")],
)
def test_production_settings_reject_unbounded_trust(setting, value) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql+psycopg://runtime@db/assam_jobs",
            **{setting: value},
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"database_url": DEFAULT_DEVELOPMENT_DATABASE_URL}, "AJI_DATABASE_URL"),
        (
            {
                "database_url": "postgresql+psycopg://runtime@db/assam_jobs",
                "debug": True,
            },
            "AJI_DEBUG",
        ),
    ],
)
def test_production_settings_fail_fast_on_unsafe_defaults(overrides, message) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, app_env="production", **overrides)


def test_production_settings_accept_explicit_safe_runtime_values() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://runtime@db/assam_jobs",
        public_allowed_hosts="jobs.example.gov.in",
        public_forwarded_allow_ips="172.16.0.0/12",
    )

    assert settings.app_env == "production"
    assert settings.debug is False
