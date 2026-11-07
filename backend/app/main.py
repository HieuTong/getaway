import logging
from datetime import date

from fastapi import FastAPI, HTTPException
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field

from .agent import TEMPORARY_STATUS_CODES, Plan, plan_trip

app = FastAPI(title="Getaway agent")
logger = logging.getLogger("uvicorn.error")  # uvicorn's logger, so messages appear in the server terminal


class PlanRequest(BaseModel):
    query: str = Field(min_length=3, max_length=300)  # caps cost and limits prompt-injection room
    origin_latitude: float = Field(ge=-90, le=90)
    origin_longitude: float = Field(ge=-180, le=180)
    trip_date: date


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/plan", response_model=Plan)
def plan(request: PlanRequest) -> Plan:
    # A plain `def` endpoint runs in FastAPI's thread pool,
    # so the slow, blocking Gemini call doesn't freeze other requests.
    try:
        return plan_trip(request.query, request.origin_latitude, request.origin_longitude, request.trip_date)
    except genai_errors.APIError as error:
        logger.warning("Gemini error %s for query %r: %s", error.code, request.query, error)
        if error.code == 429:
            raise HTTPException(
                status_code=503,
                detail="The trip planner has reached its usage limit for now. Please try again later.",
                headers={"Retry-After": "3600"},
            )
        if error.code in TEMPORARY_STATUS_CODES:
            # Temporary: 503 + Retry-After tells any client "this will work later".
            raise HTTPException(
                status_code=503,
                detail="The trip planner is very busy right now. Please try again in a minute.",
                headers={"Retry-After": "30"},
            )
        # Permanent (bad key, unknown model): our configuration is wrong, so it's a 502.
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {error}")
    except ValueError as error:
        logger.warning("Unusable agent answer for query %r: %s", request.query, error)
        raise HTTPException(status_code=502, detail=f"The agent returned an unusable answer: {error}")
