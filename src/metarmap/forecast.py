"""
TAFs (terminal aerodrome forecasts) for the forecast visualizers: what each airport's weather is forecast to be a few
hours from now.

One request to aviationweather.gov gets the latest TAF of every airport that issues one (only about 700 US stations do;
the rest are left out of the answer). A TAF is a base forecast followed by groups that change it:

  FM      from a time on, everything changes
  BECMG   the named elements change gradually, and have changed at the end of the group
  TEMPO   the named elements are temporarily like this (under half the time, an hour or two at a time)
  PROB    the same, with a 30 or 40% chance

A group only names what changes (BECMG, TEMPO, PROB), so the rest carries over. TAFs are issued about every 6 hours
(plus amendments), so they are fetched once in a while and kept: the forecast for each step is worked out from them
when the map's data is refreshed.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

from metarmap import USER_AGENT
from metarmap.decode import CATEGORIES, category_from
from metarmap.metar import parse_visibility
from metarmap.models import SkyLayer

log = logging.getLogger(__name__)

TAF_URL = "https://aviationweather.gov/api/data/taf?format=json&ids="
TIMEOUT = 30  # seconds
# TAFs change every 6 hours or so, so asking more often than this only costs aviationweather.gov requests
MIN_AGE = 30 * 60  # seconds
HOURS = (3, 6, 12)  # how far ahead the forecast visualizers look (the map's own "now" is the METAR)
TEMPORARY = ("TEMPO", "PROB")


@dataclass(frozen=True)
class Group:
    """One group of a TAF. vis is None and layers is () when the group doesn't name them."""

    start: int  # epoch seconds: when it applies from (a BECMG's: when the change is complete)
    end: int
    kind: Optional[str] = None  # None for the base forecast, else FM, BECMG, TEMPO or PROB
    vis: Optional[float] = None  # statute miles
    layers: Tuple[SkyLayer, ...] = ()
    vert_vis_ft: Optional[int] = None
    wx: Optional[str] = None  # weather codes ("-RA BR"); "" for NSW (none); None when the group doesn't name any


@dataclass
class Taf:
    issued: int = 0
    valid_to: int = 0
    groups: List[Group] = field(default_factory=list)


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_group(f) -> Optional[Group]:
    """One entry of a TAF's "fcsts", or None if it has no usable times."""
    start = _number(f.get("timeFrom"))
    end = _number(f.get("timeTo"))
    if start is None or end is None:
        return None
    kind = f.get("fcstChange") or None
    if kind == "BECMG" and _number(f.get("timeBec")) is not None:
        start = f["timeBec"]
    layers = []
    for c in f.get("clouds") or []:
        if isinstance(c, dict) and c.get("cover"):
            layers.append(SkyLayer(c["cover"], int(_number(c.get("base")) or 0)))
    try:
        vis = parse_visibility(f.get("visib"))
    except (ValueError, ZeroDivisionError):
        vis = None
    vert = _number(f.get("vertVis"))
    wx = f.get("wxString")
    wx = None if not isinstance(wx, str) or not wx.strip() else ("" if wx.strip() == "NSW" else wx.strip())
    return Group(int(start), int(end), kind, vis, tuple(layers), int(vert) if vert is not None else None, wx)


def parse_tafs(data) -> Dict[str, Taf]:
    """The latest TAF of each station in aviationweather.gov's answer, as {station: Taf}."""
    tafs: Dict[str, Taf] = {}
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict) or not entry.get("icaoId"):
            continue
        issued = int(_number(entry.get("validTimeFrom")) or 0)
        known = tafs.get(entry["icaoId"])
        if known is not None and known.issued >= issued:
            continue
        groups = [g for g in (parse_group(f) for f in entry.get("fcsts") or [] if isinstance(f, dict)) if g]
        if groups:
            tafs[entry["icaoId"]] = Taf(issued, int(_number(entry.get("validTimeTo")) or 0), groups)
    return tafs


def _worse(a, b):
    """The worse of two flight categories; either may be None."""
    if a is None or b is None:
        return a or b
    return max(a, b, key=CATEGORIES.index)


def _in_taf(taf: Taf, when: float) -> bool:
    return not (when < min(g.start for g in taf.groups) or (taf.valid_to and when >= taf.valid_to))


def _prevailing(taf: Taf, when: float):
    """
    What the base forecast and its FM and BECMG groups say at `when`, as (visibility, sky layers, vertical visibility,
    weather): a BECMG group changes only what it names, an FM group (or the base forecast) says everything, so a
    weather it leaves out is no weather.
    """
    vis, layers, vert, wx = None, (), None, ""
    for g in sorted((g for g in taf.groups if g.kind not in TEMPORARY), key=lambda g: g.start):
        if g.start > when:
            break
        if g.kind in (None, "FM"):  # everything changes
            vis, layers, vert, wx = g.vis, g.layers, g.vert_vis_ft, g.wx or ""
            continue
        vis = g.vis if g.vis is not None else vis
        layers = g.layers or layers
        vert = g.vert_vis_ft if g.vert_vis_ft is not None else vert
        wx = g.wx if g.wx is not None else wx
    return vis, layers, vert, wx


def category_at(taf: Taf, when: float, include_temporary: bool = True) -> Optional[str]:
    """
    The flight category the TAF forecasts at `when` (epoch seconds), or None when it doesn't cover that time or names
    neither a visibility nor a sky. With include_temporary, a TEMPO or PROB group in effect then counts when it is
    worse (the worst category in effect); without, only the base forecast, FM and BECMG groups do.
    """
    if not _in_taf(taf, when):
        return None
    vis, layers, vert, _ = _prevailing(taf, when)
    best = category_from(vis, layers, vert)
    if include_temporary:
        for g in taf.groups:
            if g.kind in TEMPORARY and g.start <= when < g.end:
                best = _worse(best, category_from(g.vis if g.vis is not None else vis, g.layers or layers, vert))
    return best


def weather_at(taf: Taf, when: float, include_temporary: bool = True) -> Optional[Tuple[str, ...]]:
    """
    The weather the TAF forecasts at `when`: the weather codes of the forecast in effect ("-RA BR") and, with
    include_temporary, of each TEMPO or PROB group in effect, leaving out the groups with none and repeats. An empty
    tuple is a dry forecast; None, a time the TAF doesn't cover.
    """
    if not _in_taf(taf, when):
        return None
    found = [_prevailing(taf, when)[3]]
    if include_temporary:
        found += [g.wx for g in taf.groups if g.kind in TEMPORARY and g.start <= when < g.end and g.wx]
    return tuple(dict.fromkeys(wx for wx in found if wx))  # each once


class Forecasts:
    """
    The TAFs of the map's airports. get: requests.get, or a test's own. clock: epoch seconds.
    """

    def __init__(self, get=None, clock=time.time):
        self._get = get or requests.get
        self._clock = clock
        self._lock = threading.Lock()
        self._fetching = threading.Lock()
        self._tafs: Dict[str, Taf] = {}
        self._codes: Tuple[str, ...] = ()
        self.fetched: Optional[float] = None
        self.error: Optional[str] = None

    def fetch(self, codes, force=False) -> bool:
        """
        Fetches the TAFs of `codes`, unless they were fetched less than MIN_AGE ago (and these are the same airports,
        or force). Returns True if there are new TAFs; on an error the old ones are kept (they stay valid until their
        own end).
        """
        codes = tuple(dict.fromkeys(c for c in codes if c))
        if not codes or not self._fetching.acquire(blocking=False):
            return False
        try:
            fresh = self.fetched is not None and self._clock() - self.fetched < MIN_AGE
            if fresh and codes == self._codes and not force:
                return False
            try:
                response = self._get(TAF_URL + ",".join(codes), timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
                if response.status_code == 204:  # none of them issues a TAF
                    tafs = {}
                else:
                    response.raise_for_status()
                    tafs = parse_tafs(response.json())
            except (requests.exceptions.RequestException, ValueError) as e:
                if self.error is None:  # once, not at every attempt
                    log.warning(f"TAF fetch failed: {e}")
                self.error = f"couldn't reach aviationweather.gov: {e}"
                return False
            with self._lock:
                self._tafs, self._codes, self.fetched, self.error = tafs, codes, self._clock(), None
            log.info(f"TAFs for {len(tafs)} of {len(codes)} airports")
            return True
        finally:
            self._fetching.release()

    def fetch_soon(self, codes, then=None, force=False):
        """fetch() in the background; then() afterwards (e.g. to show the new forecast on the LEDs) if it worked."""

        def run():
            if self.fetch(codes, force=force) and then is not None:
                then()

        threading.Thread(target=run, name="taf-fetch", daemon=True).start()

    def forecast(self, code, include_temporary=True) -> Optional[Tuple[Optional[str], ...]]:
        """
        The flight category forecast for the airport HOURS ahead (None for an hour its TAF doesn't reach), or None
        when it has no TAF.
        """
        with self._lock:
            taf = self._tafs.get(code)
        if taf is None:
            return None
        now = self._clock()
        return tuple(category_at(taf, now + hours * 3600, include_temporary) for hours in HOURS)

    def weather(self, code, include_temporary=True) -> Optional[Tuple[Optional[Tuple[str, ...]], ...]]:
        """
        The weather forecast for the airport HOURS ahead (weather_at(); None for an hour its TAF doesn't reach), or
        None when it has no TAF.
        """
        with self._lock:
            taf = self._tafs.get(code)
        if taf is None:
            return None
        now = self._clock()
        return tuple(weather_at(taf, now + hours * 3600, include_temporary) for hours in HOURS)
