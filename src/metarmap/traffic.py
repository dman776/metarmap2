"""
Live traffic for the Map page: the aircraft adsb.fi sees around what the page is looking at.

Fetched only while someone is looking: each Map page that has live traffic ticked asks /api/traffic with its view
(center and radius), and the map asks adsb.fi again only when what it has for that place is older than
geo.map.traffic_seconds. A view is snapped to a grid cell (cover()), so pages looking at about the same place share
one fetch. Every fetch waits at least MIN_GAP seconds after the last one, so the map never asks adsb.fi more than once
a second, however many pages are open or where they look. A view wider than MAX_VIEW_NM gets no aircraft (a whole
country holds thousands, too many for a Pi to parse). Without a view it's the circle around the airports. A failed
fetch waits longer each time.

adsb.fi's open data is free for personal, non-commercial use, at most one request a second, and the map must credit
it (the Map page does). https://github.com/adsbfi/opendata
"""

import json
import logging
import math
import threading
import time

import requests

from metarmap import USER_AGENT

log = logging.getLogger(__name__)

API_URL = "https://opendata.adsb.fi/api/v3/lat/{lat:.4f}/lon/{lon:.4f}/dist/{dist}"
TIMEOUT = 10  # seconds
MAX_RADIUS_NM = 250  # the most adsb.fi gives around one point
MARGIN_NM = 25  # around the outermost airports, so aircraft show before they reach them
STALE_SECONDS = 60  # an aircraft whose position is older than this is left out
MAX_BACKOFF = 300  # seconds: the longest wait after failed fetches
RATE_LIMITED = 60  # seconds: the least wait after adsb.fi answers 429 (too many requests)
EARTH_NM = 3440.065
GRID_DEG = 0.25  # a view is snapped to this grid, so pages looking at about the same place share a fetch
RADII = (40, 75, 110, 150)  # NM: the circles asked about for a view (a few sizes, so their answers can be shared)
MAX_VIEW_NM = 135  # the widest view (its radius) that gets aircraft: a RADII circle always covers it, snapping included
MIN_GAP = 1.1  # seconds between any two requests to adsb.fi (its limit is one a second)
KEEP_SECONDS = 120  # a place nobody has asked about for this long is forgotten
MAX_PLACES = 12
COMPACT = (",", ":")


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


def cover(lat, lon, nm):
    """
    The circle ((lat, lon), radius in NM) to ask adsb.fi about for a view of radius nm around (lat, lon): the center
    snapped to a GRID_DEG grid and the radius to RADII, so nearby views get the same circle. None when the view is
    wider than MAX_VIEW_NM.
    """
    if nm > MAX_VIEW_NM:
        return None
    snapped = (round(round(lat / GRID_DEG) * GRID_DEG, 4), round(round(lon / GRID_DEG) * GRID_DEG, 4))
    need = nm + distance_nm((lat, lon), snapped)
    return snapped, next(r for r in RADII if need <= r)


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
    "R22",
    "R44",
    "R66",
    "H500",
    "MD52",
    "MD60",
    "H269",
    "G2CA",
    "EN28",
    "EN48",
    "B06",
    "B06T",
    "B407",
    "B427",
    "B429",
    "B430",
    "B505",
    "B205",
    "B212",
    "B412",
    "UH1",
    "UH1Y",
    "H60",
    "S70",
    "S76",
    "S92",
    "H47",
    "H53",
    "H64",
    "AH1",
    "AS50",
    "AS55",
    "AS65",
    "AS32",
    "AS3B",
    "EC20",
    "EC25",
    "EC30",
    "EC35",
    "EC45",
    "EC55",
    "EC75",
    "H160",
    "BK17",
    "A109",
    "A119",
    "A139",
    "A169",
    "A189",
    "NH90",
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
        aircraft.append(
            {
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
            }
        )
    return aircraft


class Place:
    """What's known about one circle: its aircraft, when they were fetched, and how its fetches are going."""

    def __init__(self):
        self.aircraft = []
        self.text = {}  # show ground traffic? -> the aircraft as JSON, made once per fetch
        self.circle = None  # the circle the aircraft are from
        self.fetched = None  # when the last fetch that worked was
        self.tried = None  # when the last fetch started
        self.backoff = 0  # seconds to wait after failed fetches (0 after one that worked)
        self.error = None
        self.asked = 0  # when a page last asked for it


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
        self._places = {}  # circle (None: no airport positions yet) -> Place
        self._last_request = None  # when adsb.fi was last asked
        self._blocked_until = 0  # no requests before this (after adsb.fi answers 429)

    def interval(self):
        """geo.map.traffic_seconds (within TRAFFIC_SECONDS: its Rule checks it, also in a hand-edited config.json)."""
        return float(self._settings().traffic_seconds)

    def due(self, place, now):
        return (
            (place.tried is None or now - place.tried >= max(self.interval(), place.backoff))
            and now >= self._blocked_until
            and (self._last_request is None or now - self._last_request >= MIN_GAP)
        )

    def snapshot(self, view=None):
        """
        The aircraft for /api/traffic, fetching first if what's there is old (see the module's notes). view: (lat, lon,
        radius in NM) of what the page shows; without it, the circle around the airports.
        """
        return self.state(*self._refresh(view))

    def snapshot_json(self, view=None):
        """snapshot() as JSON text: the aircraft are serialized once per fetch, not once per page that asks."""
        place, wide = self._refresh(view)
        head = json.dumps(self.state(place, wide, aircraft=False), separators=COMPACT)
        return head[:-1] + ',"aircraft":' + self._aircraft_json(place) + "}"

    def _refresh(self, view):
        if view is None:
            circle, wide = area(self._points()), False
        else:
            circle = cover(*view)
            wide = circle is None
        if wide:
            return None, True
        now = self._clock()
        with self._lock:
            place = self._places.setdefault(circle, Place())
            place.asked = now
            self._forget(now)
        if self.due(place, now) and self._fetching.acquire(blocking=False):
            try:
                if self.due(place, self._clock()):  # another page may have fetched while this one waited
                    self.fetch(place, circle)
            finally:
                self._fetching.release()
        return place, False

    def _forget(self, now):
        """Drops the places nobody asks about any more (with self._lock)."""
        for circle in [c for c, p in self._places.items() if now - p.asked > KEEP_SECONDS]:
            del self._places[circle]
        while len(self._places) > MAX_PLACES:
            del self._places[min(self._places, key=lambda c: self._places[c].asked)]

    def fetch(self, place, circle):
        """Asks adsb.fi about circle. Never raises: a failure is kept as the place's error."""
        now = place.tried = self._clock()
        if circle is None:
            self._failed(place, "no airport positions yet")
            return
        self._last_request = now
        (lat, lon), radius = circle
        try:
            response = self._get(
                API_URL.format(lat=lat, lon=lon, dist=radius), timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
            )
            if response.status_code == 429:
                self._blocked_until = now + RATE_LIMITED
                self._failed(place, "adsb.fi says too many requests", at_least=RATE_LIMITED)
                return
            response.raise_for_status()
            aircraft = parse(response.json(), now)
        except (requests.exceptions.RequestException, ValueError) as e:
            self._failed(place, f"couldn't reach adsb.fi: {e}")
            return
        with self._lock:
            place.aircraft, place.text, place.circle, place.fetched = aircraft, {}, circle, now
            place.backoff, place.error = 0, None

    def _failed(self, place, error, at_least=0):
        if place.error != error:  # once, not every few seconds
            log.warning(f"live traffic: {error}")
        with self._lock:
            place.error = error
            place.backoff = min(MAX_BACKOFF, max(at_least, 2 * self.interval(), 2 * place.backoff))

    def _aircraft_json(self, place):
        ground = bool(self._settings().traffic_ground)
        with self._lock:
            text = place.text.get(ground) if place else "[]"
            if text is None:
                text = place.text[ground] = json.dumps(self._shown(place, ground), separators=COMPACT)
        return text

    @staticmethod
    def _shown(place, ground):
        return [a for a in place.aircraft if ground or not a["ground"]] if place else []

    def state(self, place, wide=False, aircraft=True):
        """What /api/traffic answers for place (None for a view too wide, see MAX_VIEW_NM)."""
        ground = bool(self._settings().traffic_ground)
        with self._lock:
            shown = self._shown(place, ground)
            circle = place.circle if place else None
            fetched, error = (place.fetched, place.error) if place else (None, None)
        state = {
            "now": self._clock(),
            "interval": self.interval(),
            "fetched": fetched,
            "error": error,
            "center": list(circle[0]) if circle else None,
            "radius": circle[1] if circle else None,
            "source": {"name": "adsb.fi", "url": "https://adsb.fi/"},
            "too_wide": wide,
            "max_view": MAX_VIEW_NM,
        }
        if aircraft:
            state["aircraft"] = shown
        return state
