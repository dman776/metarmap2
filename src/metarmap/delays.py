"""
FAA airport status for the FAA Delays visualizer: which airports are closed, under a ground stop or delayed, from the
FAA's NAS Status (nasstatus.faa.gov), fetched in the background every DELAYS_MINUTES (and with the METARs).

The feed is XML only: it answers application/xml even when JSON is asked for (checked 2026-11-14), so this is
parsed with xml.etree. It's about 2 KB:

    <AIRPORT_STATUS_INFORMATION>
      <Update_Time>Sat Nov 14 18:13:50 2026 GMT</Update_Time>
      <Delay_type>
        <Name>Airport Closures</Name>
        <Airport_Closure_List>
          <Airport><ARPT>LAX</ARPT><Reason>!LAX 05/277 ... 2605271826-2705281600</Reason>
                   <Start>May 27 at 18:26 UTC.</Start><Reopen>May 28 at 16:00 UTC.</Reopen></Airport>
        ...

Airports are named by their FAA id (LAX, HNL, SJU), not the ICAO code the Chart uses (KLAX, PHNL, TJSJ):
metar.Reports.faa_id maps them.

Only full closures count: a closure whose NOTAM says TO NON SKED, EXC or PPR is a partial restriction (LAX, SAN and
LAS have had long-running ones closing them to transient general aviation only) and is left out. A closure is in
effect between the dates of its NOTAM's range (YYMMDDhhmm-YYMMDDhhmm at the end of the Reason); without one, between
Start and Reopen, whose year is inferred from Update_Time.

Ground Delay Programs, Ground Stops and General Arrival/Departure Delay Info follow the FAA's documented format (the
older fly.faa.gov ASWS one); none were in the feed when this was written, so those are UNVERIFIED against a live feed.
A delay type not recognized is ignored, and logged once.
"""

import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from metarmap import USER_AGENT, http

log = logging.getLogger(__name__)

STATUS_URL = "https://nasstatus.faa.gov/api/airport-status-information"
TIMEOUT = 30  # seconds
DELAYS_MINUTES = 5  # how often the status is fetched: ground stops come and go within the METAR's 10 minutes

# an airport's status, worst first (Delays.status)
CLOSED, GROUND_STOP, DELAY, NORMAL = "closed", "ground_stop", "delay", "normal"
RANK = {CLOSED: 3, GROUND_STOP: 2, DELAY: 1, NORMAL: 0}

# words in a closure's NOTAM that make it partial: closed only to some (TO NON SKED TRANSIENT GA ACFT), or with
# exceptions (EXC), or by prior permission (PPR)
PARTIAL = ("TO NON SKED", "EXC", "PPR")
AIRPORT_ID = re.compile(r"[A-Z0-9]{3,4}")  # an FAA location id: SAN, 52F, or an ICAO code
NOTAM_RANGE = re.compile(r"(\d{10})(?:EST)?-(\d{10}|PERM)(?:EST)?")  # 2605271826-2705281600, ...-PERM, ...EST
WHEN = re.compile(r"([A-Za-z]{3})\s+(\d{1,2})\s+at\s+(\d{1,2}):(\d{2})")  # "May 27 at 18:26 UTC."
MONTHS = {m: n for n, m in enumerate(("jan feb mar apr may jun jul aug sep oct nov dec").split(), start=1)}
FOREVER = float("inf")


def text(element, tag):
    """The stripped text of element's first `tag` (searched at any depth), or "" if there's none."""
    found = element.find(tag)
    if found is None:
        found = element.find(f".//{tag}")
    return (found.text or "").strip() if found is not None else ""


def minutes(words):
    """
    "2 hours and 18 minutes" -> 138, "45 minutes" -> 45, "1 hour" -> 60; None when there's no number of hours or
    minutes in it.
    """
    hours = re.search(r"(\d+)\s*h(?:ou)?r", words or "", re.IGNORECASE)
    mins = re.search(r"(\d+)\s*min", words or "", re.IGNORECASE)
    if not hours and not mins:
        return None
    return (int(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)


def notam_time(digits):
    """YYMMDDhhmm (UTC) as epoch seconds; None if it isn't a date."""
    try:
        return datetime.strptime(digits, "%y%m%d%H%M").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def notam_range(reason):
    """
    The (from, until) of the last YYMMDDhhmm-YYMMDDhhmm range in a NOTAM's text, in epoch seconds (until is FOREVER for
    PERM); None if it has none.
    """
    found = NOTAM_RANGE.findall(reason or "")
    if not found:
        return None
    start, end = found[-1]
    start = notam_time(start)
    end = FOREVER if end == "PERM" else notam_time(end)
    if start is None or end is None:
        return None
    return start, end


def update_time(words):
    """Update_Time ("Sat Nov 14 18:13:50 2026 GMT") as epoch seconds, or None."""
    try:
        return datetime.strptime(words.strip(), "%a %b %d %H:%M:%S %Y GMT").replace(tzinfo=timezone.utc).timestamp()
    except (AttributeError, ValueError):
        return None


def day_time(words, near, after=None):
    """
    "May 27 at 18:26 UTC." as epoch seconds, in the year that puts it nearest `near` (epoch seconds), or for `after`
    the first one at or after it. None if it isn't such a date.
    """
    found = WHEN.search(words or "")
    if not found or near is None:
        return None
    month = MONTHS.get(found.group(1).lower())
    if month is None:
        return None
    year = datetime.fromtimestamp(near, timezone.utc).year
    candidates = []
    for y in (year - 1, year, year + 1):
        try:
            candidates.append(
                datetime(y, month, int(found.group(2)), int(found.group(3)), int(found.group(4)), tzinfo=timezone.utc)
            )
        except ValueError:  # Feb 29 in a year without one, or no such time
            continue
    stamps = [c.timestamp() for c in candidates]
    if after is not None:
        later = [s for s in stamps if s >= after]
        return min(later) if later else None
    return min(stamps, key=lambda s: abs(s - near)) if stamps else None


def is_partial(reason):
    upper = (reason or "").upper()
    return any(words in upper for words in PARTIAL)


def kind_of(name):
    """What a Delay_type's Name means: CLOSED, GROUND_STOP, DELAY, "flow" (not by airport), or None (unknown)."""
    name = (name or "").lower()
    if "closure" in name:
        return CLOSED
    if "ground stop" in name:
        return GROUND_STOP
    if "ground delay" in name or "arrival" in name or "departure" in name:
        return DELAY
    if "airspace flow" in name:
        return "flow"
    return None


def _airports(delay_type):
    """The elements under a Delay_type that are about one airport: each has an ARPT, whatever the element is called."""
    return [e for e in delay_type.iter() if e is not delay_type and e.find("ARPT") is not None]


def _delay_minutes(element):
    """
    A delay's minutes: a Ground Delay Program's Avg; for an arrival or departure delay, the middle of its Min and Max
    (the worst of its arrival and departure); None if the feed gives none that can be read.
    """
    avg = minutes(text(element, "Avg"))
    if avg is not None:
        return avg
    worst = None
    for part in list(element.iter("Arrival_Departure")) or [element]:
        low, high = minutes(text(part, "Min")), minutes(text(part, "Max"))
        known = [m for m in (low, high) if m is not None]
        if known:
            middle = round(sum(known) / len(known))
            worst = middle if worst is None else max(worst, middle)
    return worst


def parse(xml_text, unknown=None):
    """
    The feed's airports, {faa id: [{"kind", "minutes", "from", "until"}]}, and its Update_Time (epoch seconds, or None):
    ({...}, updated). "from" and "until" (epoch seconds; None and FOREVER when not given) are only set for closures.
    "reason" is the feed's own text for it (a closure's NOTAM, a ground stop's "thunderstorms"), "" if it has none.
    Partial closures and ids that aren't airport ids are left out. unknown: a set that gets the names of the delay types
    it doesn't know. Raises ValueError for text that isn't the feed's XML.
    """
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, TypeError) as e:
        raise ValueError(f"not XML: {e}") from None
    if root.tag != "AIRPORT_STATUS_INFORMATION":
        raise ValueError(f"not the airport status: <{root.tag}>")
    updated = update_time(text(root, "Update_Time"))
    airports = {}
    for delay_type in root.iter("Delay_type"):
        name = text(delay_type, "Name")
        kind = kind_of(name)
        if kind is None:
            if unknown is not None:
                unknown.add(name)
            continue
        if kind == "flow":  # an airspace flow program is about a piece of airspace, not an airport
            continue
        for element in _airports(delay_type):
            code = text(element, "ARPT").upper()
            if not AIRPORT_ID.fullmatch(code):
                log.debug(f"FAA status: {code!r} isn't an airport id; left out")
                continue
            reason = text(element, "Reason")
            entry = {"kind": kind, "minutes": None, "from": None, "until": FOREVER, "reason": reason}
            if kind == CLOSED:
                if is_partial(reason):
                    continue
                dates = notam_range(reason)
                if dates is None:
                    start = day_time(text(element, "Start"), updated)
                    end = day_time(text(element, "Reopen"), updated, after=start) if start is not None else None
                    dates = (start, FOREVER if end is None else end)
                entry["from"], entry["until"] = dates
            elif kind == DELAY:
                entry["minutes"] = _delay_minutes(element)
            airports.setdefault(code, []).append(entry)
    return airports, updated


def worst(entries, now):
    """
    The worst of an airport's entries in effect at `now`: {"kind", "minutes", "reason", "until"} ("until": epoch
    seconds, FOREVER if not known, None for what isn't a closure); {"kind": NORMAL, "minutes": None} if none are.
    """
    best = {"kind": NORMAL, "minutes": None}
    for entry in entries or ():
        if entry["kind"] == CLOSED:
            starts = entry["from"] if entry["from"] is not None else now
            if not starts <= now < entry["until"]:
                continue
        candidate = {
            "kind": entry["kind"],
            "minutes": entry["minutes"],
            "reason": entry.get("reason", ""),
            "until": entry["until"] if entry["kind"] == CLOSED else None,
        }
        if (RANK[candidate["kind"]], candidate["minutes"] or 0) > (RANK[best["kind"]], best["minutes"] or 0):
            best = candidate
    return best


def describe(status):
    """
    What an airport's status says in a sentence ("Closed by the FAA until 14 Nov 22:30Z", "FAA ground stop", "FAA delay
    of about 2 h 18 min"); "" for no status or a normal one.
    """
    kind = (status or {}).get("kind")
    if kind == CLOSED:
        until = status.get("until")
        if until is None or until == FOREVER:
            return "Closed by the FAA"
        return "Closed by the FAA until " + datetime.fromtimestamp(until, timezone.utc).strftime("%d %b %H:%MZ")
    if kind == GROUND_STOP:
        return "FAA ground stop"
    if kind == DELAY:
        mins = status.get("minutes")
        if mins is None:
            return "FAA delay"
        return f"FAA delay of about {mins // 60} h {mins % 60} min" if mins >= 60 else f"FAA delay of about {mins} min"
    return ""


class Delays:
    """
    get: http.get, or a test's own. clock: epoch seconds.
    """

    def __init__(self, get=None, clock=time.time):
        self._get = get or http.get
        self._clock = clock
        self._lock = threading.Lock()
        self._fetching = threading.Lock()
        self._airports = None  # faa id -> its entries (parse); None until the first fetch that worked
        self._shown = {}  # faa id -> its status (worst) at the last fetch, to tell whether the LEDs need redrawing
        self._unknown = set()  # the delay types already logged as unknown
        self.updated = None  # the feed's Update_Time
        self.fetched = None
        self.error = None

    def fetch(self):
        """
        Fetches the status. Returns True if it came and what's in effect now differs from the last fetch's (so the
        LEDs need redrawing); the first status that comes always does. A failed fetch keeps the last status. Never
        raises.
        """
        if not self._fetching.acquire(blocking=False):
            return False  # already under way
        try:
            return self._fetch()
        finally:
            self._fetching.release()

    def fetch_soon(self, then=None):
        """fetch() in the background; then() afterwards (e.g. to show the new status on the LEDs) if it changed."""

        def run():
            if self.fetch() and then is not None:
                then()

        threading.Thread(target=run, name="delays-fetch", daemon=True).start()

    def _fetch(self):
        unknown = set()
        try:
            response = self._get(STATUS_URL, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            airports, updated = parse(response.text, unknown)
        except (requests.exceptions.RequestException, ValueError) as e:
            self._failed(f"couldn't get the FAA airport status: {e}")
            return False
        for name in sorted(unknown - self._unknown):
            log.warning(f"FAA status: delay type {name!r} isn't one this knows; ignored")
        self._unknown |= unknown
        now = self._clock()
        shown = {code: worst(entries, now) for code, entries in airports.items()}
        with self._lock:
            # what the LEDs show now, not the feed's text: a closure that starts between fetches is a change too
            changed = self._airports is None or shown != self._shown
            self._airports, self._shown, self.updated, self.fetched, self.error = airports, shown, updated, now, None
        return changed

    def _failed(self, error):
        if self.error is None:  # once, not every few minutes
            log.warning(error)
        self.error = error

    def status(self, faa_id):
        """
        An airport's worst status in effect now, {"kind", "minutes"} (kind CLOSED, GROUND_STOP, DELAY with its
        minutes, or NORMAL); None before the first fetch that worked.
        """
        with self._lock:
            airports = self._airports
        if airports is None:
            return None
        return worst(airports.get((faa_id or "").upper()), self._clock())
