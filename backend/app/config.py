import os

from dotenv import load_dotenv

load_dotenv()  # reads backend/.env locally; on Render, values come from its environment settings


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}. Copy backend/.env.example to backend/.env and fill it in.")
    return value


GEMINI_API_KEY = _require("GEMINI_API_KEY")
GEMINI_MODEL = _require("GEMINI_MODEL")
MAPS_SERVER_KEY = _require("MAPS_SERVER_KEY")

# Optional: models to try, in order, when the main one is overloaded or out of free quota.
# Comma-separated, e.g. "model-a,model-b". Each model has its own free daily quota.
GEMINI_FALLBACK_MODELS = [
    model.strip() for model in os.getenv("GEMINI_FALLBACK_MODEL", "").split(",") if model.strip()
]

# Shared secret the app must send in the X-App-Token header. Empty = no check (local development only).
APP_ACCESS_TOKEN = os.getenv("APP_ACCESS_TOKEN", "").strip() or None
