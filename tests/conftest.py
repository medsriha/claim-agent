from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from claim_agent.app import create_app
from claim_agent.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings for a test process — never reads the developer's `.env` values.

    The ShipBob address is a name that cannot resolve, so a request that escapes the
    mock fails loudly instead of reaching a real machine. It is also distinct from the
    address the test client uses, so the two are never confused for one another.
    The database goes to a throwaway directory, one per test.
    """
    return Settings(
        environment="test",
        log_level="WARNING",
        anthropic_api_key=None,
        shipbob_base_url="http://shipbob.test",
        database_path=tmp_path / "claims.db",
    )


@pytest.fixture
def shipbob(settings: Settings) -> Iterator[respx.Router]:
    """Stands in for the ShipBob API so the suite never touches the network.

    Routes are not required to be called: most tests care about one endpoint and
    register the others only to prove they were left alone (NFR-8).
    """
    with respx.mock(base_url=settings.shipbob_base_url, assert_all_called=False) as router:
        yield router


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """A freshly built application."""
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client bound to the app, no network involved."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
