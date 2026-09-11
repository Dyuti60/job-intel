from sqlalchemy import text

from app.db.session import create_db_engine


def test_database_engine_can_connect() -> None:
    engine = create_db_engine("sqlite+pysqlite:///:memory:")

    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        engine.dispose()


def test_database_engine_preserves_configuration() -> None:
    engine = create_db_engine("sqlite+pysqlite:///:memory:")

    try:
        assert engine.pool._pre_ping is True
        assert engine.url.drivername == "sqlite+pysqlite"
    finally:
        engine.dispose()
