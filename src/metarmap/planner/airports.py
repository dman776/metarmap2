"""
Live airport data for the Chart Planner (B90), from aviationweather.gov: the stations with a current METAR in a
box (candidates), what each is (details: tower, passengers, runways) and how important it is (rank). load() does
all three and keeps the answer in a cache file for a day, so a planner run offline can still use the last one.

The requests of one fetch go out WORKERS at a time, through one gate that keeps their combined rate under the API's
limit: a continental US fetch is about 280 requests of 1 to 3 seconds each (a 504 holds one for 20 to 30), so one at a
time it took twelve minutes, and a few at a time it takes a few. Every fetch function takes an optional `progress`
callable, called from the worker threads after each request finishes (so it must be thread safe and cheap: calls
are serialized, but not on one thread); an exception in it is logged and the fetch goes on.
"""

import json
import logging
import math
import os
import queue
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
# so a request goes out at least REQUEST_SPACING seconds after the one before it, whichever worker sends it (100 a
# minute is every 0.6 s; this is 92). A 429 (rate limited) pushes the next request back by the API's Retry-After
# (at least RETRY_SECONDS, at most MAX_RETRY_AFTER) and makes the gap 1.5 times longer for the rest of the fetch, up
# to MAX_SPACING.
REQUEST_SPACING = 0.65
MAX_SPACING = 5.0  # seconds
MAX_RETRY_AFTER = 30  # seconds
# Requests in flight at once. The gate above keeps the rate the same, so more workers only hide the wait for a slow
# answer: with 1 a slow 504 stops the whole fetch, with 3 the other two go on. 1 sends them one after the other.
WORKERS = 3
MAX_WORKERS = 8
JOIN_SECONDS = 10  # how long to wait for a worker thread to end after its work is done
# What one load() may spend fetching: the continental US is about 280 requests, a few minutes with WORKERS at a
# time on a real connection, a state or a sectional a few dozen. A request in flight when the time is up still
# finishes.
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


def candidates(west, south, east, north, timeout=30, clock=None, budget=None, progress=None, workers=None):
    """
    The stations with a current METAR inside the box, as Fetched([Station, ...], failed requests): the airports
    only (K, P and T ids), once each. A box bigger than TILE_DEGREES is fetched in tiles, `workers` (WORKERS) at a
    time through the budget's gate, which keeps them under the API's rate limit; a box across the antimeridian
    (east above 180, the Western Aleutians) is fetched as two, each with longitudes the API takes (-180 to 180);
    once the budget (the time limit, the failures in a row) is spent the tiles left count as failed. The answer
    does not depend on which tile finished first. progress(done, total) is called when the tiles are known and after
    each one finishes: total is the tiles known so far, and grows by four when a dense tile is fetched again as
    four. Never raises; when it returns its threads are over.
    """
    clock = clock or Clock()
    budget = budget or _Budget(clock)
    tiles = [
        (s, w, min(s + TILE_DEGREES, north), min(w + TILE_DEGREES, e))
        for w0, e in _longitudes(west, east)
        for s, w in _grid(south, w0, north, e)
    ]
    tally = _Tally(len(tiles), progress)
    results = {}  # tile -> its stations, merged in tile order below

    def fetch(tile, push):
        s, w, n, e = tile
        failed = False
        try:
            reports = _get(METAR_URL, {"format": "json", "bbox": _bbox_text(s, w, n, e)}, timeout, clock, budget)
            if reports is None:
                failed = True
            elif len(reports) >= SPLIT_AT and (n - s) / 2 >= MIN_TILE and (e - w) / 2 >= MIN_TILE:
                ms, mw = (s + n) / 2, (w + e) / 2
                children = [(s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)]
                tally.add(len(children))  # counted before they can finish
                for child in children:
                    push(child)
            else:
                results[tile] = [station for station in map(_station, reports) if station]
        except Exception:
            log.exception(f"Could not read the stations of tile {tile}")
            failed = True
        tally.finish(failed)

    _run(tiles, fetch, _workers(workers))
    found = {}
    for tile in sorted(results):
        for station in results[tile]:
            found.setdefault(station.code, station)
    return Fetched(sorted(found.values()), tally.failed)


def details(codes, timeout=30, clock=None, budget=None, progress=None, workers=None):
    """
    What the FAA has on each airport, as Fetched({code: {"tower", "passengers", "rwyNum", "rwyLength"}}, failed
    requests): tower is True or False, passengers (thousands a year) and rwyNum are ints, rwyLength is the longest
    runway in feet (0 if unknown). A code the API doesn't know isn't in the dict. Paced, limited and run like
    candidates() (the same `budget` can be shared); progress(done, total) is called per batch of BATCH codes. Never
    raises.
    """
    clock = clock or Clock()
    budget = budget or _Budget(clock)
    codes = list(dict.fromkeys(codes))
    batches = [codes[i : i + BATCH] for i in range(0, len(codes), BATCH)]
    tally = _Tally(len(batches), progress)
    results = {}  # batch number -> its details, merged in order below

    def fetch(index, push):
        failed = False
        try:
            answer = _get(AIRPORT_URL, {"format": "json", "ids": ",".join(batches[index])}, timeout, clock, budget)
            if answer is None:
                failed = True
            else:
                results[index] = {
                    airport["icaoId"]: _detail(airport)
                    for airport in answer
                    if isinstance(airport, dict) and airport.get("icaoId")
                }
        except Exception:
            log.exception(f"Could not read the airport details of batch {index}")
            failed = True
        tally.finish(failed)

    _run(list(reversed(range(len(batches)))), fetch, _workers(workers))  # the last item goes first: batch 0 first
    found = {}
    for index in sorted(results):
        found.update(results[index])
    return Fetched(found, tally.failed)


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


def load(
    box, cache_path=CACHE_FILE, max_age=MAX_AGE, clock=None, timeout=30, deadline=DEADLINE, progress=None, workers=None
):
    """
    The airports with a current METAR in the box (west, south, east, north), best first, as Result(airports, stale,
    fetched_at, error). Each is {"code", "name", "lat", "lon", "tower", "passengers", "rwyNum", "rwyLength", "rank"}.

    A cache newer than `max_age` is used as it is. Otherwise the box is fetched (for at most `deadline` seconds,
    `workers` requests at a time) and cached. If that fails, or misses some requests, an older whole cache is used
    (stale is True, error says why): a whole answer from before beats a short one from now. With no cache a short
    answer is returned with its error and not cached; with nothing at all the airports are empty and error says why.
    progress(phase, done, total) is called while it fetches, phase "stations" (the METAR tiles) and then "details"
    (the airport batches), with the counts of candidates()/details(); it is not called for a cache that is used as
    it is. Never raises.
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

    def phase(name):
        return (lambda done, total: progress(name, done, total)) if progress else None

    budget = _Budget(clock, deadline)
    stations, failed = candidates(
        *box, timeout=timeout, clock=clock, budget=budget, progress=phase("stations"), workers=workers
    )
    extra = {}
    if stations:
        extra, failed_details = details(
            [s.code for s in stations],
            timeout=timeout,
            clock=clock,
            budget=budget,
            progress=phase("details"),
            workers=workers,
        )
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
    What one fetch may spend, shared by its worker threads. It is the gate the requests go out through, under the
    API's rate limit, and it says when to give up: after `deadline` seconds, or FAILURES_IN_A_ROW failed requests in
    a row (the reason is kept for the error message).
    """

    def __init__(self, clock, deadline=DEADLINE):
        self.clock = clock
        self.deadline = deadline
        self.until = clock.time() + deadline
        self.spacing = REQUEST_SPACING  # seconds between two requests going out; longer after a 429
        self.next = None  # the earliest time the next request may go out
        self.hold_until = float("-inf")  # when the last 429's hold ends: no request goes out before it
        self.streak = 0  # failed requests in a row
        self.reason = ""  # why it gave up, once it has
        self._lock = threading.Lock()  # streak and reason
        self._gate = threading.Lock()  # next and spacing
        self._never = threading.Event()  # the gate waits on it; nothing sets it (a clock may end a wait early itself)

    def over(self):
        with self._lock:
            if not self.reason and self.clock.time() >= self.until:
                self.reason = f"gave up after {self.deadline:g} seconds"
            return bool(self.reason)

    def _reserve(self, not_before=None):
        """Takes the next turn under the gate, `not_before` at the earliest, and returns when it is."""
        with self._gate:
            now = self.clock.time()
            turn = now if self.next is None else max(now, self.next)
            if not_before is not None:
                turn = max(turn, not_before)
            self.next = turn + self.spacing
            return turn

    def start(self):
        """
        Waits for this request's turn, then says whether it may go out (False: the budget is spent, by now or while
        it waited). The turn is taken before the wait, under the lock, so workers queue up behind each other at
        `spacing` apart and none waits while holding the lock. A 429 that comes in while a request waits holds it
        back too: it takes a new turn after the hold, so the ones that were queued don't go out together.
        """
        if self.over():
            return False
        turn = self._reserve()
        while True:
            wait = turn - self.clock.time()
            if wait > 0:
                self.clock.wait(self._never, wait)
            if self.over():
                return False
            with self._gate:
                hold = self.hold_until
                held = hold > self.clock.time()
            if not held:
                return True
            turn = self._reserve(hold)

    def rate_limited(self, seconds, sent=None):
        """
        The API answered 429 to a request that went out at `sent` (now, if not given): no request goes out for
        `seconds`, and they go out further apart from now on. The gap grows once per hold: the answers to requests
        that went out before the hold ended (the other workers' requests of the same burst) only extend it.
        """
        with self._gate:
            now = self.clock.time()
            if (now if sent is None else sent) >= self.hold_until:  # sent after the last hold: a new burst
                self.spacing = min(self.spacing * 1.5, MAX_SPACING)
            self.hold_until = max(self.hold_until, now + seconds)
            self.next = max(self.next if self.next is not None else now, self.hold_until)

    def done(self, ok):
        """Notes that a request got its answer (or, with ok False, never did)."""
        with self._lock:
            self.streak = 0 if ok else self.streak + 1
            if self.streak >= FAILURES_IN_A_ROW and not self.reason:
                self.reason = f"gave up after {FAILURES_IN_A_ROW} failed requests in a row"


class _Tally:
    """How far a fetch has got: requests finished and known, and failed. Shared by the worker threads."""

    def __init__(self, total, progress):
        self.total = total
        self.done = 0
        self.failed = 0
        self.progress = progress
        self._lock = threading.Lock()
        self._report()

    def add(self, count):
        """`count` more requests are known."""
        with self._lock:
            self.total += count

    def finish(self, failed=False):
        """One request is over (failed: it never got an answer)."""
        with self._lock:
            self.done += 1
            self.failed += bool(failed)
            self._report()

    def _report(self):
        if self.progress:
            try:
                self.progress(self.done, self.total)
            except Exception:
                log.exception("The progress callback failed")


_STOP = object()


def _workers(workers):
    """How many threads to use: `workers`, else WORKERS, from 1 to MAX_WORKERS."""
    try:
        count = int(WORKERS if workers is None else workers)
    except (TypeError, ValueError):
        count = WORKERS
    return max(1, min(count, MAX_WORKERS))


def _run(items, handler, workers):
    """
    Calls handler(item, push) for each item and each item a handler pushes, `workers` at a time, and returns when
    all are done and the threads are over. The last item goes first, as when a loop pops a list, so with one worker
    (which runs on the calling thread) the order is the plain one. A handler is meant to catch its own errors; one
    that raises is logged and its item skipped.
    """
    if workers <= 1:
        pending = list(items)
        while pending:
            try:
                handler(pending.pop(), pending.append)
            except Exception:
                log.exception("An airport request failed")
        return
    work = queue.LifoQueue()
    for item in items:
        work.put(item)

    def work_through():
        while True:
            item = work.get()
            try:
                if item is _STOP:
                    return
                handler(item, work.put)  # what it pushes is counted before this item is marked done
            except Exception:
                log.exception("An airport request failed")
            finally:
                work.task_done()

    threads = []
    for number in range(workers):
        thread = threading.Thread(target=work_through, name=f"airports-fetch-{number + 1}", daemon=True)
        try:
            thread.start()
        except RuntimeError as e:  # no more threads to be had: go on with the ones there are
            log.warning(f"Could not start fetch thread {number + 1}: {e}")
            break
        threads.append(thread)
    if not threads:
        while True:
            try:
                item = work.get_nowait()
            except queue.Empty:
                return
            try:
                handler(item, work.put)
            except Exception:
                log.exception("An airport request failed")
            finally:
                work.task_done()
    work.join()
    for _ in threads:
        work.put(_STOP)
    for thread in threads:
        thread.join(JOIN_SECONDS)


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
    could not be had: after ATTEMPTS tries, or because the budget is spent. Every try goes out through the budget's
    gate; a 429 holds the whole fetch back (see _Budget.rate_limited), not just this request.
    """
    for attempt in range(ATTEMPTS):
        if not budget.start():
            return None
        sent = clock.time()
        try:
            response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            if response.status_code == 429:
                budget.rate_limited(_retry_after(response), sent)
                raise requests.exceptions.HTTPError("HTTP 429, rate limited")
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


def _retry_after(response):
    """Seconds to wait after a 429: its Retry-After (in seconds), at least RETRY_SECONDS, at most MAX_RETRY_AFTER."""
    headers = getattr(response, "headers", None) or {}
    try:
        seconds = float(str(headers.get("Retry-After", "")).strip())
    except ValueError:  # missing, or a date
        seconds = 0.0
    if not math.isfinite(seconds):
        seconds = 0.0
    return min(max(seconds, RETRY_SECONDS), MAX_RETRY_AFTER)


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
