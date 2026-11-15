"""Bushfire safety facts from the CFA's official Fire Danger Rating and Total Fire Ban feeds.

Code, not the language model, owns these facts: they are fetched, parsed and applied by rules here,
and the model only sees them as data.

Feeds: https://www.cfa.vic.gov.au/rss-feeds (RSS 2.0, updated every minute; for personal,
non-commercial use, with a link back to the CFA wherever the ratings are shown).
Districts: https://www.cfa.vic.gov.au/warnings-restrictions/fire-districts
"""
import html
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime

import httpx

FEED_BASE = "https://www.cfa.vic.gov.au/cfa/rssfeed/"
DISTRICT_FEEDS = {
    "Central": "central-firedistrict_rss.xml",
    "East Gippsland": "eastgippsland-firedistrict_rss.xml",
    "Mallee": "mallee-firedistrict_rss.xml",
    "North Central": "northcentral-firedistrict_rss.xml",
    "North East": "northeast-firedistrict_rss.xml",
    "Northern Country": "northerncountry-firedistrict_rss.xml",
    "South West": "southwest-firedistrict_rss.xml",
    "West and South Gippsland": "westandsouthgippsland-firedistrict_rss.xml",
    "Wimmera": "wimmera-firedistrict_rss.xml",
}
CFA_RATINGS_URL = "https://www.cfa.vic.gov.au/warnings-restrictions/total-fire-bans-and-ratings"
VICEMERGENCY_URL = "https://emergency.vic.gov.au"

# Municipalities in each fire weather district, from the CFA's "Find your fire weather district" page.
DISTRICT_MUNICIPALITIES = {
    "Mallee": ["Buloke Shire", "Gannawarra Shire", "Mildura Rural City", "Swan Hill Rural City",
               "Yarriambiack Shire (north of the netting fence)"],
    "Wimmera": ["Hindmarsh Shire", "Horsham Rural City", "Northern Grampians Shire", "West Wimmera Shire",
                "Yarriambiack Shire (south of the netting fence)"],
    "South West": ["Ararat Rural City", "Colac Otway Shire", "Corangamite Shire", "Glenelg Shire", "Moyne Shire",
                   "Pyrenees Shire", "Southern Grampians Shire", "Warrnambool City"],
    "Northern Country": ["Campaspe Shire", "Greater Bendigo City", "Greater Shepparton City", "Loddon Shire",
                         "Moira Shire", "Strathbogie Shire"],
    "North Central": ["Central Goldfields Shire", "Lake Mountain Alpine Resort (Unincorporated)", "Mitchell Shire",
                      "Mount Alexander Shire", "Murrindindi Shire"],
    "Central": ["Ballarat City", "Banyule City", "Bass Coast Shire", "Bayside City", "Boroondara City",
                "Brimbank City", "Cardinia Shire", "Casey City", "Darebin City", "Frankston City",
                "French Island (Unincorporated)", "Glen Eira City", "Golden Plains Shire", "Greater Dandenong City",
                "Greater Geelong City", "Hepburn Shire", "Hobsons Bay City", "Hume City", "Kingston City",
                "Knox City", "Macedon Ranges Shire", "Manningham City", "Maribyrnong City", "Maroondah City",
                "Melbourne City", "Melton Shire", "Monash City", "Moonee Valley City", "Moorabool Shire",
                "Moreland City", "Merri-bek City",  # Moreland was renamed Merri-bek in 2022
                "Mornington Peninsula Shire", "Nillumbik Shire", "Port Phillip City", "Queenscliffe Borough",
                "Stonnington City", "Surf Coast Shire", "Whitehorse City", "Whittlesea City", "Wyndham City",
                "Yarra City", "Yarra Ranges Shire"],
    "North East": ["Alpine Shire", "Benalla Rural City", "Falls Creek Alpine Resort (Unincorporated)",
                   "Indigo Shire", "Mansfield Shire", "Mount Buller Alpine Resort (Unincorporated)",
                   "Mount Hotham Alpine Resort (Unincorporated)", "Mount Stirling Alpine Resort (Unincorporated)",
                   "Towong Shire", "Wangaratta Rural City", "Wodonga City"],
    "East Gippsland": ["East Gippsland Shire"],
    "West and South Gippsland": ["Baw Baw Shire", "Latrobe City", "Mount Baw Baw Alpine Resort (Unincorporated)",
                                 "South Gippsland Shire", "Wellington Shire"],
}

# Australia's Fire Danger Rating System levels, lowest to highest.
RATINGS = ["NO RATING", "MODERATE", "HIGH", "EXTREME", "CATASTROPHIC"]
_RATING_RE = re.compile(r"\b(NO RATING|CATASTROPHIC|EXTREME|HIGH|MODERATE)\b")  # capitals, as the feed writes them

FEED_CACHE_SECONDS = 10 * 60  # the CFA asks readers to stay reasonably fresh; 10 minutes is plenty for trip planning

_http = httpx.Client(timeout=8, follow_redirects=True)
_cache: dict[str, tuple[float, dict[date, dict] | None]] = {}
_cache_lock = threading.Lock()


def normalize_municipality(name: str) -> str:
    """'Shire of Yarra Ranges', 'Yarra Ranges Shire' and 'Yarra Ranges Shire Council' all become 'yarra ranges'."""
    text = re.sub(r"\(.*?\)", " ", name.lower())  # "(north of the netting fence)", "(unincorporated)"
    text = re.sub(r"^\s*(rural city|city|shire|borough) of\s+", "", text)
    text = re.sub(r"\b(rural city|city council|shire council|council|shire|city|borough|alpine resort)\b", " ", text)
    return " ".join(text.split())


_MUNICIPALITY_DISTRICTS: dict[str, list[str]] = {}
for _district, _names in DISTRICT_MUNICIPALITIES.items():
    for _name in _names:
        _MUNICIPALITY_DISTRICTS.setdefault(normalize_municipality(_name), []).append(_district)


def districts_for(municipality: str | None) -> list[str]:
    """The fire district(s) a municipality belongs to. Yarriambiack is split across two, so it returns both."""
    if not municipality:
        return []
    return _MUNICIPALITY_DISTRICTS.get(normalize_municipality(municipality), [])


def _plain_text(description: str) -> str:
    """The feed's description is HTML (sometimes escaped twice): unescape it and strip the tags."""
    text = html.unescape(description)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def _total_fire_ban(text: str) -> bool | None:
    lowered = text.lower()
    if "not currently a day of total fire ban" in lowered:
        return False
    if re.search(r"\bis (?:currently )?a day of total fire ban", lowered) or "total fire ban has been declared" in lowered:
        return True
    return None  # wording we don't recognise: report "unknown", never "no ban"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]  # drops any XML namespace


def parse_feed(xml_text: str) -> dict[date, dict]:
    """{day: {"rating": "HIGH" | None, "total_fire_ban": True | False | None}} for each forecast day in a district feed."""
    days: dict[date, dict] = {}
    for item in ET.fromstring(xml_text).iter():
        if _local(item.tag) != "item":
            continue
        fields = {_local(child.tag): (child.text or "") for child in item}
        try:
            day = datetime.strptime(fields.get("title", "").strip(), "%A, %d %B %Y").date()
        except ValueError:
            continue  # not a forecast day, e.g. the "Fire restrictions by municipality" item
        text = _plain_text(fields.get("description", ""))
        match = _RATING_RE.search(text)
        days[day] = {"rating": match.group(1) if match else None, "total_fire_ban": _total_fire_ban(text)}
    return days


def _forecast(district: str) -> dict[date, dict] | None:
    """A district's forecast, cached briefly. None if the feed couldn't be read (that means unknown, not safe)."""
    with _cache_lock:
        cached = _cache.get(district)
        if cached and time.time() - cached[0] < FEED_CACHE_SECONDS:
            return cached[1]
    try:
        response = _http.get(FEED_BASE + DISTRICT_FEEDS[district])
        response.raise_for_status()
        forecast = parse_feed(response.text)
    except (httpx.HTTPError, ET.ParseError) as error:
        print(f"CFA feed for {district} failed: {error}")  # never fail silently
        forecast = None
    with _cache_lock:
        _cache[district] = (time.time(), forecast)
    return forecast


def fire_outlook(municipality: str | None, day: date) -> dict | None:
    """Fire danger and Total Fire Ban for a place on a day, or None if its fire district isn't known.

    Unknown values stay None: the app must say "check before you go", never imply it's safe.
    """
    districts = districts_for(municipality)
    if not districts:
        return None
    known = []
    for district in districts:
        forecast = _forecast(district)
        entry = forecast.get(day) if forecast else None
        if entry:
            known.append((district, entry))
    if not known:
        return {"district": " / ".join(districts), "rating": None, "total_fire_ban": None}

    # A municipality split across districts takes the more dangerous one.
    district, worst = max(known, key=lambda pair: RATINGS.index(pair[1]["rating"]) if pair[1]["rating"] else -1)
    bans = [entry["total_fire_ban"] for _, entry in known]
    total_fire_ban = True if True in bans else (False if all(ban is False for ban in bans) else None)
    return {"district": district, "rating": worst["rating"], "total_fire_ban": total_fire_ban}


def is_at_least(rating: str | None, threshold: str) -> bool:
    return rating is not None and RATINGS.index(rating) >= RATINGS.index(threshold)
