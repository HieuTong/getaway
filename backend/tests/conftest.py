import os

# The app reads these at import time. Tests never call real services, so fake values are enough.
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("GEMINI_MODEL", "test-model")
os.environ.setdefault("MAPS_SERVER_KEY", "test-key")
