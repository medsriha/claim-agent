from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from tests.fixtures.decisions import investigated, screened

from claim_agent.settings import Settings
from claim_agent.storage.decision_store import DecisionStore

pytestmark = pytest.mark.integration


def recently(days_ago: int) -> datetime:
    """A moment inside every period the screen offers."""
    return datetime.now(UTC) - timedelta(days=days_ago)


async def test_a_service_nobody_has_decided_anything_on_answers_and_says_why(
    client: AsyncClient,
) -> None:
    """An empty period is an ordinary answer, not a failure.

    It comes back as a success with a sentence explaining every empty panel, because a screen
    full of blank boxes reads as a screen that broke.
    """
    response = await client.get("/analysis/performance")

    assert response.status_code == 200
    body = response.json()
    assert body["approval_trend"]["data"] is None
    assert body["approval_trend"]["empty_reason"]
    assert body["hero"]["value"] == "—"


async def test_the_reply_carries_every_figure_twice_once_to_draw_and_once_to_read(
    client: AsyncClient, settings: Settings
) -> None:
    """The browser turns a number into a length and does nothing else."""
    store = DecisionStore(settings.database_path)
    for index in range(3):
        store.record(
            investigated(decision_id=f"DEC-CASE-9001-L0{index}-01", decided_at=recently(3))
        )

    body = (await client.get("/analysis/performance")).json()

    chart = body["approval_trend"]["data"]
    drawn = next(point for point in chart["series"][0]["points"] if point["value"] is not None)
    assert drawn["value"] == 1.0
    assert drawn["text"] == "100%"
    assert chart["domain"] == {"minimum": 0.0, "maximum": 1.0}
    assert chart["gridlines"][0] == {"at": 0.0, "label": "0%"}
    assert chart["ticks"]


async def test_a_week_with_nothing_in_it_arrives_as_nothing_rather_than_zero(
    client: AsyncClient, settings: Settings
) -> None:
    """A quiet week must break the line, not draw it to the floor."""
    DecisionStore(settings.database_path).record(investigated(decided_at=recently(3)))

    body = (await client.get("/analysis/performance")).json()

    points = body["approval_trend"]["data"]["series"][0]["points"]
    assert any(point["value"] is None for point in points)
    assert all(point["text"] == "—" for point in points if point["value"] is None)


async def test_the_two_populations_are_reported_apart(
    client: AsyncClient, settings: Settings
) -> None:
    """FR-C.1: a stopped claim and an investigated product are different arguments.

    The reply carries a line for each rather than one blended figure, so nobody can read a rate
    that was flattered by claims the AI never touched.
    """
    store = DecisionStore(settings.database_path)
    store.record(screened(decided_at=recently(3)))
    store.record(investigated(decided_at=recently(3)))

    body = (await client.get("/analysis/performance")).json()

    names = [series["name"] for series in body["approval_trend"]["data"]["series"]]
    assert names == ["AI-investigated products", "Claims stopped by eligibility checks"]


async def test_money_arrives_written_out_so_nothing_in_the_browser_parses_it(
    client: AsyncClient, settings: Settings
) -> None:
    """FR-1.21, NFR-2: the browser half of never letting an amount become a number."""
    DecisionStore(settings.database_path).record(investigated(decided_at=recently(3)))

    body = (await client.get("/analysis/performance")).json()

    assert all(isinstance(figure["value"], str) for figure in body["savings"])
    assert any(figure["value"].startswith("$") for figure in body["savings"])
    assert all(one["marker"] == "PROVISIONAL" for one in body["assumptions"])


async def test_a_shorter_period_covers_less_and_says_which_one_it_used(
    client: AsyncClient,
) -> None:
    """The screen sends a name, never a date, so two people asking get the same window."""
    body = (await client.get("/analysis/performance?period=four_weeks")).json()

    assert [one["key"] for one in body["presets"] if one["applied"]] == ["four_weeks"]
    assert body["period_label"].startswith("Data period: ")


async def test_an_unknown_period_falls_back_rather_than_failing(client: AsyncClient) -> None:
    """A way of looking at the past is not something where being wrong is dangerous."""
    response = await client.get("/analysis/performance?period=since_the_dawn_of_time")

    assert response.status_code == 200
    assert [one["key"] for one in response.json()["presets"] if one["applied"]] == ["twelve_months"]


async def test_the_candidate_rules_never_offer_anything_to_switch_on(
    client: AsyncClient, settings: Settings
) -> None:
    """FR-2.9 and FR-3.1: a person approving is the only way a claim leaves review.

    The reply scores rules and says so in its own words. Nothing in it is a setting, and the
    caveat travels with the table so a screen cannot show one without the other.
    """
    DecisionStore(settings.database_path).record(investigated(decided_at=recently(3)))

    body = (await client.get("/analysis/performance")).json()

    gates = body["gates"]["data"]
    assert "FR-2.9" in gates["caveat"]
    assert all("enabled" not in row for row in gates["rows"])


async def test_an_unreadable_store_fails_the_request_rather_than_reporting_a_quiet_month(
    client: AsyncClient, settings: Settings
) -> None:
    """The one badly wrong outcome would be telling somebody nothing was decided when nobody
    looked. A broken store is a failure with its own code, not an empty period.
    """
    settings.database_path.write_text("this is not a database")

    response = await client.get("/analysis/performance")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"
