"""
The Chart Planner page (B90): Config > Plan a new chart. The form posts its choices, the planner runs in a background
thread (the first airport download for a national chart takes minutes) and the page polls for its progress and, at
last, the build sheet. Same shape as an update: a POST starts it and answers 202, a GET answers its progress, only one
runs at a time and a page that is reloaded picks it up again. It only reads: nothing here changes the Chart's settings.
"""

import inspect
import json
import logging
import math
import re
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import bottle

from metarmap.clock import Clock
from metarmap.config import MAX_LEDS
from metarmap.planner import airports as live_airports
from metarmap.planner import layout, projection
from metarmap.web.control import as_json
from metarmap.web.site import render

if TYPE_CHECKING:  # app.py imports the web, so only for the type checker
    from metarmap.app import App

log = logging.getLogger(__name__)

CODE = re.compile(r"^[A-Z0-9]{3,4}$")
SOURCES = ("current", "paste", "recommended")
CORNERS = (None, "tl", "tr", "bl", "br")
SWEEP_STEPS = [0.9 + 0.025 * i for i in range(11)]  # 90% to 115% of the board's width
BEST_SIZES = 3
MAX_BOARD_IN = 400.0  # nobody builds a board over 33 feet; a typo of 3200 would otherwise plan a vast empty board
# limits that keep one plan from running for hours on a Pi Zero: a tiny pitch or string and a big reach make the
# search and the declutter do far more work than any real board needs. On a Mac the worst 1000-pin plan these allow
# (a dense blob that cannot fit) takes about 40 s, a typical one 5 to 10 s; a Pi Zero is 20 to 40 times slower
PITCH_MM = (20.0, 1000.0)
MAX_SPACING_MM = 25.0  # the minimum spacing and the maximum move (the closest two pixels sit about 15 to 20 mm apart)
STRING_LEN = (10, 1000)
PLAN_SECONDS = 900  # a plan still running after this long is stopped, whatever the values, so it cannot run for hours
LOOKUP_SECONDS = 8  # one position lookup request: a cancel is seen within about this long
MAX_PASTED = 10 * MAX_LEDS  # entries in a pasted list, before the duplicates go: bounds the work of reading it
SWEEP_MAX_PINS = 400  # above this the board sizes are not tried: ten more plans of this size take too long on a Pi

NO_JOB = {
    "id": 0,
    "idle": True,
    "fraction": 0.0,
    "label": "",
    "done": True,
    "ok": None,
    "cancelled": False,
    "message": "",
    "error": "",
    "elapsed": 0,
    "params": None,
    "result": None,
}


Cancelled = layout.Cancelled  # raised inside the job when Cancel was pressed, by the page's steps and by the planner


def _shown(value, limit=40):
    """A value from the request for an error message: its repr, cut to `limit` characters."""
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _plural(n, one, many=None):
    return f"{n} {one if n == 1 else many or one + 's'}"


def _accepts_progress(load):
    """Whether the airport loader takes a progress= callback (the fetch reports its tiles and batches to it)."""
    try:
        params = inspect.signature(load).parameters
    except (TypeError, ValueError):
        return False
    return "progress" in params or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def _minutes_ago(when):
    """Whole minutes since an ISO time, or None if it is not one."""
    try:
        then = datetime.fromisoformat(when)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - then).total_seconds() // 60))
    except (TypeError, ValueError):
        return None


class Invalid(ValueError):
    """A value from the form that can't be used; its text is shown to the user."""


class JobClock(Clock):
    """
    The clock the airport fetch runs on. Cancel makes time jump ahead, so the fetch's budget is spent and it stops at
    its next request instead of running on; its waits end at once.
    """

    def __init__(self, cancel: threading.Event):
        self.cancel = cancel

    def time(self):
        return math.inf if self.cancel.is_set() else time.time()

    def wait(self, event, seconds):
        self.cancel.wait(seconds)
        return event.is_set() or self.cancel.is_set()


# The build sheet is made by planner/buildsheet.py. These two are looked up when used, so tests can swap them.
def make_sheet(plan, settings, power, board_in):
    from metarmap.planner import buildsheet

    return buildsheet.build_sheet(plan, settings, power=power, board_in=board_in)


def make_power(brightness, ma_white_5v, ma_white_12v):
    from metarmap.planner import buildsheet

    return buildsheet.PowerSettings(brightness=brightness, ma_white_5v=ma_white_5v, ma_white_12v=ma_white_12v)


# ---- the form's values ------------------------------------------------------------------------------------------


def _number(data, key, default, low, high, label, whole=False, low_open=False):
    value = data.get(key, default)
    if isinstance(value, str) and value.strip():
        try:
            value = float(value)
        except ValueError:
            pass
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Invalid(f"{label} must be a number")
    try:
        finite = math.isfinite(value)
    except OverflowError:  # a JSON integer of 400 digits (10**400) is too big to compare as a float
        finite = False
    if not finite:
        raise Invalid(f"{label} must be a number")
    if whole and value != int(value):
        raise Invalid(f"{label} must be a whole number")
    if value < low or value > high or (low_open and value <= low):
        raise Invalid(f"{label} must be {'above' if low_open else 'at least'} {low:g} and at most {high:g}")
    return int(value) if whole else float(value)


def _flag(data, key, default, label):
    """A switch from the form: true or false (not the text "false", which would be true), or the default if missing."""
    value = data.get(key, default)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise Invalid(f"{label} must be true or false")
    return value


def _codes(value, label):
    """A list of airport codes from a list or from text pasted with commas, spaces or lines between the codes."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        value = re.split(r"[\s,;]+", value.strip())
    if not isinstance(value, list):
        raise Invalid(f"{label} must be a list of airport codes")
    if len(value) > MAX_PASTED:
        raise Invalid(f"{label} has {len(value)} entries; {MAX_PASTED} is the most")
    found = {}  # a dict: a plain list would make the duplicates check slow for a long paste
    for code in value:
        if not isinstance(code, str):
            raise Invalid(f"{label} must be a list of airport codes (text, like KHOU), not {_shown(code)}")
        code = code.strip().upper()
        if not code:
            continue
        if not CODE.match(code):
            raise Invalid(f"{_shown(code)} is not an airport code (3 or 4 letters or digits, like KHOU)")
        found[code] = True
    if len(found) > MAX_LEDS:
        raise Invalid(f"{label} has {len(found)} airports; {MAX_LEDS} is the most")
    return list(found)


def parse(data):
    """The form's JSON as a dict of checked values. Raises Invalid with a sentence for the user."""
    if not isinstance(data, dict):
        raise Invalid("Send the values as a JSON object")
    chart = projection.chart_by_name(data.get("chart") or "")
    if chart is None:
        raise Invalid(f"No chart called {data.get('chart')!r}")
    source = data.get("source", "current")
    if source not in SOURCES:
        raise Invalid(f"source must be one of {', '.join(SOURCES)}")
    corner = data.get("start_corner") or None
    if corner not in CORNERS:
        raise Invalid("start_corner must be one of tl, tr, bl, br or empty")
    target = data.get("target", "strings")
    if target not in ("strings", "max"):
        target = _number({"t": target}, "t", 0, 1, MAX_LEDS, "The number of airports to recommend", whole=True)
    strings = data.get("strings")  # only for target "strings"; empty: the strings the must-keep airports need
    if strings is not None:
        strings = _number({"s": strings}, "s", 0, 1, MAX_LEDS, "The number of strings", whole=True)
    p = {
        "chart": chart.name,
        "source": source,
        "codes": _codes(data.get("codes"), "The list of airports") if source == "paste" else [],
        "must_keep": _codes(data.get("must_keep"), "Must keep"),
        "start_fresh": _flag(data, "start_fresh", False, "start_fresh"),
        "target": target,
        "strings": strings if target == "strings" else None,
        "coverage": _number(data, "coverage", 0.0, 0.0, 1.0, "Even coverage"),
        "width_in": _number(data, "width_in", 32.0, 0.0, MAX_BOARD_IN, "The board's width", low_open=True),
        "height_in": data.get("height_in"),
        "pitch": _number(data, "pitch", 80.0, *PITCH_MM, "The pitch (mm)"),
        "min_gap": _number(data, "min_gap", 18.0, 0.0, MAX_SPACING_MM, "The minimum spacing (mm)"),
        "max_move": _number(data, "max_move", 18.0, 0.0, MAX_SPACING_MM, "The maximum move (mm)"),
        "string_len": _number(data, "string_len", 50, *STRING_LEN, "The string length", whole=True),
        "tolerance": _number(data, "tolerance", 5.0, 0.0, 100.0, "The tolerance (%)"),
        "suggest_sizes": _flag(data, "suggest_sizes", True, "suggest_sizes"),
        "start_corner": corner,
        "brightness": _number(data, "brightness", 0.5, 0.0, 1.0, "The brightness"),
        "ma_white_5v": _number(data, "ma_white_5v", 60.0, 0.0, 1000.0, "The mA per pixel at 5 V", low_open=True),
        "ma_white_12v": _number(data, "ma_white_12v", 25.0, 0.0, 1000.0, "The mA per pixel at 12 V", low_open=True),
        "allow_skips": False,  # needs Chart support (a later change): always planned without skipped pixels
    }
    if data.get("height_in") in (None, ""):
        p["height_in"] = None
    else:
        p["height_in"] = _number(data, "height_in", None, 0.0, MAX_BOARD_IN, "The board's height", low_open=True)
    return p


# ---- the job ----------------------------------------------------------------------------------------------------


class _Limit:
    """What the layout steps ask (is_set) whether to stop: Cancel was pressed, or the plan has run too long."""

    def __init__(self, cancel: threading.Event, seconds: float):
        self._cancel = cancel
        self._end = time.monotonic() + seconds

    def is_set(self):
        return self._cancel.is_set() or time.monotonic() > self._end


def _on_the_earth(sheet, chart, board_w, board_h, found):
    """
    Puts the plan on the earth for a map that draws it over real tiles: each pixel in the sheet gets `lat` and `lon`
    (where it is placed) and `orig_lat` and `orig_lon` (where its airport really is; None for a skipped pixel), and
    the chart's map area comes back as an outline polygon. Returns (outline, bounds): bounds is {south, west, north,
    east} around the outline and every pixel, true and placed, for fitBounds. Everything is to 5 decimals and in the
    chart's own longitude range, so the Western Aleutians chart, which crosses the antimeridian, goes up to 187.65
    and the map draws it without a jump.
    """
    outline = projection.outline(chart, board_w, board_h)
    lats = [lat for lat, _lon in outline]
    lons = [lon for _lat, lon in outline]
    for pixel in sheet["pixels"]:
        lat, lon = projection.unproject(chart, pixel["x"], pixel["y"], board_w, board_h, unwrap=True)
        pixel["lat"], pixel["lon"] = round(lat, 5), round(lon, 5)
        info = found.get(pixel["code"]) if pixel["code"] else None
        if info:
            pixel["orig_lat"] = round(info["lat"], 5)
            pixel["orig_lon"] = round(projection.unwrapped(chart, info["lon"]), 5)
        else:
            pixel["orig_lat"] = pixel["orig_lon"] = None
        for key in (("lat", "lon"), ("orig_lat", "orig_lon")):
            if pixel[key[0]] is not None:
                lats.append(pixel[key[0]])
                lons.append(pixel[key[1]])
    bounds = {"south": min(lats), "west": min(lons), "north": max(lats), "east": max(lons)}
    return outline, bounds


class Planner:
    """The planner job started from the web UI. One runs at a time; the page polls progress()."""

    def __init__(self, services: "App", load=None):
        self.services = services
        self._load = load or live_airports.load
        self._lock = threading.Lock()
        self.job = None
        self._cancel = threading.Event()
        self._started = self._ended = 0.0
        self._count = 0

    def start(self, params):
        """Starts the planner. Returns (job, True), or (the job running now, False) if one already runs."""
        with self._lock:
            if self.job is not None and not self.job["done"]:
                return self.progress(), False
            self._count += 1
            self._cancel = cancel = threading.Event()
            self._started, self._ended = time.monotonic(), None
            job = self.job = {
                **NO_JOB,
                "id": self._count,
                "idle": False,
                "done": False,
                "label": "Starting",
                "params": params,
            }
            threading.Thread(target=self._run, args=(job, params, cancel), name="planner", daemon=True).start()
            return self.progress(), True

    def cancel(self):
        """Asks the running job to stop; it does at its next step (an airport fetch at its next request)."""
        with self._lock:
            if self.job is not None and not self.job["done"]:
                self._cancel.set()
                self.job["label"] = "Cancelling"
            return self.progress()

    def progress(self):
        job = self.job
        if job is None:
            return dict(NO_JOB)
        # dict() copies in one C call, so a worker or the planner thread adding a key (_downloaded, fetched_at,
        # stale) can't land in the middle of it; looping over job.items() here raised "dictionary changed size
        # during iteration", the route answered 500 and the page stopped polling
        snap = dict(job)
        return {
            **{k: v for k, v in snap.items() if not k.startswith("_")},
            "elapsed": int((self._ended or time.monotonic()) - self._started),
        }

    def _run(self, job, params, cancel):
        try:
            job["result"] = self._plan(job, params, cancel)
            job.update(ok=True, message=job["result"]["message"])
        except Cancelled:
            if cancel.is_set():
                job.update(ok=False, cancelled=True, message="Cancelled")
            else:  # nobody pressed Cancel: the plan hit its time limit
                job.update(
                    ok=False,
                    error=(
                        f"The plan was stopped after {PLAN_SECONDS // 60} minutes. Use fewer airports, a smaller "
                        "maximum move or a larger board, and try again."
                    ),
                )
        except Invalid as e:
            job.update(ok=False, error=str(e))
        except ValueError as e:  # the form's values were checked, so this is a bug in the planner: keep the traceback
            log.exception(f"planner refused its own values: {e}")
            job.update(
                ok=False,
                error="The plan failed: the planner could not use these values. The Chart's log has the details.",
            )
        except Exception as e:  # never raise to the browser: say what failed, keep the traceback in the log
            log.exception(f"planner failed: {e}")
            job.update(ok=False, error=f"The plan failed: {e}")
        finally:
            self._ended = time.monotonic()
            job["fraction"] = 1.0
            job["done"] = True

    def _step(self, job, cancel, fraction, label):
        if cancel.is_set():
            raise Cancelled()
        before = job.get("fraction")
        if fraction is not None and isinstance(before, (int, float)):
            fraction = max(fraction, before)  # a bar never goes back
        job["fraction"], job["label"] = fraction, label

    def _later(self, p, x):
        """
        Where the bar is for a step that is `x` (0 to 1) of the way through the work after the airports are found. A
        recommended plan has downloaded first: stations fill 0 to 0.6 of the bar, the details 0.6 to 0.7, and the rest
        (finding positions, planning, the board-size trials) 0.7 to 1.0. The other sources have no download.
        """
        return 0.7 + 0.3 * x if p["source"] == "recommended" else x

    def _reporter(self, job, cancel):
        """
        The callback for airports.load(progress=): progress(phase, done, total). It runs on the fetch's worker
        threads, so it only stores numbers under the lock, and it never raises: a bad value is ignored.
        """

        def progress(phase, done, total):
            try:
                if phase not in ("stations", "details"):
                    return
                if any(isinstance(v, bool) or not isinstance(v, int) for v in (done, total)):
                    return
                if total < 1 or done < 0:
                    return
                done = min(done, total)
                if phase == "stations":
                    fraction = 0.6 * done / total
                    label = f"Downloading stations: tile {done} of {total}"
                else:
                    fraction = 0.6 + 0.1 * done / total
                    label = f"Downloading airport details: batch {done} of {total}"
                with self._lock:
                    if job["done"] or cancel.is_set():
                        return
                    job["fraction"] = max(fraction, job["fraction"] or 0.0)  # the total can grow: never go back
                    job["label"] = label
                    job["_downloaded"] = True
            except Exception:  # noqa: BLE001 - a progress report must never break the fetch
                pass

        return progress

    # -- where the airports are --

    def _current(self):
        """The Chart's own airports with a code: [(code, name, display)], the pixels' ones (not the virtual)."""
        config = self.services.config
        return [(a.code, a.name, a.display) for a in config.airports[: config.data.led.count] if a.code]

    def _position(self, code):
        return self.services.metars.position(code)

    def _locate(self, codes, cancel):
        """
        Positions for codes the Chart doesn't know yet, from the same station lookup it uses. Returns the codes whose
        lookup failed (offline, a 502), which are not the same as codes the lookup does not know.
        """
        metars = self.services.metars
        missing = [c for c in codes if self._position(c) is None and c not in metars.positions]
        failed = set()
        for i in range(0, len(missing), 100):
            if cancel.is_set():
                raise Cancelled()
            batch = missing[i : i + 100]
            if not metars.lookup(batch, timeout=LOOKUP_SECONDS):
                failed.update(batch)
        return failed

    def _name(self, code):
        known = self.services.metars.positions.get(code) or {}
        return known.get("name", "")

    def _gather(self, job, cancel, p, chart):
        """
        The airports to plan, as {code: {"lat", "lon", "name", "rank"}}, in order, with what was left out
        ([{"code", "reason"}]) and notes for the page.
        """
        found, left_out, notes = {}, [], []
        current = self._current()
        names = {code: name for code, name, _display in current}
        stale = False
        if p["source"] == "recommended":
            self._step(job, cancel, None, "Fetching airports from aviationweather.gov")
            clock = JobClock(cancel)
            box = (chart.west, chart.south, chart.east, chart.north)
            reports = _accepts_progress(self._load)
            extra = {"progress": self._reporter(job, cancel)} if reports else {}
            result = self._load(box, clock=clock, **extra)
            if cancel.is_set():
                raise Cancelled()
            if result.error:
                if result.stale:
                    stale = True
                    notes.append(f"The airport list is the cached one from {result.fetched_at}: {result.error}")
                elif result.airports:
                    notes.append(f"{result.error}. The recommended airports may be fewer than the chart has.")
                else:
                    raise Invalid(f"The airports could not be fetched: {result.error}")
            for a in result.airports:
                found[a["code"]] = {
                    "lat": a["lat"],
                    "lon": a["lon"],
                    "name": a.get("name", ""),
                    "rank": float(a.get("rank", 0.0)),
                }
            job["fetched_at"] = result.fetched_at
            job["stale"] = stale
            if reports and not job.get("_downloaded") and result.fetched_at and not result.error:
                # the cache answered, so nothing was downloaded: say so in the result, where it stays on screen (a
                # status label would be replaced by the next step within a moment)
                ago = _minutes_ago(result.fetched_at)
                if ago is not None:
                    notes.append(f"The airports came from the copy saved {_plural(ago, 'minute')} ago.")
            wanted = list(p["must_keep"])  # only these stay: the page ticks the current airports unless Start fresh
        else:
            wanted = p["codes"] if p["source"] == "paste" else [code for code, _n, _d in current]
            for code in p["must_keep"]:
                if code not in wanted:
                    left_out.append({"code": code, "reason": "not one of the airports being planned"})
        self._step(job, cancel, self._later(p, 0.04), "Finding where the airports are")
        failed = self._locate([c for c in wanted if c not in found], cancel)
        for code in wanted:
            if code in found:
                continue
            pos = self._position(code)
            if pos is None:
                reason = "the position lookup failed (offline?)" if code in failed else "no known position"
                left_out.append({"code": code, "reason": reason})
                continue
            found[code] = {"lat": pos[0], "lon": pos[1], "name": names.get(code) or self._name(code), "rank": 0.0}
        for code in list(found):
            info = found[code]
            if not projection.contains(chart, info["lat"], info["lon"]):
                found.pop(code)
                if code in wanted:
                    left_out.append({"code": code, "reason": f"outside the {chart.name} chart"})
        for code, info in found.items():
            if not info["name"]:
                info["name"] = names.get(code) or self._name(code)
        return found, left_out, notes

    # -- the plan --

    def _plan(self, job, p, cancel):
        started = time.monotonic()
        chart = projection.chart_by_name(p["chart"])
        width_mm = p["width_in"] * projection.MM_PER_INCH
        height_mm = p["height_in"] * projection.MM_PER_INCH if p["height_in"] else None
        board_w, board_h = projection.board_size(chart, width_mm, height_mm)

        found, left_out, notes = self._gather(job, cancel, p, chart)
        stop = _Limit(cancel, PLAN_SECONDS)  # from here on: Cancel, or too long a plan
        keep = set(p["must_keep"])
        cap = MAX_LEDS - self.services.config.data.led.virtual_count  # the pixels the Chart can have

        def pins_at(width):
            """The airports' pins on a board `width` mm wide with this board's shape."""
            height = width * board_h / board_w
            pins = []
            for code, info in found.items():
                x, y = projection.project(chart, info["lat"], info["lon"], width, height)
                pins.append(layout.Pin(code, x, y, info["rank"], code in keep))
            return pins

        def settings_at(width):
            return layout.Settings(
                board_w=width,
                board_h=width * board_h / board_w,
                pitch=p["pitch"],
                tolerance=p["tolerance"] / 100,
                min_gap=p["min_gap"],
                max_move=p["max_move"],
                string_len=p["string_len"],
                allow_skips=False,
                start_corner=p["start_corner"],
            )

        settings = settings_at(board_w)
        pins = pins_at(board_w)
        if not pins:
            raise Invalid("There are no airports to plan: none inside the chart with a known position")
        if len([x for x in pins if x.must_keep]) > cap:
            raise Invalid(f"You keep more airports than the Chart can take: {cap} pixels")
        cap_note = f"The Chart takes at most {cap} pixels, so the plan stops at {cap} airports."
        if p["source"] == "recommended":
            self._step(job, stop, self._later(p, 0.5), "Choosing the airports")
            if p["target"] == "max":
                target = cap  # as many as fit, but no more than the Chart can have
            elif p["target"] == "strings":
                kept = len([x for x in pins if x.must_keep])
                needed = max(1, -(-kept // p["string_len"]))  # the strings the must-keep airports fill
                strings = p["strings"] or needed
                if strings < needed:
                    notes.append(
                        f"The {_plural(kept, 'airport')} you keep need{'s' if kept == 1 else ''} "
                        f"{_plural(needed, 'string')} of {p['string_len']}, so the plan uses {needed}, not {strings}."
                    )
                    strings = needed
                target = strings * p["string_len"]
            else:
                target = p["target"]
            if target > cap:
                target = cap
                notes.append(cap_note)
            chosen = layout.recommend(pins, settings, target=target, coverage=p["coverage"], cancel=stop.is_set)
            if not chosen:
                raise Invalid("None of the airports fit on the board at this spacing")
            if p["target"] == "max":
                if len(chosen) >= cap:
                    notes.append(cap_note)
            elif len(chosen) < target:
                notes.append(
                    f"Only {_plural(len(chosen), 'airport')} fit{'s' if len(chosen) == 1 else ''} at this spacing, "
                    f"not {target}. "
                    "A larger board or a smaller minimum spacing would fit more."
                )
            pins = chosen
            found = {x.code: found[x.code] for x in pins}
        elif len(pins) > cap:
            raise Invalid(f"{len(pins)} airports is more than the Chart can take: {cap} pixels")
        self._step(job, stop, self._later(p, 0.6), f"Planning {_plural(len(pins), 'airport')}")
        planned = layout.plan(pins, settings, stop.is_set)
        if cancel.is_set():
            raise Cancelled()
        power = make_power(p["brightness"], p["ma_white_5v"], p["ma_white_12v"])
        sheet = make_sheet(
            planned, settings, power, (p["width_in"], p["height_in"] or board_h / projection.MM_PER_INCH)
        )
        outline, bounds = _on_the_earth(sheet, chart, board_w, board_h, found)

        sizes = None
        if p["suggest_sizes"]:
            if len(pins) > SWEEP_MAX_PINS:
                notes.append(
                    f"Board sizes were not tried: {len(pins)} airports is over {SWEEP_MAX_PINS}, "
                    "and ten more plans of that size would take too long."
                )
            else:
                sizes = self._sizes(
                    job, stop, pins_at, settings_at, board_w, board_h, planned, lambda x: self._later(p, x)
                )
        if cancel.is_set():  # a cancel that came after the last step must not end as a success
            raise Cancelled()

        old = {code: display for code, _name, display in self._current()}
        snippet = [
            {"code": "", "name": "", "display": False}
            if item.code is None
            else {"code": item.code, "name": found[item.code]["name"], "display": old.get(item.code, False)}
            for item in planned.items
        ]
        message = f"Planned {_plural(len(pins), 'airport')} on {_plural(sheet['shopping']['strings'], 'string')}"
        if left_out:
            message += f"; left out {len(left_out)}"
        return {
            "message": message,
            "chart": {
                "name": chart.name,
                "kind": chart.kind,
                "margins": {
                    "left": chart.margin_left,
                    "right": chart.margin_right,
                    "top": chart.margin_top,
                    "bottom": chart.margin_bottom,
                },
                "height_measured": bool(chart.board_aspect or chart.printed_in),
                "outline": outline,
                "bounds": bounds,
            },
            "sheet": sheet,
            "airports": snippet,
            "names": {code: info["name"] for code, info in found.items()},
            "left_out": left_out,
            "notes": notes,
            "stale": bool(job.get("stale")),
            "fetched_at": job.get("fetched_at"),
            "sizes": sizes,
            "recommended": p["source"] == "recommended",
            "skips_allowed": False,
            "seconds": round(time.monotonic() - started, 1),
            "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def _sizes(self, job, cancel, pins_at, settings_at, board_w, board_h, planned, later):
        """
        The best few board widths from 90% to 115% of this one, with the board's shape kept. The board's own width is
        the plan already made, so it is not planned again.
        """
        widths = [board_w * step for step in SWEEP_STEPS if abs(step - 1.0) > 1e-9]
        done = []

        def make_pins(width):
            self._step(
                job,
                cancel,
                later(0.7 + 0.3 * len(done) / len(widths)),
                f"Trying board size {len(done) + 1} of {len(widths)}",
            )
            done.append(width)
            return pins_at(width)

        results = layout.sweep_sizes(make_pins, widths, settings_at, cancel=cancel.is_set)
        here = layout.SizeResult(board_w, planned.extensions, len(planned.crowded), len(planned.drops))
        ranked = sorted(results + [here], key=lambda r: (r.crowded, r.drops, r.extensions, r.width_mm))

        def row(r):
            return {
                "width_in": round(r.width_mm / projection.MM_PER_INCH, 1),
                "height_in": round(r.width_mm * board_h / board_w / projection.MM_PER_INCH, 1),
                "extensions": r.extensions,
                "crowded": r.crowded,
                "drops": r.drops,
            }

        return {"best": [row(r) for r in ranked[:BEST_SIZES]], "current": row(here)}


# ---- the page and its routes ------------------------------------------------------------------------------------


def height_note(chart):
    """What the board height field says for a chart: whether its shape is measured or only an estimate."""
    if chart.printed_in:
        width, height = chart.printed_in
        return (
            f"The {chart.name} chart is {width:g} x {height:g} in at full size, and the board keeps that shape. "
            "Change the height if your board differs."
        )
    if chart.board_aspect:
        size = projection.MEASURED_BOARDS_IN.get(chart.name)
        measured = f" ({size[0]:g} x {size[1]:g} in)" if size else ""
        return f"The shape of the {chart.name} board is measured{measured}. Change the height if your board differs."
    return (
        "The height of this sectional is an estimate from its shape and can be a few percent off: "
        "measure your board and enter its height."
    )


def chart_choices():
    """[{"name", "ratio" (height over width), "measured", "note"}] for the chart list: the sectionals, then the wall."""
    return [
        {
            "name": c.name,
            "kind": c.kind,
            "ratio": projection.board_size(c, 1.0)[1],
            "measured": bool(c.board_aspect or c.printed_in),
            "note": height_note(c),
        }
        for c in projection.charts()
    ]


def default_chart(services, choices):
    """The Chart's own sectional if it has one set; else the sectional covering most of its airports; else Houston."""
    config = services.config
    own = projection.chart_by_name(config.data.geo.map.chart or "")
    if own is not None and own.kind == "sectional":
        return own.name
    positions = [p for p in (services.metars.position(a.code) for a in config.airports if a.code) if p]
    best, best_count = "Houston", 0
    for chart in projection.charts():
        if chart.kind != "sectional":
            continue
        count = sum(1 for lat, lon in positions if projection.contains(chart, lat, lon))
        if count > best_count:
            best, best_count = chart.name, count
    return best


def page(services: "App", site):
    config = services.config
    choices = chart_choices()
    current = [
        {"code": a.code, "name": a.name, "located": services.metars.position(a.code) is not None}
        for a in config.airports[: config.data.led.count]
        if a.code
    ]
    chart = default_chart(services, choices)
    first = next(c for c in choices if c["name"] == chart)
    return render(
        site,
        "planner.tpl",
        charts=choices,
        boards=json.dumps({c["name"]: [c["ratio"], c["note"]] for c in choices}),
        chart=chart,
        height=f"{32 * first['ratio']:.1f}".rstrip("0").rstrip("."),  # on the default 32 in width
        height_note=first["note"],
        current=current,
        brightness=config.data.led.brightness.normal,
        skips_note="Needs Chart support, which comes in a later change. Until then the plan has no hidden pixels.",
    )


def add_routes(app, services: "App", site, auth, planner: Optional[Planner] = None):
    planner = planner or Planner(services)

    def refuse(reason, message, status=400):
        return as_json({"error": message, "reason": reason}, status)

    def start():
        try:
            data = bottle.request.json
        except bottle.HTTPError as e:  # bottle's own refusals: a body that is not JSON (400) or too big (413)
            big = e.status_code == 413
            return refuse("invalid", "The request is too big" if big else "The body is not valid JSON", e.status_code)
        except ValueError:
            data = None
        try:
            params = parse(data)
        except Invalid as e:
            return refuse("invalid", str(e))
        cap = MAX_LEDS - services.config.data.led.virtual_count  # the pixels the Chart can have
        if len(params["must_keep"]) > cap:  # the planner always keeps these, so they alone would be over the cap
            return refuse(
                "invalid",
                f"You keep {len(params['must_keep'])} airports, but the Chart can take only {cap} pixels. "
                "Untick some in Must keep.",
            )
        job, started = planner.start(params)
        if not started:
            return as_json({**job, "error": "A plan is already running", "reason": "running"}, 409)
        return as_json(job, 202)

    app.route("/config/planner", "GET", lambda: page(services, site), apply=auth)
    app.route("/config/planner/plan", "POST", start, apply=auth)
    app.route("/config/planner/progress", "GET", lambda: as_json(planner.progress()), apply=auth)
    app.route("/config/planner/cancel", "POST", lambda: as_json(planner.cancel()), apply=auth)
