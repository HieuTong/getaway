"""Pure text helpers: no network and no AI, so they are fast and easy to unit-test."""
import re

_DURATION = r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?)\b"

# A duration only counts as a drive limit when it's tied to driving:
#   "90 minutes drive", "2 hours away", "1.5 hrs of driving"  -> duration, then drive/away
#   "drive under 1 hour", "driving within 45 mins"            -> drive, then duration
_DRIVE_LIMIT_PATTERNS = [
    re.compile(_DURATION + r"\s*(?:of\s+)?(?:drive|driving|away)"),
    re.compile(r"(?:drive|driving)\s+(?:of\s+|under\s+|within\s+|less\s+than\s+)?" + _DURATION),
]


def drive_limit_minutes(query: str) -> int | None:
    """The maximum drive time the request asks for, in minutes, or None if it gives none.

    "a 2 hour hike, under 60 minutes drive" -> 60 (the hike length is ignored).
    """
    lowered = query.lower()
    for pattern in _DRIVE_LIMIT_PATTERNS:
        match = pattern.search(lowered)
        if match:
            value, unit = float(match.group(1)), match.group(2)
            return int(value * 60) if unit.startswith("h") else int(value)
    return None
