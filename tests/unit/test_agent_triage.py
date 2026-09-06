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
from claim_agent.agent.tools import TRIAGE_TOOL_NAMES
from claim_agent.agent.triage import ClaimTriage, triage_claim
from claim_agent.domain.claim_line import MatchOutcome
from claim_agent.domain.evidence import SHARED_EVIDENCE, EvidenceKind, EvidenceState
from claim_agent.domain.models import Case, Order, Shipment
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.settings import Settings
from claim_agent.shipbob.evidence_client import EvidenceClient

SHIPBOB = "http://shipbob.test"


IMAGE_HOST = "sa032101pubdevuc.blob.core.windows.net"


PNG_BYTES = b"\x89PNG\r\n\x1a\npretend pixels"


FIRST_IMAGE = "ATT-CASE-1001-01"
SECOND_IMAGE = "ATT-CASE-1001-02"
THIRD_IMAGE = "ATT-CASE-1001-03"
FOURTH_IMAGE = "ATT-CASE-1001-04"


AMPOULE = "Additional Collagen Ampoule Duo"
COLLAGEN = "Liposomal Tripeptide Collagen"


def build_settings() -> Settings:
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
    return CaseRecord(
        case=Case.model_validate(case),
        shipment=None if shipment is None else Shipment.model_validate(shipment),
        order=None if order is None else Order.model_validate(order),
    )


def a_context() -> ClaimContext:
    return ClaimContext(
        order_value_usd=Decimal("90.00"),
        is_high_value=False,
        days_since_delivery=8,
        delivered_date=datetime(2026, 2, 11, 11, 36, tzinfo=UTC),
    )


@dataclass
class Run:
    triage: ClaimTriage
    model: ScriptedModel
    cache: ObservationCache
    budget: RunBudget
    events: EventStream


@pytest.fixture
def api() -> Iterator[respx.Router]:
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
async def shipbob_http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=SHIPBOB, timeout=1.0) as client:
        yield client


@pytest.fixture
async def images_http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


def serve(
    api: respx.Router,
    *,
    case_id: str = "CASE-1001",
    attachments: dict[str, object] = ATTACHMENTS_1001,
    images: httpx.Response | None = None,
) -> None:
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
    model = ScriptedModel(replies=list(replies))
    structured = StructuredModel(model, max_attempts=1)
    cache = ObservationCache()
    budget = RunBudget(Policy(max_agent_steps=steps, max_image_analyses_per_run=images_allowed))
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


def asks_to_look_at(*attachment_ids: str) -> AIMessage:
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
    return ImageObservation(shows=shows, kind=kind, is_legible=legible, problem=problem)


def a_product(
    name: str, *, quantity: int = 1, sku: str | None = None, damage: tuple[str, ...] = ()
) -> ClaimedProductProposal:
    return ClaimedProductProposal(
        name=name,
        quantity=quantity,
        sku=sku,
        damage_attachment_ids=damage,
        reasoning="The photographs show it broken.",
    )


def a_split(*products: ClaimedProductProposal, ambiguity: str | None = None) -> ClaimSplit:
    return ClaimSplit(
        claimed_products=products,
        is_ambiguous=ambiguity is not None,
        ambiguity=ambiguity,
        reasoning="Worked out from the description and the photographs.",
    )


def a_whole_claim(*products: ClaimedProductProposal) -> list[Any]:
    return [
        asks_to_look_at(FIRST_IMAGE, SECOND_IMAGE, THIRD_IMAGE),
        an_image_showing(EvidenceKind.INVOICE, shows="a photograph of a paper invoice"),
        an_image_showing(EvidenceKind.CUSTOMER_CONFIRMATION, shows="an email from the customer"),
        an_image_showing(EvidenceKind.OUTER_PACKAGING_PHOTO, shows="a crushed shipping box"),
        AIMessage(content="I have seen enough."),
        a_split(*products),
    ]


def kinds_of(run: Run) -> list[EventKind]:
    return [event.kind for event in run.events.events()]


def events_of(run: Run, kind: EventKind) -> list[RunEvent]:
    return [event for event in run.events.events() if event.kind is kind]


def finding_for(run: Run, kind: EvidenceKind) -> Any:
    return next(finding for finding in run.triage.shared_evidence if finding.kind is kind)


async def test_a_claim_for_one_product_becomes_one_claim_line(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
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
    serve(api)

    run = await triage(
        shipbob_http, images_http, replies=a_whole_claim(a_product("A roll of bubble wrap"))
    )

    assert len(run.triage.claim_lines) == 1
    line = run.triage.claim_lines[0]
    assert line.match is MatchOutcome.NOT_ON_ORDER
    assert line.order_line is None
    assert line.unit_price is None

    assert run.triage.is_ambiguous is False


async def test_a_split_the_investigation_calls_unclear_is_not_turned_into_an_answer(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
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
            ),
        ],
    )

    assert run.triage.is_ambiguous is True
    assert run.triage.ambiguity == unclear

    assert len(run.triage.claim_lines) == 1


async def test_a_product_matching_two_order_lines_stops_the_claim(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
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
    serve(api)

    run = await triage(
        shipbob_http,
        images_http,
        replies=[AIMessage(content="There is nothing to see."), a_split()],
    )

    assert run.triage.is_ambiguous is True
    assert run.triage.claim_lines == ()


async def test_the_shared_evidence_is_settled_once_for_the_whole_claim(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
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

    assert all(finding.problem is None for finding in run.triage.shared_evidence)
    assert run.budget.snapshot().image_analyses_used == 0
    assert len(run.triage.claim_lines) == 1


async def test_an_image_too_poor_to_rely_on_does_not_satisfy_its_requirement(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
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

    assert [entry.succeeded for entry in run.triage.ledger] == [False]

    assert run.model.asked == []


async def test_only_the_images_the_investigation_asked_for_are_looked_at(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
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
    assert run.cache.computed_count == 2


async def test_one_image_asked_about_twice_is_analysed_once(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
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


async def test_a_pass_that_runs_out_of_steps_hands_over_what_it_found(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
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

    assert finding_for(run, EvidenceKind.INVOICE).state is EvidenceState.PRESENT
    assert run.triage.budget.steps_used == 1


async def test_a_model_that_cannot_be_reached_requests_rep_clarification(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    serve(api)

    run = await triage(
        shipbob_http, images_http, replies=[ModelConnectionError("the socket closed")]
    )

    assert run.triage.is_ambiguous is True
    assert run.triage.ambiguity == "The model provider could not be reached."
    assert run.triage.claim_lines == ()
    assert run.triage.attachment_classifications == ()


async def test_the_run_narrates_the_claim_in_the_order_it_worked_on_it(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
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


async def test_the_same_claim_investigated_twice_gives_the_same_triage(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    serve(api)
    products = (a_product(COLLAGEN, sku="COLLAGEN1"), a_product(AMPOULE, sku="AMP1"))

    first = await triage(shipbob_http, images_http, replies=a_whole_claim(*products))
    second = await triage(shipbob_http, images_http, replies=a_whole_claim(*products))

    assert first.triage == second.triage


async def test_the_triage_pass_is_offered_the_reading_tools_and_none_that_price(
    api: respx.Router, shipbob_http: httpx.AsyncClient, images_http: httpx.AsyncClient
) -> None:
    serve(api)

    run = await triage(
        shipbob_http, images_http, replies=["Nothing to look at.", ClaimSplit(reasoning="none")]
    )

    assert set(run.model.bound_tools) == set(TRIAGE_TOOL_NAMES)
    assert "compute_reimbursement" not in run.model.bound_tools
    assert "generate_invoice" not in run.model.bound_tools
