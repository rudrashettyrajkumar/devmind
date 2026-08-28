from fastapi import FastAPI
from fastapi.testclient import TestClient

from devmind.api.errors import ErrorHandlerRegistrar
from devmind.exceptions import ApprovalRequiredError, InvalidStateTransitionError


def _app_raising(exc: Exception) -> FastAPI:
    app = FastAPI()
    ErrorHandlerRegistrar().register(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return app


def test_devmind_error_maps_to_its_http_status() -> None:
    app = _app_raising(ApprovalRequiredError("session 123 is not approved"))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.status_code == 403


def test_response_body_is_rfc7807_shaped() -> None:
    app = _app_raising(InvalidStateTransitionError("cannot move from CREATED to PR_OPENED"))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    body = response.json()
    assert body["status"] == 409
    assert body["title"] == "InvalidStateTransitionError"
    assert body["detail"] == "cannot move from CREATED to PR_OPENED"
    assert body["type"] == "/errors/invalid-state-transition-error"
    assert body["instance"] == "/boom"


def test_details_included_when_present() -> None:
    app = _app_raising(ApprovalRequiredError("nope", details={"session_id": "abc"}))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.json()["details"] == {"session_id": "abc"}


def test_details_omitted_when_empty() -> None:
    app = _app_raising(ApprovalRequiredError("nope"))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert "details" not in response.json()
