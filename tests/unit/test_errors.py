"""Deliberate failures carry the response they should produce."""

from __future__ import annotations

import pytest

from claim_agent.errors import (
    ClaimAgentError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    UpstreamError,
)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (NotFoundError, 404, "not_found"),
        (InvalidRequestError, 400, "invalid_request"),
        (ConflictError, 409, "conflict"),
        (UpstreamError, 502, "upstream_unavailable"),
    ],
)
def test_each_error_maps_to_its_response(
    error: type[ClaimAgentError], status: int, code: str
) -> None:
    raised = error("boom", details={"case_id": "CASE-1001"})

    assert raised.status_code == status
    assert raised.code == code
    assert raised.details == {"case_id": "CASE-1001"}
