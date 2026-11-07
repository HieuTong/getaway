"""Data tools used by the trip-planning pipeline.

These are plain functions called by our own code (not by Gemini), so they can run in parallel.
They return empty results instead of raising, so one failed lookup doesn't sink the whole plan.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from astral import Observer
from astral.sun import sun

from .config import MAPS_SERVER_KEY

MELBOURNE = (-37.8136, 144.9631)
MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")
_http = httpx.Client(timeout=15)  # thread-safe: shared by the parallel searches


def search_places(query: str) -> dict:
    """Places API (New) text search around Melbourne. Returns {"places": [...]} or {"error": ...}."""
    try:
        response = _http.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "X-Goog-Api-Key": MAPS_SERVER_KEY,
                "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.rating",
            },
            json={
                "textQuery": f"{query} near Melbourne, Victoria",
                "locationBias": {
                    "circle": {
                        "center": {"latitude": MELBOURNE[0], "longitude": MELBOURNE[1]},
                        "radius": 50000.0,
                    }
                },
                "maxResultCount": 8,
                "regionCode": "AU",
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        return {"error": f"Places search failed: {error}"}

    places = [
        {
            "place_id": place["id"],
            "name": place.get("displayName", {}).get("text", ""),
            "address": place.get("formattedAddress", ""),
            "rating": place.get("rating"),
            "latitude": place["location"]["latitude"],
            "longitude": place["location"]["longitude"],
        }
        for place in response.json().get("places", [])
    ]
    return {"places": places}


def drive_minutes_matrix(
    origin_latitude: float,
    origin_longitude: float,
    destinations: list[tuple[float, float]],
    departure: datetime,
) -> list[int | None]:
    """Predicted drive minutes from one origin to MANY destinations, in ONE Route Matrix request.

    Returns one value per destination, in the same order; None where no route was found.
    """

    def waypoint(latitude: float, longitude: float) -> dict:
        return {"waypoint": {"location": {"latLng": {"latitude": latitude, "longitude": longitude}}}}

    minutes: list[int | None] = [None] * len(destinations)
    if not destinations:
        return minutes
    try:
        response = _http.post(
            "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix",
            headers={
                "X-Goog-Api-Key": MAPS_SERVER_KEY,
                "X-Goog-FieldMask": "originIndex,destinationIndex,duration,condition",
            },
            json={
                "origins": [waypoint(origin_latitude, origin_longitude)],
                "destinations": [waypoint(latitude, longitude) for latitude, longitude in destinations],
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE",
                "departureTime": departure.isoformat(),
            },
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return minutes  # plan without drive times rather than failing completely

    for element in response.json():
        # Google's JSON omits fields whose value is the default, so index 0 arrives as "missing".
        index = element.get("destinationIndex", 0)
        if element.get("condition") == "ROUTE_EXISTS" and "duration" in element:
            minutes[index] = round(int(element["duration"].rstrip("s")) / 60)  # "5520s" -> 92
    return minutes


def sunset_time(latitude: float, longitude: float, day: date) -> str:
    """Local sunset time ("HH:MM", Melbourne time) at a place on a date. Pure maths, no API call."""
    times = sun(Observer(latitude=latitude, longitude=longitude), date=day, tzinfo=MELBOURNE_TZ)
    return times["sunset"].strftime("%H:%M")
