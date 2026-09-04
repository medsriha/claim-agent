"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from claim_agent.app import create_app
from claim_agent.settings import Settings


@pytest.fixture
def settings() -> Settings:
    """Settings for a test process — never reads the developer's `.env` values."""
    return Settings(environment="test", log_level="WARNING", anthropic_api_key=None)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """A freshly built application."""
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client bound to the app, no network involved."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
