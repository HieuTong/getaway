from datetime import date

import pytest

from app import agent, fire

# A trimmed copy of the CFA district feed's shape: one item per day, plus the municipality list item.
SAMPLE_FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<title>Country Fire Authority - Total Fire Ban &amp; Fire Danger Ratings - Central Forecast</title>
<item><title>Saturday, 14 November 2026</title>
<description>&lt;p&gt;Today, Sat, 14 Nov 2026 is not currently a day of Total Fire Ban.&lt;/p&gt;&lt;p&gt;Central: MODERATE&lt;br/&gt;&lt;img alt="Moderate"/&gt;&lt;/p&gt;&lt;p&gt;Displays when Total Fire Ban in force&lt;/p&gt;</description></item>
<item><title>Sunday, 15 November 2026</title>
<description>&lt;p&gt;Tomorrow, Sun, 15 Nov 2026 is a day of Total Fire Ban.&lt;/p&gt;&lt;p&gt;Central: EXTREME&lt;/p&gt;&lt;p&gt;Displays when Total Fire Ban in force&lt;/p&gt;</description></item>
<item><title>Wednesday, 18 November 2026</title>
<description>&lt;p&gt;Central: NO RATING&lt;/p&gt;</description></item>
<item><title>Fire restrictions by muncipality</title>
<description>BALLARAT:No - restrictions may apply&lt;br/&gt;CASEY:No - restrictions may apply</description></item>
</channel></rss>"""


def test_parse_feed_reads_each_day_and_skips_the_municipality_list():
    days = fire.parse_feed(SAMPLE_FEED)
    assert days == {
        date(2026, 11, 14): {"rating": "MODERATE", "total_fire_ban": False},
        date(2026, 11, 15): {"rating": "EXTREME", "total_fire_ban": True},
        date(2026, 11, 18): {"rating": "NO RATING", "total_fire_ban": None},  # wording missing: unknown, not "no ban"
    }


@pytest.mark.parametrize("google_name, expected", [
    ("Yarra Ranges Shire", ["Central"]),
    ("Shire of Yarra Ranges", ["Central"]),
    ("City of Greater Geelong", ["Central"]),
    ("Colac Otway Shire", ["South West"]),
    ("Merri-bek City", ["Central"]),
    ("Murrindindi Shire Council", ["North Central"]),
    ("Yarriambiack Shire", ["Mallee", "Wimmera"]),  # split district: both, and the worse one is used
    ("Somewhere Unknown", []),
    (None, []),
])
def test_districts_for_matches_google_council_names(google_name, expected):
    assert fire.districts_for(google_name) == expected


def test_fire_outlook_uses_the_feed_and_never_guesses(monkeypatch):
    monkeypatch.setattr(fire, "_forecast", lambda district: fire.parse_feed(SAMPLE_FEED))
    assert fire.fire_outlook("Yarra Ranges Shire", date(2026, 11, 15)) == {
        "district": "Central", "rating": "EXTREME", "total_fire_ban": True}
    # A day beyond the forecast: district known, everything else unknown.
    assert fire.fire_outlook("Yarra Ranges Shire", date(2026, 12, 25)) == {
        "district": "Central", "rating": None, "total_fire_ban": None}
    assert fire.fire_outlook("Somewhere Unknown", date(2026, 11, 15)) is None


def place(place_id, rating=None, ban=None):
    return {"place_id": place_id, "name": f"Place {place_id}", "latitude": -37.8, "longitude": 145.3,
            "drive_minutes": 60, "rating": 4.5,
            "fire": {"district": "Central", "rating": rating, "total_fire_ban": ban}}


def test_catastrophic_places_are_never_suggested_even_for_a_beach():
    kept, note = agent._fire_filter("a quiet beach", [place("a", "CATASTROPHIC"), place("b", "MODERATE")])
    assert [p["place_id"] for p in kept] == ["b"]
    assert "Skipped Place a" in note and "VicEmergency" in note


def test_bush_trips_skip_extreme_days_and_total_fire_bans():
    places = [place("extreme", "EXTREME"), place("ban", "HIGH", True), place("ok", "MODERATE", False)]
    kept, note = agent._fire_filter("a waterfall hike", places)
    assert [p["place_id"] for p in kept] == ["ok"]
    assert "VicEmergency" in note


def test_beach_trips_keep_extreme_places_but_warn():
    kept, note = agent._fire_filter("a beach for a swim", [place("hot", "EXTREME")])
    assert [p["place_id"] for p in kept] == ["hot"]
    assert "HIGH fire danger" in note


def test_unknown_fire_danger_is_never_presented_as_safe():
    kept, note = agent._fire_filter("a forest walk", [place("x", None, None)])
    assert [p["place_id"] for p in kept] == ["x"]
    assert "isn't forecast yet" in note and "VicEmergency" in note


def test_suggestions_carry_the_fire_facts_from_code_not_the_model():
    chosen = agent.Choices(summary="One option.", choices=[agent.Choice(place_id="ok", reason="Shady.")])
    plan = agent._build_plan(chosen, {"ok": place("ok", "HIGH", False)})
    assert plan.suggestions[0].fire_danger == "HIGH"
    assert plan.suggestions[0].total_fire_ban is False
    assert plan.suggestions[0].fire_district == "Central"
