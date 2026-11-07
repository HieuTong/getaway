import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as clock_time, timedelta

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from . import tools
from .config import GEMINI_API_KEY, GEMINI_FALLBACK_MODELS, GEMINI_MODEL

# Errors that mean "this model can't serve us right now" (overloaded or out of quota): try the next model.
TEMPORARY_STATUS_CODES = {429, 503}
# Only overload (503) clears within seconds. A 429 is usually the daily quota, so don't retry the same model.
RETRY_SAME_MODEL_CODES = [503]

PLAN_CACHE_SECONDS = 6 * 60 * 60  # identical requests within 6 hours reuse the saved plan
MAX_CANDIDATES = 8

# Plain-code search planning: map words in the request to a category search. No AI call needed.
CATEGORY_SEARCHES = {
    "hiking trails and bushwalks": ("hike", "hiking", "walk", "bushwalk", "trail", "forest"),
    "beaches": ("beach", "swim", "surf", "coast"),
    "scenic lookouts": ("lookout", "view", "scenic"),
    "waterfalls": ("waterfall", "falls"),
}


# ---------- What the app receives (unchanged, so the iOS app needs no update) ----------

class Suggestion(BaseModel):
    place_id: str
    name: str
    latitude: float
    longitude: float
    reason: str
    drive_minutes: int | None = None
    leave_by: str | None = None  # "HH:MM", Melbourne time


class Plan(BaseModel):
    summary: str
    suggestions: list[Suggestion]


# ---------- What Gemini returns (structured output: the SDK validates this shape) ----------

class Choice(BaseModel):
    place_id: str
    reason: str
    leave_by: str | None = None


class Choices(BaseModel):
    summary: str
    choices: list[Choice]


CHOOSE_PROMPT = """You are Getaway, a day-trip planner for people leaving from Melbourne, Victoria, Australia.
You receive the user's request and a list of real candidate places with predicted drive times.

Rules:
- Choose up to 3 places, best first, ONLY from the candidates, using their exact place_id.
- Respect the user's limits, such as maximum drive time. Skip candidates without a drive time if
  the user gave a drive limit.
- For walks and hikes, leave enough time to drive there, walk, and drive back before sunset.
- leave_by is the latest sensible departure time ("HH:MM", Melbourne time).
- Each reason is one or two short sentences. The summary is one sentence."""

# Retry overload (503) on the same model with short exponential backoff (about 1s, 2s).
_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(
            attempts=3, initial_delay=1.0, max_delay=8.0, http_status_codes=RETRY_SAME_MODEL_CODES
        )
    ),
)

_pool = ThreadPoolExecutor(max_workers=2)  # runs the Places searches side by side

# In-memory cache of recent AI plans. FastAPI runs requests on several threads, so access is guarded by a lock.
_cache: dict[tuple, tuple[float, Plan]] = {}
_cache_lock = threading.Lock()


def plan_trip(query: str, origin_latitude: float, origin_longitude: float, trip_date: date) -> Plan:
    # Same question, same day, same ~1 km starting area -> same answer. Rounding stops GPS jitter missing the cache.
    key = (" ".join(query.lower().split()), trip_date.isoformat(), round(origin_latitude, 2), round(origin_longitude, 2))
    with _cache_lock:
        cached = _cache.get(key)
        if cached and time.time() - cached[0] < PLAN_CACHE_SECONDS:
            print(f"plan served from cache for {query!r}")
            return cached[1]

    started = time.perf_counter()

    # 1. Plain code collects the facts ONCE, whichever model (if any) ends up answering.
    candidates = _search(query)
    places = list(candidates.values())[:MAX_CANDIDATES]
    if not places:
        return Plan(summary="No places matched that request. Try describing it differently.", suggestions=[])
    departure = _departure_time(trip_date)
    minutes = tools.drive_minutes_matrix(
        origin_latitude, origin_longitude, [(p["latitude"], p["longitude"]) for p in places], departure
    )
    for place, drive in zip(places, minutes):
        place["drive_minutes"] = drive
    sunset = tools.sunset_time(origin_latitude, origin_longitude, trip_date)

    # 2. One Gemini call to choose and explain, trying each model in turn.
    facts = {
        "request": query,
        "trip_date": trip_date.isoformat(),
        "assumed_departure": departure.strftime("%H:%M"),
        "sunset": sunset,
        "candidates": [
            {key: place.get(key) for key in ("place_id", "name", "address", "rating", "drive_minutes")}
            for place in places
        ],
    }
    for model in [GEMINI_MODEL] + GEMINI_FALLBACK_MODELS:
        try:
            chosen = _generate(model, CHOOSE_PROMPT, json.dumps(facts), Choices)
        except genai_errors.APIError as error:
            if error.code in TEMPORARY_STATUS_CODES:
                print(f"Model {model} unavailable ({error.code}); trying the next option")
                continue
            raise  # permanent problem (bad key, unknown model): report it
        plan = _build_plan(chosen, candidates)
        print(f"plan ready in {time.perf_counter() - started:.1f}s with {model} (1 Gemini call)")
        with _cache_lock:
            _cache[key] = (time.time(), plan)
        return plan

    # 3. Every model is busy or out of free quota: degrade gracefully instead of failing.
    #    Not cached, so the next request gets an AI answer once quota is back.
    print(f"plan ready in {time.perf_counter() - started:.1f}s with the rule-based fallback (no AI)")
    return _rule_based_plan(query, places)


def _search(query: str) -> dict[str, dict]:
    """Search with the user's own words plus a matching category, in parallel, keeping each place once."""
    queries = [query]
    lowered = query.lower()
    for category, words in CATEGORY_SEARCHES.items():
        if any(word in lowered for word in words):
            queries.append(category)
            break
    candidates: dict[str, dict] = {}
    for result in _pool.map(tools.search_places, queries):
        for place in result.get("places", []):
            candidates.setdefault(place["place_id"], place)
    return candidates


def _build_plan(chosen: Choices, candidates: dict[str, dict]) -> Plan:
    # Code owns the facts: names, coordinates and drive times come from Google's data, never from the model.
    # Any place ID the model invented isn't in `candidates`, so it's dropped here.
    suggestions = []
    for choice in chosen.choices:
        place = candidates.get(choice.place_id)
        if place is None:
            continue
        suggestions.append(
            Suggestion(
                place_id=place["place_id"],
                name=place["name"],
                latitude=place["latitude"],
                longitude=place["longitude"],
                reason=choice.reason,
                drive_minutes=place.get("drive_minutes"),
                leave_by=choice.leave_by,
            )
        )
        if len(suggestions) == 3:
            break
    return Plan(summary=chosen.summary, suggestions=suggestions)


def _rule_based_plan(query: str, places: list[dict]) -> Plan:
    """No AI available: the top-rated candidates that fit the user's drive limit, explained plainly."""
    limit = _drive_limit_minutes(query)
    eligible = [
        p for p in places
        if p.get("drive_minutes") is not None and (limit is None or p["drive_minutes"] <= limit)
    ]
    ranked = sorted(eligible, key=lambda p: (-(p.get("rating") or 0), p["drive_minutes"]))[:3]
    suggestions = [
        Suggestion(
            place_id=p["place_id"],
            name=p["name"],
            latitude=p["latitude"],
            longitude=p["longitude"],
            reason=_plain_reason(p),
            drive_minutes=p["drive_minutes"],
        )
        for p in ranked
    ]
    within = f" within {limit} minutes' drive" if limit else ""
    return Plan(
        summary=f"The AI planner is resting for today, so here are the best-rated matches{within}.",
        suggestions=suggestions,
    )


def _plain_reason(place: dict) -> str:
    parts = []
    if place.get("rating"):
        parts.append(f"Rated {place['rating']:.1f}")
    parts.append(f"about {place['drive_minutes']} min drive")
    text = ", ".join(parts) + "."
    return text[0].upper() + text[1:]


def _drive_limit_minutes(query: str) -> int | None:
    """Reads limits like "under 90 minutes drive" or "2 hours away". None if the request gives no drive limit."""
    lowered = query.lower()
    if "drive" not in lowered and "away" not in lowered:
        return None  # "a 2 hour hike" is about walking time, not driving
    match = re.search(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?)\b", lowered)
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2)
    return int(value * 60) if unit.startswith("h") else int(value)


def _generate(model: str, system_prompt: str, contents: str, schema: type[BaseModel]) -> BaseModel:
    """One Gemini call that must answer in `schema`'s exact JSON shape."""
    response = _client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=schema,  # structured output: the SDK validates and builds the object for us
            temperature=0.2,
        ),
    )
    if response.parsed is None:
        raise ValueError("the model returned no valid structured answer")
    return response.parsed


def _departure_time(trip_date: date) -> datetime:
    """8:00am on the trip date, or a few minutes from now if that's already past (Routes needs a future time)."""
    planned = datetime.combine(trip_date, clock_time(8, 0), tzinfo=tools.MELBOURNE_TZ)
    earliest = datetime.now(tools.MELBOURNE_TZ) + timedelta(minutes=5)
    return max(planned, earliest)
