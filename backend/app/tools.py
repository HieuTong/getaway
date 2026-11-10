"""Data tools used by the trip-planning pipeline.

These are plain functions called by our own code (not by Gemini), so they can run in parallel.
They return empty results instead of raising, so one failed lookup doesn't sink the whole plan,
but every failure is logged: degrading gracefully must never mean failing silently.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from astral import Observer
from astral.sun import sun

from .config import MAPS_SERVER_KEY

MELBOURNE = (-37.8136, 144.9631)
MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

_http = httpx.Client(timeout=15)                 # thread-safe: shared by parallel requests
_route_pool = ThreadPoolExecutor(max_workers=8)  # for the one-request-per-place fallback


def _describe(error: httpx.HTTPError) -> str:
    """Short, readable reason for a failed request, including Google's own message."""
    response = getattr(error, "response", None)
    if response is None:
        return str(error)
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"
    if isinstance(body, list):  # Route Matrix returns a list, even for errors
        body = body[0] if body else {}
    message = body.get("error", {}).get("message", "") if isinstance(body, dict) else ""
    return f"HTTP {response.status_code}: {message}"


def _latlng(latitude: float, longitude: float) -> dict:
    return {"location": {"latLng": {"latitude": latitude, "longitude": longitude}}}


def search_places(query: str) -> dict:
    """Places API (New) text search around Melbourne. Returns {"places": [...]} or {"error": ...}."""
    try:
        response = _http.post(
            PLACES_URL,
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
        return {"error": f"Places search failed: {_describe(error)}"}

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
    """Predicted drive minutes from one origin to many destinations, in the same order (None = no route).

    Tries one Route Matrix request first. If Google refuses it, falls back to one Compute Routes
    request per destination, sent in parallel, so the plan still gets its drive times.
    """
    if not destinations:
        return []
    try:
        response = _http.post(
            MATRIX_URL,
            headers={
                "X-Goog-Api-Key": MAPS_SERVER_KEY,
                "X-Goog-FieldMask": "originIndex,destinationIndex,duration,condition",
            },
            json={
                "origins": [{"waypoint": _latlng(origin_latitude, origin_longitude)}],
                "destinations": [{"waypoint": _latlng(lat, lng)} for lat, lng in destinations],
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE",
                "departureTime": departure.isoformat(),
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        print(f"Route Matrix failed ({_describe(error)}); falling back to one Compute Routes request per place")
        return list(_route_pool.map(
            lambda destination: _route_minutes(origin_latitude, origin_longitude, destination, departure),
            destinations,
        ))

    minutes: list[int | None] = [None] * len(destinations)
    for element in response.json():
        # Google's JSON omits fields whose value is the default, so index 0 arrives as "missing".
        index = element.get("destinationIndex", 0)
        if element.get("condition") == "ROUTE_EXISTS" and "duration" in element:
            minutes[index] = round(int(element["duration"].rstrip("s")) / 60)  # "5520s" -> 92
    return minutes


def _route_minutes(origin_latitude: float, origin_longitude: float,
                   destination: tuple[float, float], departure: datetime) -> int | None:
    """One Compute Routes request: predicted drive minutes to a single destination, or None."""
    try:
        response = _http.post(
            ROUTES_URL,
            headers={"X-Goog-Api-Key": MAPS_SERVER_KEY, "X-Goog-FieldMask": "routes.duration"},
            json={
                "origin": _latlng(origin_latitude, origin_longitude),
                "destination": _latlng(*destination),
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE",
                "departureTime": departure.isoformat(),
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        print(f"Compute Routes failed: {_describe(error)}")
        return None
    routes = response.json().get("routes", [])
    if not routes or "duration" not in routes[0]:
        return None
    return round(int(routes[0]["duration"].rstrip("s")) / 60)


def sunset_time(latitude: float, longitude: float, day: date) -> str:
    """Local sunset time ("HH:MM", Melbourne time) at a place on a date. Pure maths, no API call."""
    times = sun(Observer(latitude=latitude, longitude=longitude), date=day, tzinfo=MELBOURNE_TZ)
    return times["sunset"].strftime("%H:%M")
