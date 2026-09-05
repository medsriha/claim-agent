"""Reading a claim's reports and acting on one, over HTTP (FR-2.8, FR-2.9, FR-2.9b, FR-C.1)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from tests.fakes.model import scripted
from tests.fixtures.attachments import ATTACHMENTS_1002, INVOICE_342578703
from tests.fixtures.shipbob import (
    CASE_1001,
    CASE_1002,
    CASE_1004,
    ORDER_1001,
    ORDER_1002,
    ORDER_1004,
    SHIPMENT_1001,
    SHIPMENT_1002,
    SHIPMENT_1004,
    mock_shipbob,
)
from tests.unit.test_report_models import a_report, a_screening_report
from tests.unit.test_report_render import a_context

from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.schemas import (
    ClaimedProductProposal,
    ClaimSplit,
    DamagedItem,
    EvidenceJudgement,
    InvestigationConclusion,
    RevisedClaimReport,
    RevisionConclusion,
    SettledProduct,
)
from claim_agent.api.deps import get_models
from claim_agent.app import create_app
from claim_agent.domain.evidence import EvidenceKind, EvidenceState
from claim_agent.domain.outcome import Recommendation
from claim_agent.report.models import ClarificationReportContent, Report, ReportState
from claim_agent.settings import Settings
from claim_agent.storage.decision_store import DecisionStore
from claim_agent.storage.merchant_memory import MerchantMemory
from claim_agent.storage.report_store import ReportStore

pytestmark = pytest.mark.integration

# Wide enough to catch every decision a test could take, so a test never has to know when
# the clock said the request happened.
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
FAR_AHEAD = datetime(2100, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(settings: Settings) -> ReportStore:
    """The store the application will read, on this test's own database file."""
    return ReportStore(settings.database_path)


@pytest.fixture
def decisions(settings: Settings) -> DecisionStore:
    """The record of decisions the application writes to, on the same file."""
    return DecisionStore(settings.database_path)


@pytest.fixture
def app(settings: Settings, store: ReportStore) -> FastAPI:
    """An application reading the same store the test writes to."""
    return create_app(settings, report_store=store)


@pytest.fixture
async def client(app: FastAPI) -> Any:
    """An HTTP client bound to that application, no network involved."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def a_second_product(**overrides: Any) -> Report:
    """The other damaged product on the same claim."""
    fields: dict[str, Any] = {
        "report_id": "RPT-CASE-1001-L02",
        "claim_line_id": "CASE-1001-L02",
        "product_name": "Additional Collagen Ampoule Duo",
        "amount_usd": Decimal("18.00"),
    }
    fields.update(overrides)
    return a_report(**fields)


# --- A claim's reports (FR-2.9b) ---------------------------------------------


async def test_a_claim_comes_back_as_all_of_its_reports(
    client: AsyncClient, store: ReportStore
) -> None:
    """FR-2.9b: a rep works from a case, not from a list of disconnected products."""
    store.record(a_report())
    store.record(a_second_product())

    response = await client.get("/cases/CASE-1001/reports")

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "CASE-1001"
    assert len(body["reports"]) == 2


async def test_a_claim_nobody_has_asked_about_comes_back_empty(client: AsyncClient) -> None:
    """FR-2.9b: an empty list is a claim nobody investigated, not a failure."""
    response = await client.get("/cases/CASE-9999/reports")

    assert response.status_code == 200
    assert response.json()["reports"] == []


async def test_money_arrives_as_text_rather_than_a_number(
    client: AsyncClient, store: ReportStore
) -> None:
    """FR-1.21: a figure that went through a floating point number is one nobody can trust."""
    store.record(a_report())

    body = (await client.get("/cases/CASE-1001/reports")).json()

    assert body["reports"][0]["amount_usd"] == "52.00"


# --- One report, and the products beside it (FR-2.9a) ------------------------


async def test_a_report_carries_the_other_products_on_its_claim(
    client: AsyncClient, store: ReportStore
) -> None:
    """FR-2.9a: a rep approving one product should see the second without opening it."""
    store.record(a_report())
    store.record(a_second_product())

    body = (await client.get("/reports/RPT-CASE-1001-L01")).json()

    assert body["report"]["claim_line_id"] == "CASE-1001-L01"
    (sibling,) = body["siblings"]
    assert sibling["claim_line_id"] == "CASE-1001-L02"
    assert sibling["product_name"] == "Additional Collagen Ampoule Duo"


async def test_a_siblings_state_is_read_now_rather_than_taken_from_a_copy(
    client: AsyncClient, store: ReportStore
) -> None:
    """FR-2.9a: a copy stored with the report would say waiting beside an approved product."""
    store.record(a_report())
    store.record(a_second_product())

    await client.post("/reports/RPT-CASE-1001-L02/approve", json={})
    body = (await client.get("/reports/RPT-CASE-1001-L01")).json()

    (sibling,) = body["siblings"]
    assert sibling["state"] == "approved"


async def test_a_claim_of_one_product_has_no_siblings(
    client: AsyncClient, store: ReportStore
) -> None:
    """FR-2.9a: nothing beside it is an ordinary answer, not a gap."""
    store.record(a_report())

    body = (await client.get("/reports/RPT-CASE-1001-L01")).json()

    assert body["siblings"] == []


async def test_a_report_that_does_not_exist_says_so(client: AsyncClient) -> None:
    """NFR-4: a caller is always left with something they can act on."""
    response = await client.get("/reports/RPT-NOBODY")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_an_earlier_version_can_be_read_back(client: AsyncClient, store: ReportStore) -> None:
    """FR-R.13: the version a rep was looking at has to survive being superseded."""
    store.record(a_report(version=1))
    store.record(a_report(version=2))

    latest = (await client.get("/reports/RPT-CASE-1001-L01")).json()
    earlier = (await client.get("/reports/RPT-CASE-1001-L01?version=1")).json()

    assert latest["report"]["version"] == 2
    assert earlier["report"]["version"] == 1


# --- Approving (FR-2.8, FR-2.9, FR-C.1) --------------------------------------


async def test_approving_a_report_leaves_it_approved_and_records_the_decision(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    """FR-2.9, FR-C.1: approving is the only way out, and it produces one durable record."""
    store.record(a_report())

    response = await client.post("/reports/RPT-CASE-1001-L01/approve", json={})

    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    assert store.get("RPT-CASE-1001-L01").state is ReportState.APPROVED  # type: ignore[union-attr]
    assert decisions.count() == 1


async def test_approving_at_a_different_figure_records_both(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    """FR-2.1: a report approved at a different figure must not show only the old one."""
    store.record(a_report())

    body = (
        await client.post(
            "/reports/RPT-CASE-1001-L01/approve",
            json={"amount_usd": "31.20", "rep_words": "Confirmed by phone."},
        )
    ).json()

    assert body["amount_usd"] == "52.00"
    assert body["decided"]["amount_usd"] == "31.20"
    (decision,) = decisions.decided_between(LONG_AGO, FAR_AHEAD)
    assert decision.action == "approved_with_override"
    assert decision.rep_words == "Confirmed by phone."


async def test_a_figure_over_the_cap_is_accepted_and_flagged(
    client: AsyncClient, store: ReportStore
) -> None:
    """FR-R.8, FR-C.4: losing a decision a person made is worse than recording one to query."""
    store.record(a_report())

    body = (
        await client.post("/reports/RPT-CASE-1001-L01/approve", json={"amount_usd": "150.00"})
    ).json()

    assert body["state"] == "approved"
    assert body["decided"]["amount_usd"] == "150.00"
    assert body["reviews"][-1]["over_the_cap_by"] == "50.00"


async def test_a_figure_that_is_not_an_amount_is_refused(
    client: AsyncClient, store: ReportStore
) -> None:
    """FR-1.21: treating it as "no change" would approve a figure nobody chose."""
    store.record(a_report())

    response = await client.post(
        "/reports/RPT-CASE-1001-L01/approve", json={"amount_usd": "about fifty"}
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"]["amount_usd"] == "about fifty"
    assert store.get("RPT-CASE-1001-L01").state is ReportState.AWAITING_REVIEW  # type: ignore[union-attr]


async def test_a_reworded_email_is_shown_in_full(client: AsyncClient, store: ReportStore) -> None:
    """FR-2.7: a rep approves wording, so after a rewording the wording is theirs."""
    store.record(a_report())

    body = (
        await client.post(
            "/reports/RPT-CASE-1001-L01/approve",
            json={"email": {"subject": "Your claim", "body": "We are refunding you."}},
        )
    ).json()

    assert body["drafted_email"]["body"] == ("We are refunding you.\n\nApproved amount: $52.00")
    assert body["reviews"][-1]["edited_email"]["body"] == "We are refunding you."


async def test_a_recipient_cannot_be_sent_from_a_caller(
    client: AsyncClient, store: ReportStore
) -> None:
    """FR-3.2: who hears about a claim comes from the claim, not from whoever is reviewing it."""
    store.record(a_report())

    response = await client.post(
        "/reports/RPT-CASE-1001-L01/approve",
        json={"email": {"subject": "Your claim", "body": "Hello.", "to": "someone@else.test"}},
    )

    assert response.status_code == 422


async def test_approving_twice_leaves_one_decision(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    """FR-3.5: a double-click must not count as two decisions."""
    store.record(a_report())

    first = await client.post("/reports/RPT-CASE-1001-L01/approve", json={})
    again = await client.post("/reports/RPT-CASE-1001-L01/approve", json={})

    assert first.status_code == 200
    assert again.status_code == 200
    assert decisions.count() == 1


async def test_approving_an_approved_report_differently_is_refused(
    client: AsyncClient, store: ReportStore
) -> None:
    """FR-2.9: a decision a person took is not something a later request may replace."""
    store.record(a_report())
    await client.post("/reports/RPT-CASE-1001-L01/approve", json={})

    response = await client.post("/reports/RPT-CASE-1001-L01/approve", json={"amount_usd": "31.20"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_a_claim_the_quick_checks_stopped_can_be_approved(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    """FR-0.4, FR-C.1: the cheapest decision in the system still has to be recordable."""
    store.record(a_screening_report())

    response = await client.post("/reports/RPT-CASE-1004/approve", json={})

    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    assert decisions.count() == 1


# --- Sending a report back, and what comes back (FR-2.8, FR-R.1 to FR-R.14) ---


async def test_sending_a_report_back_records_the_note_in_the_reps_own_words(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    """FR-2.8, FR-C.1: the rep says what is wrong in their own words, kept as written.

    Nothing is stood in for here, so nothing reworks the report — ShipBob cannot be reached
    from a test process. What the note itself does is still the whole of what this checks,
    and the rework has its own tests below.
    """
    store.record(a_report())

    body = (
        await client.post(
            "/reports/RPT-CASE-1001-L01/send-back",
            json={"feedback": "The packaging photo is the box, not the product."},
        )
    ).json()

    assert body["reviews"][-1]["rep_words"] == ("The packaging photo is the box, not the product.")
    assert decisions.count() == 1


async def test_a_note_the_agent_could_not_answer_still_leaves_a_report_to_act_on(
    client: AsyncClient, store: ReportStore
) -> None:
    """NFR-4: a rework that could not run must never cost a rep the work they were deciding on.

    ShipBob is unreachable from this test process, so the rework never starts. What comes
    back is the next version with every finding unchanged and a sentence saying why.
    """
    before = a_report()
    store.record(before)

    body = (
        await client.post(
            "/reports/RPT-CASE-1001-L01/send-back", json={"feedback": "Look at the box again."}
        )
    ).json()

    assert body["version"] == before.version + 1
    assert body["state"] == "awaiting_review"
    assert body["recommendation"] == before.recommendation
    assert body["revisions"][-1]["reworked"] is False
    assert "could not be read" in body["revisions"][-1]["reply"]


async def test_fr_r_14_what_a_representative_said_is_remembered_against_the_merchant(
    client: AsyncClient, store: ReportStore, settings: Settings
) -> None:
    """FR-R.14, FR-3.8: the system should be better on the merchant's next claim, not just this one."""
    store.record(a_report())

    await client.post(
        "/reports/RPT-CASE-1001-L01/send-back",
        json={"feedback": "This merchant always sends the invoice separately, by email."},
    )

    remembered = MerchantMemory(settings.database_path).corrections_for("334430")
    assert [correction.summary for correction in remembered] == [
        "This merchant always sends the invoice separately, by email."
    ]
    assert remembered[0].case_id == "CASE-1001"


async def test_fr_r_8_a_stopped_claim_gets_an_answer_and_keeps_its_verdict(
    client: AsyncClient,
    store: ReportStore,
    decisions: DecisionStore,
    a_scripted_reply: list[Any],
) -> None:
    """FR-R.8: feedback cannot overturn a verdict from fixed rules — and is still answered.

    The representative is arguing with the age limit. They get a reply, because being told
    nothing is the failure this whole feature exists to prevent, and the report keeps every
    reason it was stopped for.
    """
    store.record(a_screening_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative=(
                "This was filed 73 days after delivery and the limit is 60, which is a fixed "
                "rule I cannot set aside."
            ),
            left_unchanged=("The verdict and the four checks behind it.",),
        )
    )

    body = (
        await client.post(
            "/reports/RPT-CASE-1004/send-back", json={"feedback": "Sixty days is too strict."}
        )
    ).json()

    assert decisions.count() == 1
    assert "73 days after delivery" in body["revisions"][-1]["reply"]
    assert body["recommendation"] is None
    assert body["content"] == a_screening_report().content.model_dump(mode="json")


async def test_a_stopped_claims_merchant_email_can_still_be_reworded(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    """FR-0.4, FR-R.8: the wording is the one thing about a stopped claim that is open."""
    store.record(a_screening_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative="Softened it, and kept the reason the same.",
            changed=("Reworded the merchant email.",),
            email_subject="About your claim",
            email_body="We are sorry we cannot take this one on. Here is why.",
        )
    )

    body = (
        await client.post(
            "/reports/RPT-CASE-1004/send-back", json={"feedback": "That email reads harshly."}
        )
    ).json()

    assert body["drafted_email"]["body"].startswith("We are sorry")
    assert body["content"] == a_screening_report().content.model_dump(mode="json")


async def test_two_different_notes_on_one_report_are_two_decisions(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    """FR-C.1: a rep who says one thing and then another has decided twice."""
    store.record(a_report())

    await client.post("/reports/RPT-CASE-1001-L01/send-back", json={"feedback": "One."})
    await client.post("/reports/RPT-CASE-1001-L01/send-back", json={"feedback": "Two."})

    assert decisions.count() == 2


async def test_a_report_sent_back_can_still_be_approved(
    client: AsyncClient, store: ReportStore
) -> None:
    """FR-2.9: a case may cycle any number of times and still needs a person to release it."""
    store.record(a_report())
    await client.post("/reports/RPT-CASE-1001-L01/send-back", json={"feedback": "Look again."})

    response = await client.post("/reports/RPT-CASE-1001-L01/approve", json={})

    assert response.status_code == 200
    assert response.json()["state"] == "approved"


async def test_an_approved_report_cannot_be_sent_back(
    client: AsyncClient, store: ReportStore
) -> None:
    """FR-3.1: un-approving would undo something that releases execution."""
    store.record(a_report())
    await client.post("/reports/RPT-CASE-1001-L01/approve", json={})

    response = await client.post(
        "/reports/RPT-CASE-1001-L01/send-back", json={"feedback": "Actually, no."}
    )

    assert response.status_code == 409


async def test_acting_on_a_report_that_does_not_exist_says_so(client: AsyncClient) -> None:
    """NFR-4: a caller is always left with something they can act on."""
    response = await client.post("/reports/RPT-NOBODY/approve", json={})

    assert response.status_code == 404


# --- A store that cannot be read (NFR-4) -------------------------------------


async def test_a_store_that_cannot_be_read_fails_rather_than_reporting_an_empty_claim(
    settings: Settings,
) -> None:
    """NFR-4: a claim whose reports could not be read must not read as a claim with none."""
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.database_path.write_text("this is not a database at all")
    app = create_app(settings, report_store=ReportStore(settings.database_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/cases/CASE-1001/reports")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"


# --- The rework itself, end to end (FR-R.1, FR-R.9, FR-R.12, FR-R.13) --------


def a_reworked_answer(**overrides: Any) -> RevisionConclusion:
    """What the agent comes back with: the box was never photographed after all."""
    fields: dict[str, Any] = {
        "evidence": (
            EvidenceJudgement(
                kind=EvidenceKind.OUTER_PACKAGING_PHOTO,
                state=EvidenceState.MISSING,
                observed="That image is the product itself, so the box was never photographed.",
            ),
        ),
        "recommendation": Recommendation.REQUEST_INFO,
        "reasoning": "The outer box was never photographed, so the claim cannot be settled yet.",
        "requested_details": ("a photograph of the outer shipping box with the label visible",),
        "changed": ("Marked the outer packaging photograph missing, as you said.",),
        "left_unchanged": ("The invoice and the customer confirmation.",),
        "reply_to_representative": "You were right, and I have gone back to the merchant for it.",
        "email_subject": "About your damaged shipment",
        "email_body": (
            "Please send a photograph of the outer shipping box with the label visible."
        ),
    }
    fields.update(overrides)
    return RevisionConclusion.model_validate(fields)


@pytest.fixture
def a_scripted_reply(app: FastAPI, shipbob: respx.Router) -> Iterator[list[Any]]:
    """Answer the agent from a script, and serve the sample claims from a stand-in ShipBob.

    The list handed back is the queue: append an answer for each message a test will send, in
    the order it will send them. A product report's message is answered with a
    `RevisionConclusion`; a claim-level or stopped claim's with a `RevisedClaimReport`.
    """
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)
    mock_shipbob(shipbob, case=CASE_1004, shipment=SHIPMENT_1004, order=ORDER_1004)
    # A product rework prices the shipment before it starts, the same way an investigation
    # does, so the stand-in has to answer that too or the request escapes to a name nothing
    # serves.
    shipbob.post("/invoices/generate").respond(200, json=INVOICE_342578703)
    answers: list[Any] = []

    def models() -> tuple[object, StructuredModel]:
        """Both models, from the script, built only once something actually needs them."""
        return (
            scripted(*[AIMessage(content="I have read the note.") for _ in answers]),
            StructuredModel(scripted(*answers), max_attempts=1),
        )

    app.dependency_overrides[get_models] = lambda: models
    yield answers
    app.dependency_overrides.clear()


async def test_fr_r_1_a_note_gets_the_report_reworked_and_handed_back(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    """FR-R.1, FR-R.9: the rep says what is wrong, and the agent reworks the whole report."""
    store.record(a_report())
    a_scripted_reply.append(a_reworked_answer())

    body = (
        await client.post(
            "/reports/RPT-CASE-1001-L01/send-back",
            json={"feedback": "The packaging photo is the box, not the product."},
        )
    ).json()

    assert body["version"] == 2
    assert body["state"] == "awaiting_review"
    assert body["recommendation"] == "request_info"
    assert body["amount_usd"] is None


async def test_fr_r_10_the_reworked_report_says_what_changed_and_what_did_not(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    """FR-R.10: a rep confirms their feedback was understood without re-reading everything."""
    store.record(a_report())
    a_scripted_reply.append(a_reworked_answer())

    body = (
        await client.post(
            "/reports/RPT-CASE-1001-L01/send-back",
            json={"feedback": "The packaging photo is the box, not the product."},
        )
    ).json()

    turn = body["revisions"][-1]
    assert turn["reworked"] is True
    assert turn["feedback"] == "The packaging photo is the box, not the product."
    assert turn["reply"] == "You were right, and I have gone back to the merchant for it."
    assert turn["changed"] == ["Marked the outer packaging photograph missing, as you said."]
    assert turn["left_unchanged"] == ["The invoice and the customer confirmation."]


async def test_fr_r_11_the_merchant_email_is_rewritten_to_match(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    """FR-R.11: a revised recommendation with a stale email is an inconsistent state."""
    store.record(a_report())
    a_scripted_reply.append(a_reworked_answer())

    body = (
        await client.post(
            "/reports/RPT-CASE-1001-L01/send-back",
            json={"feedback": "The packaging photo is the box, not the product."},
        )
    ).json()

    assert "outer shipping box" in body["drafted_email"]["body"]
    assert body["drafted_email"]["is_draft"] is True


async def test_fr_r_13_the_version_the_representative_decided_on_can_still_be_read_back(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    """FR-R.13: every version is kept, because it is the record of how a decision was reached."""
    store.record(a_report())
    a_scripted_reply.append(a_reworked_answer())

    await client.post(
        "/reports/RPT-CASE-1001-L01/send-back", json={"feedback": "Look at the box again."}
    )

    first = (await client.get("/reports/RPT-CASE-1001-L01?version=1")).json()["report"]
    assert first["recommendation"] == "approve"
    assert first["revisions"] == []


async def test_fr_r_12_a_second_note_carries_the_first_one_into_the_rework(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    """FR-R.12: each cycle carries the full feedback history, so a correction is not undone."""
    store.record(a_report())
    a_scripted_reply.append(a_reworked_answer())
    a_scripted_reply.append(
        a_reworked_answer(
            changed=("Also asked for a clearer invoice.",),
            reply_to_representative="Added the invoice to what the merchant is asked for.",
        )
    )

    await client.post(
        "/reports/RPT-CASE-1001-L01/send-back", json={"feedback": "The packaging photo is wrong."}
    )
    body = (
        await client.post(
            "/reports/RPT-CASE-1001-L01/send-back",
            json={"feedback": "Ask for the invoice again while you are there."},
        )
    ).json()

    assert body["version"] == 3
    assert [turn["feedback"] for turn in body["revisions"]] == [
        "The packaging photo is wrong.",
        "Ask for the invoice again while you are there.",
    ]
    assert [turn["turn"] for turn in body["revisions"]] == [1, 2]


async def test_a_reworked_report_can_then_be_approved(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    """FR-2.9: a case may cycle any number of times and still needs a person to release it."""
    store.record(a_report())
    a_scripted_reply.append(a_reworked_answer())

    await client.post(
        "/reports/RPT-CASE-1001-L01/send-back", json={"feedback": "Look at the box again."}
    )
    response = await client.post("/reports/RPT-CASE-1001-L01/approve", json={})

    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    assert response.json()["version"] == 2


# --- A claim nobody could split into products (FR-1a.4, FR-R.1) --------------


def a_clarification_report(**overrides: Any) -> Report:
    """A claim whose split was never settled, so it names no product at all."""
    fields: dict[str, Any] = {
        "report_id": "RPT-CASE-1002",
        "case_id": "CASE-1002",
        "claim_line_id": None,
        "product_name": None,
        "recommendation": "request_info",
        "amount_usd": None,
        "confidence": None,
        "content": ClarificationReportContent(
            context=a_context(),
            ambiguity="The bottle's label is turned away, so it cannot be told apart from the "
            "order's two 24oz lines.",
            concerns=("Two similar products, and nothing distinguishes them.",),
            requested_details=(
                "The exact name and product code of each damaged item",
                "The quantity damaged of each item",
            ),
        ),
    }
    fields.update(overrides)
    return a_report(**fields)


@pytest.fixture
def case_1002(shipbob: respx.Router) -> None:
    """Serve CASE-1002 and its images from the stand-in, for a claim that has to be re-read."""
    mock_shipbob(shipbob, case=CASE_1002, shipment=SHIPMENT_1002, order=ORDER_1002)
    shipbob.get("/cases/CASE-1002/attachments").respond(200, json=ATTACHMENTS_1002)


async def test_fr_r_1_a_claim_that_names_no_product_still_answers_the_representative(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
    """FR-R.1: no report kind swallows a message. The rep asked; the agent answers.

    This is the case the feature was got wrong on first: a report whose whole purpose is to
    ask the representative a question used to refuse the answer to it.
    """
    store.record(a_clarification_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative=(
                "Both 24oz bottles, then. I still need a straight-on photograph of each before "
                "this can be settled."
            ),
            changed=("Dropped the request to name the products, which you have answered.",),
            ambiguity="The products are settled; the damage photographs are not readable.",
            requested_details=("A photograph of each damaged bottle taken straight on",),
            email_subject="About your damaged shipment",
            email_body="Please send a photograph of each damaged bottle taken straight on.",
        )
    )

    body = (
        await client.post(
            "/reports/RPT-CASE-1002/send-back",
            json={"feedback": "Both 24oz bottles were damaged."},
        )
    ).json()

    assert body["version"] == 2
    assert "Both 24oz bottles, then" in body["revisions"][-1]["reply"]
    assert body["content"]["requested_details"] == [
        "A photograph of each damaged bottle taken straight on"
    ]
    assert "straight on" in body["drafted_email"]["body"]


async def test_a_claim_that_names_no_product_can_never_be_given_an_amount(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
    """FR-1.21: nothing on a report that names no product was ever priced, so no figure exists.

    The representative asks outright for a refund. There is no field the answer could put one
    in, so the report comes back with no amount however the model replies.
    """
    store.record(a_clarification_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative="I cannot price this until the claim is investigated.",
            needs_more_from_representative=True,
        )
    )

    body = (
        await client.post(
            "/reports/RPT-CASE-1002/send-back",
            json={"feedback": "approve the refund for the two bottles and generate an email"},
        )
    ).json()

    assert body["amount_usd"] is None
    assert body["recommendation"] != "approve"
    assert body["revisions"][-1]["needs_reply"] is True


async def test_an_answer_that_changes_nothing_leaves_the_report_exactly_as_it_was(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
    """A question answered is not a report reworked, and the two must not be confused.

    A form full of blanks would otherwise read as "nothing is unclear, nothing is needed from
    the merchant, send them nothing" — none of which the agent said.
    """
    before = a_clarification_report()
    store.record(before)
    a_scripted_reply.append(
        RevisedClaimReport(reply_to_representative="Yes, both photographs are of the same box.")
    )

    body = (
        await client.post(
            "/reports/RPT-CASE-1002/send-back",
            json={"feedback": "Are the two photos the same box?"},
        )
    ).json()

    assert body["content"] == before.content.model_dump(mode="json")
    assert body["drafted_email"] == (
        before.drafted_email.model_dump(mode="json") if before.drafted_email else None
    )
    assert body["revisions"][-1]["reworked"] is False


# --- Investigating the claim again, because the rep settled it (FR-1a.4) -----

BOTANICAL = "CleanBoss Botanical Disinfectant & Cleaner 24oz 2 Pack"
MULTI_SURFACE = "CleanBoss Multi Surface Cleaner 24oz"


def a_settled_split() -> ClaimSplit:
    """The split the fresh investigation reaches, now that the rep has named the products."""
    return ClaimSplit(
        claimed_products=(
            ClaimedProductProposal(
                name=MULTI_SURFACE,
                quantity=2,
                sku="A00300",
                reasoning="The representative confirmed both 24oz multi-surface bottles.",
            ),
        ),
        reasoning="The representative settled which products were damaged.",
    )


def an_investigated_line() -> InvestigationConclusion:
    """One product's findings, asking the merchant for the photograph that is still missing."""
    return InvestigationConclusion(
        evidence=(
            EvidenceJudgement(
                kind=EvidenceKind.DAMAGED_PRODUCT_PHOTO,
                state=EvidenceState.UNUSABLE,
                observed="The label is turned away from the camera.",
                attachment_id="ATT-CASE-1002-01",
                problem="The bottle is photographed from behind.",
            ),
        ),
        recommendation=Recommendation.REQUEST_INFO,
        reasoning="The products are settled, but the damage photograph cannot be relied on.",
        requested_details=("A photograph of each damaged bottle taken straight on",),
        email_subject="About your damaged shipment",
        email_body="Please send a photograph of each damaged bottle taken straight on.",
    )


async def test_a_representative_settling_the_split_gets_the_claim_investigated_again(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
    """FR-1a.4: the one honest route from "we cannot tell which product" to a report to approve.

    The agent cannot price a claim nobody could split, so when the representative settles it,
    the claim is investigated properly rather than a figure being invented for it.
    """
    store.record(a_clarification_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative=(
                "Both 24oz multi-surface bottles — I am investigating the claim again on that."
            ),
            needs_fresh_investigation=True,
        )
    )
    a_scripted_reply.append(a_settled_split())
    a_scripted_reply.append(an_investigated_line())

    body = (
        await client.post(
            "/reports/RPT-CASE-1002/send-back",
            json={"feedback": "Both 24oz multi-surface bottles were damaged."},
        )
    ).json()

    assert body["revisions"][-1]["reinvestigated"] is True
    produced = (await client.get("/cases/CASE-1002/reports")).json()["reports"]
    named = [report["product_name"] for report in produced if report["product_name"]]
    assert named == [MULTI_SURFACE]


async def test_a_fresh_investigation_never_overwrites_the_version_the_rep_was_looking_at(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
    """FR-R.13: the record of how a decision was reached survives the claim being redone.

    A fresh investigation writes its reports as version 1, and the claim-level report shares a
    name with the one it would produce for a split it still could not settle. Writing that
    naively would erase the conversation.
    """
    store.record(a_clarification_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative="Investigating it again.", needs_fresh_investigation=True
        )
    )
    a_scripted_reply.append(a_settled_split())
    a_scripted_reply.append(an_investigated_line())

    await client.post(
        "/reports/RPT-CASE-1002/send-back", json={"feedback": "Both multi-surface bottles."}
    )

    first = (await client.get("/reports/RPT-CASE-1002?version=1")).json()["report"]
    assert first["revisions"] == []
    assert first["content"]["kind"] == "clarification"
    latest = (await client.get("/reports/RPT-CASE-1002")).json()["report"]
    assert latest["version"] == 2
    assert len(latest["revisions"]) == 1


async def test_what_the_representative_said_reaches_the_fresh_investigation(
    client: AsyncClient,
    store: ReportStore,
    settings: Settings,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
    """FR-R.14, FR-0.5: their answer travels by the channel that already existed.

    A message is written against the merchant the moment it is sent, and a claim being
    investigated reads those corrections as starting context — so nothing new had to be
    invented to get the representative's answer in front of the split.
    """
    store.record(a_clarification_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative="Investigating it again.", needs_fresh_investigation=True
        )
    )
    a_scripted_reply.append(a_settled_split())
    a_scripted_reply.append(an_investigated_line())

    await client.post(
        "/reports/RPT-CASE-1002/send-back",
        json={"feedback": "Both 24oz multi-surface bottles were damaged."},
    )

    remembered = MerchantMemory(settings.database_path).corrections_for("334430")
    assert [correction.summary for correction in remembered] == [
        "Both 24oz multi-surface bottles were damaged."
    ]


# --- Naming a product, without redoing the whole claim (FR-1a.4) -------------


def a_directed_approval() -> RevisionConclusion:
    """What the product's own pass concludes once the representative has directed a payment."""
    return RevisionConclusion(
        evidence=(
            EvidenceJudgement(
                kind=EvidenceKind.DAMAGED_PRODUCT_PHOTO,
                state=EvidenceState.PRESENT,
                observed="The bottle is split down one side.",
                attachment_id="ATT-CASE-1002-01",
            ),
        ),
        damaged_items=(DamagedItem(product_name=MULTI_SURFACE, quantity=2, sku="A00300"),),
        recommendation=Recommendation.APPROVE,
        reasoning="The representative confirmed the product and directed the refund.",
        recommended_amount_usd="25.98",
        amount_reasoning="Both 24oz bottles are a total loss at 12.99 each.",
        representative_directed_outcome=True,
        changed=("Approved the two multi-surface bottles, as you directed.",),
        reply_to_representative="Done — the refund is drafted for both bottles.",
        email_subject="About your damaged shipment",
        email_body="We have approved your claim for the damaged multi-surface cleaner.",
    )


async def test_naming_a_product_produces_a_priced_report_without_redoing_the_claim(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
    """FR-1a.4: a representative who answers the question should not wait for the whole claim.

    Investigating the claim again re-reads every image, re-splits it, and on a claim nobody
    could split very often fails to split it a second time — leaving the representative who
    just answered that exact question with nothing. Naming the product costs one pass.
    """
    store.record(a_clarification_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative="Taken as read: the 24oz multi surface cleaner.",
            settled_products=(SettledProduct(name=MULTI_SURFACE, quantity=2, sku="A00300"),),
        )
    )
    a_scripted_reply.append(a_directed_approval())

    body = (
        await client.post(
            "/reports/RPT-CASE-1002/send-back",
            json={
                "feedback": (
                    "CleanBoss Multi Surface Cleaner 24oz is the one. "
                    "Generate a refund for the product"
                )
            },
        )
    ).json()

    assert "cannot" not in body["revisions"][-1]["reply"]
    produced = (await client.get("/cases/CASE-1002/reports")).json()["reports"]
    approved = [report for report in produced if report["product_name"] == MULTI_SURFACE]
    assert len(approved) == 1
    assert approved[0]["recommendation"] == "approve"
    assert approved[0]["amount_usd"] == "25.98"
    assert "$25.98" in approved[0]["drafted_email"]["body"]


async def test_a_directed_payment_says_on_the_report_what_it_set_aside(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
    """NFR-5: a payment a representative directed and one the evidence earned must differ."""
    store.record(a_clarification_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative="Taken as read.",
            settled_products=(SettledProduct(name=MULTI_SURFACE, quantity=2, sku="A00300"),),
        )
    )
    a_scripted_reply.append(a_directed_approval())

    await client.post(
        "/reports/RPT-CASE-1002/send-back",
        json={"feedback": "The multi surface cleaner. Refund it."},
    )

    produced = (await client.get("/cases/CASE-1002/reports")).json()["reports"]
    approved = next(r for r in produced if r["product_name"] == MULTI_SURFACE)
    outcome = approved["content"]["outcome"]
    assert outcome["directed_by_representative"] is True
    assert "evidence_incomplete" in outcome["waived"]
