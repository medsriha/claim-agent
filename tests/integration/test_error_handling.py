from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from claim_agent.errors import NotFoundError

pytestmark = pytest.mark.integration


@pytest.fixture
def failing_app(app: FastAPI) -> FastAPI:
    @app.get("/boom/expected")
    async def expected() -> None:
        raise NotFoundError("No such case.", details={"case_id": "CASE-9999"})

    @app.get("/boom/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("password=hunter2")

    return app


async def _get(app: FastAPI, path: str) -> tuple[int, dict[str, object]]:
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as http:
        response = await http.get(path)
    return response.status_code, response.json()


async def test_deliberate_error_uses_its_own_status_and_code(failing_app: FastAPI) -> None:
    status, body = await _get(failing_app, "/boom/expected")

    assert status == 404
    assert body["error"] == {
        "code": "not_found",
        "message": "No such case.",
        "details": {"case_id": "CASE-9999"},
    }


async def test_unexpected_error_does_not_leak_internals(failing_app: FastAPI) -> None:
    status, body = await _get(failing_app, "/boom/unexpected")

    assert status == 500
    assert "hunter2" not in str(body)
