"""
Live airport data for the Chart Planner (B90), from aviationweather.gov: the stations with a current METAR in a
box (candidates), what each is (details: tower, passengers, runways) and how important it is (rank). load() does
all three and keeps the answer in a cache file for a day, so a planner run offline can still use the last one.
"""

import json
import logging
import math
import os
import re
import tempfile
import threading
from collections import namedtuple
from datetime import datetime, timedelta

import requests

from metarmap import USER_AGENT
from metarmap.clock import Clock

log = logging.getLogger(__name__)

METAR_URL = "https://aviationweather.gov/api/data/metar"
AIRPORT_URL = "https://aviationweather.gov/api/data/airport"

# A bigger box gets fewer stations back (on 2026-11-13: a 10 degree box 68, its four 5 degree boxes 110, sixteen
# 1.25 degree boxes about 115), so a box is fetched as tiles. At 2.5 degrees the count is within about 2% of 1.25.
# A tile that answers with SPLIT_AT stations or more is dense (a big city) and is fetched again as four smaller
# ones, down to MIN_TILE.
TILE_DEGREES = 2.5
MIN_TILE = 1.25
SPLIT_AT = 30
BATCH = 100  # airport codes in one request; the API took 400 (2858 characters of URL), so this is far below its limit
ATTEMPTS = 2  # tries for one request: the API answers 504 now and then
RETRY_SECONDS = 2
MAX_AGE = timedelta(days=1)
CLOCK_SLACK = timedelta(minutes=5)  # a cache written this far ahead of the clock is from the future, not fresh
CACHE_FILE = os.path.join("planner-cache", "airports.json")  # next to config.json and metarmap.log: the working folder

# aviationweather.gov: "All requests are rate limited to 100 requests per minute" (https://aviationweather.gov/data/api/),
# so a request goes out at least REQUEST_SPACING seconds after the one before it (100 a minute is every 0.6 s)
REQUEST_SPACING = 0.65
# What one load() may spend fetching: the continental US is about 280 requests, roughly ten minutes on a real
# connection, a state or a sectional a few dozen. A request in flight when the time is up still finishes.
DEADLINE = 900  # seconds
FAILURES_IN_A_ROW = 5  # failed requests (each already tried ATTEMPTS times) in a row after which a fetch gives up

# an airport's id: K (the 48 states), P (Alaska, Hawaii, Pacific), T (Caribbean). Buoys and weather sites have
# other ids (five digits or letters); FAA ids with digits (K11R) are airports.
AIRPORT_ID = re.compile(r"^[KPT][A-Z0-9]{3}$")

# passengers are in thousands a year (KIAH 40970, KHOU 13110)
CLASS_B_PASSENGERS = 5000
CLASS_C_PASSENGERS = 300
# rank() caps what it adds to a tier's 100 points so that a bad value can't lift an airport into the next tier:
# at most 60 + 30 + 1 points
MOST_PASSENGERS = 10**6
LONGEST_RUNWAY = 30000
MOST_RUNWAYS = 10

Station = namedtuple("Station", "code name lat lon")
Fetched = namedtuple("Fetched", "items failed")  # what a fetch got, and how many of its requests could not be made
Result = namedtuple("Result", "airports stale fetched_at error")


def candidates(west, south, east, north, timeout=30, clock=None, budget=None):
    """
    The stations with a current METAR inside the box, as Fetched([Station, ...], failed requests): the airports
    only (K, P and T ids), once each. A box bigger than TILE_DEGREES is fetched in tiles, paced under the API's rate
    limit; a box across the antimeridian (east above 180, the Western Aleutians) is fetched as two, each with
    longitudes the API takes (-180 to 180); once the budget (the time limit, the failures in a row) is spent the
    tiles left count as failed. Never raises.
    """
    clock = clock or Clock()
    budget = budget or _Budget(clock)
    found = {}
    failed = 0
    pending = [
        (s, w, min(s + TILE_DEGREES, north), min(w + TILE_DEGREES, e))
        for w0, e in _longitudes(west, east)
        for s, w in _grid(south, w0, north, e)
    ]
    while pending:
        s, w, n, e = pending.pop()
        reports = _get(METAR_URL, {"format": "json", "bbox": _bbox_text(s, w, n, e)}, timeout, clock, budget)
        if reports is None:
            failed += 1
            continue
        if len(reports) >= SPLIT_AT and (n - s) / 2 >= MIN_TILE and (e - w) / 2 >= MIN_TILE:
            ms, mw = (s + n) / 2, (w + e) / 2
            pending += [(s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)]
            continue
        for report in reports:
            station = _station(report)
            if station:
                found.setdefault(station.code, station)
    return Fetched(sorted(found.values()), failed)


def details(codes, timeout=30, clock=None, budget=None):
    """
    What the FAA has on each airport, as Fetched({code: {"tower", "passengers", "rwyNum", "rwyLength"}}, failed
    requests): tower is True or False, passengers (thousands a year) and rwyNum are ints, rwyLength is the longest
    runway in feet (0 if unknown). A code the API doesn't know isn't in the dict. Paced and limited like
    candidates() (the same `budget` can be shared). Never raises.
    """
    clock = clock or Clock()
    budget = budget or _Budget(clock)
    codes = list(dict.fromkeys(codes))
    found = {}
    failed = 0
    for i in range(0, len(codes), BATCH):
        answer = _get(AIRPORT_URL, {"format": "json", "ids": ",".join(codes[i : i + BATCH])}, timeout, clock, budget)
        if answer is None:
            failed += 1
            continue
        for airport in answer:
            code = airport.get("icaoId") if isinstance(airport, dict) else None
            if code:
                found[code] = _detail(airport)
    return Fetched(found, failed)


def rank(detail):
    """
    How important an airport is for a pixel on the map, higher first; `detail` is one of details()' dicts (an empty
    one ranks lowest). A tier decides, and the rest only orders airports within it:

        tier 4  towered, 5,000 thousand passengers a year or more (a Class B airport, in effect)
        tier 3  towered, 300 thousand or more, or three runways or more (Class C)
        tier 2  any other tower
        tier 1  no tower, but passengers or two runways
        tier 0  the rest
        rank = tier * 100 + 10 * log10(1 + passengers) + longest runway in thousands of feet + runways / 10

    The three parts after the tier are capped (a million passengers, 30,000 ft, 10 runways) to add up to less than
    100, so a higher tier always wins.
    """
    tower = bool(detail.get("tower"))
    passengers = min(max(_number(detail.get("passengers")), 0), MOST_PASSENGERS)
    runways = min(max(_number(detail.get("rwyNum")), 0), MOST_RUNWAYS)
    longest = min(max(_number(detail.get("rwyLength")), 0), LONGEST_RUNWAY)
    if tower and passengers >= CLASS_B_PASSENGERS:
        tier = 4
    elif tower and (passengers >= CLASS_C_PASSENGERS or runways >= 3):
        tier = 3
    elif tower:
        tier = 2
    elif passengers > 0 or runways >= 2:
        tier = 1
    else:
        tier = 0
    return tier * 100 + 10 * math.log10(1 + passengers) + longest / 1000 + runways / 10


def load(box, cache_path=CACHE_FILE, max_age=MAX_AGE, clock=None, timeout=30, deadline=DEADLINE):
    """
    The airports with a current METAR in the box (west, south, east, north), best first, as Result(airports, stale,
    fetched_at, error). Each is {"code", "name", "lat", "lon", "tower", "passengers", "rwyNum", "rwyLength", "rank"}.

    A cache newer than `max_age` is used as it is. Otherwise the box is fetched (for at most `deadline` seconds) and
    cached. If that fails, or misses some requests, an older whole cache is used (stale is True, error says why):
    a whole answer from before beats a short one from now. With no cache a short answer is returned with its error
    and not cached; with nothing at all the airports are empty and error says why. Never raises.
    """
    clock = clock or Clock()
    if not (
        isinstance(box, (tuple, list))
        and len(box) == 4
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in box)
    ):
        return Result([], False, None, "the area is not four numbers (west, south, east, north)")
    box = tuple(float(x) for x in box)
    key = _key(box)
    entry = _entry(_read_cache(cache_path), key, clock.now())
    if entry and _age(entry, clock) <= max_age:
        return Result(entry["airports"], False, entry["fetched_at"], None)

    budget = _Budget(clock, deadline)
    stations, failed = candidates(*box, timeout=timeout, clock=clock, budget=budget)
    extra = {}
    if stations:
        extra, failed_details = details([s.code for s in stations], timeout=timeout, clock=clock, budget=budget)
        failed += failed_details
    now = clock.now().isoformat()
    if stations and not failed:
        airports = _combine(stations, extra)
        _store(cache_path, key, {"fetched_at": now, "airports": airports})
        return Result(airports, False, now, None)
    if not stations and not failed:
        return Result([], False, now, "aviationweather.gov has no airport with a METAR in this area")
    error = _why(stations, failed, budget)
    if entry:
        log.warning(f"Airports for {key}: {error}; using the cache from {entry['fetched_at']}")
        return Result(
            entry["airports"], True, entry["fetched_at"], f"{error}; using the cache from {entry['fetched_at']}"
        )
    if stations:
        return Result(_combine(stations, extra), False, now, error)
    return Result([], False, None, error)


class _Budget:
    """
    What one fetch may spend. It paces the requests under the API's rate limit and says when to give up: after
    `deadline` seconds, or FAILURES_IN_A_ROW failed requests in a row (the reason is kept for the error message).
    """

    def __init__(self, clock, deadline=DEADLINE):
        self.clock = clock
        self.deadline = deadline
        self.until = clock.time() + deadline
        self.last = None  # when the last request went out
        self.streak = 0  # failed requests in a row
        self.reason = ""  # why it gave up, once it has

    def over(self):
        if not self.reason and self.clock.time() >= self.until:
            self.reason = f"gave up after {self.deadline:g} seconds"
        return bool(self.reason)

    def start(self):
        """Waits until the next request may go out."""
        if self.last is not None:
            wait = self.last + REQUEST_SPACING - self.clock.time()
            if wait > 0:
                self.clock.wait(threading.Event(), wait)
        self.last = self.clock.time()

    def done(self, ok):
        """Notes that a request got its answer (or, with ok False, never did)."""
        self.streak = 0 if ok else self.streak + 1
        if self.streak >= FAILURES_IN_A_ROW and not self.reason:
            self.reason = f"gave up after {FAILURES_IN_A_ROW} failed requests in a row"


def _why(stations, failed, budget):
    if stations:
        error = f"{failed} requests to aviationweather.gov failed, so the list may be short"
    else:
        error = "aviationweather.gov did not answer"
    return f"{error} ({budget.reason})" if budget.reason else error


def _longitudes(west, east):
    """
    The (west, east) ranges to ask the API for: one, or two for a box across the antimeridian, whose longitudes run
    past 180 (the Western Aleutian Islands chart is 168.17 to 187.65): up to 180, and from -180 to the rest.
    """
    if west < -180:
        return [(west + 360, 180.0), (-180.0, east)] if east > -180 else [(west + 360, east + 360)]
    if east > 180:
        return [(west, 180.0), (-180.0, east - 360)] if west < 180 else [(west - 360, east - 360)]
    return [(west, east)]


def _coordinate(value):
    """
    A latitude or longitude as the API takes it: four decimals, no trailing zeros. Stepping a tile edge in floats
    leaves noise (31.52 + 2.5 is 34.019999999999996) and the API answers a 400 to that.
    """
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _bbox_text(south, west, north, east):
    """The bbox parameter, south,west,north,east."""
    return ",".join(_coordinate(value) for value in (south, west, north, east))


def _grid(south, west, north, east):
    """The southwest corners of the TILE_DEGREES tiles that cover the box."""
    if north <= south or east <= west:
        return []
    rows = math.ceil((north - south) / TILE_DEGREES - 1e-9)
    columns = math.ceil((east - west) / TILE_DEGREES - 1e-9)
    return [
        (south + row * TILE_DEGREES, west + column * TILE_DEGREES) for row in range(rows) for column in range(columns)
    ]


def _get(url, params, timeout, clock, budget):
    """
    The JSON list the API answers with ([] for its 204: a valid request with nothing to report), or None if it
    could not be had: after ATTEMPTS tries, or because the budget is spent.
    """
    for attempt in range(ATTEMPTS):
        if budget.over():
            return None
        budget.start()
        try:
            response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            response.raise_for_status()
            answer = [] if response.status_code == 204 else response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            log.warning(f"{url} {params}: {e}")
            if attempt + 1 < ATTEMPTS:
                clock.wait(threading.Event(), RETRY_SECONDS)
            continue
        budget.done(True)
        return answer if isinstance(answer, list) else []
    budget.done(False)
    return None


def _station(report):
    """A Station from one METAR report, or None for a weather site that isn't an airport or one with no position."""
    try:
        code = str(report["icaoId"]).upper()
        lat, lon = float(report["lat"]), float(report["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (AIRPORT_ID.match(code) and -90 <= lat <= 90 and -180 <= lon <= 180):  # not NaN or infinity either
        return None
    name = str(report.get("name") or "").split(",")[0].strip()  # "Walnut Ridge Rgnl, AR, US"
    return Station(code, name, lat, lon)


def _detail(airport):
    """The fields the planner uses from one entry of the airport API's list."""
    listed = airport.get("runways")
    runways = [r for r in listed if isinstance(r, dict)] if isinstance(listed, list) else []
    longest = 0
    for runway in runways:
        try:
            longest = max(longest, int(str(runway.get("dimension")).split("x")[0]))
        except ValueError:
            pass
    return {
        "tower": bool(str(airport.get("tower") or "").strip()),
        "passengers": _number(airport.get("passengers")),
        "rwyNum": _number(airport.get("rwyNum")) or len(runways),
        "rwyLength": longest,
    }


def _number(value):
    """An int from an API value that may be a string, a float, empty or nonsense; 0 if it isn't a finite number."""
    try:
        number = float(str(value).strip())
    except ValueError:
        return 0
    return int(number) if math.isfinite(number) else 0


def _combine(stations, extra):
    """The airports for the planner, best first: each station with its details and rank."""
    airports = []
    for station in stations:
        detail = extra.get(station.code) or {"tower": False, "passengers": 0, "rwyNum": 0, "rwyLength": 0}
        airports.append(
            {
                "code": station.code,
                "name": station.name,
                "lat": station.lat,
                "lon": station.lon,
                **detail,
                "rank": round(rank(detail), 3),
            }
        )
    airports.sort(key=lambda a: (-a["rank"], a["code"]))
    return airports


def _key(box):
    return ",".join(f"{float(x):g}" for x in box)


def _age(entry, clock):
    try:
        return clock.now() - datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, TypeError, ValueError):
        return timedelta.max


def _entry(cache, key, now):
    """
    The cache's entry for a box if it is one this module could have written ({"fetched_at": an ISO time with a time
    zone that is not in the future (`now` is the time it is, give or take CLOCK_SLACK), "airports": [dict with a
    code, lat and lon, ...] and not empty), else None: anything else is treated as no entry.
    """
    entry = cache.get(key)
    if not (isinstance(entry, dict) and isinstance(entry.get("fetched_at"), str)):
        return None
    airports = entry.get("airports")
    if not isinstance(airports, list) or not airports or not all(_airport_ok(a) for a in airports):
        return None
    try:
        fetched = datetime.fromisoformat(entry["fetched_at"])
        if fetched.tzinfo is None or fetched - now > CLOCK_SLACK:
            return None
    except (TypeError, ValueError):
        return None
    return entry


def _airport_ok(airport):
    """Whether a cached airport has what a caller needs of it: a code and a finite lat and lon."""
    if not (isinstance(airport, dict) and isinstance(airport.get("code"), str) and airport["code"]):
        return False
    return all(
        isinstance(airport.get(k), (int, float)) and not isinstance(airport.get(k), bool) and math.isfinite(airport[k])
        for k in ("lat", "lon")
    )


def _read_cache(path):
    """The cache file's {box key: {"fetched_at", "airports"}}; {} if there is none or it isn't readable."""
    try:
        with open(path) as f:
            cache = json.load(f)
    except (OSError, ValueError):
        return {}
    return cache if isinstance(cache, dict) else {}


_cache_lock = threading.Lock()


def _store(path, key, entry):
    """
    Saves one box's entry. The file is read again under the lock, so another box's entry saved meanwhile (by a
    request on another thread) isn't lost, and the new file is written whole next to it and moved into place, so a
    reader never sees half of one. A failure is logged, not raised.
    """
    with _cache_lock:
        cache = _read_cache(path)
        cache[key] = entry
        temporary = None
        try:
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=folder or ".", prefix=".airports-", suffix=".tmp")
            with os.fdopen(handle, "w") as f:
                json.dump(cache, f)
            os.chmod(temporary, 0o644)  # mkstemp makes it private
            os.replace(temporary, path)
            temporary = None
        except OSError as e:
            log.warning(f"Could not save the airport cache {path}: {e}")
        finally:
            if temporary:
                try:
                    os.remove(temporary)
                except OSError:
                    pass
