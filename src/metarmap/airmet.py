"""
G-AIRMETs (graphical AIRMETs) for the AIRMET visualizer: which hazards each airport is inside.

Over the contiguous US, text AIRMETs ended in January 2025; aviationweather.gov now has G-AIRMETs, areas forecast as
snapshots 0, 3, 6, 9 and 12 hours ahead. Asked without a forecast hour, it answers with the snapshot nearest now,
so one request gives the current picture. It's fetched with the METARs (every 10 minutes): new G-AIRMETs come about
every 3 to 6 hours, plus amendments.

Three groups: Sierra (IFR, mountain obscuration), Tango (turbulence, strong surface wind, low-level wind shear) and
Zulu (icing; its freezing level lines aren't a hazard and are left out). Only hazards starting below MAX_BASE_FT
count: high-level turbulence (always FL180 and above) doesn't affect flying from the airport.
"""
import threading
import time

import requests

from metarmap import __version__
from metarmap.lib.safe_logging import safe_log

API_URL = "https://aviationweather.gov/api/data/gairmet?format=json"
# aviationweather.gov asks for a user agent of our own, so automated filtering doesn't block the map
USER_AGENT = f"metarmap/{__version__} (+https://github.com/dman776/metarmap2)"
TIMEOUT = 30  # seconds
MAX_BASE_FT = 18000

# hazard -> what it's called (short: the Map page's popup title; the legend explains each); in order of how much it
# matters, which picks the colors when an airport is in several
HAZARDS = {
    "ICE": "Icing",
    "LLWS": "Low-level wind shear",
    "IFR": "IFR",
    "TURB-LO": "Turbulence",
    "TURB-HI": "Turbulence",
    "MT_OBSC": "Mountain obscuration",
    "SFC_WND": "Strong surface wind",
}


def feet(value):
    """A G-AIRMET altitude ("080" is 8,000 ft) in feet; None for none or one that isn't a number."""
    try:
        return int(value) * 100
    except (TypeError, ValueError):
        return None


def base_ft(advisory):
    """Where the hazard starts, in feet: 0 at the surface, or the freezing level's lowest for icing based there."""
    base = advisory.get("base")
    if base == "FZL":  # icing from the freezing level up
        return feet(advisory.get("fzlbase")) or 0
    return feet(base) or 0  # None or "SFC": IFR, mountain obscuration, wind and wind shear are at the surface


def parse(data):
    """The hazard areas in aviationweather.gov's answer that start below MAX_BASE_FT."""
    areas = []
    for a in data if isinstance(data, list) else []:
        if not isinstance(a, dict) or a.get("hazard") not in HAZARDS or a.get("geometryType") != "AREA":
            continue
        try:
            coords = [(float(c["lat"]), float(c["lon"])) for c in a.get("coords") or []]
        except (KeyError, TypeError, ValueError):
            continue
        if len(coords) < 3 or base_ft(a) >= MAX_BASE_FT:
            continue
        areas.append({
            "hazard": a["hazard"],
            "product": a.get("product"),
            "name": HAZARDS[a["hazard"]],
            "base": base_ft(a),
            "top": feet(a.get("top")),
            "due_to": a.get("due_to"),
            "severity": a.get("severity"),
            "valid": a.get("validTime"),
            "expires": a.get("expireTime"),
            "coords": coords,
        })
    return areas


def inside(lat, lon, polygon):
    """Whether (lat, lon) is inside the polygon [(lat, lon), ...] (ray casting; fine for areas this size)."""
    found = False
    for (lat1, lon1), (lat2, lon2) in zip(polygon, polygon[-1:] + polygon[:-1]):
        if (lat1 > lat) != (lat2 > lat) and lon < (lon2 - lon1) * (lat - lat1) / (lat2 - lat1) + lon1:
            found = not found
    return found


class Airmets:
    """get: requests.get, or a test's own. clock: epoch seconds."""

    def __init__(self, get=None, clock=time.time):
        self._get = get or requests.get
        self._clock = clock
        self._lock = threading.Lock()
        self._areas = None  # None until the first fetch works
        self.fetched = None
        self.error = None

    def fetch(self):
        """Fetches the G-AIRMETs. Returns True if it worked; on an error the old ones are kept (until they expire)."""
        try:
            response = self._get(API_URL, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
            if response.status_code == 204:  # nothing in effect
                areas = []
            else:
                response.raise_for_status()
                areas = parse(response.json())
        except (requests.exceptions.RequestException, ValueError) as e:
            if self.error is None:  # once, not every 10 minutes
                safe_log(f"G-AIRMET fetch failed: {e}")
            self.error = f"couldn't reach aviationweather.gov: {e}"
            return False
        with self._lock:
            self._areas, self.fetched, self.error = areas, self._clock(), None
        return True

    def areas(self):
        """The hazard areas in effect (not expired); None before the first fetch that worked."""
        with self._lock:
            areas = self._areas
        if areas is None:
            return None
        now = self._clock()
        return [a for a in areas if not isinstance(a["expires"], (int, float)) or a["expires"] > now]

    def hazards_at(self, lat, lon):
        """The hazards over a place, most important first, each once; None before the first fetch that worked."""
        areas = self.areas()
        if areas is None:
            return None
        found = {a["hazard"] for a in areas if inside(lat, lon, a["coords"])}
        return [h for h in HAZARDS if h in found]

    def state(self):
        """For /api/airmets: the areas (for the Map page), and when they were fetched."""
        return {"fetched": self.fetched, "error": self.error, "areas": self.areas() or []}
