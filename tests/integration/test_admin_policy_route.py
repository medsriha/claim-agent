"""Changing the claim policy over HTTP, and the change reaching the next claim.

This file is where the point of the admin panel is actually proved (FR-0.7, NFR-7).
Reading and writing the thresholds is the easy half; the half worth a test is that a
claim screened after a change is judged by the new numbers, with nothing restarted in
between, and that a change the policy refuses leaves every later claim exactly as it
was.

CASE-1001 does the work throughout. It was delivered on 11 February and filed on 19
February — eight days — so it passes the sixty-day age limit comfortably, and dropping
that limit below eight turns it away. Both numbers come from REQUIREMENTS.md.
"""

from __future__ import annotations

import pytest
import respx
from httpx import AsyncClient
from tests.fixtures.shipbob import CASE_1001, ORDER_1001, SHIPMENT_1001, mock_shipbob

from claim_agent.policy import Policy

pytestmark = pytest.mark.integration


async def test_reading_the_policy_lists_the_thresholds_the_panel_offers(
    client: AsyncClient,
) -> None:
    """FR-0.7: the panel is offered the values it is meant to change, and no others.

    The four it is not offered are still policy values, still read by whatever reads
    them, and still set from the environment — they are simply not changeable from a
    browser while the service runs.
    """
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
        "min_assessment_confidence",
        "max_agent_steps",
        "max_tool_retries",
    }
    assert body["matches_startup"] is True
    assert body["changed_at"] is None


async def test_a_threshold_the_panel_does_not_offer_is_refused_over_http(
    client: AsyncClient,
) -> None:
    """FR-0.7: the omission is the rule, not just the screen's choice of controls."""
    response = await client.put("/admin/policy", json={"values": {"max_tool_retries": "5"}})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert "cannot be changed from the admin panel" in response.json()["error"]["message"]


async def test_a_changed_threshold_judges_the_very_next_claim(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    """FR-0.7, NFR-7: this is what the panel is for — a change with no restart.

    The same claim is screened twice, either side of a change to the age limit, and
    the two answers differ. Nothing else about the request changes.
    """
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
    """FR-0.4, FR-0.7: the explanation a merchant is owed uses the number in force.

    The email tells a merchant the arithmetic, not just the outcome. If it quoted a
    threshold the claim was not actually judged by, the write-up would be wrong in
    the one place a person outside ShipBob reads it.
    """
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)
    await client.put("/admin/policy", json={"values": {"max_claim_age_days": "5"}})

    screened = await client.post("/cases/CASE-1001/preflight")

    email_body = screened.json()["report"]["drafted_email"]["body"]
    assert "8 days" in email_body
    assert "5 days" in email_body


async def test_a_change_is_reported_back_with_what_it_started_as(client: AsyncClient) -> None:
    """FR-0.7: the reply says what is now in force, so nothing has to be guessed at."""
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
    """NFR-4: a submission with one bad value changes nothing at all.

    Both values are sent together, one of them impossible. Accepting the good one
    and refusing the other would leave a policy nobody asked for, so neither lands.
    """
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
    """FR-0.7: an unknown name is an error, not a change that silently does nothing."""
    response = await client.put("/admin/policy", json={"values": {"made_up_value": "5"}})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert "made_up_value" in response.json()["error"]["message"]


async def test_reset_puts_the_startup_thresholds_back(
    client: AsyncClient, shipbob: respx.Router
) -> None:
    """FR-0.7: whoever is demonstrating this can put it back the way it was."""
    mock_shipbob(shipbob, case=CASE_1001, shipment=SHIPMENT_1001, order=ORDER_1001)
    await client.put("/admin/policy", json={"values": {"max_claim_age_days": "5"}})

    reset = await client.post("/admin/policy/reset")

    assert reset.status_code == 200
    assert reset.json()["matches_startup"] is True
    assert reset.json()["changed_at"] is None

    screened = await client.post("/cases/CASE-1001/preflight")
    assert screened.json()["verdict"] == "proceed"
