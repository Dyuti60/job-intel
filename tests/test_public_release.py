from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import get_db
from app.public_main import create_public_app
from tests.test_master_api import _new_candidate_revision, _publish
from tests.test_public_recruitments_api import _published


@contextmanager
def _public_client(test_engine, **overrides) -> Generator[TestClient, None, None]:
    session_factory = sessionmaker(bind=test_engine, expire_on_commit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        public_allowed_hosts="testserver,public.example.test",
        **overrides,
    )
    application = create_public_app(settings)
    application.dependency_overrides[get_db] = override_get_db
    with TestClient(application) as public_client:
        yield public_client


def test_public_app_exposes_only_public_read_and_health_surfaces(test_engine) -> None:
    with _public_client(test_engine) as public_client:
        assert public_client.get("/jobs").status_code == 200
        assert public_client.get("/api/public/v1/recruitments").status_code == 200
        assert public_client.get("/healthz").json() == {"status": "ok"}
        assert public_client.get("/readyz").json() == {"status": "ok"}
        for private_path in (
            "/review",
            "/operations",
            "/api/v1/health",
            "/api/v1/recruitment-master",
            "/docs",
            "/openapi.json",
        ):
            assert public_client.get(private_path).status_code == 404
        assert public_client.post("/jobs").status_code == 405
        assert public_client.post("/api/public/v1/recruitments").status_code == 405


def test_public_security_headers_host_guard_and_hsts(test_engine) -> None:
    with _public_client(test_engine) as public_client:
        response = public_client.get("/jobs")
        assert response.headers["content-security-policy"].startswith("default-src 'none'")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "strict-transport-security" not in response.headers
        assert public_client.get("/jobs", headers={"host": "evil.example"}).status_code == 400

    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        public_allowed_hosts="public.example.test",
    )
    with TestClient(create_public_app(settings), base_url="https://public.example.test") as client:
        assert client.get("/healthz").headers["strict-transport-security"].startswith(
            "max-age=31536000"
        )


def test_public_etag_revalidates_against_current_master(
    client: TestClient, test_engine
) -> None:
    graph = _published(client, "RELEASE_ETAG", end="2026-10-20", vacancies=10)
    master_id = graph["publication"]["master"]["id"]
    with _public_client(test_engine) as public_client:
        first = public_client.get(f"/jobs/{master_id}")
        assert first.status_code == 200
        assert first.headers["cache-control"] == "public, max-age=60, must-revalidate"
        etag = first.headers["etag"]
        replay = public_client.get(f"/jobs/{master_id}", headers={"if-none-match": etag})
        assert replay.status_code == 304
        assert replay.content == b""

        newer = _new_candidate_revision(
            client,
            graph,
            "release-etag-v2",
            [
                {
                    "field_path": "application.end_date",
                    "value_type": "DATE",
                    "value": "2026-10-27",
                },
                {"field_path": "vacancies.total", "value_type": "INTEGER", "value": 10},
            ],
        )
        second_publication = _publish(client, newer["confidence"]["id"])
        assert second_publication.status_code == 201

        refreshed = public_client.get(f"/jobs/{master_id}", headers={"if-none-match": etag})
        assert refreshed.status_code == 200
        assert refreshed.headers["etag"] != etag
        assert "2026-10-27" in refreshed.text


def test_public_rate_limit_and_request_target_bound(test_engine) -> None:
    with _public_client(
        test_engine,
        public_rate_limit_requests=2,
        public_rate_limit_window_seconds=60,
        public_max_request_target_bytes=512,
    ) as public_client:
        assert public_client.get("/jobs").status_code == 200
        assert public_client.get("/jobs?q=assam").status_code == 200
        limited = public_client.get("/jobs?q=third")
        assert limited.status_code == 429
        assert limited.headers["retry-after"]
        assert limited.headers["cache-control"] == "no-store"
        assert public_client.get("/healthz").status_code == 200
        assert public_client.get(f"/static/public.css?padding={'x' * 600}").status_code == 414


def test_public_readiness_is_bounded_on_database_failure(test_engine) -> None:
    app = create_public_app(
        Settings(
            _env_file=None,
            database_url="sqlite+pysqlite:///:memory:",
            public_allowed_hosts="testserver",
        )
    )

    class BrokenSession:
        def execute(self, *_args, **_kwargs) -> None:
            raise SQLAlchemyError("database details must not escape")

    def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    with TestClient(app) as public_client:
        response = public_client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "database details" not in response.text


def test_release_artifacts_keep_public_runtime_bounded() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.public.yml").read_text(encoding="utf-8")
    ignore = Path(".dockerignore").read_text(encoding="utf-8")

    assert 'CMD [".venv/bin/python", "-m", "workers.public_server"]' in dockerfile
    assert "USER appuser" in dockerfile
    assert "HEALTHCHECK" in dockerfile and "/readyz" in dockerfile
    assert "read_only: true" in compose
    assert '127.0.0.1:${AJI_PUBLIC_BIND_PORT:-8001}:8000' in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert ".env" in ignore and "data" in ignore and "tests" in ignore
