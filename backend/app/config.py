import os

from dotenv import load_dotenv

load_dotenv()  # reads backend/.env into environment variables


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}. Copy backend/.env.example to backend/.env and fill it in.")
    return value


GEMINI_API_KEY = _require("GEMINI_API_KEY")
GEMINI_MODEL = _require("GEMINI_MODEL")
MAPS_SERVER_KEY = _require("MAPS_SERVER_KEY")

# Optional: a second model to try when the main one is overloaded. Leave empty to disable.
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "").strip() or None
