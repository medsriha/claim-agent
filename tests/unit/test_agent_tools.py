"""The tools an investigation has — what each answers, and every way each fails.

Nothing here reaches the network and nothing here needs a key. ShipBob and the image
storage are both answered by a stand-in running in the same process, and the model
answers from a script the test writes beforehand.

Four of these tests are not about behaviour at all. They are the structural guarantee
FR-1.2 asks for, written down as something that fails the build: the investigation's
tool surface is exactly the eleven read and reasoning tools in FR-1.2, none is named for an
action that changes anything, nothing in the agent package can even reach the code that
sends and pays, and the one ShipBob client an investigation holds cannot write either.
An instruction telling a model not to send an email is worth nothing; a system with no
way to send one is worth everything.
"""

from __future__ import annotations

import ast
import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from tests.fakes.model import ScriptedModel, scripted
from tests.fixtures.attachments import (
    INVOICE_342578703,
    INVOICE_UNAVAILABLE_BODY,
    attachment_payload,
    attachments_payload,
)

import claim_agent.agent
from claim_agent.agent.budget import RunBudget
from claim_agent.agent.events import EventKind
from claim_agent.agent.events import EventStream as RunEvents
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.ledger import RunLedger, StepKind
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.schemas import ImageObservation
from claim_agent.agent.tools import (
    CHECK_CURRENCY,
    CHECK_DOCUMENT_TOTALS,
    CHECK_EVIDENCE_IS_ENOUGH,
    COMPARE_PRICES,
    COMPUTE_REIMBURSEMENT,
    GENERATE_INVOICE,
    INSPECT_IMAGE,
    LIST_ATTACHMENTS,
    MATCH_DAMAGED_PRODUCT,
    READ_CASE_FACTS,
    READ_REQUESTED_REMEDY,
    TOOL_NAMES,
    AmountCheck,
    AttachmentListing,
    ImageInspection,
    ShipmentInvoice,
    investigation_tools,
)
from claim_agent.domain.evidence import EvidenceKind, EvidenceState
from claim_agent.errors import UpstreamError
from claim_agent.policy import Policy
from claim_agent.settings import Settings
from claim_agent.shipbob.evidence_client import EvidenceClient

# The claim every test here works on: CASE-1001, whose shipment ShipBob prices as two
# products, $38.00 and $52.00. Using ShipBob's own sample keeps the invoice and the
# products in these tests the ones the requirements quote.
CASE_ID = "CASE-1001"
SHIPMENT_ID = "342578703"
USER_ID = "334430"

SHIPBOB = "http://shipbob.test"
IMAGES = "https://storage.images.test/case-1001"

FIRST_IMAGE = "ATT-CASE-1001-01"
SECOND_IMAGE = "ATT-CASE-1001-02"

# The first eight bytes are the marker every PNG file starts with; the rest stands in for
# the picture, and is never looked at by anything under test.
PNG_BYTES = b"\x89PNG\r\n\x1a\npretend pixels"

# Two images on the claim, with addresses on a host the fetcher is told it may use. Their
# file names are ShipBob's kind of unhelpful — deliberately, since nothing may decide
# anything from one (FR-1.4).
CLAIM_IMAGES = attachments_payload(
    attachment_payload(attachment_id=FIRST_IMAGE, file_name="Inv.png", url=f"{IMAGES}/01.png"),
    attachment_payload(attachment_id=SECOND_IMAGE, file_name="329233.png", url=f"{IMAGES}/02.png"),
)

# Anything that reads as an amount of money: a figure with cents after it. Used to show
# that the arithmetic tool never hands the model one (FR-1.21).
MONEY = re.compile(r"\d+\.\d{2}")

# Words that would name a tool able to change something at ShipBob. "reimburse" is
# deliberately absent: `compute_reimbursement` works out whether an amount exists and
# pays nobody, so it would fail a plain substring test while being exactly the arithmetic
# FR-1.21 asks for. The leading verb is checked instead, which does catch a
# `reimburse_merchant`, and the exact list of names below is what really pins the surface
# down.
WRITE_VERBS = frozenset(
    {"send", "email", "submit", "pay", "post", "create", "update", "delete", "reimburse"}
)
UNMISTAKABLY_WRITING = ("send", "email", "submit", "pay", "delete")


def build_settings() -> Settings:
    """Settings for a test process, with the attachment bounds spelled out.

    The image host is a name that only the stand-in answers to, and caching is off, so
    one test can never see another test's downloads.
    """
    return Settings(
        environment="test",
        log_level="WARNING",
        anthropic_api_key=None,
        shipbob_base_url=SHIPBOB,
        attachment_allowed_hosts=("images.test",),
        attachment_cache_dir=None,
        attachment_timeout_seconds=1.0,
    )


@dataclass
class Run:
    """One investigation's tools, and the things they write to, kept for a test to read.

    A test drives the tools and then asks this what the run spent, what it remembered,
    what it recorded and what it said out loud.
    """

    tools: dict[str, BaseTool]
    model: ScriptedModel
    cache: ObservationCache
    budget: RunBudget
    ledger: RunLedger
    events: RunEvents


@pytest.fixture
def api() -> Iterator[respx.Router]:
    """Stands in for ShipBob and for the image storage, so nothing reaches the network.

    Routes are not required to be called: several tests register one only to show it was
    left alone.
    """
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
async def shipbob_http() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client aimed at the stand-in ShipBob, built the way the application builds one."""
    async with httpx.AsyncClient(base_url=SHIPBOB, timeout=1.0) as client:
        yield client


@pytest.fixture
async def images_http() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client for fetching images, which carry their whole address."""
    async with httpx.AsyncClient() as client:
        yield client


def build_run(
    shipbob_http: httpx.AsyncClient,
    images_http: httpx.AsyncClient,
    *,
    model: ScriptedModel | None = None,
    images_allowed: int = 20,
    shipment_id: str | None = SHIPMENT_ID,
    user_id: str | None = USER_ID,
) -> Run:
    """Assemble one run's tools, the way the investigation will assemble them.

    Retrying is off on both clients: a test that is not about retrying should not sit
    through the waits between attempts.
    """
    chat = model if model is not None else scripted()
    settings = build_settings()
    cache = ObservationCache()
    budget = RunBudget(Policy(max_image_analyses_per_run=images_allowed))
    ledger = RunLedger()
    events = RunEvents()
    tools = investigation_tools(
        case_id=CASE_ID,
        shipment_id=shipment_id,
        user_id=user_id,
        evidence=EvidenceClient(shipbob_http, max_attempts=1),
        fetcher=ImageFetcher(images_http, settings),
        model=StructuredModel(chat, max_attempts=1),
        cache=cache,
        budget=budget,
        ledger=ledger,
        events=events,
        policy=Policy(),
    )
    return Run(
        tools={tool.name: tool for tool in tools},
        model=chat,
        cache=cache,
        budget=budget,
        ledger=ledger,
        events=events,
    )


async def call(run: Run, name: str, **arguments: object) -> ToolMessage:
    """Make one tool call the way the investigation makes one, and take back the answer.

    The call is made as a tool call rather than as a plain function call, so the test
    gets both halves of the answer: the sentence the model reads, and the outcome the run
    keeps beside it.
    """
    answer = await run.tools[name].ainvoke(
        {"name": name, "args": arguments, "id": f"call-{name}", "type": "tool_call"}
    )
    assert isinstance(answer, ToolMessage)
    return answer


def said(message: ToolMessage) -> str:
    """Everything the model was told by one tool call."""
    return str(message.content)


def a_photo_of_damage(**overrides: object) -> ImageObservation:
    """What the model says when it has looked at a clear photograph of a broken product."""
    fields: dict[str, object] = {
        "shows": "a shampoo bottle with its cap snapped off",
        "kind": EvidenceKind.DAMAGED_PRODUCT_PHOTO,
        "is_legible": True,
        "problem": None,
        "confidence": 0.9,
    }
    fields.update(overrides)
    return ImageObservation.model_validate(fields)


def serve_the_claim(api: respx.Router, *, images: dict[str, object] | None = None) -> None:
    """Answer every read this claim can make, so a test only registers what it changes."""
    api.get(f"{SHIPBOB}/cases/{CASE_ID}/attachments").respond(
        200, json=images if images is not None else CLAIM_IMAGES
    )
    api.post(f"{SHIPBOB}/invoices/generate").respond(200, json=INVOICE_342578703)
    api.get(f"{IMAGES}/01.png").respond(200, content=PNG_BYTES)
    api.get(f"{IMAGES}/02.png").respond(200, content=PNG_BYTES)


# --- The structural guarantee (FR-1.2) --------------------------------------


def test_the_investigation_is_given_exactly_these_read_and_reasoning_tools(
    shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.2: every tool the agent holds only reads or works something out.

    Asserted as an exact set rather than a length, so adding a tool of any kind fails
    here and has to be argued for against the requirement. **The count is not the
    guarantee and never was** — this list grew from four when reading ShipBob's sample
    data turned up four ways a recommendation could be quietly wrong. What must not
    change is that none of them writes anything, which the two tests below check by
    name and by import graph.
    """
    run = build_run(shipbob_http, images_http)

    assert set(run.tools) == {
        LIST_ATTACHMENTS,
        INSPECT_IMAGE,
        GENERATE_INVOICE,
        COMPUTE_REIMBURSEMENT,
        CHECK_CURRENCY,
        CHECK_DOCUMENT_TOTALS,
        READ_CASE_FACTS,
        COMPARE_PRICES,
        CHECK_EVIDENCE_IS_ENOUGH,
        MATCH_DAMAGED_PRODUCT,
        READ_REQUESTED_REMEDY,
    }
    assert set(run.tools) == set(TOOL_NAMES)


def test_no_tool_is_named_for_something_that_changes_anything(
    shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.2: the agent has no ability to send an email or pay anybody.

    A name is not a guarantee on its own — the guarantee is that the tools above are
    the whole surface — but a tool called `send_email` appearing here would be the first
    sign that somebody had reached for one.
    """
    run = build_run(shipbob_http, images_http)

    for name in run.tools:
        assert name.split("_")[0] not in WRITE_VERBS
        for word in UNMISTAKABLY_WRITING:
            assert word not in name


def test_nothing_in_the_agent_can_reach_the_code_that_sends_and_pays() -> None:
    """FR-1.2: sending and paying are unreachable from the agent, structurally.

    Every module the investigation is built from is read and its imports are checked. The
    package that sends an email and submits a reimbursement exists and is empty; the day
    it is filled in, this test is what stops the investigation being handed it.
    """
    package = Path(str(claim_agent.agent.__file__)).parent
    modules = sorted(package.glob("*.py"))
    assert modules, "no agent modules were found to check"

    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("claim_agent.execution"), module.name
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                assert not node.module.startswith("claim_agent.execution"), module.name


def test_the_only_shipbob_client_the_investigation_holds_can_only_read() -> None:
    """FR-1.2: the agent's ShipBob client lists attachments and prices a shipment, and nothing else.

    Checked on the class rather than on an instance, so a write method added later is
    caught whether or not any tool happens to call it.
    """
    methods = [name for name in dir(EvidenceClient) if not name.startswith("_")]

    assert set(methods) == {"list_attachments", "generate_invoice", "aclose"}
    for name in methods:
        assert name.split("_")[0] not in WRITE_VERBS
        for word in UNMISTAKABLY_WRITING:
            assert word not in name


# --- Listing the images (FR-1.4, FR-1.6) ------------------------------------


async def test_listing_the_images_gives_back_their_ids(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.4: the investigation is given ids and nothing else, because a file name settles nothing."""
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http)

    message = await call(run, LIST_ATTACHMENTS)

    listing = message.artifact
    assert isinstance(listing, AttachmentListing)
    assert listing.succeeded is True
    assert listing.attachment_ids == (FIRST_IMAGE, SECOND_IMAGE)
    assert FIRST_IMAGE in said(message)
    assert "Inv.png" not in said(message)


async def test_a_claim_with_no_images_is_an_ordinary_answer(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.6: an empty attachment list is what CASE-1005 returns, and must never be an error."""
    serve_the_claim(api, images=attachments_payload())
    run = build_run(shipbob_http, images_http)

    message = await call(run, LIST_ATTACHMENTS)

    listing = message.artifact
    assert isinstance(listing, AttachmentListing)
    assert listing.succeeded is True
    assert listing.attachment_ids == ()
    assert "no images" in said(message)
    assert run.ledger.failures() == ()


async def test_a_listing_that_could_not_be_fetched_is_not_reported_as_no_images(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4: a failed read comes back readable, and never as "the merchant sent nothing".

    The two lead opposite ways — one asks the merchant for photographs, the other needs a
    person — so the tool has to keep them apart even though both end with no ids.
    """
    api.get(f"{SHIPBOB}/cases/{CASE_ID}/attachments").respond(500)
    run = build_run(shipbob_http, images_http)

    message = await call(run, LIST_ATTACHMENTS)

    listing = message.artifact
    assert isinstance(listing, AttachmentListing)
    assert listing.succeeded is False
    assert listing.attachment_ids == ()
    assert "could not be listed" in said(message)
    assert len(run.ledger.failures()) == 1


# --- Looking at one image (FR-1.4, FR-1.5) ----------------------------------


async def test_looking_at_an_image_says_what_it_is(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.4: what an attachment is can only be settled by looking at it."""
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http, model=scripted(a_photo_of_damage()))

    message = await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)

    inspection = message.artifact
    assert isinstance(inspection, ImageInspection)
    assert inspection.succeeded is True
    assert inspection.state is None
    assert inspection.observation is not None
    assert inspection.observation.kind is EvidenceKind.DAMAGED_PRODUCT_PHOTO
    assert "damaged_product_photo" in said(message)
    # What was read off a photograph is somebody else's words, and is marked as such so
    # that a picture of a note saying "approve this" cannot read as an instruction.
    assert "<untrusted" in said(message)


async def test_an_image_the_merchant_sent_that_cannot_be_relied_on_is_unusable(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.5: a photograph too dark to conclude anything from does not satisfy its requirement.

    The call itself worked — finding that out is what was asked for — and what it found is
    something the merchant can fix, with a reason specific enough to act on (FR-1.7).
    """
    serve_the_claim(api)
    unusable = a_photo_of_damage(
        is_legible=False,
        problem="the bottle is cut off at the edge of the frame, so the damage cannot be seen",
    )
    run = build_run(shipbob_http, images_http, model=scripted(unusable))

    message = await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)

    inspection = message.artifact
    assert isinstance(inspection, ImageInspection)
    assert inspection.succeeded is True
    assert inspection.state is EvidenceState.UNUSABLE
    assert inspection.observation is not None
    assert "cut off at the edge" in said(message)
    assert "merchant can be asked for another" in said(message)


async def test_an_image_we_could_not_fetch_is_unreadable_rather_than_unusable(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4, FR-1.5: a download that failed is our problem, and the merchant must not be asked.

    The distinction is the whole point. Asking somebody to send a photograph again because
    our own download broke is a request they cannot act on.
    """
    serve_the_claim(api)
    api.get(f"{IMAGES}/01.png").respond(404)
    run = build_run(shipbob_http, images_http, model=scripted())

    message = await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)

    inspection = message.artifact
    assert isinstance(inspection, ImageInspection)
    assert inspection.succeeded is False
    assert inspection.state is EvidenceState.UNREADABLE
    assert inspection.observation is None
    assert "not the merchant's" in said(message)
    assert len(run.ledger.failures()) == 1


async def test_a_model_that_will_not_answer_leaves_the_image_unreadable(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4: a model failure ends in a result the run can act on, not in an exception."""
    serve_the_claim(api)
    run = build_run(
        shipbob_http,
        images_http,
        model=scripted(UpstreamError("The model provider could not be reached.")),
    )

    message = await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)

    inspection = message.artifact
    assert isinstance(inspection, ImageInspection)
    assert inspection.succeeded is False
    assert inspection.state is EvidenceState.UNREADABLE
    # The attempt is not remembered, so a moment of trouble does not become this claim's
    # permanent answer about the image.
    assert run.cache.keys() == (f"attachments:{CASE_ID}",)


async def test_an_id_that_is_on_no_image_comes_back_as_something_to_correct(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4: the model naming an id this claim does not have is answered, not raised.

    It is neither our failure nor the merchant's, so no evidence state is recorded — the
    model is simply told which ids exist and can try again.
    """
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http)

    message = await call(run, INSPECT_IMAGE, attachment_id="ATT-CASE-9999-99")

    inspection = message.artifact
    assert isinstance(inspection, ImageInspection)
    assert inspection.succeeded is False
    assert inspection.state is None
    assert "no image with the id" in said(message)
    assert run.budget.snapshot().image_analyses_used == 0


# --- Never paying twice for the same look (NFR-8) ---------------------------


async def test_the_same_image_and_question_is_only_looked_at_once(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-8: image analysis is not repeated for the same attachment within a case.

    The model is asked once and the second call is handed the first call's answer. The
    memo counts the two upstream reads it also holds — the attachment listing and, where a
    test asks for it, the invoice — so the count is compared against what those come to.
    """
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http, model=scripted(a_photo_of_damage()))

    first = await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)
    second = await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)

    assert said(first) == said(second)
    assert len(run.model.asked) == 1
    assert run.budget.snapshot().image_analyses_used == 1
    # One listing and one look at an image. A second look would make it three.
    assert run.cache.computed_count == 2


async def test_a_different_question_about_the_same_image_is_looked_at_again(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-8: the memo remembers an answer to a question, not a fact about a file.

    Two questions can have different answers, so they must never share a memo — the saving
    is not worth handing back an answer to something nobody asked.
    """
    serve_the_claim(api)
    run = build_run(
        shipbob_http,
        images_http,
        model=scripted(a_photo_of_damage(), a_photo_of_damage(shows="the box is crushed")),
    )

    await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)
    await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE, question="is the box crushed?")

    assert len(run.model.asked) == 2
    assert run.budget.snapshot().image_analyses_used == 2


async def test_a_run_that_has_looked_at_its_last_image_is_told_so(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-8, FR-1.3: the image allowance is a ceiling a generous step budget cannot lift.

    Running out is an answer the investigation can act on — draw a conclusion from what
    you have — and never an exception, so the run still reaches a recommendation (FR-1.16).
    """
    serve_the_claim(api)
    run = build_run(
        shipbob_http, images_http, model=scripted(a_photo_of_damage()), images_allowed=1
    )

    await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)
    message = await call(run, INSPECT_IMAGE, attachment_id=SECOND_IMAGE)

    inspection = message.artifact
    assert isinstance(inspection, ImageInspection)
    assert inspection.succeeded is False
    assert inspection.observation is None
    assert "as many images as it is allowed" in said(message)
    assert len(run.model.asked) == 1


async def test_an_image_already_looked_at_is_still_answered_once_the_allowance_is_gone(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-8: an answer this claim already holds costs nothing, so the allowance does not gate it."""
    serve_the_claim(api)
    run = build_run(
        shipbob_http, images_http, model=scripted(a_photo_of_damage()), images_allowed=1
    )

    await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)
    assert run.budget.has_image_analysis_left() is False

    message = await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)

    inspection = message.artifact
    assert isinstance(inspection, ImageInspection)
    assert inspection.succeeded is True
    assert inspection.observation is not None


# --- Pricing the shipment (FR-1.18) -----------------------------------------


async def test_generating_an_invoice_gives_back_the_priced_lines(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.18: the invoice is what a recommended amount is priced from, so the run can read it.

    Prices are shown to the model on purpose, the same way the prompts show the order's
    prices: it cannot refuse to guess between two similar products without seeing that
    they cost different amounts (FR-1.13).
    """
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http)

    message = await call(run, GENERATE_INVOICE)

    invoice = message.artifact
    assert isinstance(invoice, ShipmentInvoice)
    assert invoice.succeeded is True
    assert invoice.invoice_id == "INV-342578703"
    assert [line.name for line in invoice.line_items] == [
        "Additional Collagen Ampoule Duo",
        "Liposomal Tripeptide Collagen",
    ]
    assert invoice.line_items[1].unit_price == Decimal("52.00")
    assert "52.00" in said(message)


async def test_a_shipment_shipbob_will_not_price_comes_back_as_an_answer(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.18, NFR-4: a 422 invoice_unavailable is a settled answer the run carries on from.

    It is not an outage and not a crash. The investigation still has to reach a
    recommendation, and it can only do that if it is told plainly that there is no invoice.
    """
    serve_the_claim(api)
    api.post(f"{SHIPBOB}/invoices/generate").respond(422, json=INVOICE_UNAVAILABLE_BODY)
    run = build_run(shipbob_http, images_http)

    message = await call(run, GENERATE_INVOICE)

    invoice = message.artifact
    assert isinstance(invoice, ShipmentInvoice)
    assert invoice.succeeded is False
    assert invoice.invoice_id is None
    assert invoice.line_items == ()
    assert "could not be priced" in said(message)


async def test_a_claim_with_no_shipment_says_so_without_asking_shipbob(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4: a claim that names no shipment is answered from what we already know."""
    serve_the_claim(api)
    priced = api.post(f"{SHIPBOB}/invoices/generate")
    run = build_run(shipbob_http, images_http, shipment_id=None)

    message = await call(run, GENERATE_INVOICE)

    invoice = message.artifact
    assert isinstance(invoice, ShipmentInvoice)
    assert invoice.succeeded is False
    assert "does not say which shipment" in said(message)
    assert priced.call_count == 0


# --- Working out whether an amount exists (FR-1.21) -------------------------


async def test_the_amount_check_never_tells_the_model_what_the_figure_is(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.21, FR-1.20: the tool checks the investigation's own figure against the cap.

    The model decides the amount now, so this shows figures where it once withheld them —
    what the products cost, what was proposed, and what it would come to. Withholding one
    here would protect nothing when the model produced it.

    The guarantee that remains is at the other end and is asserted below: the sentence
    tells the run to leave the amount out of the email so only the capped figure is added.
    """
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http)

    message = await call(
        run,
        COMPUTE_REIMBURSEMENT,
        damaged_items=[
            {"product_name": "Liposomal Tripeptide Collagen", "quantity": 1, "sku": "COLLAGEN1"}
        ],
        proposed_amount_usd="40.00",
    )

    check = message.artifact
    assert isinstance(check, AmountCheck)
    assert check.succeeded is True
    assert check.priced_products == ("Liposomal Tripeptide Collagen",)
    assert check.priced_from == "INV-342578703"
    assert check.proposed_usd == "40.00"
    assert check.recommended_usd == "40.00"
    assert check.items_total_usd == "52.00"
    assert check.capped is False
    # The one rule about money that did not change with FR-1.21.
    assert "Do not write an amount or placeholder in the email" in said(message)


async def test_the_amount_check_says_when_a_figure_is_over_the_cap(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.20: the cap is the only limit on the figure, so the run can check it first.

    Told what it would be brought down to rather than simply refused, so the run can decide
    whether it still wants to recommend paying at all.
    """
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http)

    message = await call(
        run,
        COMPUTE_REIMBURSEMENT,
        damaged_items=[{"product_name": "Liposomal Tripeptide Collagen", "quantity": 1}],
        proposed_amount_usd="250.00",
    )

    check = message.artifact
    assert isinstance(check, AmountCheck)
    assert check.capped is True
    assert check.proposed_usd == "250.00"
    assert check.recommended_usd == "100.00"
    assert "brought down" in said(message)


async def test_a_figure_that_is_not_money_is_refused_and_never_interpreted(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.21, NFR-4: a payout somebody had to guess at is worse than no payout.

    Told back plainly so the run can write it properly on its next turn, rather than a
    currency sign being quietly stripped off and a figure paid that nobody typed.
    """
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http)

    message = await call(
        run,
        COMPUTE_REIMBURSEMENT,
        damaged_items=[{"product_name": "Liposomal Tripeptide Collagen", "quantity": 1}],
        proposed_amount_usd="$40",
    )

    check = message.artifact
    assert isinstance(check, AmountCheck)
    assert check.succeeded is False
    assert "written as money" in said(message)


async def test_the_amount_check_refuses_to_price_a_product_it_cannot_match(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.13: a product on no invoice line is not guessed at, whatever figure was named."""
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http)

    message = await call(
        run,
        COMPUTE_REIMBURSEMENT,
        damaged_items=[{"product_name": "A bottle of something else", "quantity": 1}],
        proposed_amount_usd="20.00",
    )

    check = message.artifact
    assert isinstance(check, AmountCheck)
    assert check.priced_products == ()
    assert "could be found on invoice" in said(message)


async def test_the_amount_check_says_when_nothing_has_been_established_as_damaged(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.21: no damaged products means nothing to check, and ShipBob is not asked."""
    serve_the_claim(api)
    priced = api.post(f"{SHIPBOB}/invoices/generate")
    run = build_run(shipbob_http, images_http)

    message = await call(run, COMPUTE_REIMBURSEMENT, damaged_items=[], proposed_amount_usd="20.00")

    check = message.artifact
    assert isinstance(check, AmountCheck)
    assert "nothing to check an amount against" in said(message)
    assert priced.call_count == 0


async def test_an_amount_cannot_be_checked_when_the_shipment_will_not_price(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4: no invoice means no comparison, said plainly rather than raised or guessed at."""
    serve_the_claim(api)
    api.post(f"{SHIPBOB}/invoices/generate").respond(422, json=INVOICE_UNAVAILABLE_BODY)
    run = build_run(shipbob_http, images_http)

    message = await call(
        run,
        COMPUTE_REIMBURSEMENT,
        damaged_items=[{"product_name": "Liposomal Tripeptide Collagen", "quantity": 1}],
        proposed_amount_usd="20.00",
    )

    check = message.artifact
    assert isinstance(check, AmountCheck)
    assert check.succeeded is False
    assert "could not be priced" in said(message)


# --- Writing every call down (FR-1.1, NFR-3, NFR-5) -------------------------


async def test_every_tool_call_is_written_into_the_run_record(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-3, NFR-5: a representative can see what the run did without reading a log.

    The record names the thing each step was about, so she can look at the same image the
    system looked at (FR-2.2).
    """
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http, model=scripted(a_photo_of_damage()))

    await call(run, LIST_ATTACHMENTS)
    await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)
    await call(run, GENERATE_INVOICE)

    entries = run.ledger.entries()
    assert [entry.name for entry in entries] == [
        LIST_ATTACHMENTS,
        INSPECT_IMAGE,
        GENERATE_INVOICE,
    ]
    assert [entry.sequence for entry in entries] == [1, 2, 3]
    assert all(entry.kind is StepKind.TOOL_CALL for entry in entries)
    assert all(entry.succeeded for entry in entries)
    assert [entry.reference for entry in entries] == [CASE_ID, FIRST_IMAGE, SHIPMENT_ID]


async def test_a_tool_call_that_failed_stays_in_the_record(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-3, NFR-4: leaving a failure out would hide why clarification is needed."""
    serve_the_claim(api)
    api.get(f"{IMAGES}/01.png").respond(500)
    run = build_run(shipbob_http, images_http)

    await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)

    failed = run.ledger.failures()
    assert len(failed) == 1
    assert failed[0].name == INSPECT_IMAGE
    assert failed[0].reference == FIRST_IMAGE
    assert "could not be read" in failed[0].observed


async def test_every_tool_call_is_announced_while_the_run_is_still_working(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.1: a tool being called is the investigation choosing what to look at next.

    That choosing is the reason this is an agent rather than a fixed sequence, and it is
    the thing worth putting in front of somebody watching.
    """
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http, model=scripted(a_photo_of_damage()))

    await call(run, LIST_ATTACHMENTS)
    await call(run, INSPECT_IMAGE, attachment_id=FIRST_IMAGE)

    events = run.events.events()
    assert [event.kind for event in events] == [EventKind.TOOL_CALLED, EventKind.TOOL_CALLED]
    assert [event.detail["tool"] for event in events] == [LIST_ATTACHMENTS, INSPECT_IMAGE]
    assert events[1].detail["reference"] == FIRST_IMAGE


async def test_a_failed_call_is_announced_as_a_failure(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4: somebody watching sees that a step went wrong, rather than seeing nothing."""
    api.get(f"{SHIPBOB}/cases/{CASE_ID}/attachments").respond(500)
    run = build_run(shipbob_http, images_http)

    await call(run, LIST_ATTACHMENTS)

    announced = run.events.events()
    assert len(announced) == 1
    assert announced[0].detail["succeeded"] == "no"
    assert "could not be listed" in announced[0].summary


async def test_a_call_whose_arguments_do_not_fit_is_answered_rather_than_raised(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4: a model's malformed call is something the run recovers from, not a stopped run.

    The tool library checks a call before our code runs, so this failure never reaches the
    record — the run sees an error result and the model is told to try again.
    """
    serve_the_claim(api)
    run = build_run(shipbob_http, images_http)

    message = await call(run, INSPECT_IMAGE)

    assert message.status == "error"
    assert "did not fit this tool's arguments" in said(message)
