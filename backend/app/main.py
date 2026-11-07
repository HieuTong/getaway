from datetime import date

from fastapi import FastAPI, HTTPException
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field

from .agent import Plan, plan_trip

app = FastAPI(title="Getaway agent")


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
        # Gemini itself refused the request (bad key, unknown model, quota...). 502 = the service behind us failed.
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {error}")
    except ValueError as error:
        raise HTTPException(status_code=502, detail=f"The agent returned an unusable answer: {error}")
