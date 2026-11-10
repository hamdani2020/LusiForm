from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_200_without_auth() -> None:
    # No Authorization header is sent: health must not require auth.
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "authorization" not in response.request.headers


def test_health_ignores_invalid_credentials() -> None:
    response = TestClient(app).get("/api/health", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 200
