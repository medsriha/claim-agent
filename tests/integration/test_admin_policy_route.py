from __future__ import annotations

from datetime import UTC, datetime

import pytest
import respx
from httpx import AsyncClient
from tests.fixtures.decisions import investigated
from tests.fixtures.shipbob import CASE_1001, ORDER_1001, SHIPMENT_1001, mock_shipbob
from tests.unit.test_report_models import a_report

from claim_agent.domain.models import MerchantCorrection
from claim_agent.policy import Policy
from claim_agent.settings import Settings
from claim_agent.storage.decision_store import DecisionStore
from claim_agent.storage.merchant_memory import MerchantMemory
from claim_agent.storage.report_store import ReportStore

pytestmark = pytest.mark.integration


async def test_reading_the_policy_lists_the_thresholds_the_panel_offers(
    client: AsyncClient,
) -> None:
    response = await client.get("/admin/policy")

    assert response.status_code == 200
    body = response.json()
    offered = [value["name"] for value in body["values"]]
    assert offered == [
        "reimbursement_cap_usd",
        "max_claim_age_days",
        "age_limit_inclusive",
        "high_value_order_usd",
        "high_value_inclusive",
        "damaged_in_transit_sub_category",
    ]
    assert set(Policy.model_fields) - set(offered) == {
        "min_description_length",
        "max_agent_steps",
        "max_tool_calls_per_step",
        "max_image_analyses_per_run",
        "precedent_results_per_product",
        "min_precedent_similarity",
        "usd_conversion_rates",
        "conversion_rates_as_of",
        "assume_usd_when_currency_unknown",
        "default_date_region",
        "price_divergence_fraction",
        "document_total_tolerance",
        "unanswerable_case_statuses",
        "internal_email_domain",
        "min_order_reference_confidence",
        "min_item_match_confidence",
    }
    assert body["matches_startup"] is True
    assert body["changed_at"] is None


async def test_a_threshold_the_panel_does_not_offer_is_refused_over_http(
    client: AsyncClient,
) -> None:
    response = await client.put("/admin/policy", json={"values": {"max_agent_steps": "5"}})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert "cannot be changed from the admin panel" in response.json()["error"]["message"]


async def test_a_changed_threshold_judges_the_very_next_claim(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    before = await client.post("/cases/CASE-1001/preflight")
    assert before.json()["verdict"] == "proceed"

    changed = await client.put("/admin/policy", json={"values": {"max_claim_age_days": "5"}})
    assert changed.status_code == 200

    after = await client.post("/cases/CASE-1001/preflight")
    assert after.status_code == 200
    assert after.json()["verdict"] == "terminal"
    assert after.json()["terminal_reasons"] == ["claim_too_old"]


async def test_the_merchant_email_quotes_the_new_limit(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)
    await client.put("/admin/policy", json={"values": {"max_claim_age_days": "5"}})

    screened = await client.post("/cases/CASE-1001/preflight")

    email_body = screened.json()["report"]["drafted_email"]["body"]
    assert "8 days" in email_body
    assert "5 days" in email_body


async def test_a_change_is_reported_back_with_what_it_started_as(client: AsyncClient) -> None:
    response = await client.put("/admin/policy", json={"values": {"max_claim_age_days": "5"}})

    body = response.json()
    age_limit = next(value for value in body["values"] if value["name"] == "max_claim_age_days")
    assert age_limit["value"] == "5"
    assert age_limit["startup_value"] == "60"
    assert age_limit["changed"] is True
    assert body["matches_startup"] is False
    assert body["changed_at"] is not None


async def test_a_refused_change_leaves_later_claims_alone(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)

    refused = await client.put(
        "/admin/policy",
        json={"values": {"max_claim_age_days": "5", "max_agent_steps": "0"}},
    )

    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "invalid_request"
    complaints = refused.json()["error"]["details"]["values"]
    assert [complaint["name"] for complaint in complaints] == ["max_agent_steps"]

    still_in_force = await client.get("/admin/policy")
    assert still_in_force.json()["matches_startup"] is True

    screened = await client.post("/cases/CASE-1001/preflight")
    assert screened.json()["verdict"] == "proceed"


async def test_a_name_that_is_no_part_of_the_policy_is_refused(client: AsyncClient) -> None:
    response = await client.put("/admin/policy", json={"values": {"made_up_value": "5"}})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert "made_up_value" in response.json()["error"]["message"]


async def test_reset_puts_the_startup_thresholds_back(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)
    await client.put("/admin/policy", json={"values": {"max_claim_age_days": "5"}})

    reset = await client.post("/admin/policy/reset")

    assert reset.status_code == 200
    assert reset.json()["matches_startup"] is True
    assert reset.json()["changed_at"] is None

    screened = await client.post("/cases/CASE-1001/preflight")
    assert screened.json()["verdict"] == "proceed"


async def test_an_operator_can_empty_everything_the_service_remembers(
    client: AsyncClient, settings: Settings
) -> None:
    memory = MerchantMemory(settings.database_path)
    memory.record_correction(
        MerchantCorrection(
            user_id="334430",
            case_id="CASE-1001",
            summary="The two-pack was claimed, not the single bottle.",
            recorded_at=datetime(2026, 3, 21, tzinfo=UTC),
        )
    )
    ReportStore(settings.database_path).record(a_report())
    DecisionStore(settings.database_path).record(investigated())

    response = await client.post("/admin/forget-everything")

    assert response.status_code == 200
    assert response.json() == {
        "corrections": 1,
        "reports": 1,
        "decisions": 1,
        "past_claims": 0,
    }
    assert memory.corrections_for("334430") == ()


async def test_the_back_and_forth_on_a_report_goes_with_it(
    client: AsyncClient, settings: Settings
) -> None:
    reports = ReportStore(settings.database_path)
    reports.record(a_report(version=1))
    reports.record(a_report(version=2))

    response = await client.post("/admin/forget-everything")

    assert response.json()["reports"] == 2
    assert reports.versions_of("RPT-CASE-1001-L01") == []


async def test_forgetting_when_there_is_nothing_to_forget_says_so(client: AsyncClient) -> None:
    response = await client.post("/admin/forget-everything")

    assert response.status_code == 200
    assert response.json() == {
        "corrections": 0,
        "reports": 0,
        "decisions": 0,
        "past_claims": 0,
    }
