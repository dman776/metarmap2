"""
Live traffic for the Map page: the aircraft adsb.fi sees around the map's airports.

Fetched only while someone is looking: each Map page that has live traffic ticked asks /api/traffic, and the map asks
adsb.fi again only when what it has is older than geo.map.traffic_seconds. One fetch serves every open page, so the
map never asks adsb.fi more often than that, however many pages are open. A failed fetch waits longer each time.

adsb.fi's open data is free for personal, non-commercial use, at most one request a second, and the map must credit
it (the Map page does). https://github.com/adsbfi/opendata
"""
import math
import threading
import time

import requests

from metarmap import __version__
from metarmap.lib.safe_logging import safe_log
from metarmap.settings import TRAFFIC_SECONDS

API_URL = "https://opendata.adsb.fi/api/v3/lat/{lat:.4f}/lon/{lon:.4f}/dist/{dist}"
USER_AGENT = f"metarmap/{__version__} (+https://github.com/dman776/metarmap2)"
TIMEOUT = 10  # seconds
MAX_RADIUS_NM = 250  # the most adsb.fi gives around one point
MARGIN_NM = 25  # around the outermost airports, so aircraft show before they reach them
STALE_SECONDS = 60  # an aircraft whose position is older than this is left out
MAX_BACKOFF = 300  # seconds: the longest wait after failed fetches
RATE_LIMITED = 60  # seconds: the least wait after adsb.fi answers 429 (too many requests)
EARTH_NM = 3440.065


def distance_nm(a, b):
    """Great-circle distance between two (lat, lon) points, in nautical miles."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_NM * math.asin(min(1.0, math.sqrt(h)))


def area(points):
    """
    The circle to ask adsb.fi about: ((lat, lon), radius in NM) around every airport plus MARGIN_NM, at most
    MAX_RADIUS_NM (a map wider than that shows the traffic around its middle). None without any airport.
    """
    points = list(points)
    if not points:
        return None
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    center = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
    radius = max(distance_nm(center, p) for p in points) + MARGIN_NM
    return center, min(MAX_RADIUS_NM, math.ceil(radius))


# what the Map page draws, from the ADS-B emitter category (DO-260B): its shape and size
KINDS = {
    "A1": "light",  # under 15,500 lb: a Cessna 172, a Bonanza
    "A2": "small",  # 15,500 to 75,000 lb: business and regional jets
    "A3": "large",  # 75,000 to 300,000 lb: a 737, an A320
    "A4": "large",  # a 757 (high vortex)
    "A5": "heavy",  # over 300,000 lb: a 777, an A330
    "A6": "small",  # high performance (fast, agile): military jets
    "A7": "helicopter",
    "B1": "glider",
    "B2": "balloon",
    "B4": "light",  # ultralight, hang glider, paraglider
    "B6": "drone",
    "C1": "vehicle",  # emergency vehicle on an airport
    "C2": "vehicle",  # service vehicle
}
# ICAO type designators the category doesn't tell apart: the biggest heavies, and helicopters (many send A1, or none)
SUPER = {"A388", "A124", "A225", "B741", "B742", "B743", "B744", "B748", "C5M", "BLCF"}
HELICOPTERS = {
    "R22", "R44", "R66", "H500", "MD52", "MD60", "H269", "G2CA", "EN28", "EN48", "B06", "B06T", "B407", "B427", "B429",
    "B430", "B505", "B205", "B212", "B412", "UH1", "UH1Y", "H60", "S70", "S76", "S92", "H47", "H53", "H64", "AH1",
    "AS50", "AS55", "AS65", "AS32", "AS3B", "EC20", "EC25", "EC30", "EC35", "EC45", "EC55", "EC75", "H160", "BK17",
    "A109", "A119", "A139", "A169", "A189", "NH90",
}


def kind_of(category, type_code):
    """What an aircraft looks like on the Map page (see KINDS); "unknown" when neither tells."""
    if type_code in HELICOPTERS:
        return "helicopter"
    if type_code in SUPER:
        return "super"
    return KINDS.get(category, "unknown")


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def first_number(*values):
    """The first of values that's a number (0 included), else None."""
    return next((n for n in map(number, values) if n is not None), None)


def parse(data, fetched):
    """
    The aircraft in an adsb.fi answer that have a position no older than STALE_SECONDS. fetched: when it was fetched
    (epoch seconds); each aircraft's "at" is when its position was reported.
    """
    aircraft = []
    for a in (data or {}).get("ac") or []:
        lat, lon = number(a.get("lat")), number(a.get("lon"))
        seen = number(a.get("seen_pos"))
        if seen is None:
            seen = number(a.get("seen")) or 0
        if lat is None or lon is None or not a.get("hex") or seen > STALE_SECONDS:
            continue
        ground = a.get("alt_baro") == "ground"
        emergency = a.get("emergency")
        aircraft.append({
            "hex": a["hex"],
            "flight": (a.get("flight") or "").strip() or None,
            "reg": a.get("r"),
            "type": a.get("t"),
            "desc": a.get("desc"),
            "operator": a.get("ownOp"),
            "lat": lat,
            "lon": lon,
            "ground": ground,
            "alt": None if ground else first_number(a.get("alt_baro"), a.get("alt_geom")),
            "gs": number(a.get("gs")),
            "track": first_number(a.get("track"), a.get("true_heading")),
            "vrate": first_number(a.get("baro_rate"), a.get("geom_rate")),
            "squawk": a.get("squawk"),
            "emergency": emergency if emergency and emergency != "none" else None,
            "category": a.get("category"),
            "kind": kind_of(a.get("category"), a.get("t")),
            "at": round(fetched - seen, 2),
        })
    return aircraft


class Traffic:
    """
    settings: returns geo.map now (traffic_seconds, traffic_ground), so a change on the Config page applies at once.
    points: returns the airports' positions, [(lat, lon), ...].
    get: requests.get, or a test's own. clock: epoch seconds.
    """

    def __init__(self, settings, points, get=None, clock=time.time):
        self._settings = settings
        self._points = points
        self._get = get or requests.get
        self._clock = clock
        self._fetching = threading.Lock()  # one fetch at a time; other pages get what's there meanwhile
        self._lock = threading.Lock()
        self._aircraft = []
        self._area = None
        self._fetched = None  # when the last fetch that worked was
        self._tried = None  # when the last fetch started
        self._backoff = 0  # seconds to wait after failed fetches (0 after one that worked)
        self._error = None

    def interval(self):
        """geo.map.traffic_seconds, kept within TRAFFIC_SECONDS (config.json can be edited by hand)."""
        low, high = TRAFFIC_SECONDS
        try:
            seconds = float(self._settings().traffic_seconds)
        except (TypeError, ValueError):
            return low
        return min(high, max(low, seconds))

    def due(self, now):
        return self._tried is None or now - self._tried >= max(self.interval(), self._backoff)

    def snapshot(self):
        """The aircraft for /api/traffic, fetching first if what's there is old (see the module's notes)."""
        if self.due(self._clock()) and self._fetching.acquire(blocking=False):
            try:
                if self.due(self._clock()):  # another page may have fetched while this one waited
                    self.fetch()
            finally:
                self._fetching.release()
        return self.state()

    def fetch(self):
        """Asks adsb.fi about the area around the airports. Never raises: a failure is kept as state()["error"]."""
        now = self._tried = self._clock()
        circle = area(self._points())
        if circle is None:
            self._failed("no airport positions yet")
            return
        (lat, lon), radius = circle
        try:
            response = self._get(API_URL.format(lat=lat, lon=lon, dist=radius), timeout=TIMEOUT,
                                 headers={"User-Agent": USER_AGENT})
            if response.status_code == 429:
                self._failed("adsb.fi says too many requests", at_least=RATE_LIMITED)
                return
            response.raise_for_status()
            aircraft = parse(response.json(), now)
        except (requests.exceptions.RequestException, ValueError) as e:
            self._failed(f"couldn't reach adsb.fi: {e}")
            return
        with self._lock:
            self._aircraft, self._area, self._fetched = aircraft, circle, now
            self._backoff, self._error = 0, None

    def _failed(self, error, at_least=0):
        if self._error != error:  # once, not every few seconds
            safe_log(f"live traffic: {error}")
        with self._lock:
            self._error = error
            self._backoff = min(MAX_BACKOFF, max(at_least, 2 * self.interval(), 2 * self._backoff))

    def state(self):
        ground = bool(self._settings().traffic_ground)
        with self._lock:
            aircraft = [a for a in self._aircraft if ground or not a["ground"]]
            circle, fetched, error = self._area, self._fetched, self._error
        return {
            "now": self._clock(),
            "interval": self.interval(),
            "fetched": fetched,
            "error": error,
            "center": list(circle[0]) if circle else None,
            "radius": circle[1] if circle else None,
            "source": {"name": "adsb.fi", "url": "https://adsb.fi/"},
            "aircraft": aircraft,
        }
