"""
Live traffic for the Map page: the aircraft adsb.fi sees around what the page is looking at.

Fetched only while someone is looking: each Map page that has live traffic ticked asks /api/traffic with its view
(center, radius and, from the Map page, its half-height and half-width in degrees), and the map asks adsb.fi again only
when what it has for a circle is older than geo.map.traffic_seconds. A view up to MAX_RADIUS_NM (the most adsb.fi gives
around one point) is one circle, snapped to a grid cell (cover()), so pages looking at about the same place share one
fetch. A wider view, up to MAX_VIEW_NM, is split into 2 x 2 boxes (3 x 2 if that's not enough) and each box gets its
own circle (covering()); the aircraft from them are merged, each one once, at most MAX_AIRCRAFT. At most MAX_PLACES
circles are kept; one a page is still asking about is never dropped to make room, so a view that doesn't fit waits.

Every fetch waits at least MIN_GAP seconds after the last one, so the map never asks adsb.fi more than once a second,
however many circles, pages or places: a page's request fetches at most one circle itself and answers at once with what
is there, and a background thread fetches the rest as they come due, MIN_GAP apart, the view asked about last first (it
stops once no page has asked about them since their last fetch). Only one view with a circle not fetched before starts
per geo.map.traffic_seconds, or sooner once the last one to start has been left (ABANDONED_SECONDS: a page panning),
so a script that keeps changing its view can't keep the Pi fetching. A view wider than MAX_VIEW_NM gets no aircraft
(a whole country holds thousands, too many for a Pi to parse). Without a view it's the circle around the airports. A
failed fetch waits longer each time; adsb.fi's 429 stops every fetch for a while.

adsb.fi's open data is free for personal, non-commercial use, at most one request a second, and the map must credit
it (the Map page does). https://github.com/adsbfi/opendata
"""

import itertools
import json
import logging
import math
import threading
import time
from typing import Dict

import requests

from metarmap import USER_AGENT, http

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
RADII = (40, 75, 110, 150, 200, 250)  # NM: the circles asked about for a view (a few sizes, so answers can be shared)
MAX_VIEW_NM = 500  # the widest view (center to corner) that gets aircraft: a few adsb.fi circles side by side
LAYOUTS = ((2, 2), (3, 2), (2, 3))  # columns x rows of circles tried, in turn, for a view wider than one circle
MAX_AIRCRAFT = 1500  # at most this many aircraft in an answer (the nearest the middle), so a Pi and a browser keep up
MIN_GAP = 1.1  # seconds between any two requests to adsb.fi (its limit is one a second)
KEEP_SECONDS = 120  # a place nobody has asked about for this long is forgotten
MAX_PLACES = 19  # circles kept: three of the widest views (6 circles each) and one more
WANTED_SECONDS = 10  # a circle asked about within the interval and this long is fetched in the background
ABANDONED_SECONDS = 2.5  # a view nobody asked about this long has been left (a page waiting for one asks every 1.2 s)
UNTRIED_SECONDS = 5  # but one never fetched only this long (a page waiting for it asks again every second or so)
STARTED_KEPT = 8  # views remembered as started (their circles skip the one-new-view-per-interval wait)
SHOWN_KEPT = 8  # views whose merged aircraft (and JSON) are kept
TOO_MANY = "adsb.fi says too many requests"
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
    snapped to a GRID_DEG grid and the radius to RADII, so nearby views get the same circle. A view too wide to snap
    and still be covered (within about 11 NM of the limit) gets its own exact circle. None when the view is wider
    than one circle (MAX_RADIUS_NM).
    """
    if nm > MAX_RADIUS_NM:
        return None
    snapped = (round(round(lat / GRID_DEG) * GRID_DEG, 4), round(round(lon / GRID_DEG) * GRID_DEG, 4))
    need = nm + distance_nm((lat, lon), snapped)
    radius = next((r for r in RADII if need <= r), None)
    if radius is None:
        return (round(lat, 4), round(lon, 4)), math.ceil(nm)
    return snapped, radius


def wrap(lon):
    """A longitude in -180 to 180."""
    return (lon + 180) % 360 - 180


def square(lat, nm):
    """(half-height, half-width) in degrees of a square view whose corners are nm from its center at lat."""
    dlat = math.degrees(nm / math.sqrt(2) / EARTH_NM)
    return dlat, min(180.0, dlat / max(0.01, math.cos(math.radians(lat))))


def enclose(south, north, west, east):
    """
    The smallest circle ((lat, lon), radius in NM) centered on the box's middle meridian that holds the box. Its
    farthest points are corners (along a parallel the distance grows away from the middle, along a meridian it is
    largest at an end), so the center's latitude is where a south and a north corner are as far.
    """
    mid = (west + east) / 2
    lo, hi = south, north
    for _ in range(30):
        la = (lo + hi) / 2
        if distance_nm((la, mid), (south, west)) < distance_nm((la, mid), (north, west)):
            lo = la
        else:
            hi = la
    center = ((lo + hi) / 2, mid)
    return center, max(distance_nm(center, (south, west)), distance_nm(center, (north, west)))


def grid(lat, lon, dlat, dlon, columns, rows):
    """The view's box cut into columns x rows, one circle each (snapped when it can be); None if one is too big."""
    south, north = max(-90.0, lat - dlat), min(90.0, lat + dlat)
    circles = []
    for r in range(rows):
        s, n = south + (north - south) * r / rows, south + (north - south) * (r + 1) / rows
        for c in range(columns):
            w, e = lon - dlon + 2 * dlon * c / columns, lon - dlon + 2 * dlon * (c + 1) / columns
            (clat, clon), radius = enclose(s, n, w, e)
            circle = cover(clat, wrap(clon), radius)
            if circle is None:
                return None
            circles.append(circle)
    return tuple(dict.fromkeys(circles))


def covering(lat, lon, nm, dlat=None, dlon=None):
    """
    The circles to ask adsb.fi about for a view of radius nm (center to corner) around (lat, lon), as a tuple of
    ((lat, lon), radius in NM), each at most MAX_RADIUS_NM: one (cover()) up to MAX_RADIUS_NM, else the view's box
    (dlat, dlon: its half-height and half-width in degrees; a square when not given) cut into the first of LAYOUTS
    whose circles hold it. None when the view is wider than MAX_VIEW_NM (or its box too big for those circles).
    """
    if nm > MAX_VIEW_NM:
        return None
    if nm <= MAX_RADIUS_NM:
        return (cover(lat, lon, nm),)
    if dlat is None or dlon is None:
        dlat, dlon = square(lat, nm)
    layouts = list(LAYOUTS)
    if dlon * math.cos(math.radians(lat)) < dlat:  # taller than wide: three rows before three columns
        layouts[1], layouts[2] = layouts[2], layouts[1]
    return next((c for c in (grid(lat, lon, dlat, dlon, *layout) for layout in layouts) if c), None)


def merge(lists, center=None, limit=None):
    """
    The aircraft from several circles, each one (by hex) once, its newest position; at most limit (MAX_AIRCRAFT), the
    ones nearest center (lat, lon) when there are more.
    """
    limit = MAX_AIRCRAFT if limit is None else limit
    lists = list(lists)
    if len(lists) == 1:
        found = list(lists[0])
    else:
        newest: Dict[str, dict] = {}
        for aircraft in lists:
            for a in aircraft:
                seen = newest.get(a["hex"])
                if seen is None or a["at"] > seen["at"]:
                    newest[a["hex"]] = a
        found = list(newest.values())
    if len(found) > limit:
        lat, lon = center or (0.0, 0.0)
        k = math.cos(math.radians(lat)) ** 2
        found.sort(key=lambda a: (a["lat"] - lat) ** 2 + k * wrap(a["lon"] - lon) ** 2)
        del found[limit:]
    return found


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

    _serials = itertools.count()

    def __init__(self, key=None):
        self.key = key  # the circle asked about (None: no airport positions yet)
        self.serial = next(Place._serials)  # tells a place from one made later for the same circle
        self.view = ()  # the circles of the last view that asked for it
        self.aircraft = []
        self.circle = None  # the circle the aircraft are from
        self.fetched = None  # when the last fetch that worked was
        self.tried = None  # when the last fetch started
        self.backoff = 0  # seconds to wait after failed fetches (0 after one that worked)
        self.error = None
        self.asked = 0  # when a page last asked for it


def start_thread(work):
    threading.Thread(target=work, name="traffic", daemon=True).start()


class Traffic:
    """
    settings: returns geo.map now (traffic_seconds, traffic_ground), so a change on the Config page applies at once.
    points: returns the airports' positions, [(lat, lon), ...].
    get: http.get, or a test's own. clock: epoch seconds. sleep: time.sleep. spawn: runs a function in the background
    (a new thread), for the circles of a view after the first.
    """

    def __init__(self, settings, points, get=None, clock=time.time, sleep=time.sleep, spawn=start_thread):
        self._settings = settings
        self._points = points
        self._get = get or http.get
        self._clock = clock
        self._sleep = sleep
        self._spawn = spawn
        self._fetching = threading.Lock()  # one fetch at a time; other pages get what's there meanwhile
        self._lock = threading.Lock()
        self._places = {}  # circle (None: no airport positions yet) -> Place
        self._shown = {}  # (circles, show ground traffic?) -> (what they were made from, aircraft, their JSON)
        self._last_request = None  # when adsb.fi was last asked
        self._last_new = None  # when a view with a circle never fetched last started its first fetch
        self._started: Dict[frozenset, float] = {}  # the views that started lately (their circles) -> when
        self._last_view: frozenset = frozenset()  # the last of them
        self._blocked_until = 0  # no requests before this (after adsb.fi answers 429)
        self._working = False  # the background fetch is running

    def interval(self):
        """geo.map.traffic_seconds (within TRAFFIC_SECONDS: its Rule checks it, also in a hand-edited config.json)."""
        return float(self._settings().traffic_seconds)

    def due(self, place, now, gap=True):
        """Whether place may be fetched now; gap=False: but for MIN_GAP since the last request."""
        return (
            (place.tried is None or now - place.tried >= max(self.interval(), place.backoff))
            and now >= self._blocked_until
            and (not gap or self._last_request is None or now - self._last_request >= MIN_GAP)
            and self._may_start(place, now)
        )

    def _may_start(self, place, now):
        """
        Whether place may have its first fetch now: only one new view starts per interval, but the rest of a view that
        started lately may follow (also a circle of it dropped by _forget() and asked for again), and a new one may
        start as soon as the last one to start has been left (ABANDONED_SECONDS), so a page panning a wide view gets
        the view it stopped at without waiting out the interval for the ones it passed.
        """
        if place.tried is not None or self._last_new is None or now - self._last_new >= self.interval():
            return True
        started = self._started.get(frozenset(place.view or (place.key,)))
        if started is not None and now - started <= KEEP_SECONDS:
            return True
        last = [self._places.get(c) for c in self._last_view]
        return all(p is None or now - p.asked > ABANDONED_SECONDS for p in last)

    def _due_at(self, place, now):
        """
        About when place may be fetched, but for MIN_GAP (now or later); None for a circle never fetched that has to
        wait for another view to have started (only one new view per interval). due() says for sure.
        """
        if place.tried is None:
            if not self._may_start(place, now):
                return None
            at = now
        else:
            at = place.tried + max(self.interval(), place.backoff)
        return max(at, self._blocked_until)

    def _most_due(self, places, now, gap=True):
        """The place to fetch first: one never tried, else the one tried longest ago. None when none is due."""
        due = [p for p in places if self.due(p, now, gap)]
        return min(due, key=lambda p: (p.tried is not None, p.tried or 0)) if due else None

    def snapshot(self, view=None):
        """
        The aircraft for /api/traffic, fetching first if what's there is old (see the module's notes). view: (lat, lon,
        radius in NM[, half-height, half-width in degrees]) of what the page shows; without it, the circle around the
        airports.
        """
        return self.state(*self._refresh(view))

    def snapshot_json(self, view=None):
        """snapshot() as JSON text: the aircraft are serialized once per fetch, not once per page that asks."""
        places, wide, center = self._refresh(view)
        head = json.dumps(self.state(places, wide, center, aircraft=False), separators=COMPACT)
        return head[:-1] + ',"aircraft":' + self._aircraft(places, center, text=True) + "}"

    def _refresh(self, view):
        """The view's places (fetching the most due of them if it may), whether it's too wide, and its center."""
        if view is None:
            circles, center = (area(self._points()),), None
        else:
            circles, center = covering(*view), (round(view[0], 4), round(view[1], 4))
        if circles is None:
            return [], True, center
        now = self._clock()
        with self._lock:
            for circle in circles:  # asked now, so not forgotten
                if circle in self._places:
                    self._places[circle].asked = now
            self._forget(now)
            missing = [c for c in circles if c not in self._places]
            fits = self._make_room(len(missing), now)
            places = []
            for circle in circles:
                place = self._places.get(circle)
                if place is None:
                    place = Place(circle)
                    if fits:
                        self._places[circle] = place
                place.asked, place.view = now, circles
                places.append(place)
        # a view that doesn't fit waits (loading, nothing fetched for it) until pages looking elsewhere stop asking
        first = self._most_due([p for p in places if self._places.get(p.key) is p], now)
        if first is not None and self._fetching.acquire(blocking=False):
            try:
                if self.due(first, self._clock()):  # another page may have fetched while this one waited
                    self.fetch(first, first.key)
            finally:
                self._fetching.release()
        self._fetch_rest()
        return places, False, center

    def _forget(self, now):
        """Drops the places nobody asks about any more, and the merged aircraft made from them (with self._lock)."""
        for circle in [c for c, p in self._places.items() if now - p.asked > KEEP_SECONDS]:
            del self._places[circle]
        self._forget_shown()

    def _forget_shown(self):
        for key in [k for k in self._shown if any(c not in self._places for c in k[0])]:
            del self._shown[key]

    def _in_use(self, place, now):
        """
        Whether a page is still looking at place: asked about within an interval and WANTED_SECONDS, or, one never
        fetched, within UNTRIED_SECONDS (a page waiting for it asks again every second or so; one that has moved on,
        e.g. panning a wide view, stops, and its circles are dropped and not fetched).
        """
        if place.tried is None:
            return now - place.asked <= UNTRIED_SECONDS
        return now - place.asked <= self.interval() + WANTED_SECONDS

    def _idle(self, place, now):
        """
        Whether place may be dropped to make room: not in use (_in_use()), or never fetched and not asked about for
        ABANDONED_SECONDS (nothing is lost, and a page panning a wide view gets room for the view it has moved to).
        """
        return not self._in_use(place, now) or (place.tried is None and now - place.asked > ABANDONED_SECONDS)

    def _make_room(self, needed, now):
        """
        Makes room for needed more places, at most MAX_PLACES in all, by dropping ones no page is looking at any more
        (_idle()): those never fetched first (nothing is lost), then those asked about least lately. False, dropping
        none, when that's not enough: a view that doesn't fit waits, rather than every view on screen throwing away
        another's answers and fetching them again. With self._lock.
        """
        room = MAX_PLACES - len(self._places)
        if needed <= room:
            return True
        idle = sorted(((p.tried is not None, p.asked), c) for c, p in self._places.items() if self._idle(p, now))
        if needed > room + len(idle):
            return False
        for _, circle in idle[: needed - room]:
            del self._places[circle]
        self._forget_shown()
        return True

    def _waiting(self, now):
        """
        (place, about when it's due) for the next one the background fetch is for, of the places a page is looking at
        (_in_use()) and has asked about since they were last tried (a page that looks elsewhere now doesn't keep its
        old ones fetched): one never fetched first, the one asked about last (the view a page has just moved to, and a
        wide view always behind can't keep the others from starting), else the one due soonest. A circle of a view of
        several is waited for if it's due within about the time its view's circles take one after another; a view of
        one circle only once it's due (its page asked, but another fetch had just gone: nothing is fetched ahead of a
        page asking). Never one waiting out a failure or a 429. None when there's none.
        With self._lock.
        """
        soonest = None
        for p in self._places.values():
            if p.key is None or not self._in_use(p, now) or (p.tried is not None and p.asked <= p.tried):
                continue
            at = self._due_at(p, now)
            ahead = MIN_GAP * len(p.view) + 1 if len(p.view) > 1 else 0  # a wide view's circles come due MIN_GAP apart
            rank = (p.tried is not None, -p.asked if p.tried is None else at)
            if at is not None and at - now <= ahead and (soonest is None or rank < soonest[2]):
                soonest = p, at, rank
        return soonest[:2] if soonest else None

    def _fetch_rest(self):
        """Starts the background fetch (_work) if a circle pages asked about lately is waiting and it isn't running."""
        with self._lock:
            if self._working or self._waiting(self._clock()) is None:
                return
            self._working = True
        try:
            self._spawn(self._work)
        except RuntimeError as e:  # no thread to be had: the pages' own requests fetch them, one each
            log.warning(f"live traffic: can't fetch in the background: {e}")
            with self._lock:
                self._working = False

    def _work(self):
        """
        Fetches the circles pages asked about lately as they come due, one at a time, each MIN_GAP after the last
        request (so never more than one a second), until there are none (_waiting()); a page's request meanwhile
        answers with what's there. Waiting for the ones due soon keeps a wide view's circles fetched about once an
        interval (when there are few enough of them to fetch one a second), though a page asks only once an interval.
        After each wait it chooses again: a page may have moved on meanwhile.
        """
        try:
            for _ in range(8 * MAX_PLACES):  # each pass fetches one or waits: never for ever (a page starts it again)
                planned = self._plan()
                if planned is None:
                    return
                place, start = planned
                wait = start - self._clock()
                if wait > 0:
                    self._sleep(wait + 0.01)  # a little over, for rounding
                    continue
                self._fetch_due(place)
        except Exception:  # a thread that dies quietly would stop every later background fetch
            log.warning("live traffic: background fetch failed", exc_info=True)
        with self._lock:
            self._working = False

    def _plan(self):
        """(place, when to fetch it) for the background fetch's next pass; None, and it stops, when there's none."""
        with self._lock:
            found = self._waiting(self._clock())
            if found is None:
                self._working = False
                return None
        place, at = found
        last = self._last_request
        return place, (at if last is None else max(at, last + MIN_GAP))

    def _fetch_due(self, place):
        """
        Fetches place if it's still kept (not dropped while the background fetch waited) and due (another page's request
        may have fetched it meanwhile).
        """
        with self._fetching:
            with self._lock:
                kept = self._places.get(place.key) is place
            if kept and self.due(place, self._clock()):
                self.fetch(place, place.key)

    def fetch(self, place, circle):
        """Asks adsb.fi about circle. Never raises: a failure is kept as the place's error."""
        first = place.tried is None
        now = place.tried = self._clock()
        if circle is None:
            self._failed(place, "no airport positions yet")
            return
        self._last_request = now
        view = frozenset(place.view or (circle,))
        started = self._started.get(view)
        if first and (started is None or now - started > KEEP_SECONDS):  # a new view starts: the rest may follow
            self._started.pop(view, None)  # (put back last: the ones kept are the latest)
            self._last_new = self._started[view] = now
            self._last_view = view
            while len(self._started) > STARTED_KEPT:
                del self._started[next(iter(self._started))]
        (lat, lon), radius = circle
        try:
            response = self._get(
                API_URL.format(lat=lat, lon=lon, dist=radius), timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
            )
            if response.status_code == 429:
                self._blocked_until = now + RATE_LIMITED
                self._failed(place, TOO_MANY, at_least=RATE_LIMITED)
                return
            response.raise_for_status()
            aircraft = parse(response.json(), now)
        except (requests.exceptions.RequestException, ValueError) as e:
            self._failed(place, f"couldn't reach adsb.fi: {e}")
            return
        with self._lock:
            place.aircraft, place.circle, place.fetched = aircraft, circle, now
            place.backoff, place.error = 0, None

    def _failed(self, place, error, at_least=0):
        if place.error != error:  # once, not every few seconds
            log.warning(f"live traffic: {error}")
        with self._lock:
            place.error = error
            place.backoff = min(MAX_BACKOFF, max(at_least, 2 * self.interval(), 2 * place.backoff))

    def _aircraft(self, places, center, text=False):
        """
        The aircraft shown for places (merged, see merge()), or their JSON: made once per fetch of any of them, not
        once per page that asks. Past MAX_AIRCRAFT the ones kept are the nearest the middle: of the circle for one, so
        every page looking at it gets the same; of the view (center) for several.
        """
        ground = bool(self._settings().traffic_ground)
        one = len(places) == 1
        middle = (places[0].key[0] if places and places[0].key else None) if one or center is None else center
        key = (tuple(p.key for p in places), ground, middle)
        stamp = tuple((p.serial, p.fetched) for p in places)
        with self._lock:
            made = self._shown.pop(key, None)  # put back last: the ones kept are the ones used lately
            if made is None or made[0] != stamp:
                lists = [[a for a in p.aircraft if ground or not a["ground"]] for p in places]
                made = [stamp, merge(lists, middle) if places else [], None]
            self._shown[key] = made
            while len(self._shown) > SHOWN_KEPT:
                del self._shown[next(iter(self._shown))]
            if not text:
                return made[1]
            if made[2] is None:
                made[2] = json.dumps(made[1], separators=COMPACT)
            return made[2]

    def state(self, places, wide=False, center=None, aircraft=True):
        """
        What /api/traffic answers for a view's places ([] for a view too wide, see MAX_VIEW_NM). center: the view's,
        (lat, lon); None for the circle around the airports.
        """
        with self._lock:
            done = [p.fetched for p in places if p.fetched is not None]
            fetched = min(done) if done else None  # the oldest, so the answer doesn't look newer than it is
            # only when every circle fails: one that does in a wide view leaves the rest shown (circles[] says)
            error = places[0].error if places and all(p.error for p in places) else None
            if len(places) == 1:
                circle = places[0].circle
            elif done:  # around every circle of the view
                circle = center, math.ceil(max(distance_nm(center, p.key[0]) + p.key[1] for p in places))
            else:
                circle = None
            circles = [
                {"center": list(p.key[0]), "radius": p.key[1], "fetched": p.fetched, "error": p.error}
                for p in places
                if p.key
            ]
        if places and error is None and self._clock() < self._blocked_until:
            error = TOO_MANY  # adsb.fi said so to another place: nobody asks until it's over
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
            "circles": circles,
            "loading": error is None and any(p.fetched is None and p.error is None for p in places),
        }
        if aircraft:
            state["aircraft"] = self._aircraft(places, center)
        return state
