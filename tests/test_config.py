from app.core.config import Settings


def test_settings_load_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "Assam Job Intelligence"
    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_settings_load_environment(monkeypatch) -> None:
    monkeypatch.setenv("AJI_APP_ENV", "test")
    monkeypatch.setenv("AJI_DEBUG", "true")
    monkeypatch.setenv("AJI_DATABASE_URL", "sqlite+pysqlite:///:memory:")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.debug is True
    assert settings.database_url == "sqlite+pysqlite:///:memory:"
