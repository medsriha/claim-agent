from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
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
from claim_agent.agent.schemas import (
    AssessmentJudgement,
    ClaimedProductProposal,
    ClaimSplit,
    DamagedItem,
    EvidenceJudgement,
    InvestigationConclusion,
)
from claim_agent.api.deps import get_models
from claim_agent.app import create_app
from claim_agent.domain.assessment import AssessmentName
from claim_agent.domain.evidence import EvidenceKind, EvidenceState
from claim_agent.domain.outcome import Recommendation
from claim_agent.settings import Settings
from claim_agent.storage.decision_store import DecisionStore
from claim_agent.storage.report_store import ReportStore

pytestmark = pytest.mark.integration


def read_stream(body: str) -> list[tuple[str, str]]:
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
    return [name for name, _ in messages]


@pytest.fixture
def a_scripted_investigation(app: FastAPI) -> Iterator[None]:
    app.dependency_overrides[get_models] = lambda: an_unsettled_split
    yield
    app.dependency_overrides.clear()


def an_unsettled_split() -> tuple[object, StructuredModel]:
    return (
        scripted(AIMessage(content="I have read the claim.")),
        StructuredModel(
            scripted(
                ClaimSplit(
                    is_ambiguous=True,
                    ambiguity="The photographs do not say which of the two products broke.",
                    reasoning="Two similar products, and nothing distinguishes them.",
                )
            ),
            max_attempts=1,
        ),
    )


def a_merchant_resolvable_split() -> tuple[object, StructuredModel]:
    detail = "a clear photograph showing the damaged product's front label"
    return (
        scripted(AIMessage(content="I have read the claim.")),
        StructuredModel(
            scripted(
                ClaimSplit(
                    is_ambiguous=True,
                    ambiguity="The photograph does not distinguish two similar products.",
                    requested_details=(detail,),
                    email_subject="More information needed for your claim",
                    email_body=f"Please send {detail}.",
                    reasoning="The product label is not legible.",
                )
            ),
            max_attempts=1,
        ),
    )


A_REMARK_IN_SEVERAL_LINES = (
    "Here is what I am weighing up:\n"
    "\n"
    "- The **box** is crushed.\n"
    "- The bottle inside looks intact.\n"
    "\n"
    "So I will look at the third photograph next."
)


@pytest.fixture
def an_investigation_that_writes_a_list(app: FastAPI) -> Iterator[None]:
    def scripted_models() -> tuple[object, StructuredModel]:
        return (
            scripted(AIMessage(content=A_REMARK_IN_SEVERAL_LINES)),
            StructuredModel(
                scripted(
                    ClaimSplit(
                        is_ambiguous=True,
                        ambiguity="The photographs do not say which of the two products broke.",
                        reasoning="Two similar products, and nothing distinguishes them.",
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
    shipbob.get("/cases/CASE-1004").respond(200, json=CASE_1004)
    shipbob.get("/shipments/330936165").respond(200, json=SHIPMENT_1004)
    shipbob.get("/orders/322882110").respond(200, json=ORDER_1004)
    images = shipbob.get("/cases/CASE-1004/attachments").respond(200, json=ATTACHMENTS_1004)
    invoicing = shipbob.post("/invoices/generate").respond(200, json=INVOICE_342578703)

    response = await client.post("/cases/CASE-1004/investigate")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    messages = read_stream(response.text)

    assert names(messages) == ["progress", "progress", "result", "done"]
    assert "cannot be processed" in messages[0][1]
    assert "The report is ready for review." in messages[1][1]
    result = json.loads(messages[2][1])
    assert set(result) == {"report", "report_unavailable_reason"}
    assert result["report"]["content"]["reasons"] == ["claim_too_old"]

    assert images.call_count == 0
    assert invoicing.call_count == 0


async def test_a_case_shipbob_does_not_have_ends_the_stream_with_a_reason(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    shipbob.get("/cases/CASE-9999").respond(404, json=CASE_NOT_FOUND_BODY)

    response = await client.post("/cases/CASE-9999/investigate")

    assert response.status_code == 200
    messages = read_stream(response.text)
    assert names(messages) == ["failed", "done"]
    assert "not_found" in messages[0][1]


async def test_an_investigation_says_what_it_is_doing_before_it_says_what_it_found(
    client: AsyncClient, shipbob: respx.Router, a_scripted_investigation: None
) -> None:
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

    assert said.count("progress") > 1
    assert "passed the eligibility checks" in messages[0][1]


async def test_what_the_investigation_says_arrives_whole_and_in_one_message(
    client: AsyncClient, shipbob: respx.Router, an_investigation_that_writes_a_list: None
) -> None:
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
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)
    shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)

    response = await client.post("/cases/CASE-1001/investigate")

    messages = read_stream(response.text)
    assert any(
        "which of the two products broke" in data for name, data in messages if name == "progress"
    )

    result = json.loads(next(data for name, data in messages if name == "result"))
    report = result["report"]
    assert report["recommendation"] == "request_rep_clarification"
    assert report["confidence"] is None
    assert report["drafted_email"] is None
    assert "which of the two products broke" in report["content"]["ambiguity"]


async def test_a_claim_that_needs_a_model_and_has_no_key_is_told_so_on_the_stream(
    client: AsyncClient, shipbob: respx.Router
) -> None:
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
    shipbob.get("/cases/CASE-1004").respond(200, json=CASE_1004)
    shipbob.get("/shipments/330936165").respond(200, json=SHIPMENT_1004)
    shipbob.get("/orders/322882110").respond(200, json=ORDER_1004)

    response = await client.post("/cases/CASE-1004/investigate")

    assert response.status_code == 200
    assert names(read_stream(response.text)) == ["progress", "progress", "result", "done"]


async def test_a_stopped_claim_keeps_its_write_up_so_it_can_be_approved_later(
    settings: Settings, shipbob: respx.Router
) -> None:
    shipbob.get("/cases/CASE-1004").respond(200, json=CASE_1004)
    shipbob.get("/shipments/330936165").respond(200, json=SHIPMENT_1004)
    shipbob.get("/orders/322882110").respond(200, json=ORDER_1004)
    reports = ReportStore(settings.database_path)
    app = create_app(settings, report_store=reports)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post("/cases/CASE-1004/investigate")

    result = json.loads(dict(read_stream(response.text))["result"])
    assert set(result) == {"report", "report_unavailable_reason"}
    assert result["report_unavailable_reason"] is None
    kept = result["report"]
    assert kept["stage"] == "screening"
    assert kept["product_names"] == []

    assert len(reports.for_case("CASE-1004").reports) == 1


async def test_asking_twice_keeps_one_report_rather_than_two(
    settings: Settings, shipbob: respx.Router
) -> None:
    shipbob.get("/cases/CASE-1004").respond(200, json=CASE_1004)
    shipbob.get("/shipments/330936165").respond(200, json=SHIPMENT_1004)
    shipbob.get("/orders/322882110").respond(200, json=ORDER_1004)
    reports = ReportStore(settings.database_path)
    app = create_app(settings, report_store=reports)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        await http.post("/cases/CASE-1004/investigate")
        await http.post("/cases/CASE-1004/investigate")

    assert len(reports.for_case("CASE-1004").reports) == 1


async def test_a_store_that_cannot_be_written_still_reports_what_was_found(
    settings: Settings, shipbob: respx.Router, tmp_path: Path
) -> None:
    shipbob.get("/cases/CASE-1004").respond(200, json=CASE_1004)
    shipbob.get("/shipments/330936165").respond(200, json=SHIPMENT_1004)
    shipbob.get("/orders/322882110").respond(200, json=ORDER_1004)
    unwritable = tmp_path / "reports.db"
    unwritable.write_text("this is not a database at all")
    app = create_app(settings, report_store=ReportStore(unwritable))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post("/cases/CASE-1004/investigate")

    assert response.status_code == 200
    messages = dict(read_stream(response.text))
    result = json.loads(messages["result"])

    assert result["report"]["content"]["reasons"] == ["claim_too_old"]
    assert "cannot be approved yet" in result["report_unavailable_reason"]


async def test_a_split_nobody_could_settle_keeps_a_clarification_report(
    settings: Settings, shipbob: respx.Router
) -> None:
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)
    shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)
    shipbob.post("/invoices/generate").respond(200, json=INVOICE_342578703)
    reports = ReportStore(settings.database_path)
    app = create_app(settings, report_store=reports)
    app.dependency_overrides[get_models] = lambda: an_unsettled_split

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post("/cases/CASE-1001/investigate")

    result = json.loads(dict(read_stream(response.text))["result"])
    report = result["report"]
    assert report["recommendation"] == "request_rep_clarification"
    assert report["drafted_email"] is None
    assert result["report_unavailable_reason"] is None
    (kept,) = reports.for_case("CASE-1001").reports
    assert kept.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert kept.drafted_email is None


async def test_a_merchant_resolvable_split_returns_a_request_and_email(
    settings: Settings, shipbob: respx.Router
) -> None:
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)
    shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)
    reports = ReportStore(settings.database_path)
    app = create_app(settings, report_store=reports)
    app.dependency_overrides[get_models] = lambda: a_merchant_resolvable_split

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post("/cases/CASE-1001/investigate")

    result = json.loads(dict(read_stream(response.text))["result"])
    report = result["report"]
    detail = "a clear photograph showing the damaged product's front label"
    assert report["recommendation"] == "request_info"
    assert report["content"]["requested_details"] == [detail]
    assert detail in report["drafted_email"]["body"]
    (kept,) = reports.for_case("CASE-1001").reports
    assert kept.recommendation is Recommendation.REQUEST_INFO
    assert kept.drafted_email is not None


def a_settled_investigation() -> tuple[object, StructuredModel]:
    return (
        scripted(
            AIMessage(content="I have read the claim."),
            AIMessage(content="I have looked at the photographs."),
        ),
        StructuredModel(
            scripted(
                ClaimSplit(
                    claimed_products=(
                        ClaimedProductProposal(
                            name="Liposomal Tripeptide Collagen",
                            sku="COLLAGEN1",
                            quantity=1,
                            damage_attachment_ids=("ATT-CASE-1001-03",),
                            reasoning="The photographs show this bottle broken.",
                        ),
                    ),
                    reasoning="One product is named and photographed.",
                ),
                InvestigationConclusion(
                    evidence=tuple(
                        EvidenceJudgement(
                            kind=kind,
                            state=(
                                EvidenceState.MISSING
                                if kind is EvidenceKind.OUTER_PACKAGING_PHOTO
                                else EvidenceState.PRESENT
                            ),
                            observed=(
                                "No outer packaging photo was attached."
                                if kind is EvidenceKind.OUTER_PACKAGING_PHOTO
                                else f"The {kind.value.replace('_', ' ')} is there and readable."
                            ),
                            attachment_id=(
                                None
                                if kind is EvidenceKind.OUTER_PACKAGING_PHOTO
                                else "ATT-CASE-1001-02"
                            ),
                        )
                        for kind in EvidenceKind
                    ),
                    assessments=tuple(
                        AssessmentJudgement(
                            name=name,
                            passed=True,
                            reasoning="Established from the photographs.",
                        )
                        for name in AssessmentName
                    ),
                    damaged_items=(
                        DamagedItem(
                            product_name="Liposomal Tripeptide Collagen",
                            sku="COLLAGEN1",
                            quantity=1,
                        ),
                    ),
                    recommendation=Recommendation.REQUEST_INFO,
                    reasoning="The bottle is smashed, but the claim's evidence is not all in.",
                    concerns=("The outer mailer is only lightly marked.",),
                    email_subject="About your claim",
                    email_body="Could you send us a photograph of the outer box?",
                ),
            ),
            max_attempts=1,
        ),
    )


async def test_a_claim_that_reaches_a_recommendation_keeps_a_report_per_product(
    settings: Settings, shipbob: respx.Router
) -> None:
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)
    shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)
    shipbob.post("/invoices/generate").respond(200, json=INVOICE_342578703)
    reports = ReportStore(settings.database_path)
    app = create_app(settings, report_store=reports)
    app.dependency_overrides[get_models] = lambda: a_settled_investigation

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post("/cases/CASE-1001/investigate")
        kept = (await http.get("/cases/CASE-1001/reports")).json()

    result = json.loads(dict(read_stream(response.text))["result"])
    assert result["report_unavailable_reason"] is None
    report = result["report"]
    assert report["stage"] == "investigation"
    assert report["product_names"] == ["Liposomal Tripeptide Collagen"]
    assert report["recommendation"] == "request_info"
    requested_details = report["content"]["requested_details"]
    assert "a photo of the outer shipping box the order arrived in, damaged or not" in (
        requested_details
    )
    assert report["drafted_email"] is not None
    assert all(detail in report["drafted_email"]["body"] for detail in requested_details)
    assert report["content"]["attachments"][0]["url"].startswith("https://")

    assert report["amount_usd"] is None
    assert isinstance(report["content"]["amount"]["proposed_usd"], str)

    assert len(kept["reports"]) == 1


async def test_a_kept_report_can_then_be_approved(
    settings: Settings, shipbob: respx.Router
) -> None:
    shipbob.get("/cases/CASE-1001").respond(200, json=CASE_1001)
    shipbob.get("/shipments/342578703").respond(200, json=SHIPMENT_1001)
    shipbob.get("/orders/334291211").respond(200, json=ORDER_1001)
    shipbob.get("/cases/CASE-1001/attachments").respond(200, json=ATTACHMENTS_1001)
    shipbob.post("/invoices/generate").respond(200, json=INVOICE_342578703)
    app = create_app(settings, report_store=ReportStore(settings.database_path))
    app.dependency_overrides[get_models] = lambda: a_settled_investigation

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post("/cases/CASE-1001/investigate")
        report_id = json.loads(dict(read_stream(response.text))["result"])["report"]["report_id"]
        approved = await http.post(f"/reports/{report_id}/approve", json={"amount_usd": "31.20"})

    assert approved.status_code == 200
    body = approved.json()
    assert body["state"] == "approved"
    assert body["decided"]["amount_usd"] == "31.20"
    assert DecisionStore(settings.database_path).count() == 1
