"""
TFRs (temporary flight restrictions) for the TFR visualizer: which airports are inside or near one, now or soon.

From the FAA's tfr.faa.gov: its list of TFRs (number, type, place), then each TFR's detail (XML) for its areas: each
area's outline, floor and ceiling, and when it's in effect. TFRs rarely change, so a detail is fetched once, when a
TFR first appears in the list (an amended TFR gets a new number). The list is fetched with the METARs (every 10
minutes), in the background, so the first start's few dozen details don't hold up the LEDs.

Only areas with a floor below MAX_FLOOR_FT count. TFRs without an outline (some long-running security areas) can't
be placed, so they're left out.

The details are XML because tfr.faa.gov has no JSON with them: its JSON list has no altitudes or times (only dates in
the description's words), its GeoJSON outlines (geoserver V_TFR_LOC) have neither and can't be matched to a TFR's
areas, and getWebText is an HTML table in JSON. JSON is preferred everywhere else (checked 2026-11-01).
"""
import math
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from metarmap import __version__
from metarmap.advisories import inside
from metarmap.lib.safe_logging import safe_log

LIST_URL = "https://tfr.faa.gov/tfrapi/exportTfrList"
DETAIL_URL = "https://tfr.faa.gov/download/detail_{}.xml"  # 6/4084 -> detail_6_4084.xml
PAGE_URL = "https://tfr.faa.gov/tfr3/?page=detail_{}"  # the FAA's page for one TFR
USER_AGENT = f"metarmap/{__version__} (+https://github.com/dman776/metarmap2)"
TIMEOUT = 30  # seconds
DETAIL_SPACING = 0.5  # seconds between detail downloads, to be gentle with tfr.faa.gov
MAX_FLOOR_FT = 18000
SOON_SECONDS = 24 * 3600  # a TFR starting within this counts as upcoming
FOREVER = float("inf")

# type (as the FAA's list names it) -> what it's called; in order of how much it matters, which picks the color when
# an airport has several
TYPES = {
    "VIP": "VIP",
    "HAZARDS": "Hazards",
    "SECURITY": "Security",
    "SPECIAL": "Special",
    "AIR SHOWS/SPORTS": "Air show or sports",
    "UAS PUBLIC GATHERING": "UAS public gathering",
}


def utc(text):
    """Epoch seconds for "2026-11-06T17:30:00" (UTC), or None."""
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except (AttributeError, ValueError):
        return None


def degrees(text):
    """42.98154645N or 090.68611111W as signed degrees, or None."""
    try:
        text = text.strip()
        value = float(text[:-1])
    except (AttributeError, ValueError, IndexError):
        return None
    return -value if text[-1] in "SW" else value


def feet(value, uom):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value * 100 if (uom or "").upper() == "FL" else value


def find(element, path):
    found = element.find(path)
    return found.text if found is not None and found.text is not None else None


def parse_detail(xml_text):
    """
    The areas of one TFR's detail XML: [{"name", "floor", "floor_ref", "ceiling", "ceiling_ref", "from", "until",
    "coords"}], altitudes in feet ("AGL" or "MSL"), times in epoch seconds (None: no start given, i.e. in effect;
    FOREVER: no end given). Areas without an outline are left out. Raises ValueError for text that isn't XML.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"not XML: {e}") from None
    areas = []
    for group in root.iter("TFRAreaGroup"):
        area = group.find("aseTFRArea")
        merged = group.find("abdMergedArea")
        if area is None or merged is None:
            continue
        coords = []
        for avx in merged.iter("Avx"):
            lat, lon = degrees(find(avx, "geoLat")), degrees(find(avx, "geoLong"))
            if lat is not None and lon is not None:
                coords.append((lat, lon))
        if len(coords) < 3:
            continue
        starts = [utc(e.text) for e in area.iter("dateEffective") if e.text]
        ends = [utc(e.text) for e in area.iter("dateExpire") if e.text]
        starts, ends = [s for s in starts if s is not None], [e for e in ends if e is not None]
        areas.append({
            "name": find(area, "txtName"),
            "floor": feet(find(area, "valDistVerLower"), find(area, "uomDistVerLower")) or 0,
            "floor_ref": "AGL" if find(area, "codeDistVerLower") == "HEI" else "MSL",
            "ceiling": feet(find(area, "valDistVerUpper"), find(area, "uomDistVerUpper")),
            "ceiling_ref": "AGL" if find(area, "codeDistVerUpper") == "HEI" else "MSL",
            "from": min(starts) if starts else None,
            "until": max(ends) if ends else FOREVER,
            "coords": coords,
        })
    return areas


def distance_nm(lat, lon, polygon):
    """
    How far (lat, lon) is from the polygon's edge in nautical miles; 0 inside. Flat-earth around the point, which is
    plenty for the few tens of miles that matter here.
    """
    if inside(lat, lon, polygon):
        return 0.0
    scale = math.cos(math.radians(lat))
    points = [((plon - lon) * 60 * scale, (plat - lat) * 60) for plat, plon in polygon]
    best = FOREVER
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        dx, dy = x2 - x1, y2 - y1
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(x1 + t * dx, y1 + t * dy))
    return best


class Tfrs:
    """
    nearby: returns the TFR nearby distance in NM now (a setting, so a change applies at once).
    get: requests.get, or a test's own. clock: epoch seconds. sleep: time.sleep.
    """

    def __init__(self, nearby=lambda: 10, get=None, clock=time.time, sleep=time.sleep):
        self._nearby = nearby
        self._get = get or requests.get
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._fetching = threading.Lock()
        self._tfrs = None  # notam id -> {"notam", "type", "description", "areas"}; None until the first list
        self._details = {}  # notam id -> its areas (parsed details are kept: TFRs don't change, they're replaced)
        self.fetched = None
        self.error = None

    # ---- fetching ---------------------------------------------------------------------------------------------

    def fetch(self):
        """
        Fetches the list, and the details of TFRs not seen before. Returns True if the list came; a detail that
        fails is tried again next time. Never raises.
        """
        if not self._fetching.acquire(blocking=False):
            return False  # already under way
        try:
            return self._fetch()
        finally:
            self._fetching.release()

    def fetch_soon(self, then=None):
        """fetch() in the background; then() afterwards (e.g. to show the new TFRs on the LEDs) if it worked."""
        def run():
            if self.fetch() and then is not None:
                then()
        threading.Thread(target=run, name="tfr-fetch", daemon=True).start()

    def _fetch(self):
        try:
            listed = self._json(LIST_URL)
            if not isinstance(listed, list):
                raise ValueError("the TFR list isn't a list")
        except (requests.exceptions.RequestException, ValueError) as e:
            self._failed(f"couldn't get the TFR list: {e}")
            return False
        tfrs, failed = {}, 0
        for item in listed:
            notam = item.get("notam_id") if isinstance(item, dict) else None
            if not notam or item.get("type") not in TYPES:
                continue
            if notam not in self._details:
                if failed < 3:  # tfr.faa.gov is having trouble: leave the rest for next time
                    try:
                        self._sleep(DETAIL_SPACING)
                        self._details[notam] = parse_detail(self._text(DETAIL_URL.format(notam.replace("/", "_"))))
                    except (requests.exceptions.RequestException, ValueError) as e:
                        safe_log(f"TFR {notam}: couldn't get its detail: {e}")
                        failed += 1
                if notam not in self._details:
                    continue
            tfrs[notam] = {"notam": notam, "type": item["type"], "description": item.get("description") or "",
                           "areas": self._details[notam]}
        self._details = {n: self._details[n] for n in tfrs}  # forget the TFRs that are gone
        with self._lock:
            self._tfrs, self.fetched, self.error = tfrs, self._clock(), None
        return True

    def _response(self, url):
        response = self._get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response

    def _json(self, url):
        return self._response(url).json()

    def _text(self, url):
        return self._response(url).text

    def _failed(self, error):
        if self.error is None:  # once, not every 10 minutes
            safe_log(error)
        self.error = error

    # ---- what's where -----------------------------------------------------------------------------------------

    def areas(self):
        """
        Every area in effect now or starting within SOON_SECONDS, floor below MAX_FLOOR_FT, as {"notam", "type",
        "description", "upcoming", ...the area}; None before the first list.
        """
        with self._lock:
            tfrs = self._tfrs
        if tfrs is None:
            return None
        now = self._clock()
        found = []
        for tfr in tfrs.values():
            for area in tfr["areas"]:
                starts = area["from"] if area["from"] is not None else now
                if area["until"] <= now or starts > now + SOON_SECONDS or area["floor"] >= MAX_FLOOR_FT:
                    continue
                found.append({"notam": tfr["notam"], "type": tfr["type"], "description": tfr["description"],
                              "upcoming": starts > now, **area})
        return found

    def nearby_nm(self):
        try:
            return max(0.0, float(self._nearby()))
        except (TypeError, ValueError):
            return 0.0

    def at(self, lat, lon):
        """
        The TFRs at a place, most important first (in effect before upcoming, inside before nearby, then by type):
        [{"type", "upcoming", "inside"}], one per type and state; None before the first list. "inside" False: within
        the nearby distance.
        """
        areas = self.areas()
        if areas is None:
            return None
        reach = self.nearby_nm()
        found = {}
        for area in areas:
            distance = distance_nm(lat, lon, area["coords"])
            if distance > reach:
                continue
            key = (area["type"], area["upcoming"])
            found[key] = found.get(key, False) or distance == 0
        order = list(TYPES)
        return sorted(({"type": t, "upcoming": upcoming, "inside": found[(t, upcoming)]} for t, upcoming in found),
                      key=lambda f: (f["upcoming"], not f["inside"], order.index(f["type"])))

    def state(self):
        """For /api/tfrs: the areas (for the Map page), and when the list was fetched."""
        return {"fetched": self.fetched, "error": self.error, "nearby_nm": self.nearby_nm(),
                "areas": [{**a, "until": None if a["until"] == FOREVER else a["until"],
                           "url": PAGE_URL.format(a["notam"].replace("/", "_"))} for a in self.areas() or []]}
