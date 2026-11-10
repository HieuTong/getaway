from datetime import datetime

import pytest

from app import agent, tools
from app.agent import Choice, Choices
from app.parsing import drive_limit_minutes


def place(place_id: str, rating: float | None, minutes: int | None) -> dict:
    return {
        "place_id": place_id,
        "name": f"Place {place_id}",
        "address": "",
        "rating": rating,
        "latitude": -38.0,
        "longitude": 145.0,
        "drive_minutes": minutes,
    }


@pytest.mark.parametrize(
    "query, expected",
    [
        ("a quiet beach under 90 minutes drive", 90),
        ("somewhere cool, 2 hours away", 120),
        ("a lookout, 1.5 hrs drive max", 90),
        ("drive under 1 hour to a waterfall", 60),
        ("a 2 hour hike, under 60 minutes drive", 60),  # the bug these tests caught: hike length != drive limit
        ("a 2 hour hike near the coast", None),         # walking time, not a drive limit
        ("a quiet beach", None),
    ],
)
def test_drive_limit_reads_only_driving_limits(query, expected):
    assert drive_limit_minutes(query) == expected


def test_build_plan_drops_invented_place_ids_and_uses_our_facts():
    candidates = {"real": place("real", 4.5, 60)}
    chosen = Choices(
        summary="Two options.",
        choices=[
            Choice(place_id="invented-by-the-model", reason="Sounds nice."),
            Choice(place_id="real", reason="Shady and close.", leave_by="08:00"),
        ],
    )
    plan = agent._build_plan(chosen, candidates)

    assert [s.place_id for s in plan.suggestions] == ["real"]
    assert plan.suggestions[0].drive_minutes == 60  # from Google's data, not from the model
    assert plan.suggestions[0].name == "Place real"


def test_rule_based_plan_respects_drive_limit_and_ranks_by_rating():
    places = [
        place("too-far", 4.9, 150),
        place("good", 4.2, 60),
        place("best", 4.8, 80),
        place("no-route", 5.0, None),
    ]
    plan = agent._rule_based_plan("a beach under 90 minutes drive", places)

    assert [s.place_id for s in plan.suggestions] == ["best", "good"]
    assert "90 minutes" in plan.summary


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_route_matrix_reads_index_zero_even_when_google_omits_it(monkeypatch):
    payload = [
        {"condition": "ROUTE_EXISTS", "duration": "3600s"},  # Google's JSON leaves out destinationIndex 0
        {"destinationIndex": 1, "condition": "ROUTE_NOT_FOUND"},
        {"destinationIndex": 2, "condition": "ROUTE_EXISTS", "duration": "5520s"},
    ]
    monkeypatch.setattr(tools._http, "post", lambda *args, **kwargs: FakeResponse(payload))

    minutes = tools.drive_minutes_matrix(
        -37.81, 144.96, [(-38.0, 145.0)] * 3, datetime(2026, 12, 27, 8, tzinfo=tools.MELBOURNE_TZ)
    )

    assert minutes == [60, None, 92]


def test_route_matrix_refused_falls_back_to_compute_routes(monkeypatch):
    import httpx

    def fake_post(url, **kwargs):
        request = httpx.Request("POST", url)
        if "computeRouteMatrix" in url:
            # Google's real Route Matrix error format: a list, even for errors.
            body = [{"error": {"code": 403, "message": "Permission denied on the service."}}]
            return httpx.Response(403, json=body, request=request)
        return httpx.Response(200, json={"routes": [{"duration": "3600s"}]}, request=request)

    monkeypatch.setattr(tools._http, "post", fake_post)
    minutes = tools.drive_minutes_matrix(
        -37.81, 144.96, [(-38.0, 145.0)] * 2, datetime(2026, 12, 27, 8, tzinfo=tools.MELBOURNE_TZ)
    )

    assert minutes == [60, 60]  # the fallback filled in every drive time


def test_route_matrix_refused_falls_back_to_compute_routes(monkeypatch):
    import httpx

    def fake_post(url, **kwargs):
        request = httpx.Request("POST", url)
        if "computeRouteMatrix" in url:
            # Google's real Route Matrix error format: a list, even for errors.
            body = [{"error": {"code": 403, "message": "Permission denied on the service."}}]
            return httpx.Response(403, json=body, request=request)
        return httpx.Response(200, json={"routes": [{"duration": "3600s"}]}, request=request)

    monkeypatch.setattr(tools._http, "post", fake_post)
    minutes = tools.drive_minutes_matrix(
        -37.81, 144.96, [(-38.0, 145.0)] * 2, datetime(2026, 12, 27, 8, tzinfo=tools.MELBOURNE_TZ)
    )

    assert minutes == [60, 60]  # the fallback filled in every drive time
