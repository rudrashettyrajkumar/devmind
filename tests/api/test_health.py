from fastapi.testclient import TestClient

from devmind.core.config import Settings
from devmind.main import ApplicationFactory


def _client() -> TestClient:
    settings = Settings(anthropic_api_key="sk-ant-test")  # type: ignore[call-arg]
    app = ApplicationFactory(settings).create()
    return TestClient(app)


def test_health_returns_200() -> None:
    with _client() as client:
        response = client.get("/health")
    assert response.status_code == 200


def test_health_body_shape() -> None:
    with _client() as client:
        response = client.get("/health")
    body = response.json()
    assert body["status"] == "ok"
    assert body["sandbox_backend"] in {"docker", "subprocess"}
    assert body["database"] == "not_configured"
    assert body["provider_reachable"] is True
    assert "version" in body


def test_health_names_a_resolved_backend_never_auto() -> None:
    with _client() as client:
        response = client.get("/health")
    assert response.json()["sandbox_backend"] != "auto"
