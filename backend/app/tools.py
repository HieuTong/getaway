"""Tools the agent can call.

Gemini reads each function's name, type hints and docstring to decide when and how to call it,
so the docstrings here are part of the prompt, not just comments.
Tools return errors as data ({"error": ...}) instead of raising, so the model can recover.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from astral import Observer
from astral.sun import sun

from .config import MAPS_SERVER_KEY

MELBOURNE = (-37.8136, 144.9631)
MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")
_http = httpx.Client(timeout=15)


def search_places(query: str) -> dict:
    """Search Google Places for day-trip destinations around Melbourne, Victoria.

    Args:
        query: What to look for, for example "shaded rainforest walks" or "quiet surf beaches".

    Returns:
        {"places": [...]} with up to 8 places, each with place_id, name, address, rating,
        latitude and longitude. Or {"error": ...} if the search failed.
    """
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


def drive_minutes(
    origin_latitude: float,
    origin_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
    departure_time: str,
) -> dict:
    """Predicted driving time in minutes, using typical traffic for that departure time.

    Args:
        origin_latitude: Start latitude.
        origin_longitude: Start longitude.
        destination_latitude: Destination latitude.
        destination_longitude: Destination longitude.
        departure_time: Melbourne local time in ISO 8601, for example "2026-12-26T08:00:00". Must be in the future.

    Returns:
        {"minutes": number} or {"error": ...}.
    """
    try:
        departure = datetime.fromisoformat(departure_time)
    except ValueError:
        return {"error": "departure_time must look like 2026-12-26T08:00:00"}
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=MELBOURNE_TZ)

    def waypoint(latitude: float, longitude: float) -> dict:
        return {"location": {"latLng": {"latitude": latitude, "longitude": longitude}}}

    try:
        response = _http.post(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            headers={"X-Goog-Api-Key": MAPS_SERVER_KEY, "X-Goog-FieldMask": "routes.duration"},
            json={
                "origin": waypoint(origin_latitude, origin_longitude),
                "destination": waypoint(destination_latitude, destination_longitude),
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
                "departureTime": departure.isoformat(),
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        return {"error": f"Routes request failed: {error}"}

    routes = response.json().get("routes", [])
    if not routes:
        return {"error": "No driving route found."}
    seconds = int(routes[0]["duration"].rstrip("s"))  # Google sends durations like "5520s"
    return {"minutes": round(seconds / 60)}


def sunset_time(latitude: float, longitude: float, date_iso: str) -> dict:
    """Local sunset time at a place on a date. Use it to make sure a trip finishes before dark.

    Args:
        latitude: Place latitude.
        longitude: Place longitude.
        date_iso: The date as "YYYY-MM-DD".

    Returns:
        {"sunset": "HH:MM"} in Melbourne time, or {"error": ...}.
    """
    try:
        day = date.fromisoformat(date_iso)
    except ValueError:
        return {"error": "date_iso must look like 2026-12-26"}
    times = sun(Observer(latitude=latitude, longitude=longitude), date=day, tzinfo=MELBOURNE_TZ)
    return {"sunset": times["sunset"].strftime("%H:%M")}
