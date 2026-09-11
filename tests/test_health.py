from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_application_metadata() -> None:
    app = create_app()

    assert app.title == "Assam Job Intelligence"
    assert app.version == "0.1.0"
