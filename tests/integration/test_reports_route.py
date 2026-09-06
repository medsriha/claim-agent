from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from tests.fakes.model import scripted
from tests.fixtures.attachments import ATTACHMENTS_1002, INVOICE_342578703, invoice_from_order
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
    RevisionMode,
    RevisionPlan,
    SettledProduct,
)
from claim_agent.api.deps import get_models
from claim_agent.app import create_app
from claim_agent.domain.evidence import EvidenceKind, EvidenceState
from claim_agent.domain.outcome import Recommendation
from claim_agent.report.models import (
    ClarificationReportContent,
    InvestigationReportContent,
    Report,
    ReportState,
)
from claim_agent.settings import Settings
from claim_agent.storage.decision_store import DecisionStore
from claim_agent.storage.merchant_memory import MerchantMemory
from claim_agent.storage.report_store import ReportStore

pytestmark = pytest.mark.integration


LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
FAR_AHEAD = datetime(2100, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(settings: Settings) -> ReportStore:
    return ReportStore(settings.database_path)


@pytest.fixture
def decisions(settings: Settings) -> DecisionStore:
    return DecisionStore(settings.database_path)


@pytest.fixture
def app(settings: Settings, store: ReportStore) -> FastAPI:
    return create_app(settings, report_store=store)


@pytest.fixture
async def client(app: FastAPI) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def read_stream(body: str) -> list[tuple[str, dict[str, Any]]]:
    messages: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        lines = [line for line in block.splitlines() if line]
        if not lines:
            continue
        name = next((line[7:] for line in lines if line.startswith("event: ")), "")
        data = next((line[6:] for line in lines if line.startswith("data: ")), "")
        messages.append((name, json.loads(data)))
    return messages


async def send_feedback(client: AsyncClient, report_id: str, feedback: str) -> dict[str, Any]:
    response = await client.post(
        f"/reports/{report_id}/send-back",
        headers={"Accept": "text/event-stream"},
        json={"feedback": feedback},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    messages = read_stream(response.text)
    assert [name for name, _ in messages][-2:] == ["result", "done"]
    return cast(dict[str, Any], (await client.get(f"/reports/{report_id}")).json())


def a_claim_of_two_products(**overrides: Any) -> Report:
    fields: dict[str, Any] = {
        "product_names": ("Liposomal Tripeptide Collagen", "Additional Collagen Ampoule Duo"),
    }
    fields.update(overrides)
    return a_report(**fields)


async def test_fr_2_9b_a_claim_comes_back_as_its_one_report(
    client: AsyncClient, store: ReportStore
) -> None:
    store.record(a_claim_of_two_products())

    response = await client.get("/cases/CASE-1001/reports")

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "CASE-1001"
    assert len(body["reports"]) == 1
    assert len(body["reports"][0]["product_names"]) == 2


async def test_a_claim_nobody_has_asked_about_comes_back_empty(client: AsyncClient) -> None:
    response = await client.get("/cases/CASE-9999/reports")

    assert response.status_code == 200
    assert response.json()["reports"] == []


async def test_money_arrives_as_text_rather_than_a_number(
    client: AsyncClient, store: ReportStore
) -> None:
    store.record(a_report())

    body = (await client.get("/cases/CASE-1001/reports")).json()

    assert body["reports"][0]["amount_usd"] == "52.00"


async def test_fr_2_9a_a_report_names_every_damaged_product_on_its_claim(
    client: AsyncClient, store: ReportStore
) -> None:
    store.record(a_claim_of_two_products())

    body = (await client.get("/reports/RPT-CASE-1001")).json()

    assert body["case_id"] == "CASE-1001"
    assert body["product_names"] == [
        "Liposomal Tripeptide Collagen",
        "Additional Collagen Ampoule Duo",
    ]


async def test_a_claim_of_one_product_names_just_the_one(
    client: AsyncClient, store: ReportStore
) -> None:
    store.record(a_report())

    body = (await client.get("/reports/RPT-CASE-1001")).json()

    assert body["product_names"] == ["Liposomal Tripeptide Collagen"]


async def test_a_report_that_does_not_exist_says_so(client: AsyncClient) -> None:
    response = await client.get("/reports/RPT-NOBODY")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_an_earlier_version_can_be_read_back(client: AsyncClient, store: ReportStore) -> None:
    store.record(a_report(version=1))
    store.record(a_report(version=2))

    latest = (await client.get("/reports/RPT-CASE-1001")).json()
    earlier = (await client.get("/reports/RPT-CASE-1001?version=1")).json()

    assert latest["version"] == 2
    assert earlier["version"] == 1


async def test_approving_a_report_leaves_it_approved_and_records_the_decision(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    store.record(a_report())

    response = await client.post("/reports/RPT-CASE-1001/approve", json={})
    report = store.get("RPT-CASE-1001")

    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    assert report is not None
    assert report.state is ReportState.APPROVED
    assert decisions.count() == 1


async def test_approving_at_a_different_figure_records_both(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    store.record(a_report())

    body = (
        await client.post(
            "/reports/RPT-CASE-1001/approve",
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
    store.record(a_report())

    body = (
        await client.post("/reports/RPT-CASE-1001/approve", json={"amount_usd": "150.00"})
    ).json()

    assert body["state"] == "approved"
    assert body["decided"]["amount_usd"] == "150.00"
    assert body["reviews"][-1]["over_the_cap_by"] == "50.00"


async def test_a_figure_that_is_not_an_amount_is_refused(
    client: AsyncClient, store: ReportStore
) -> None:
    store.record(a_report())

    response = await client.post(
        "/reports/RPT-CASE-1001/approve", json={"amount_usd": "about fifty"}
    )
    report = store.get("RPT-CASE-1001")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"]["amount_usd"] == "about fifty"
    assert report is not None
    assert report.state is ReportState.AWAITING_REVIEW


async def test_a_reworded_email_is_shown_in_full(client: AsyncClient, store: ReportStore) -> None:
    store.record(a_report())

    body = (
        await client.post(
            "/reports/RPT-CASE-1001/approve",
            json={"email": {"subject": "Your claim", "body": "We are refunding you."}},
        )
    ).json()

    assert body["drafted_email"]["body"] == ("We are refunding you.\n\nApproved amount: $52.00")
    assert body["reviews"][-1]["edited_email"]["body"] == "We are refunding you."


async def test_a_recipient_cannot_be_sent_from_a_caller(
    client: AsyncClient, store: ReportStore
) -> None:
    store.record(a_report())

    response = await client.post(
        "/reports/RPT-CASE-1001/approve",
        json={"email": {"subject": "Your claim", "body": "Hello.", "to": "someone@else.test"}},
    )

    assert response.status_code == 422


async def test_approving_twice_leaves_one_decision(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    store.record(a_report())

    first = await client.post("/reports/RPT-CASE-1001/approve", json={})
    again = await client.post("/reports/RPT-CASE-1001/approve", json={})

    assert first.status_code == 200
    assert again.status_code == 200
    assert decisions.count() == 1


async def test_approving_an_approved_report_differently_is_refused(
    client: AsyncClient, store: ReportStore
) -> None:
    store.record(a_report())
    await client.post("/reports/RPT-CASE-1001/approve", json={})

    response = await client.post("/reports/RPT-CASE-1001/approve", json={"amount_usd": "31.20"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_a_claim_the_quick_checks_stopped_can_be_approved(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    store.record(a_screening_report())

    response = await client.post("/reports/RPT-CASE-1004/approve", json={})

    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    assert decisions.count() == 1


async def test_sending_a_report_back_records_the_note_in_the_reps_own_words(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    store.record(a_report())

    body = await send_feedback(
        client, "RPT-CASE-1001", "The packaging photo is the box, not the product."
    )

    assert body["reviews"][-1]["rep_words"] == ("The packaging photo is the box, not the product.")
    assert decisions.count() == 1


async def test_a_note_the_agent_could_not_answer_still_leaves_a_report_to_act_on(
    client: AsyncClient, store: ReportStore
) -> None:
    before = a_report()
    store.record(before)

    body = await send_feedback(client, "RPT-CASE-1001", "Look at the box again.")

    assert body["version"] == before.version
    assert body["state"] == "awaiting_review"
    assert body["recommendation"] == before.recommendation
    assert body["revisions"][-1]["reworked"] is False
    assert "could not be reached" in body["revisions"][-1]["reply"]


async def test_fr_c_2_approving_at_a_different_figure_is_remembered_against_the_merchant(
    client: AsyncClient, store: ReportStore, settings: Settings
) -> None:
    store.record(a_report())

    await client.post(
        "/reports/RPT-CASE-1001/approve",
        json={"amount_usd": "18.00"},
    )

    remembered = MerchantMemory(settings.database_path).corrections_for("334430")
    assert len(remembered) == 1
    assert "$52.00" in remembered[0].summary
    assert "$18.00" in remembered[0].summary
    assert remembered[0].case_id == "CASE-1001"


async def test_fr_c_2_approving_as_it_stands_is_remembered_as_nothing(
    client: AsyncClient, store: ReportStore, settings: Settings
) -> None:
    store.record(a_report())

    await client.post("/reports/RPT-CASE-1001/approve", json={})

    assert MerchantMemory(settings.database_path).corrections_for("334430") == ()


async def test_fr_c_2_rewording_the_email_alone_is_remembered_as_nothing(
    client: AsyncClient, store: ReportStore, settings: Settings
) -> None:
    store.record(a_report())

    await client.post(
        "/reports/RPT-CASE-1001/approve",
        json={"email": {"subject": "Your claim", "body": "We have approved your claim."}},
    )

    assert MerchantMemory(settings.database_path).corrections_for("334430") == ()


async def test_fr_r_14_what_a_representative_said_is_remembered_against_the_merchant(
    client: AsyncClient, store: ReportStore, settings: Settings
) -> None:
    store.record(a_report())

    await client.post(
        "/reports/RPT-CASE-1001/send-back",
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

    body = await send_feedback(client, "RPT-CASE-1004", "Sixty days is too strict.")

    assert decisions.count() == 1
    assert "73 days after delivery" in body["revisions"][-1]["reply"]
    assert body["recommendation"] is None
    assert body["content"] == a_screening_report().content.model_dump(mode="json")


async def test_a_stopped_claims_merchant_email_can_still_be_reworded(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    store.record(a_screening_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative="Softened it, and kept the reason the same.",
            changed=("Reworded the merchant email.",),
            email_subject="About your claim",
            email_body="We are sorry we cannot take this one on. Here is why.",
        )
    )

    body = await send_feedback(client, "RPT-CASE-1004", "That email reads harshly.")

    assert body["drafted_email"]["body"].startswith("We are sorry")
    assert body["content"] == a_screening_report().content.model_dump(mode="json")


async def test_two_different_notes_on_one_report_are_two_decisions(
    client: AsyncClient, store: ReportStore, decisions: DecisionStore
) -> None:
    store.record(a_report())

    await client.post("/reports/RPT-CASE-1001/send-back", json={"feedback": "One."})
    await client.post("/reports/RPT-CASE-1001/send-back", json={"feedback": "Two."})

    assert decisions.count() == 2


async def test_a_report_sent_back_can_still_be_approved(
    client: AsyncClient, store: ReportStore
) -> None:
    store.record(a_report())
    await client.post("/reports/RPT-CASE-1001/send-back", json={"feedback": "Look again."})

    response = await client.post("/reports/RPT-CASE-1001/approve", json={})

    assert response.status_code == 200
    assert response.json()["state"] == "approved"


async def test_an_approved_report_cannot_be_sent_back(
    client: AsyncClient, store: ReportStore
) -> None:
    store.record(a_report())
    await client.post("/reports/RPT-CASE-1001/approve", json={})

    response = await client.post(
        "/reports/RPT-CASE-1001/send-back", json={"feedback": "Actually, no."}
    )

    assert response.status_code == 409


async def test_acting_on_a_report_that_does_not_exist_says_so(client: AsyncClient) -> None:
    response = await client.post("/reports/RPT-NOBODY/approve", json={})

    assert response.status_code == 404


async def test_a_store_that_cannot_be_read_fails_rather_than_reporting_an_empty_claim(
    settings: Settings,
) -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.database_path.write_text("this is not a database at all")
    app = create_app(settings, report_store=ReportStore(settings.database_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/cases/CASE-1001/reports")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"


def a_reworked_answer(**overrides: Any) -> RevisionConclusion:
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


def a_full_rework_plan() -> RevisionPlan:
    return RevisionPlan(
        mode=RevisionMode.REWORK_REPORT,
        reply_to_representative="I need to revisit the report evidence for that.",
    )


def queue_full_rework(answers: list[Any], conclusion: RevisionConclusion | None = None) -> None:
    answers.extend((a_full_rework_plan(), conclusion or a_reworked_answer()))


@pytest.fixture
def a_scripted_reply(app: FastAPI, shipbob: respx.Router) -> Iterator[list[Any]]:
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)
    mock_shipbob(shipbob, case=CASE_1004, shipment=SHIPMENT_1004, order=ORDER_1004)

    shipbob.post("/invoices/generate").respond(200, json=INVOICE_342578703)
    answers: list[Any] = []

    def models() -> tuple[object, StructuredModel]:
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
    store.record(a_report())
    queue_full_rework(a_scripted_reply)

    body = await send_feedback(
        client, "RPT-CASE-1001", "The packaging photo is the box, not the product."
    )

    assert body["version"] == 2
    assert body["state"] == "awaiting_review"
    assert body["recommendation"] == "request_info"
    assert body["amount_usd"] is None


async def test_feedback_streams_progress_and_only_returns_a_report_reference(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    store.record(a_report())
    queue_full_rework(a_scripted_reply)

    response = await client.post(
        "/reports/RPT-CASE-1001/send-back",
        headers={"Accept": "text/event-stream"},
        json={"feedback": "The packaging photo is the box, not the product."},
    )

    messages = read_stream(response.text)
    assert next(name for name, _ in messages) == "progress"
    assert [name for name, _ in messages][-2:] == ["result", "done"]
    result = next(payload for name, payload in messages if name == "result")
    assert set(result) == {"report_id", "report_version", "revision"}
    assert result["report_version"] == 2
    assert "content" not in result
    assert "reply" in result["revision"]


async def test_generating_an_email_uses_the_stored_report_without_reopening_evidence(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    shipbob: respx.Router,
) -> None:
    store.record(a_report())
    a_scripted_reply.append(
        RevisionPlan(
            mode=RevisionMode.EMAIL_ONLY,
            reply_to_representative="I generated the refund email.",
            changed=("Rewrote the merchant email as requested.",),
            left_unchanged=("The evidence, recommendation, and approved amount.",),
            email_subject="Your damaged-shipment refund",
            email_body="We approved your claim for the damaged item.",
        )
    )

    response = await client.post(
        "/reports/RPT-CASE-1001/send-back",
        headers={"Accept": "text/event-stream"},
        json={"feedback": "Generate the refund email."},
    )

    messages = read_stream(response.text)
    result = next(payload for name, payload in messages if name == "result")
    report = (await client.get("/reports/RPT-CASE-1001")).json()
    progress_kinds = {payload["kind"] for name, payload in messages if name == "progress"}
    assert result["report_version"] == 2
    assert report["drafted_email"]["subject"] == "Your damaged-shipment refund"
    assert "We approved your claim" in report["drafted_email"]["body"]
    assert "Approved amount: $52.00" in report["drafted_email"]["body"]
    assert progress_kinds.isdisjoint({"investigation_started", "tool_called", "image_classified"})
    assert len(shipbob.calls) == 0


async def test_a_question_uses_the_stored_report_without_creating_a_report_version(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    shipbob: respx.Router,
) -> None:
    store.record(a_report())
    a_scripted_reply.append(
        RevisionPlan(
            mode=RevisionMode.ANSWER_ONLY,
            reply_to_representative=(
                "The refund was recommended because the stored evidence supports the claim."
            ),
            left_unchanged=("The complete report.",),
        )
    )

    response = await client.post(
        "/reports/RPT-CASE-1001/send-back",
        headers={"Accept": "text/event-stream"},
        json={"feedback": "Why was this refund recommended?"},
    )

    messages = read_stream(response.text)
    result = next(payload for name, payload in messages if name == "result")
    assert result["report_version"] is None
    assert len(store.versions_of("RPT-CASE-1001")) == 1
    assert len(shipbob.calls) == 0


async def test_fr_r_10_the_reworked_report_says_what_changed_and_what_did_not(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    store.record(a_report())
    queue_full_rework(a_scripted_reply)

    body = await send_feedback(
        client, "RPT-CASE-1001", "The packaging photo is the box, not the product."
    )

    turn = body["revisions"][-1]
    assert turn["reworked"] is True
    assert turn["feedback"] == "The packaging photo is the box, not the product."
    assert turn["reply"] == "You were right, and I have gone back to the merchant for it."
    assert turn["changed"] == ["Marked the outer packaging photograph missing, as you said."]
    assert turn["left_unchanged"] == ["The invoice and the customer confirmation."]


async def test_fr_r_11_the_merchant_email_is_rewritten_to_match(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    store.record(a_report())
    queue_full_rework(a_scripted_reply)

    body = await send_feedback(
        client, "RPT-CASE-1001", "The packaging photo is the box, not the product."
    )

    assert "outer shipping box" in body["drafted_email"]["body"]
    assert body["drafted_email"]["is_draft"] is True


async def test_fr_r_13_the_version_the_representative_decided_on_can_still_be_read_back(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    store.record(a_report())
    queue_full_rework(a_scripted_reply)

    await client.post(
        "/reports/RPT-CASE-1001/send-back", json={"feedback": "Look at the box again."}
    )

    first = (await client.get("/reports/RPT-CASE-1001?version=1")).json()
    assert first["recommendation"] == "approve"
    assert first["revisions"] == []


async def test_fr_r_12_a_second_note_carries_the_first_one_into_the_rework(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    store.record(a_report())
    queue_full_rework(a_scripted_reply)
    queue_full_rework(
        a_scripted_reply,
        a_reworked_answer(
            changed=("Also asked for a clearer invoice.",),
            reply_to_representative="Added the invoice to what the merchant is asked for.",
        ),
    )

    await client.post(
        "/reports/RPT-CASE-1001/send-back", json={"feedback": "The packaging photo is wrong."}
    )
    body = await send_feedback(
        client, "RPT-CASE-1001", "Ask for the invoice again while you are there."
    )

    assert body["version"] == 2
    assert [turn["feedback"] for turn in body["revisions"]] == [
        "The packaging photo is wrong.",
        "Ask for the invoice again while you are there.",
    ]
    assert [turn["turn"] for turn in body["revisions"]] == [1, 2]


async def test_a_reworked_report_can_then_be_approved(
    client: AsyncClient, store: ReportStore, a_scripted_reply: list[Any]
) -> None:
    store.record(a_report())
    queue_full_rework(a_scripted_reply)

    await client.post(
        "/reports/RPT-CASE-1001/send-back", json={"feedback": "Look at the box again."}
    )
    response = await client.post("/reports/RPT-CASE-1001/approve", json={})

    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    assert response.json()["version"] == 2


def a_clarification_report(**overrides: Any) -> Report:
    fields: dict[str, Any] = {
        "report_id": "RPT-CASE-1002",
        "case_id": "CASE-1002",
        "product_names": (),
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
    mock_shipbob(shipbob, case=CASE_1002, shipment=SHIPMENT_1002, order=ORDER_1002)
    shipbob.get("/cases/CASE-1002/attachments").respond(200, json=ATTACHMENTS_1002)


async def test_fr_r_1_a_claim_that_names_no_product_still_answers_the_representative(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
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

    body = await send_feedback(client, "RPT-CASE-1002", "Both 24oz bottles were damaged.")

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
    store.record(a_clarification_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative="I cannot price this until the claim is investigated.",
            needs_more_from_representative=True,
        )
    )

    body = await send_feedback(
        client,
        "RPT-CASE-1002",
        "approve the refund for the two bottles and generate an email",
    )

    assert body["amount_usd"] is None
    assert body["recommendation"] != "approve"
    assert body["revisions"][-1]["needs_reply"] is True


async def test_an_answer_that_changes_nothing_leaves_the_report_exactly_as_it_was(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
    before = a_clarification_report()
    store.record(before)
    a_scripted_reply.append(
        RevisedClaimReport(reply_to_representative="Yes, both photographs are of the same box.")
    )

    response = await client.post(
        "/reports/RPT-CASE-1002/send-back",
        headers={"Accept": "text/event-stream"},
        json={"feedback": "Are the two photos the same box?"},
    )
    result = next(payload for name, payload in read_stream(response.text) if name == "result")
    body = (await client.get("/reports/RPT-CASE-1002")).json()

    assert result["report_version"] is None
    assert len(store.versions_of("RPT-CASE-1002")) == 1
    assert body["content"] == before.content.model_dump(mode="json")
    assert body["drafted_email"] == (
        before.drafted_email.model_dump(mode="json") if before.drafted_email else None
    )
    assert body["revisions"][-1]["reworked"] is False


BOTANICAL = "CleanBoss Botanical Disinfectant & Cleaner 24oz 2 Pack"
MULTI_SURFACE = "CleanBoss Multi Surface Cleaner 24oz"


def a_settled_split() -> ClaimSplit:
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

    body = await send_feedback(
        client, "RPT-CASE-1002", "Both 24oz multi-surface bottles were damaged."
    )

    assert body["revisions"][-1]["reinvestigated"] is True
    (produced,) = (await client.get("/cases/CASE-1002/reports")).json()["reports"]
    assert produced["product_names"] == [MULTI_SURFACE]


async def test_a_fresh_investigation_never_overwrites_the_version_the_rep_was_looking_at(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
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

    first = (await client.get("/reports/RPT-CASE-1002?version=1")).json()
    assert first["revisions"] == []
    assert first["content"]["kind"] == "clarification"
    latest = (await client.get("/reports/RPT-CASE-1002")).json()
    assert latest["version"] == 2
    assert len(latest["revisions"]) == 1


async def test_what_the_representative_said_reaches_the_fresh_investigation(
    client: AsyncClient,
    store: ReportStore,
    settings: Settings,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
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


def a_directed_approval() -> RevisionConclusion:
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
    store.record(a_clarification_report())
    a_scripted_reply.append(
        RevisedClaimReport(
            reply_to_representative="Taken as read: the 24oz multi surface cleaner.",
            settled_products=(SettledProduct(name=MULTI_SURFACE, quantity=2, sku="A00300"),),
        )
    )
    a_scripted_reply.append(a_directed_approval())

    body = await send_feedback(
        client,
        "RPT-CASE-1002",
        "CleanBoss Multi Surface Cleaner 24oz is the one. Generate a refund for the product",
    )

    assert "cannot" not in body["revisions"][-1]["reply"]
    (approved,) = (await client.get("/cases/CASE-1002/reports")).json()["reports"]
    assert approved["product_names"] == [MULTI_SURFACE]
    assert approved["recommendation"] == "approve"
    assert approved["amount_usd"] == "25.98"
    assert "$25.98" in approved["drafted_email"]["body"]


async def test_a_directed_payment_says_on_the_report_what_it_set_aside(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
) -> None:
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

    (approved,) = (await client.get("/cases/CASE-1002/reports")).json()["reports"]
    outcome = approved["content"]["outcome"]
    assert outcome["directed_by_representative"] is True
    assert "evidence_incomplete" in outcome["waived"]


def a_report_asking_the_merchant() -> Report:
    asking = a_report()
    content = asking.content
    assert isinstance(content, InvestigationReportContent)
    return asking.model_copy(
        update={
            "recommendation": Recommendation.REQUEST_INFO,
            "amount_usd": None,
            "content": content.model_copy(
                update={
                    "outcome": content.outcome.model_copy(
                        update={"recommendation": Recommendation.REQUEST_INFO}
                    ),
                    "requested_details": ("a clear photograph showing the full product label",),
                }
            ),
        }
    )


def an_approval_as_directed(**overrides: Any) -> RevisedClaimReport:
    fields: dict[str, Any] = {
        "reply_to_representative": "Taken as read: the multi surface cleaner. Pricing it now.",
        "settled_products": (SettledProduct(name=MULTI_SURFACE, quantity=2, sku="A00300"),),
        "representative_directed_payment": True,
        "email_subject": "Your damage claim has been approved",
        "email_body": "We have approved your claim for the damaged multi surface cleaner.",
    }
    fields.update(overrides)
    return RevisedClaimReport.model_validate(fields)


@pytest.fixture
def invoice_1002(shipbob: respx.Router) -> None:
    shipbob.post("/invoices/generate").respond(
        200, json=invoice_from_order(ORDER_1002, shipment_id="344745459")
    )


async def test_an_instruction_to_pay_a_named_product_is_priced_and_not_investigated(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    shipbob: respx.Router,
    case_1002: None,
    invoice_1002: None,
) -> None:
    store.record(a_clarification_report())
    a_scripted_reply.append(an_approval_as_directed())

    response = await client.post(
        "/reports/RPT-CASE-1002/send-back",
        headers={"Accept": "text/event-stream"},
        json={"feedback": "The multi surface cleaner is the one. Approve the refund."},
    )

    messages = read_stream(response.text)
    progress_kinds = {payload["kind"] for name, payload in messages if name == "progress"}
    assert progress_kinds.isdisjoint({"tool_called", "image_classified", "attachments_listed"})
    assert not any("/attachments" in str(call.request.url) for call in shipbob.calls)

    (approved,) = (await client.get("/cases/CASE-1002/reports")).json()["reports"]
    assert approved["version"] == 2
    assert approved["product_names"] == [MULTI_SURFACE]
    assert approved["recommendation"] == "approve"
    assert approved["amount_usd"] == "25.98"
    assert "Approved amount: $25.98" in approved["drafted_email"]["body"]
    assert approved["content"]["outcome"]["directed_by_representative"] is True
    round_ = approved["revisions"][-1]
    assert round_["reworked"] is True
    assert round_["reinvestigated"] is False
    assert "$25.98" in round_["reply"]
    assert "cannot" not in round_["reply"]


async def test_a_figure_the_representative_named_is_what_a_named_product_is_paid(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    case_1002: None,
    invoice_1002: None,
) -> None:
    store.record(a_clarification_report())
    a_scripted_reply.append(an_approval_as_directed(directed_amount_usd="20.00"))

    body = await send_feedback(
        client, "RPT-CASE-1002", "The multi surface cleaner. Refund twenty dollars."
    )

    assert body["amount_usd"] == "20.00"
    assert "Approved amount: $20.00" in body["drafted_email"]["body"]


async def test_approving_an_investigated_report_costs_one_invoice_read(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    shipbob: respx.Router,
) -> None:
    store.record(a_report_asking_the_merchant())
    a_scripted_reply.append(
        RevisionPlan(
            mode=RevisionMode.APPROVE_AS_DIRECTED,
            reply_to_representative="Approving it as you directed.",
            changed=("Approved the collagen as you directed.",),
            left_unchanged=("Every finding about the evidence.",),
            email_subject="Your damage claim has been approved",
            email_body="We have approved your claim for the damaged collagen.",
        )
    )

    response = await client.post(
        "/reports/RPT-CASE-1001/send-back",
        headers={"Accept": "text/event-stream"},
        json={"feedback": "Approve the refund."},
    )

    messages = read_stream(response.text)
    progress_kinds = {payload["kind"] for name, payload in messages if name == "progress"}
    assert progress_kinds.isdisjoint({"tool_called", "image_classified"})
    assert [str(call.request.url.path) for call in shipbob.calls].count("/invoices/generate") == 1
    assert not any("/attachments" in str(call.request.url) for call in shipbob.calls)

    report = (await client.get("/reports/RPT-CASE-1001")).json()
    assert report["version"] == 2
    assert report["recommendation"] == "approve"
    assert report["amount_usd"] == "52.00"
    assert "Approved amount: $52.00" in report["drafted_email"]["body"]
    assert report["content"]["outcome"]["directed_by_representative"] is True
    assert report["content"]["evidence"] == a_report().content.model_dump(mode="json")["evidence"]
    round_ = report["revisions"][-1]
    assert round_["reworked"] is True
    assert round_["reinvestigated"] is False
    assert round_["changed"] == ["Approved the collagen as you directed."]
    assert round_["reply"].startswith("Approving it as you directed.")


async def test_a_directed_payment_nobody_can_price_asks_for_the_figure_and_keeps_the_draft(
    client: AsyncClient,
    store: ReportStore,
    a_scripted_reply: list[Any],
    shipbob: respx.Router,
    case_1002: None,
) -> None:
    store.record(a_clarification_report())
    shipbob.post("/invoices/generate").respond(422, json={"error": "invoice_unavailable"})
    a_scripted_reply.append(an_approval_as_directed())

    body = await send_feedback(
        client, "RPT-CASE-1002", "The multi surface cleaner is the one. Approve the refund."
    )

    assert body["recommendation"] == "request_rep_clarification"
    assert body["amount_usd"] is None
    assert body["drafted_email"]["subject"] == "Your damage claim has been approved"
    assert "Approved amount" not in body["drafted_email"]["body"]
    round_ = body["revisions"][-1]
    assert round_["needs_reply"] is True
    assert "Tell me the amount" in round_["reply"]
