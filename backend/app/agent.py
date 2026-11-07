import functools
from datetime import date

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from . import tools
from .config import GEMINI_API_KEY, GEMINI_FALLBACK_MODEL, GEMINI_MODEL

# Errors that mean "busy, try later": overloaded (503) or rate-limited (429).
# Anything else (bad key, unknown model) won't fix itself, so it's never retried.
TEMPORARY_STATUS_CODES = {429, 503}


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


SYSTEM_PROMPT = """You are Getaway, a day-trip planner for people leaving from Melbourne, Victoria, Australia.

How to work:
- Use search_places to find candidates. Try more than one search if the first results don't fit.
- Use drive_minutes from the user's starting point, for a sensible departure time on the trip date.
- For walks and hikes, use sunset_time and leave enough time to drive there, walk, and drive back before dark.
- Respect the user's limits, such as maximum drive time.

Rules:
- Only suggest places returned by search_places, using their exact place_id. Never invent places.
- Suggest at most 3 places, best first. Keep each reason to one or two short sentences.
- When you are done, reply with ONLY a JSON object, no markdown and no other text, in this shape:
{"summary": "...", "suggestions": [{"place_id": "...", "name": "...", "latitude": 0.0, "longitude": 0.0,
  "reason": "...", "drive_minutes": 0, "leave_by": "HH:MM"}]}
"""

# Layer 1: retry temporary failures on the SAME model, with exponential backoff (about 2s, 4s, 8s).
_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(
            attempts=3, initial_delay=1.0, max_delay=8.0, http_status_codes=sorted(TEMPORARY_STATUS_CODES)
        )
    ),
)


def plan_trip(query: str, origin_latitude: float, origin_longitude: float, trip_date: date) -> Plan:
    prompt = (
        f"Request: {query}\n"
        f"Trip date: {trip_date.isoformat()}\n"
        f"Starting point: {origin_latitude}, {origin_longitude}"
    )

    # Layer 2: if the main model is still overloaded after its retries, try the fallback model,
    # which runs on separate capacity. Planning only reads data, so running it again is safe.
    models = [GEMINI_MODEL] + ([GEMINI_FALLBACK_MODEL] if GEMINI_FALLBACK_MODEL else [])
    for index, model in enumerate(models):
        try:
            return _run_agent(model, prompt)
        except genai_errors.APIError as error:
            is_last_model = index == len(models) - 1
            if error.code in TEMPORARY_STATUS_CODES and not is_last_model:
                print(f"Model {model} unavailable ({error.code}); trying {models[index + 1]}")
                continue
            raise
    raise RuntimeError("no Gemini model configured")  # unreachable: GEMINI_MODEL is required


def _run_agent(model: str, prompt: str) -> Plan:
    # Fresh per attempt: the place IDs this attempt's search tool really returned,
    # so we can reject any suggestion the model made up.
    seen_place_ids: set[str] = set()

    @functools.wraps(tools.search_places)  # keeps the name and docstring Gemini reads
    def search_places(query: str) -> dict:
        result = tools.search_places(query)
        seen_place_ids.update(place["place_id"] for place in result.get("places", []))
        return result

    # A tool-calling agent is a multi-turn conversation (model -> tool -> model -> ...),
    # so we use a chat. A new chat per request keeps users' trips separate.
    chat = _client.chats.create(
        model=model,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[search_places, tools.drive_minutes, tools.sunset_time],
            # The SDK runs the tool loop for us; this caps it so a confused model can't loop forever.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=15),
            temperature=0.2,  # planning, not creative writing: keep answers consistent
        ),
    )
    response = chat.send_message(prompt)

    plan = _parse_plan(response.text or "")
    plan.suggestions = [s for s in plan.suggestions if s.place_id in seen_place_ids][:3]
    return plan


def _parse_plan(text: str) -> Plan:
    # Models sometimes wrap JSON in markdown code fences, so take the outermost {...} only.
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in the model's answer")
    return Plan.model_validate_json(text[start : end + 1])
