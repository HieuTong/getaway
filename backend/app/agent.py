import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as clock_time, timedelta

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from . import tools
from .config import GEMINI_API_KEY, GEMINI_FALLBACK_MODEL, GEMINI_MODEL

# Errors that mean "this model can't serve us right now". Both send us to the fallback model.
TEMPORARY_STATUS_CODES = {429, 503}
# Only overload (503) clears within seconds. A 429 is often a daily quota, so retrying the same model is pointless.
RETRY_SAME_MODEL_CODES = [503]

PLAN_CACHE_SECONDS = 6 * 60 * 60  # identical requests within 6 hours reuse the saved plan
MAX_SEARCHES = 2
MAX_CANDIDATES = 8


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


# ---------- What Gemini returns (structured output: the SDK validates these shapes) ----------

class SearchPlan(BaseModel):
    queries: list[str]


class Choice(BaseModel):
    place_id: str
    reason: str
    leave_by: str | None = None


class Choices(BaseModel):
    summary: str
    choices: list[Choice]


SEARCH_PROMPT = """You turn a day-trip request from someone in Melbourne, Victoria, Australia into
Google Places text-search queries. Return 1 or 2 short, specific queries
(for example "shaded rainforest walks" or "quiet swimming beaches"). Do not add a location."""

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

_pool = ThreadPoolExecutor(max_workers=MAX_SEARCHES)  # runs the Places searches side by side

# In-memory cache of recent plans. FastAPI runs requests on several threads, so access is guarded by a lock.
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

    # If a model can't serve us (overloaded or out of quota), try the fallback model, which has its own
    # capacity and quota. Planning only reads data, so running it again is safe.
    models = [GEMINI_MODEL] + ([GEMINI_FALLBACK_MODEL] if GEMINI_FALLBACK_MODEL else [])
    for index, model in enumerate(models):
        try:
            started = time.perf_counter()
            plan = _run_pipeline(model, query, origin_latitude, origin_longitude, trip_date)
            print(f"plan ready in {time.perf_counter() - started:.1f}s with {model} (2 Gemini calls)")
            with _cache_lock:
                _cache[key] = (time.time(), plan)
            return plan
        except genai_errors.APIError as error:
            is_last_model = index == len(models) - 1
            if error.code in TEMPORARY_STATUS_CODES and not is_last_model:
                print(f"Model {model} unavailable ({error.code}); trying {models[index + 1]}")
                continue
            raise
    raise RuntimeError("no Gemini model configured")  # unreachable: GEMINI_MODEL is required


def _run_pipeline(model: str, query: str, origin_latitude: float, origin_longitude: float, trip_date: date) -> Plan:
    # Gemini call 1: understand the request well enough to know what to search for.
    search_plan = _generate(model, SEARCH_PROMPT, f"Request: {query}", SearchPlan)
    queries = [q.strip() for q in search_plan.queries if q.strip()][:MAX_SEARCHES] or [query]

    # Plain code: run the searches in parallel and merge them, keeping each place once.
    candidates: dict[str, dict] = {}
    for result in _pool.map(tools.search_places, queries):
        for place in result.get("places", []):
            candidates.setdefault(place["place_id"], place)
    places = list(candidates.values())[:MAX_CANDIDATES]
    if not places:
        return Plan(summary="No places matched that request. Try describing it differently.", suggestions=[])

    # Plain code: every drive time in ONE Route Matrix request, plus sunset (pure maths, no API).
    departure = _departure_time(trip_date)
    minutes = tools.drive_minutes_matrix(
        origin_latitude, origin_longitude, [(p["latitude"], p["longitude"]) for p in places], departure
    )
    for place, drive in zip(places, minutes):
        place["drive_minutes"] = drive
    sunset = tools.sunset_time(origin_latitude, origin_longitude, trip_date)

    # Gemini call 2: judgement and writing, using only facts our code collected.
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
    chosen = _generate(model, CHOOSE_PROMPT, json.dumps(facts), Choices)

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
