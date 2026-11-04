"""
G-AIRMETs and SIGMETs for the Advisories visualizer: which advisories each airport is inside.

AIRMETs: over the contiguous US, text AIRMETs ended in January 2025; aviationweather.gov now has G-AIRMETs (graphical
AIRMETs), areas forecast as snapshots 0, 3, 6, 9 and 12 hours ahead. Asked without a forecast hour, it answers with the
snapshot nearest now, so one request gives the current picture. Three groups: Sierra (IFR, mountain obscuration),
Tango (turbulence, strong surface wind, low-level wind shear) and Zulu (icing; its freezing level lines aren't a hazard
and are left out).

SIGMETs: the severe ones (thunderstorms, including the US convective SIGMETs, severe turbulence and icing, mountain
wave, volcanic ash, dust and sand storms, tropical cyclones), issued by the US and other countries. Each is valid for
a few hours; only those valid now count.

Both are fetched with the METARs (every 10 minutes). Only advisories starting below MAX_BASE_FT count: high-level
turbulence doesn't affect flying from the airport.
"""

import logging
import threading
import time

import requests

from metarmap import USER_AGENT

log = logging.getLogger(__name__)

AIRMET_URL = "https://aviationweather.gov/api/data/gairmet?format=json"
SIGMET_URL = "https://aviationweather.gov/api/data/sigmet?format=json"
# aviationweather.gov asks for a user agent of our own, so automated filtering doesn't block the map
TIMEOUT = 30  # seconds
MAX_BASE_FT = 18000

# hazard -> what it's called (short: the Map page's popup title; the legend explains each). In order of how much it
# matters, which picks the colors when an airport is in several
AIRMETS = {
    "ICE": "Icing",
    "LLWS": "Low-level wind shear",
    "IFR": "IFR",
    "TURB-LO": "Turbulence",
    "TURB-HI": "Turbulence",
    "MT_OBSC": "Mountain obscuration",
    "SFC_WND": "Strong surface wind",
}
SIGMETS = {
    "CONV": "Convective SIGMET",
    "TS": "Thunderstorms",
    "TC": "Tropical cyclone",
    "ICE": "Severe icing",
    "TURB": "Severe turbulence",
    "MTW": "Mountain wave",
    "VA": "Volcanic ash",
    "DS": "Dust storm",
    "SS": "Sandstorm",
}


def feet(value):
    """A G-AIRMET altitude ("080" is 8,000 ft) in feet; None for none or one that isn't a number."""
    try:
        return int(value) * 100
    except (TypeError, ValueError):
        return None


def base_ft(advisory):
    """Where a G-AIRMET's hazard starts, in feet: 0 at the surface, or the freezing level's lowest for icing there."""
    base = advisory.get("base")
    if base == "FZL":  # icing from the freezing level up
        return feet(advisory.get("fzlbase")) or 0
    return feet(base) or 0  # None or "SFC": IFR, mountain obscuration, wind and wind shear are at the surface


def outline(advisory):
    """The area's [(lat, lon), ...], or None if it isn't one."""
    try:
        coords = [(float(c["lat"]), float(c["lon"])) for c in advisory.get("coords") or []]
    except (KeyError, TypeError, ValueError):
        return None
    return coords if len(coords) >= 3 else None


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_airmets(data):
    """The G-AIRMET hazard areas in aviationweather.gov's answer that start below MAX_BASE_FT."""
    areas = []
    for a in data if isinstance(data, list) else []:
        if not isinstance(a, dict) or a.get("hazard") not in AIRMETS or a.get("geometryType") != "AREA":
            continue
        coords = outline(a)
        if coords is None or base_ft(a) >= MAX_BASE_FT:
            continue
        areas.append(
            {
                "kind": "AIRMET",
                "hazard": a["hazard"],
                "product": a.get("product"),
                "name": AIRMETS[a["hazard"]],
                "base": base_ft(a),
                "top": feet(a.get("top")),
                "due_to": a.get("due_to"),
                "severity": a.get("severity"),
                "valid": a.get("validTime"),
                "from": None,
                "expires": a.get("expireTime"),
                "coords": coords,
            }
        )
    return areas


def movement(direction, speed):
    """Where a SIGMET is heading: "Toward 320° at 5 kt" (the US gives degrees) or "Toward E at 20 kt"; None if not."""
    if direction in (None, ""):
        return None
    try:
        toward = f"{int(direction):03d}°"
    except (TypeError, ValueError):
        toward = str(direction)
    try:
        speed = int(speed)
    except (TypeError, ValueError):
        speed = None
    return f"Toward {toward}" + (f" at {speed} kt" if speed else "")


def parse_sigmets(data):
    """The SIGMET areas in aviationweather.gov's answer that start below MAX_BASE_FT (altitudes are in feet here)."""
    areas = []
    for a in data if isinstance(data, list) else []:
        if not isinstance(a, dict) or a.get("hazard") not in SIGMETS:
            continue
        coords = outline(a)
        base = number(a.get("base")) or 0  # thunderstorms: from the surface
        if coords is None or base >= MAX_BASE_FT:
            continue
        moving = movement(a.get("dir"), a.get("spd"))
        areas.append(
            {
                "kind": "SIGMET",
                "hazard": a["hazard"],
                "name": SIGMETS[a["hazard"]],
                "series": a.get("seriesId"),
                "qualifier": a.get("qualifier"),  # e.g. SEV, OCNL SEV, FRQ, EMBD
                "observed": a.get("sigmetType") == "OBS",
                "base": base,
                "top": number(a.get("top")),
                "moving": moving or None,
                "from": a.get("validTimeFrom"),
                "expires": a.get("validTimeTo"),
                "text": a.get("rawSigmet"),
                "coords": coords,
            }
        )
    return areas


def inside(lat, lon, polygon):
    """Whether (lat, lon) is inside the polygon [(lat, lon), ...] (ray casting; fine for areas this size)."""
    found = False
    for (lat1, lon1), (lat2, lon2) in zip(polygon, polygon[-1:] + polygon[:-1]):
        if (lat1 > lat) != (lat2 > lat) and lon < (lon2 - lon1) * (lat - lat1) / (lat2 - lat1) + lon1:
            found = not found
    return found


def in_effect(area, now):
    starts, ends = number(area.get("from")), number(area.get("expires"))
    return (starts is None or starts <= now) and (ends is None or ends > now)


class Feed:
    """One of the two: its last areas, and how its last fetch went."""

    def __init__(self, name, url, parse):
        self.name, self.url, self.parse = name, url, parse
        self.areas = None  # None until the first fetch works
        self.fetched = None
        self.error = None


class Advisories:
    """get: requests.get, or a test's own. clock: epoch seconds."""

    def __init__(self, get=None, clock=time.time):
        self._get = get or requests.get
        self._clock = clock
        self._lock = threading.Lock()
        self._feeds = {
            "airmet": Feed("G-AIRMET", AIRMET_URL, parse_airmets),
            "sigmet": Feed("SIGMET", SIGMET_URL, parse_sigmets),
        }

    def fetch(self):
        """
        Fetches the G-AIRMETs and SIGMETs. Returns True if either worked; a feed that fails keeps its old areas (until
        they expire).
        """
        return [self._fetch(feed) for feed in self._feeds.values()].count(True) > 0

    def _fetch(self, feed):
        try:
            response = self._get(feed.url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
            if response.status_code == 204:  # nothing in effect
                areas = []
            else:
                response.raise_for_status()
                areas = feed.parse(response.json())
        except (requests.exceptions.RequestException, ValueError) as e:
            if feed.error is None:  # once, not every 10 minutes
                log.warning(f"{feed.name} fetch failed: {e}")
            feed.error = f"couldn't reach aviationweather.gov: {e}"
            return False
        with self._lock:
            feed.areas, feed.fetched, feed.error = areas, self._clock(), None
        return True

    def areas(self, kind):
        """The "airmet" or "sigmet" areas in effect now; None before that feed's first fetch that worked."""
        with self._lock:
            areas = self._feeds[kind].areas
        if areas is None:
            return None
        now = self._clock()
        return [a for a in areas if in_effect(a, now)]

    def hazards_at(self, lat, lon):
        """
        {"airmets": [...], "sigmets": [...]}: the hazards over a place, most important first, each once. Either is None
        before its feed's first fetch that worked.
        """
        found = {}
        for kind, order in (("airmet", AIRMETS), ("sigmet", SIGMETS)):
            areas = self.areas(kind)
            hazards = None if areas is None else {a["hazard"] for a in areas if inside(lat, lon, a["coords"])}
            found[kind + "s"] = None if hazards is None else [h for h in order if h in hazards]
        return found

    def state(self):
        """For /api/advisories: each feed's last fetch, and the areas in effect (for the Map page)."""
        return {
            **{kind: {"fetched": feed.fetched, "error": feed.error} for kind, feed in self._feeds.items()},
            "areas": (self.areas("sigmet") or []) + (self.areas("airmet") or []),
        }
