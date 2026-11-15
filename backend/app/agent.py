import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as clock_time, timedelta

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from . import fire, tools
from .config import GEMINI_API_KEY, GEMINI_FALLBACK_MODELS, GEMINI_MODEL
from .parsing import drive_limit_minutes

# Errors that mean "this model can't serve us right now" (overloaded or out of quota): try the next model.
TEMPORARY_STATUS_CODES = {429, 503}
# Only overload (503) clears within seconds. A 429 is usually the daily quota, so don't retry the same model.
RETRY_SAME_MODEL_CODES = [503]

GEMINI_TIMEOUT_MS = 60_000   # a model slower than this is skipped for the next option, instead of blocking for minutes
MAX_OUTPUT_TOKENS = 4096     # caps the answer, including thinking, so a request can't run away

PLAN_CACHE_SECONDS = 6 * 60 * 60  # identical requests within 6 hours reuse the saved plan
MAX_CANDIDATES = 8

# Plain-code search planning: map words in the request to a category search. No AI call needed.
CATEGORY_SEARCHES = {
    "hiking trails and bushwalks": ("hike", "hiking", "walk", "bushwalk", "trail", "forest"),
    "beaches": ("beach", "swim", "surf", "coast"),
    "scenic lookouts": ("lookout", "view", "scenic"),
    "waterfalls": ("waterfall", "falls"),
}

# Trips into bushland, where a fire can cut off the way out. Beaches and towns are treated as lower risk.
BUSH_WORDS = ("hike", "hiking", "walk", "bushwalk", "trail", "forest", "rainforest", "waterfall", "falls",
              "lookout", "ranges", "national park", "camp", "picnic")

SAFETY_REMINDER = "Conditions can change quickly: check the VicEmergency app or emergency.vic.gov.au before you leave."


# ---------- What the app receives (the iOS app ignores fields it doesn't know) ----------

class Suggestion(BaseModel):
    place_id: str
    name: str
    latitude: float
    longitude: float
    reason: str
    drive_minutes: int | None = None
    leave_by: str | None = None          # "HH:MM", Melbourne time
    fire_danger: str | None = None       # CFA rating for the trip date: MODERATE ... CATASTROPHIC; None = unknown
    total_fire_ban: bool | None = None   # None = unknown
    fire_district: str | None = None


class Plan(BaseModel):
    summary: str
    suggestions: list[Suggestion]
    used_ai: bool = True                 # False when the rule-based fallback answered, or no AI call was needed
    safety_note: str | None = None       # shown above the picks; always set when fire information applies


# ---------- What Gemini returns (structured output: the SDK validates this shape) ----------

class Choice(BaseModel):
    place_id: str
    reason: str
    leave_by: str | None = None


class Choices(BaseModel):
    summary: str
    choices: list[Choice]


CHOOSE_PROMPT = """You are Getaway, a day-trip planner for people leaving from Melbourne, Victoria, Australia.
You receive the user's request and a list of real candidate places with predicted drive times and,
where known, the CFA fire danger rating and Total Fire Ban status for the trip date.

Rules:
- Choose up to 3 places, best first, ONLY from the candidates, using their exact place_id.
- Respect the user's limits, such as maximum drive time. Skip candidates without a drive time if
  the user gave a drive limit.
- For walks and hikes, leave enough time to drive there, walk, and drive back before sunset.
- Bushfire safety comes first: prefer places with a lower fire danger, and when a pick's fire danger
  is HIGH or above, or a Total Fire Ban applies, say so plainly in its reason.
- leave_by is the latest sensible departure time ("HH:MM", Melbourne time).
- Each reason is one or two short sentences. The summary is one sentence."""

# Retry overload (503) on the same model with short exponential backoff; give up on any single request after the timeout.
_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(
        timeout=GEMINI_TIMEOUT_MS,
        retry_options=types.HttpRetryOptions(
            attempts=3, initial_delay=1.0, max_delay=8.0, http_status_codes=RETRY_SAME_MODEL_CODES
        ),
    ),
)

_pool = ThreadPoolExecutor(max_workers=2)  # runs the Places searches side by side

# In-memory cache of recent AI plans. FastAPI runs requests on several threads, so access is guarded by a lock.
_cache: dict[tuple, tuple[float, Plan]] = {}
_cache_lock = threading.Lock()


def plan_trip(query: str, origin_latitude: float, origin_longitude: float, trip_date: date,
              use_cache: bool = True) -> Plan:
    # Same question, same day, same ~1 km starting area -> same answer. Rounding stops GPS jitter missing the cache.
    key = (" ".join(query.lower().split()), trip_date.isoformat(), round(origin_latitude, 2), round(origin_longitude, 2))
    with _cache_lock:
        cached = _cache.get(key) if use_cache else None  # evaluations bypass the cache
        if cached and time.time() - cached[0] < PLAN_CACHE_SECONDS:
            print(f"plan served from cache for {query!r}")
            return cached[1]

    started = time.perf_counter()

    # 1. Plain code collects the facts ONCE, whichever model (if any) ends up answering.
    candidates = _search(query)
    places = list(candidates.values())[:MAX_CANDIDATES]
    if not places:
        return Plan(summary="No places matched that request. Try describing it differently.", suggestions=[], used_ai=False)
    departure = _departure_time(trip_date)
    minutes = tools.drive_minutes_matrix(
        origin_latitude, origin_longitude, [(p["latitude"], p["longitude"]) for p in places], departure
    )
    for place, drive in zip(places, minutes):
        place["drive_minutes"] = drive
        place["fire"] = fire.fire_outlook(place.get("municipality"), trip_date)
    sunset = tools.sunset_time(origin_latitude, origin_longitude, trip_date)
    print(f"{len(places)} candidates, {sum(m is not None for m in minutes)} with drive times, "
          f"after {time.perf_counter() - started:.1f}s")

    # 2. Bushfire rules, applied by code before any model sees the candidates (see _fire_filter).
    places, safety_note = _fire_filter(query, places)
    candidates = {p["place_id"]: p for p in places}  # removed places can't be chosen, even by a mistaken model
    if not places:
        return Plan(summary="Every match is in an area with dangerous fire conditions that day, so Getaway "
                            "isn't suggesting any of them. Try a beach or a town instead.",
                    suggestions=[], used_ai=False, safety_note=safety_note)

    # 3. One Gemini call to choose and explain, trying each model in turn.
    facts = {
        "request": query,
        "trip_date": trip_date.isoformat(),
        "assumed_departure": departure.strftime("%H:%M"),
        "sunset": sunset,
        "candidates": [
            {
                **{key: place.get(key) for key in ("place_id", "name", "address", "rating", "drive_minutes")},
                "fire_danger": (place.get("fire") or {}).get("rating"),
                "total_fire_ban": (place.get("fire") or {}).get("total_fire_ban"),
            }
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
        except (httpx.TimeoutException, ValueError) as error:
            # Too slow, or no valid structured answer: another model may still do better.
            print(f"Model {model} gave no usable answer ({type(error).__name__}: {error}); trying the next option")
            continue
        plan = _build_plan(chosen, candidates)
        plan.safety_note = safety_note
        print(f"plan ready in {time.perf_counter() - started:.1f}s with {model} (1 Gemini call)")
        with _cache_lock:
            _cache[key] = (time.time(), plan)
        return plan

    # 4. Every model is busy, out of free quota or too slow: degrade gracefully instead of failing.
    #    Not cached, so the next request gets an AI answer once a model is available again.
    print(f"plan ready in {time.perf_counter() - started:.1f}s with the rule-based fallback (no AI)")
    plan = _rule_based_plan(query, places)
    plan.safety_note = safety_note
    return plan


def is_bush_trip(query: str) -> bool:
    lowered = query.lower()
    return any(word in lowered for word in BUSH_WORDS)


def _fire_filter(query: str, places: list[dict]) -> tuple[list[dict], str | None]:
    """Removes candidates that are unsafe because of bushfire conditions, and explains why.

    These are hard rules in code, not suggestions to the model:
    - CATASTROPHIC: never suggested (the CFA advises leaving high-risk areas, and parks may close).
    - Bush trips (hikes, forests, waterfalls...) on an EXTREME day or a day of Total Fire Ban: not suggested.
    Unknown fire information is never treated as safe: the note tells people to check before they go.
    """
    bush = is_bush_trip(query)
    kept, removed = [], []
    for place in places:
        outlook = place.get("fire") or {}
        rating, ban = outlook.get("rating"), outlook.get("total_fire_ban")
        unsafe = rating == "CATASTROPHIC" or (bush and (fire.is_at_least(rating, "EXTREME") or ban is True))
        (removed if unsafe else kept).append(place)

    notes = []
    if removed:
        names = ", ".join(p["name"] for p in removed[:3]) + (" and others" if len(removed) > 3 else "")
        notes.append(f"Skipped {names}: dangerous fire conditions forecast there that day.")
    elevated = [p for p in kept if fire.is_at_least((p.get("fire") or {}).get("rating"), "HIGH")
                or (p.get("fire") or {}).get("total_fire_ban") is True]
    if elevated:
        notes.append("Some picks have a HIGH fire danger rating or higher: have a plan to leave early if a fire starts.")
    if bush and any((p.get("fire") or {}).get("rating") is None for p in kept):
        notes.append("Fire danger isn't forecast yet for every pick on that date.")
    if notes or bush:
        notes.append(SAFETY_REMINDER)
    return kept, " ".join(notes) or None


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
        if "error" in result:
            print(result["error"])  # never fail silently
        for place in result.get("places", []):
            candidates.setdefault(place["place_id"], place)
    return candidates


def _suggestion(place: dict, reason: str, leave_by: str | None = None) -> Suggestion:
    # Code owns the facts: names, coordinates, drive times and fire ratings come from our data, never from the model.
    outlook = place.get("fire") or {}
    return Suggestion(
        place_id=place["place_id"],
        name=place["name"],
        latitude=place["latitude"],
        longitude=place["longitude"],
        reason=reason,
        drive_minutes=place.get("drive_minutes"),
        leave_by=leave_by,
        fire_danger=outlook.get("rating"),
        total_fire_ban=outlook.get("total_fire_ban"),
        fire_district=outlook.get("district"),
    )


def _build_plan(chosen: Choices, candidates: dict[str, dict]) -> Plan:
    print(f"model chose {[c.place_id for c in chosen.choices]}; real IDs look like {list(candidates)[:2]}")
    # Any place ID the model invented (or a place the fire rules removed) isn't in `candidates`, so it's dropped here.
    suggestions = []
    for choice in chosen.choices:
        place = candidates.get(choice.place_id)
        if place is None:
            continue
        suggestions.append(_suggestion(place, choice.reason, choice.leave_by))
        if len(suggestions) == 3:
            break
    return Plan(summary=chosen.summary, suggestions=suggestions)


def _rule_based_plan(query: str, places: list[dict]) -> Plan:
    """No AI available: the top-rated candidates that fit the user's drive limit, lowest fire danger first."""
    limit = drive_limit_minutes(query)
    eligible = [
        p for p in places
        if p.get("drive_minutes") is not None and (limit is None or p["drive_minutes"] <= limit)
    ]

    def fire_rank(place: dict) -> int:
        rating = (place.get("fire") or {}).get("rating")
        return fire.RATINGS.index(rating) if rating else 1  # unknown sits between none and moderate

    ranked = sorted(eligible, key=lambda p: (fire_rank(p), -(p.get("rating") or 0), p["drive_minutes"]))[:3]
    within = f" within {limit} minutes' drive" if limit else ""
    return Plan(
        summary=f"The AI planner is resting for today, so here are the best-rated matches{within}.",
        suggestions=[_suggestion(p, _plain_reason(p)) for p in ranked],
        used_ai=False,
    )


def _plain_reason(place: dict) -> str:
    parts = []
    if place.get("rating"):
        parts.append(f"Rated {place['rating']:.1f}")
    parts.append(f"about {place['drive_minutes']} min drive")
    rating = (place.get("fire") or {}).get("rating")
    if fire.is_at_least(rating, "HIGH"):
        parts.append(f"fire danger {rating.lower()}")
    text = ", ".join(parts) + "."
    return text[0].upper() + text[1:]


def _thinking_config(model: str) -> types.ThinkingConfig | None:
    """Choosing 3 places from 8 needs little reasoning, so keep thinking (and waiting) to a minimum."""
    if model.startswith("gemini-3"):
        return types.ThinkingConfig(thinking_level="low")  # Gemini 3 models can't switch thinking off; "low" is fastest
    if model.startswith("gemini-2.5-flash"):
        return types.ThinkingConfig(thinking_budget=0)     # Gemini 2.5 Flash uses a token budget; 0 turns thinking off
    return None                                            # other models: keep their defaults


def _generate(model: str, system_prompt: str, contents: str, schema: type[BaseModel]) -> BaseModel:
    """One Gemini call that must answer in `schema`'s exact JSON shape. Logs its time and thinking tokens."""
    started = time.perf_counter()
    response = _client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=schema,  # structured output: the SDK validates and builds the object for us
            max_output_tokens=MAX_OUTPUT_TOKENS,
            thinking_config=_thinking_config(model),
            # Google advises keeping Gemini 3 models at their default temperature; older models answer more consistently lower.
            temperature=None if model.startswith("gemini-3") else 0.2,
        ),
    )
    usage = response.usage_metadata
    thinking_tokens = getattr(usage, "thoughts_token_count", None) if usage else None
    print(f"Gemini {model}: {time.perf_counter() - started:.1f}s, thinking tokens: {thinking_tokens}")
    if response.parsed is None:
        raise ValueError("the model returned no valid structured answer")
    return response.parsed


def _departure_time(trip_date: date) -> datetime:
    """8:00am on the trip date, or a few minutes from now if that's already past (Routes needs a future time)."""
    planned = datetime.combine(trip_date, clock_time(8, 0), tzinfo=tools.MELBOURNE_TZ)
    earliest = datetime.now(tools.MELBOURNE_TZ) + timedelta(minutes=5)
    return max(planned, earliest)
