from app.core.config import Settings


def test_settings_load_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "Assam Job Intelligence"
    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.confidence_standard_threshold == 80
    assert settings.confidence_critical_threshold == 90
    assert settings.confidence_revision_threshold == 85


def test_settings_load_environment(monkeypatch) -> None:
    monkeypatch.setenv("AJI_APP_ENV", "test")
    monkeypatch.setenv("AJI_DEBUG", "true")
    monkeypatch.setenv("AJI_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("AJI_CONFIDENCE_STANDARD_THRESHOLD", "75")
    monkeypatch.setenv("AJI_CONFIDENCE_CRITICAL_THRESHOLD", "88")
    monkeypatch.setenv("AJI_CONFIDENCE_REVISION_THRESHOLD", "82")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.debug is True
    assert settings.database_url == "sqlite+pysqlite:///:memory:"
    assert settings.confidence_standard_threshold == 75
    assert settings.confidence_critical_threshold == 88
    assert settings.confidence_revision_threshold == 82
