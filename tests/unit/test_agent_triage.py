"""Layer 1a: working out which products a claim is for, and settling shared evidence.

Nothing here reaches the network and nothing here needs a key. ShipBob and the image
storage are both answered by a stand-in running in the same process, and the model
answers from a script the test writes beforehand. That is also what makes these tests
about the triage rather than about the model: the answers are fixed, so what is left
to observe is what the triage does with them.

The attachment listings are ShipBob's own, from `tests/fixtures/attachments.py`, so a
test here is written against the images a real claim actually carries — including
CASE-1005, which has none at all.

**The script has to be read as one queue.** The same scripted model answers the
pass's turns *and* the questions about images, in the order they are asked: a turn
that asks to look at two images spends three replies — the turn itself, then one
answer per image.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from langchain_core.exceptions import ModelConnectionError
from langchain_core.messages import AIMessage
from tests.fakes.model import ScriptedModel
from tests.fixtures.attachments import (
    ATTACHMENTS_1001,
    ATTACHMENTS_1002,
    ATTACHMENTS_1005,
    INVOICE_342578703,
)
from tests.fixtures.shipbob import (
    CASE_1001,
    CASE_1002,
    CASE_1005,
    ORDER_1001,
    ORDER_1002,
    ORDER_1005,
    SHIPMENT_1001,
    order_line_item,
    order_payload,
)

from claim_agent.agent.budget import RunBudget
from claim_agent.agent.events import EventKind, EventStream, RunEvent
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.ledger import RunLedger
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.schemas import ClaimedProductProposal, ClaimSplit, ImageObservation
from claim_agent.agent.triage import ClaimTriage, triage_claim
from claim_agent.domain.claim_line import MatchOutcome
from claim_agent.domain.evidence import SHARED_EVIDENCE, EvidenceKind, EvidenceState
from claim_agent.domain.models import Case, Order, Shipment
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.settings import Settings
from claim_agent.shipbob.evidence_client import EvidenceClient

SHIPBOB = "http://shipbob.test"

# The host ShipBob really serves its sample images from. Every attachment address in
# the fixtures points here, so this is the one host the fetcher is told it may use.
IMAGE_HOST = "sa032101pubdevuc.blob.core.windows.net"

# The first eight bytes are the marker every PNG file starts with; the rest stands in
# for the picture, and is never looked at by anything under test.
PNG_BYTES = b"\x89PNG\r\n\x1a\npretend pixels"

# CASE-1001's four images. Their names say nothing about what they hold, which is why
# a test may only refer to them by id (FR-1.4).
FIRST_IMAGE = "ATT-CASE-1001-01"
SECOND_IMAGE = "ATT-CASE-1001-02"
THIRD_IMAGE = "ATT-CASE-1001-03"
FOURTH_IMAGE = "ATT-CASE-1001-04"

# The two products on CASE-1001's order, written exactly as the order writes them.
AMPOULE = "Additional Collagen Ampoule Duo"
COLLAGEN = "Liposomal Tripeptide Collagen"


# --- Building a claim to triage ---------------------------------------------


def build_settings() -> Settings:
    """Settings for a test process, with the attachment bounds spelled out.

    Caching is off so that one test can never see another test's downloads.
    """
    return Settings(
        environment="test",
        log_level="WARNING",
        anthropic_api_key=None,
        shipbob_base_url=SHIPBOB,
        attachment_allowed_hosts=(IMAGE_HOST,),
        attachment_cache_dir=None,
        attachment_timeout_seconds=1.0,
    )


def a_record(
    case: dict[str, object] = CASE_1001,
    order: dict[str, object] | None = ORDER_1001,
    shipment: dict[str, object] | None = SHIPMENT_1001,
) -> CaseRecord:
    """What the pre-flight screen read about a claim — the claim, its parcel, its order."""
    return CaseRecord(
        case=Case.model_validate(case),
        shipment=None if shipment is None else Shipment.model_validate(shipment),
        order=None if order is None else Order.model_validate(order),
    )


def a_context() -> ClaimContext:
    """The facts the deterministic screen worked out before any of this ran (FR-0.5)."""
    return ClaimContext(
        order_value_usd=Decimal("90.00"),
        is_high_value=False,
        days_since_delivery=8,
        delivered_date=datetime(2026, 2, 11, 11, 36, tzinfo=UTC),
    )


@dataclass
class Run:
    """One triage and the things it wrote to, kept for a test to read afterwards."""

    triage: ClaimTriage
    model: ScriptedModel
    cache: ObservationCache
    budget: RunBudget
    events: EventStream


@pytest.fixture
def api() -> Iterator[respx.Router]:
    """Stands in for ShipBob and for the image storage, so nothing reaches the network.

    Routes are not required to be called: several tests register one only to show the
    investigation left it alone.
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


def serve(
    api: respx.Router,
    *,
    case_id: str = "CASE-1001",
    attachments: dict[str, object] = ATTACHMENTS_1001,
    images: httpx.Response | None = None,
) -> None:
    """Answer every read a triage can make, so a test only registers what it changes."""
    api.get(f"{SHIPBOB}/cases/{case_id}/attachments").respond(200, json=attachments)
    api.post(f"{SHIPBOB}/invoices/generate").respond(200, json=INVOICE_342578703)
    api.get(host=IMAGE_HOST).mock(
        return_value=images if images is not None else httpx.Response(200, content=PNG_BYTES)
    )


async def triage(
    shipbob_http: httpx.AsyncClient,
    images_http: httpx.AsyncClient,
    *,
    replies: Sequence[Any],
    record: CaseRecord | None = None,
    steps: int = 12,
    images_allowed: int = 20,
) -> Run:
    """Triage one claim with the model answering from `replies`, and keep what it wrote.

    Retrying is off on the ShipBob client and on the structured asker, so one queued
    reply answers exactly one question and a test that is not about retrying does not
    sit through the waits between attempts.
    """
    model = ScriptedModel(replies=list(replies))
    structured = StructuredModel(model, max_attempts=1)
    cache = ObservationCache()
    budget = RunBudget(
        Policy(max_agent_steps=steps, max_image_analyses_per_run=images_allowed, max_tool_retries=0)
    )
    events = EventStream()

    answer = await triage_claim(
        record=record if record is not None else a_record(),
        context=a_context(),
        evidence=EvidenceClient(shipbob_http, max_attempts=1),
        fetcher=ImageFetcher(images_http, build_settings()),
        chat=model,
        structured=structured,
        cache=cache,
        budget=budget,
        ledger=RunLedger(),
        events=events,
        policy=Policy(),
    )
    return Run(triage=answer, model=model, cache=cache, budget=budget, events=events)


# --- Writing the script -----------------------------------------------------


def asks_to_look_at(*attachment_ids: str) -> AIMessage:
    """A turn in which the pass asks to look at some of the claim's images."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "inspect_image",
                "args": {"attachment_id": attachment_id},
                "id": f"call-{attachment_id}",
                "type": "tool_call",
            }
            for attachment_id in attachment_ids
        ],
    )


def an_image_showing(
    kind: EvidenceKind | None,
    *,
    shows: str = "what the photograph shows",
    legible: bool = True,
    problem: str | None = None,
) -> ImageObservation:
    """What the model says when it has looked at one image."""
    return ImageObservation(
        shows=shows, kind=kind, is_legible=legible, problem=problem, confidence=0.9
    )


def a_product(
    name: str, *, quantity: int = 1, sku: str | None = None, damage: tuple[str, ...] = ()
) -> ClaimedProductProposal:
    """One product the pass says was damaged."""
    return ClaimedProductProposal(
        name=name,
        quantity=quantity,
        sku=sku,
        damage_attachment_ids=damage,
        reasoning="The photographs show it broken.",
        confidence=0.9,
    )


def a_split(
    *products: ClaimedProductProposal, ambiguity: str | None = None, confidence: float = 0.9
) -> ClaimSplit:
    """The form the pass ends on: which products the claim is for, or why nobody can tell."""
    return ClaimSplit(
        claimed_products=products,
        is_ambiguous=ambiguity is not None,
        ambiguity=ambiguity,
        reasoning="Worked out from the description and the photographs.",
        confidence=confidence,
    )


def a_whole_claim(*products: ClaimedProductProposal) -> list[Any]:
    """A script in which the pass looks at three images and then names some products.

    The three answers are the three pieces of shared evidence, so a test that is about
    the split rather than about the evidence gets a complete set without saying so.
    """
    return [
        asks_to_look_at(FIRST_IMAGE, SECOND_IMAGE, THIRD_IMAGE),
        an_image_showing(EvidenceKind.INVOICE, shows="a photograph of a paper invoice"),
        an_image_showing(EvidenceKind.CUSTOMER_CONFIRMATION, shows="an email from the customer"),
        an_image_showing(EvidenceKind.OUTER_PACKAGING_PHOTO, shows="a crushed shipping box"),
        AIMessage(content="I have seen enough."),
        a_split(*products),
    ]


def kinds_of(run: Run) -> list[EventKind]:
    """Everything the run said about itself, in the order it said it."""
    return [event.kind for event in run.events.events()]


def events_of(run: Run, kind: EventKind) -> list[RunEvent]:
    """Everything of one kind the run said about itself, in order."""
    return [event for event in run.events.events() if event.kind is kind]


def finding_for(run: Run, kind: EvidenceKind) -> Any:
    """The claim's settled answer for one piece of shared evidence."""
    return next(finding for finding in run.triage.shared_evidence if finding.kind is kind)


# --- Which products the claim is for (FR-1a.1, FR-1a.2, FR-1a.5) ------------


async def test_a_claim_for_one_product_becomes_one_claim_line(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1a.5: one damaged product is one claim line, through the ordinary machinery.

    There is deliberately no shortcut for the simple case: the same pass runs, the same
    matching runs, and what comes out is a list with one line in it.
    """
    serve(api)

    run = await triage(
        shipbob_http, images_http, replies=a_whole_claim(a_product(AMPOULE, sku="AMP1"))
    )

    assert run.triage.is_ambiguous is False
    assert len(run.triage.claim_lines) == 1
    line = run.triage.claim_lines[0]
    assert line.claim_line_id == "CASE-1001-L01"
    assert line.match is MatchOutcome.MATCHED
    assert line.product_name == AMPOULE
    assert line.unit_price == Decimal("38.00")


async def test_a_claim_for_two_products_becomes_two_claim_lines(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1a.1: a claim covering two damaged products is split into one line for each.

    Each line carries the photographs the pass tied to that product, so the run that
    investigates one of them has somewhere to start.
    """
    serve(api)

    run = await triage(
        shipbob_http,
        images_http,
        replies=a_whole_claim(
            a_product(AMPOULE, sku="AMP1", damage=(FOURTH_IMAGE,)),
            a_product(COLLAGEN, quantity=2, sku="COLLAGEN1", damage=(THIRD_IMAGE,)),
        ),
    )

    assert run.triage.is_ambiguous is False
    assert [line.product_name for line in run.triage.claim_lines] == [AMPOULE, COLLAGEN]
    assert [line.claim_line_id for line in run.triage.claim_lines] == [
        "CASE-1001-L01",
        "CASE-1001-L02",
    ]
    assert run.triage.claim_lines[0].damage_attachment_ids == (FOURTH_IMAGE,)
    assert run.triage.claim_lines[1].damage_attachment_ids == (THIRD_IMAGE,)
    assert run.triage.claim_lines[1].claimed.quantity == 2


async def test_a_product_that_is_not_on_the_order_is_still_reported(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1a.2: a claim for something the order does not hold is a finding, not an error.

    The line exists, it says plainly that nothing on the order is this product, and it
    carries no price — because there is none to carry. A representative needs to see
    that rather than have the line quietly dropped.
    """
    serve(api)

    run = await triage(
        shipbob_http, images_http, replies=a_whole_claim(a_product("A roll of bubble wrap"))
    )

    assert len(run.triage.claim_lines) == 1
    line = run.triage.claim_lines[0]
    assert line.match is MatchOutcome.NOT_ON_ORDER
    assert line.order_line is None
    assert line.unit_price is None
    # Not knowing which product was meant and knowing it is not on the order are
    # different things, and only the first stops the claim here.
    assert run.triage.is_ambiguous is False


# --- Refusing to guess (FR-1a.4, FR-1.13) -----------------------------------


async def test_a_split_the_investigation_calls_unclear_is_not_turned_into_an_answer(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1a.4: when the pass says it cannot tell which products, the claim goes to a person.

    This is CASE-1002, the real example: the order holds two different 24oz bottles at
    different prices and a photograph of a broken bottle does not say which. What is
    unclear is passed on in the pass's own words, so a representative can settle in
    seconds what the system was right to refuse to choose.
    """
    serve(api, case_id="CASE-1002", attachments=ATTACHMENTS_1002)
    unclear = (
        "The photographs show a damaged 24oz bottle, but the order holds two different "
        "24oz bottles at different prices."
    )

    run = await triage(
        shipbob_http,
        images_http,
        record=a_record(case=CASE_1002, order=ORDER_1002),
        replies=[
            asks_to_look_at("ATT-CASE-1002-01"),
            an_image_showing(EvidenceKind.DAMAGED_PRODUCT_PHOTO, shows="a broken 24oz bottle"),
            AIMessage(content="I cannot tell which bottle this is."),
            a_split(
                a_product("CleanBoss Multi Surface Cleaner 24oz", sku="A00300"),
                ambiguity=unclear,
                confidence=0.4,
            ),
        ],
    )

    assert run.triage.is_ambiguous is True
    assert run.triage.ambiguity == unclear
    # The candidate is still reported. It is what the pass was choosing between, and
    # showing it is what lets a representative see the choice rather than just be told
    # there was one.
    assert len(run.triage.claim_lines) == 1


async def test_a_product_matching_two_order_lines_stops_the_claim(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.13: when one claimed product could be either of two order lines, nobody chooses.

    The pass itself was sure here — it is the matching against the order that finds two
    candidates. The two can carry different prices, so narrowing them to one would
    invent the payout, and the triage says so instead.

    The order below is ShipBob's CASE-1002 order with a second, cheaper line of the same
    name added, because no order ShipBob supplies holds two lines with one name. The
    added line's product code starts with a 9, the marker this project uses for anything
    it invented.
    """
    two_lines_alike = order_payload(
        order_id="336431771",
        user_id="283959",
        line_items=[
            order_line_item(name="CleanBoss Multi Surface Cleaner 24oz", sku="A00300", quantity=2),
            order_line_item(name="CleanBoss Multi Surface Cleaner 24oz", sku="900300", quantity=1),
        ],
    )
    serve(api, case_id="CASE-1002", attachments=ATTACHMENTS_1002)

    run = await triage(
        shipbob_http,
        images_http,
        record=a_record(case=CASE_1002, order=two_lines_alike),
        replies=[
            AIMessage(content="The description names the cleaner."),
            a_split(a_product("CleanBoss Multi Surface Cleaner 24oz")),
        ],
    )

    assert run.triage.is_ambiguous is True
    assert run.triage.ambiguity is not None
    assert "CleanBoss Multi Surface Cleaner 24oz" in run.triage.ambiguity
    assert run.triage.claim_lines[0].match is MatchOutcome.AMBIGUOUS
    assert len(run.triage.claim_lines[0].candidate_order_lines) == 2


async def test_a_split_naming_no_products_at_all_stops_the_claim(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1a.4: naming no products is not an answer to "which products", so a person looks.

    An empty split with nothing said about why is the shape a claim would silently
    disappear in: no lines to investigate, and nothing to tell anybody.
    """
    serve(api)

    run = await triage(
        shipbob_http,
        images_http,
        replies=[AIMessage(content="There is nothing to see."), a_split()],
    )

    assert run.triage.is_ambiguous is True
    assert run.triage.claim_lines == ()


# --- The shared evidence, settled once (FR-1a.3) ----------------------------


async def test_the_shared_evidence_is_settled_once_for_the_whole_claim(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1a.3: the invoice, the confirmation and the box are settled once, for every line.

    A claim covering two products gets one answer about the parcel, not two, so the two
    products can never disagree about whether the box was photographed. Each image was
    looked at once (NFR-8), and the photograph of the damaged product is deliberately
    not among the settled findings: that one belongs to a single product.
    """
    serve(api)

    run = await triage(
        shipbob_http,
        images_http,
        replies=a_whole_claim(
            a_product(AMPOULE, sku="AMP1"),
            a_product(COLLAGEN, sku="COLLAGEN1"),
        ),
    )

    assert len(run.triage.claim_lines) == 2
    assert [finding.kind for finding in run.triage.shared_evidence] == list(SHARED_EVIDENCE)
    assert all(finding.state is EvidenceState.PRESENT for finding in run.triage.shared_evidence)
    assert EvidenceKind.DAMAGED_PRODUCT_PHOTO not in {
        finding.kind for finding in run.triage.shared_evidence
    }
    assert finding_for(run, EvidenceKind.INVOICE).attachment_id == FIRST_IMAGE
    assert run.budget.snapshot().image_analyses_used == 3


async def test_evidence_nobody_sent_is_missing_rather_than_assumed(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1a.3, FR-1.6: a claim with no images at all settles every shared item as missing.

    This is CASE-1005, whose listing really is empty. It must reach the triage as an
    empty listing rather than as a failure, cost nothing to investigate, and end with
    all three shared items recorded as missing so the merchant can be asked for them.
    """
    serve(api, case_id="CASE-1005", attachments=ATTACHMENTS_1005)

    run = await triage(
        shipbob_http,
        images_http,
        record=a_record(case=CASE_1005, order=ORDER_1005, shipment=None),
        replies=[
            AIMessage(content="This claim has no images, so there is nothing to look at."),
            a_split(a_product("30-day Pouch LOAM Prebiotic Fiber Formula", sku="LOAM-30DAY-001")),
        ],
    )

    assert run.triage.attachments == ()
    assert run.triage.attachment_classifications == ()
    assert [finding.state for finding in run.triage.shared_evidence] == [
        EvidenceState.MISSING,
        EvidenceState.MISSING,
        EvidenceState.MISSING,
    ]
    # Nothing the merchant can be asked for is recorded as our own failure.
    assert all(finding.problem is None for finding in run.triage.shared_evidence)
    assert run.budget.snapshot().image_analyses_used == 0
    assert len(run.triage.claim_lines) == 1


async def test_an_image_too_poor_to_rely_on_does_not_satisfy_its_requirement(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.5, FR-1.7: a blurry invoice counts as not having one, and says what to ask for.

    The merchant can fix this, so the reason is kept in words they could act on.
    """
    serve(api)

    run = await triage(
        shipbob_http,
        images_http,
        replies=[
            asks_to_look_at(FIRST_IMAGE),
            an_image_showing(
                EvidenceKind.INVOICE,
                shows="a photograph of an invoice",
                legible=False,
                problem="the total is out of focus and cannot be read",
            ),
            AIMessage(content="That is all I can establish."),
            a_split(a_product(AMPOULE, sku="AMP1")),
        ],
    )

    invoice = finding_for(run, EvidenceKind.INVOICE)
    assert invoice.state is EvidenceState.UNUSABLE
    assert invoice.attachment_id == FIRST_IMAGE
    assert invoice.problem == "the total is out of focus and cannot be read"


async def test_an_image_we_could_not_read_is_never_blamed_on_the_merchant(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4: an image this system could not fetch sends the claim to a person, not the merchant.

    Nothing was learned from the image, so nothing can be said about what it held. The
    unsettled shared items are recorded as unreadable rather than missing, because
    asking a merchant to send again what our own download lost is a request they cannot
    act on.
    """
    serve(api, images=httpx.Response(500))

    run = await triage(
        shipbob_http,
        images_http,
        replies=[
            asks_to_look_at(FIRST_IMAGE),
            AIMessage(content="I could not read that one."),
            a_split(a_product(AMPOULE, sku="AMP1")),
        ],
    )

    assert [classified.state for classified in run.triage.attachment_classifications] == [
        EvidenceState.UNREADABLE
    ]
    assert [finding.state for finding in run.triage.shared_evidence] == [
        EvidenceState.UNREADABLE,
        EvidenceState.UNREADABLE,
        EvidenceState.UNREADABLE,
    ]


async def test_the_claim_stops_when_its_images_cannot_even_be_listed(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4: ShipBob refusing the listing gives back a triage for a person, not an error.

    Without the listing there is no honest question to ask, because telling the pass
    that a claim has no images when we simply could not look would invite a split made
    against evidence nobody checked for.
    """
    api.get(f"{SHIPBOB}/cases/CASE-1001/attachments").respond(503)

    run = await triage(shipbob_http, images_http, replies=[])

    assert run.triage.is_ambiguous is True
    assert run.triage.claim_lines == ()
    assert run.triage.split is None
    assert [finding.state for finding in run.triage.shared_evidence] == [
        EvidenceState.UNREADABLE,
        EvidenceState.UNREADABLE,
        EvidenceState.UNREADABLE,
    ]
    # The failure is written into the record, so "why was this escalated?" is
    # answerable from what the representative is handed (NFR-3).
    assert [entry.succeeded for entry in run.triage.ledger] == [False]
    # Nothing was asked of the model, because there was nothing to ask about.
    assert run.model.asked == []


# --- The investigation chooses what to look at (FR-1.1, NFR-8) --------------


async def test_only_the_images_the_investigation_asked_for_are_looked_at(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.1, NFR-8: nothing classifies every attachment in turn before the pass runs.

    CASE-1001 carries four images and the pass asks about one of them. If the triage
    were a fixed sequence dressed up as an agent, all four would have been paid for.
    """
    serve(api)

    run = await triage(
        shipbob_http,
        images_http,
        replies=[
            asks_to_look_at(SECOND_IMAGE),
            an_image_showing(EvidenceKind.DAMAGED_PRODUCT_PHOTO, shows="a broken ampoule"),
            AIMessage(content="The description already names the product."),
            a_split(a_product(AMPOULE, sku="AMP1")),
        ],
    )

    assert len(run.triage.attachments) == 4
    assert [classified.attachment_id for classified in run.triage.attachment_classifications] == [
        SECOND_IMAGE
    ]
    assert run.budget.snapshot().image_analyses_used == 1
    assert run.cache.computed_count == 2  # the listing, and the one image


async def test_one_image_asked_about_twice_is_analysed_once(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-8: looking at the same photograph again costs nothing and adds nothing.

    The claim's memo answers the second look, so the image is reported once and the
    expensive work happens once.
    """
    serve(api)

    run = await triage(
        shipbob_http,
        images_http,
        replies=[
            asks_to_look_at(FIRST_IMAGE, FIRST_IMAGE),
            an_image_showing(EvidenceKind.INVOICE, shows="a photograph of a paper invoice"),
            AIMessage(content="I already had that one."),
            a_split(a_product(AMPOULE, sku="AMP1")),
        ],
    )

    assert [classified.attachment_id for classified in run.triage.attachment_classifications] == [
        FIRST_IMAGE
    ]
    assert run.budget.snapshot().image_analyses_used == 1


# --- Giving up rather than guessing (FR-1.16, NFR-4) ------------------------


async def test_a_pass_that_runs_out_of_steps_hands_over_what_it_found(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """FR-1.16, NFR-4: an exhausted allowance escalates the claim rather than raising.

    Nothing is invented to fill the gap: there are no claim lines, the reason the pass
    stopped is what a representative is told, and the one image it did manage to read
    is still reported.
    """
    serve(api)

    run = await triage(
        shipbob_http,
        images_http,
        steps=1,
        replies=[
            asks_to_look_at(FIRST_IMAGE),
            an_image_showing(EvidenceKind.INVOICE, shows="a photograph of a paper invoice"),
        ],
    )

    assert run.triage.is_ambiguous is True
    assert run.triage.split is None
    assert run.triage.claim_lines == ()
    assert run.triage.ambiguity is not None
    assert "steps" in run.triage.ambiguity
    # What the pass did establish is carried forward rather than lost.
    assert finding_for(run, EvidenceKind.INVOICE).state is EvidenceState.PRESENT
    assert run.triage.budget.steps_used == 1


async def test_a_model_that_cannot_be_reached_escalates_the_claim(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4: a provider failure ends in front of a person, never as an exception.

    Nothing was established at all here, so every shared item is settled as missing and
    the claim carries the reason it stopped.
    """
    serve(api)

    run = await triage(
        shipbob_http, images_http, replies=[ModelConnectionError("the socket closed")]
    )

    assert run.triage.is_ambiguous is True
    assert run.triage.ambiguity == "The model provider could not be reached."
    assert run.triage.claim_lines == ()
    assert run.triage.attachment_classifications == ()


# --- Saying what is happening while it happens ------------------------------


async def test_the_run_narrates_the_claim_in_the_order_it_worked_on_it(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """The images, then the evidence, then the split — in that order, all three settled.

    A representative watching sees the investigation choosing what to look at, then
    what each image turned out to be, then all three pieces of shared evidence whether
    or not they were found, and finally what the claim is for.
    """
    serve(api)

    run = await triage(
        shipbob_http,
        images_http,
        replies=a_whole_claim(a_product(AMPOULE, sku="AMP1")),
    )

    said = kinds_of(run)
    assert said[0] is EventKind.ATTACHMENTS_LISTED
    assert said[-1] is EventKind.CLAIM_SPLIT
    assert said[-4:-1] == [EventKind.EVIDENCE_SETTLED] * 3
    # Each image is announced as it is read, so the classifications come before the
    # evidence they are settled into.
    assert said.index(EventKind.IMAGE_CLASSIFIED) < said.index(EventKind.EVIDENCE_SETTLED)
    assert len(events_of(run, EventKind.IMAGE_CLASSIFIED)) == 3
    assert [event.detail["state"] for event in events_of(run, EventKind.EVIDENCE_SETTLED)] == [
        "present",
        "present",
        "present",
    ]
    assert events_of(run, EventKind.CLAIM_SPLIT)[0].detail["settled"] == "yes"


async def test_a_claim_that_could_not_be_split_still_says_so_out_loud(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-4: a stream that simply stopped would leave a watcher unable to tell what happened."""
    serve(api)

    run = await triage(
        shipbob_http,
        images_http,
        replies=[
            AIMessage(content="I cannot tell."),
            a_split(ambiguity="Nothing names a product."),
        ],
    )

    split_said = events_of(run, EventKind.CLAIM_SPLIT)
    assert len(split_said) == 1
    assert split_said[0].detail["settled"] == "no"
    assert "Nothing names a product." in split_said[0].summary


# --- The same claim, twice (NFR-1) ------------------------------------------


async def test_the_same_claim_investigated_twice_gives_the_same_triage(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    """NFR-1: two runs over the same claim, answered the same way, produce the same answer.

    Everything a report would be built from is compared: the lines and their
    identifiers, the settled evidence, what each image was, and the record of the run
    itself. Nothing here reads a clock or depends on which order two things finished
    in, so the two are equal outright.
    """
    serve(api)
    products = (a_product(COLLAGEN, sku="COLLAGEN1"), a_product(AMPOULE, sku="AMP1"))

    first = await triage(shipbob_http, images_http, replies=a_whole_claim(*products))
    second = await triage(shipbob_http, images_http, replies=a_whole_claim(*products))

    assert first.triage == second.triage
