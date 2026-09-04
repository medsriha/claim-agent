"""Investigating a claim over HTTP, and what the stream says while it happens.

Everything here goes through the real application: the real screen, the real
dependencies, the real route. Only two things are stood in for — ShipBob, which is
intercepted in this process, and the model, which answers from a script. So what these
tests observe is the wiring, which is the part unit tests cannot see.

The stream is the subject. A representative watching one has to be told what is
happening, told it in an order, and told *something* whatever goes wrong — a connection
that simply stops is the failure this whole shape exists to prevent (NFR-4).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
import respx
from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import AIMessage
from tests.fakes.model import scripted
from tests.fixtures.attachments import ATTACHMENTS_1001, ATTACHMENTS_1004, INVOICE_342578703
from tests.fixtures.shipbob import (
    CASE_1001,
    CASE_1004,
    CASE_NOT_FOUND_BODY,
    ORDER_1001,
    ORDER_1004,
    SHIPMENT_1001,
    SHIPMENT_1004,
)

from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.schemas import ClaimSplit
from claim_agent.api.deps import get_models

pytestmark = pytest.mark.integration


def read_stream(body: str) -> list[tuple[str, str]]:
    """Split a server-sent-event stream into the named messages it carried.

    Each message is a name and its one line of data, in the order they arrived. The
    order matters as much as the contents: a representative reads this top to bottom.
    """
    messages: list[tuple[str, str]] = []
    for block in body.split("\n\n"):
        lines = [line for line in block.splitlines() if line]
        if not lines:
            continue
        name = next((line[len("event: ") :] for line in lines if line.startswith("event: ")), "")
        data = next((line[len("data: ") :] for line in lines if line.startswith("data: ")), "")
        messages.append((name, data))
    return messages


def names(messages: list[tuple[str, str]]) -> list[str]:
    """Just the message names, for asserting on the shape of a stream."""
    return [name for name, _ in messages]


@pytest.fixture
def a_scripted_investigation(app: FastAPI) -> Iterator[None]:
    """Answer every model question from a script, so no key and no network are needed.

    The split comes back ambiguous on purpose. It is the shortest complete run there
    is — the claim is investigated, nothing is guessed, and no product-level pass
    happens — which makes it the right shape for testing the wiring rather than the
    judgement (FR-1a.4).
    """

    def scripted_models() -> tuple[object, StructuredModel]:
        """Both models, from a script, built only if the investigation asks for them."""
        return (
            scripted(AIMessage(content="I have read the claim.")),
            StructuredModel(
                scripted(
                    ClaimSplit(
                        is_ambiguous=True,
                        ambiguity="The photographs do not say which of the two products broke.",
                        reasoning="Two similar products, and nothing distinguishes them.",
                        confidence=0.3,
                    )
                ),
                max_attempts=1,
            ),
        )

    app.dependency_overrides[get_models] = lambda: scripted_models
    yield
    app.dependency_overrides.clear()


A_REMARK_IN_SEVERAL_LINES = (
    "Here is what I am weighing up:\n"
    "\n"
    "- The **box** is crushed.\n"
    "- The bottle inside looks intact.\n"
    "\n"
    "So I will look at the third photograph next."
)
"""A remark of the shape a model actually writes: a sentence, a list, a conclusion."""


@pytest.fixture
def an_investigation_that_writes_a_list(app: FastAPI) -> Iterator[None]:
    """Answer from a script whose remark runs to several lines, blank ones included."""

    def scripted_models() -> tuple[object, StructuredModel]:
        return (
            scripted(AIMessage(content=A_REMARK_IN_SEVERAL_LINES)),
            StructuredModel(
                scripted(
                    ClaimSplit(
                        is_ambiguous=True,
                        ambiguity="The photographs do not say which of the two products broke.",
                        reasoning="Two similar products, and nothing distinguishes them.",
                        confidence=0.3,
                    )
                ),
                max_attempts=1,
            ),
        )

    app.dependency_overrides[get_models] = lambda: scripted_models
    yield
    app.dependency_overrides.clear()


async def test_a_stopped_claim_is_explained_and_never_reaches_the_agent(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    """NFR-8, FR-0.4: an ineligible claim costs three cheap reads and no AI at all.

    CASE-1004 was filed 73 days after delivery. It carries four attachments, and the
    correct behaviour is to never look at any of them — which is why the images route is
    registered here and then asserted to have been left alone.
    """
    shipbob.get("/cases/CASE-1004").respond(200, json=CASE_1004)
    shipbob.get("/shipments/330936165").respond(200, json=SHIPMENT_1004)
    shipbob.get("/orders/322882110").respond(200, json=ORDER_1004)
    images = shipbob.get("/cases/CASE-1004/attachments").respond(200, json=ATTACHMENTS_1004)
    invoicing = shipbob.post("/invoices/generate").respond(200, json=INVOICE_342578703)

    response = await client.post("/cases/CASE-1004/investigate")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    messages = read_stream(response.text)
    assert names(messages) == ["progress", "result", "done"]
    assert "cannot be processed" in messages[0][1]
    assert "claim_too_old" in messages[1][1]
    # The whole point: its photographs were never touched, and no invoice was priced.
    assert images.call_count == 0
    assert invoicing.call_count == 0


async def test_a_case_shipbob_does_not_have_ends_the_stream_with_a_reason(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    """NFR-4: a stream that simply stops is the failure this shape exists to prevent.

    The stream has already opened by the time the read fails, so there is no status code
    left to change. The reason is sent as a message instead, and the stream still closes
    tidily rather than being dropped.
    """
    shipbob.get("/cases/CASE-9999").respond(404, json=CASE_NOT_FOUND_BODY)

    response = await client.post("/cases/CASE-9999/investigate")

    assert response.status_code == 200
    messages = read_stream(response.text)
    assert names(messages) == ["failed", "done"]
    assert "not_found" in messages[0][1]


async def test_an_investigation_says_what_it_is_doing_before_it_says_what_it_found(
    client: AsyncClient, shipbob: respx.Router, a_scripted_investigation: None
) -> None:
    """The reason this streams at all: the work is shown, not summarised afterwards.

    A screening message, then whatever the investigation says as it goes, then one
    result and a close. The result arrives last because a report read half-arrived is
    worse than one that arrives a moment later.
    """
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)
    shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)

    response = await client.post("/cases/CASE-1001/investigate")

    assert response.status_code == 200
    messages = read_stream(response.text)
    said = names(messages)

    assert said[0] == "progress"
    assert said[-2:] == ["result", "done"]
    assert said.count("result") == 1
    # More than one thing was said before the result, which is what makes this a
    # narration rather than a reply with extra steps.
    assert said.count("progress") > 1
    assert "passed the eligibility checks" in messages[0][1]


async def test_what_the_investigation_says_arrives_whole_and_in_one_message(
    client: AsyncClient, shipbob: respx.Router, an_investigation_that_writes_a_list: None
) -> None:
    """A remark reaches the browser as written, line breaks and all.

    Two things could go wrong here and neither may. A stream ends a message with a
    blank line, so a remark that contains one could be read as two half-messages; and
    a remark trimmed to keep it short would lose its ending, which is the part saying
    what the run decided to do next. Sending each message as data rather than as loose
    text is what prevents the first, and nothing trims it any more.
    """
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)
    shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)

    response = await client.post("/cases/CASE-1001/investigate")

    remarks = [
        json.loads(data)
        for name, data in read_stream(response.text)
        if name == "progress" and json.loads(data)["kind"] == "thinking"
    ]
    assert [remark["summary"] for remark in remarks] == [A_REMARK_IN_SEVERAL_LINES]


async def test_the_stream_carries_the_claim_split_and_says_what_was_unclear(
    client: AsyncClient, shipbob: respx.Router, a_scripted_investigation: None
) -> None:
    """FR-1a.4: an ambiguous split is handed over, and the stream says what is unclear.

    A representative can settle it in seconds if they are told what the difficulty was.
    Guessing a split is silent and expensive; this is neither.
    """
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)
    shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)

    response = await client.post("/cases/CASE-1001/investigate")

    result = next(data for name, data in read_stream(response.text) if name == "result")
    assert "which of the two products broke" in result
    # Nothing may be investigated while the split is unsettled, so there are no
    # per-product findings to report.
    assert '"lines":[]' in result.replace(" ", "")


async def test_a_claim_that_needs_a_model_and_has_no_key_is_told_so_on_the_stream(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    """NFR-6: being misconfigured is a handled state, and it is ours rather than ShipBob's.

    The message says a key is missing rather than blaming the provider, so nobody goes
    looking at a status page for a credential that was never set. It arrives on the
    stream because the screening has already been sent by then — the model is not built
    until a claim is actually going on.
    """
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)

    response = await client.post("/cases/CASE-1001/investigate")

    assert response.status_code == 200
    messages = read_stream(response.text)
    assert names(messages) == ["progress", "failed", "done"]
    assert "configuration_error" in messages[1][1]
    assert "ANTHROPIC_API_KEY" in messages[1][1]


async def test_a_stopped_claim_needs_no_model_and_so_needs_no_key(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    """NFR-8: an ineligible claim must not fail for want of a credential it never uses.

    There is no API key configured anywhere in these tests. CASE-1004 is turned away by
    the screen, so it never asks for a model and comes back with its explanation — which
    is only true because the model is built at the point of use rather than when the
    request arrives.
    """
    shipbob.get("/cases/CASE-1004").respond(200, json=CASE_1004)
    shipbob.get("/shipments/330936165").respond(200, json=SHIPMENT_1004)
    shipbob.get("/orders/322882110").respond(200, json=ORDER_1004)

    response = await client.post("/cases/CASE-1004/investigate")

    assert response.status_code == 200
    assert names(read_stream(response.text)) == ["progress", "result", "done"]
