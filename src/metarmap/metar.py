"""
Module to handle METAR fetching and processing
"""

import json
import logging
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from typing import Dict, Optional

import requests

from metarmap import USER_AGENT
from metarmap.clock import Clock
from metarmap.models import Report, SkyLayer

log = logging.getLogger(__name__)

# without `hours`, the API returns each station's latest report. (With hours=5 it returned up to ~13 reports per
# station and stopped at 400, so a long airport list could lose the newest ones.)
API_URL = "https://aviationweather.gov/api/data/metar?format=json&ids="
# where airports are and their names (the METARs don't place airports that aren't reporting); JSON
STATION_URL = "https://aviationweather.gov/api/data/stationinfo?format=json&ids="
# a station whose latest report is older than this counts as not reporting (the API returns it however old it is)
MAX_REPORT_AGE = timedelta(hours=5)
ALTIMETER = re.compile(r"\bA(\d{4})\b")  # "A3023": 30.23 inHg, in a US report's body
HPA_PER_INHG = 33.8639


def parse_visibility(value):
    """Statute miles from the report: "10+", "6.0", "0.25", "1/2" or "1 1/2" (None if not reported)."""
    text = str(value or "").replace("+", "").strip()
    if not text:
        return None
    return float(sum(Fraction(part) for part in text.split()))


def airport_codes(airports):
    """The airports to fetch: each code once, in LED order, skipping LEDs with no airport."""
    return list(dict.fromkeys(a.code for a in airports if a.code))


# ---- parsing (no state: the Reports class below fetches and keeps the results) ------------------------------------


def latest_reports(content):
    """
    The newest report for each station in a JSON response, as {station: report}. Newest by its time rather than
    its position in the response. An empty response (no reports) is {}.
    """
    text = content.decode() if isinstance(content, bytes) else (content or "")
    reports = json.loads(text) if text.strip() else []
    by_station = {}
    for m in reports if isinstance(reports, list) else []:
        if isinstance(m, dict) and m.get("icaoId"):
            current = by_station.get(m["icaoId"])
            if current is None or (m.get("obsTime") or 0) > (current.get("obsTime") or 0):
                by_station[m["icaoId"]] = m
    return by_station


def process(content, codes, now):
    """
    The METARs for `codes` from a JSON response, as (data, reporting, missing): data is {code: parse_report()},
    or None for an airport with no report, a report older than MAX_REPORT_AGE before `now`, or one that can't be read.
    """
    by_station = latest_reports(content)
    data: Dict[str, Optional[Report]] = {}
    reporting, missing = [], []
    oldest_allowed = now - MAX_REPORT_AGE
    for airport in codes:
        metar = by_station.get(airport)
        if metar is None:
            data[airport] = None
            missing.append(airport)
            continue
        try:
            parsed = parse_report(metar)
            if parsed.obs_time is not None and parsed.obs_time < oldest_allowed:
                log.info(
                    f"{airport}: latest report is from {parsed.obs_time:%Y-%m-%d %H:%MZ}; treating it as not reporting"
                )
                data[airport] = None
                missing.append(airport)
                continue
            data[airport] = parsed
            reporting.append(airport)
        except Exception as e:
            # one malformed report only affects its own airport
            log.exception(f"Could not parse METAR for {airport}: {e} raw: {metar.get('raw_text')}")
            data[airport] = None
            missing.append(airport)
    return data, reporting, missing


def parse_report(metar) -> Report:
    """
    Converts one METAR from the JSON response into the Report used everywhere else.
    """

    def num(key, default=None):
        value = metar.get(key)
        if value in (None, ""):
            return default
        return float(str(value).replace("+", ""))

    raw_metar = (metar.get("rawOb") or "").strip()  # the JSON can end it with a space
    temp_c = num("temp")
    dewpoint_c = num("dewp")
    obs_time = metar.get("obsTime")

    clouds = [sc for sc in metar.get("clouds") or [] if isinstance(sc, dict)]
    sky_conditions = tuple(SkyLayer(sc.get("cover", ""), int(sc.get("base") or 0)) for sc in clouds)
    if not sky_conditions and metar.get("cover"):  # a clear sky has no layers, only "cover": "CLR"
        sky_conditions = (SkyLayer(metar["cover"]),)

    wind_dir = metar.get("wdir")
    return Report(
        raw=raw_metar,
        name=metar.get("name") or "",  # e.g. "Houston/Hobby Arpt, TX, US"
        elevation_m=int(round(num("elev", 0))),
        flight_category=metar.get("fltCat"),
        wind_dir="" if wind_dir is None else str(wind_dir),  # degrees, or "VRB"
        wind_speed=int(num("wspd")) if num("wspd") is not None else None,
        wind_gust_speed=int(num("wgst", 0)),
        visibility_sm=parse_visibility(metar.get("visib")),
        visibility_more="+" in str(metar.get("visib") or ""),  # "10+": more than 10 miles
        vert_vis_ft=int(num("vertVis")) * 100 if num("vertVis") is not None else None,  # reported in hundreds of ft
        weather=metar.get("wxString") or "",
        temp_c=int(round(temp_c)) if temp_c is not None else None,
        dewpoint_c=int(round(dewpoint_c)) if dewpoint_c is not None else None,
        altimeter_inhg=altimeter_inhg(raw_metar, num("altim")),
        lightning="LTG" in raw_metar,
        sky_conditions=sky_conditions,
        obs_time=datetime.fromtimestamp(obs_time, timezone.utc) if obs_time else None,
        latitude=num("lat"),
        longitude=num("lon"),
    )


def altimeter_inhg(raw, hectopascals):
    """
    The altimeter setting in inHg: as the report gives it (A3023 -> 30.23), which is exact; otherwise converted
    from the JSON's hectopascals (rounded to 0.1 hPa, so it can be 0.01 inHg off); None if neither.
    """
    found = ALTIMETER.search(raw.split(" RMK ")[0])
    if found:
        return int(found.group(1)) / 100
    return round(hectopascals / HPA_PER_INHG, 2) if hectopascals else None


# ---- mock METARs (dev_mode): a report typed on the Airports page replaces the fetched one ---------------------

MOCK_KEY = "mock_metar"  # the airport's key in config.json
MPS_TO_KT = 1.94384
METERS_PER_SM = 1609.344


def mock_text(airport):
    """The mock METAR saved for an airport (config.json's mock_metar), or ""."""
    return str(getattr(airport, "_extra", {}).get(MOCK_KEY) or "").strip()


def observed(day, hour, minute, now):
    """The time of a report's DDHHMMZ: this month, or last month if that day is still ahead."""
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for _ in range(2):
        try:
            at = month.replace(day=day, hour=hour, minute=minute)
        except ValueError:  # e.g. the 31st in a 30-day month
            at = None
        if at is not None and at <= now + timedelta(minutes=5):
            return at
        month = (month - timedelta(days=1)).replace(day=1)
    raise ValueError(f"{day:02d}{hour:02d}{minute:02d}Z isn't a time in the last month")


def parse_raw(raw, now) -> Report:
    """
    A METAR typed by hand ("METAR KDWH 272353Z AUTO 08003KT 9SM CLR 21/18 A3014 RMK ...") as parse_report() gives
    one from the JSON, for the mock METARs. The flight category comes from the visibility and ceiling (FAA limits).
    Only the body is read, not the remarks. Raises ValueError if it doesn't start like a METAR.
    """
    from metarmap.decode import estimate_category, parse_weather_group

    raw = " ".join(str(raw or "").split())
    tokens = raw.split(" RMK ")[0].split()
    if tokens and tokens[0] in ("METAR", "SPECI"):
        tokens = tokens[1:]
    if not tokens or not re.fullmatch(r"[A-Z0-9]{3,4}", tokens[0]):
        raise ValueError("a METAR starts with the airport code, e.g. METAR KDWH 272353Z ...")
    tokens = tokens[1:]
    obs_time = None
    if tokens and re.fullmatch(r"\d{6}Z", tokens[0]):
        obs_time = observed(int(tokens[0][:2]), int(tokens[0][2:4]), int(tokens[0][4:6]), now)
        tokens = tokens[1:]

    wind_dir, wind_speed, gust = "", None, 0
    visibility, more, wx, sky, vert_vis = None, False, [], [], None
    temp_c = dewpoint_c = None
    altim = None
    i = 0
    while i < len(tokens):
        t = tokens[i]
        wind = re.fullmatch(r"(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)", t)
        miles = re.fullmatch(r"([MP])?(\d+(?:/\d+)?)SM", t)
        clouds = re.fullmatch(r"(FEW|SCT|BKN|OVC)(\d{3})(?:CB|TCU)?", t)
        temps = re.fullmatch(r"(M?\d{2})/(M?\d{2})?", t)
        if wind:
            factor = MPS_TO_KT if wind.group(4) == "MPS" else 1
            wind_dir = wind.group(1) if wind.group(1) == "VRB" else str(int(wind.group(1)))  # as the JSON: "80"
            wind_speed = int(round(int(wind.group(2)) * factor))
            gust = int(round(int(wind.group(3)) * factor)) if wind.group(3) else 0
        elif re.fullmatch(r"\d{3}V\d{3}", t):  # varying wind direction
            pass
        elif t.isdigit() and i + 1 < len(tokens) and re.fullmatch(r"\d/\dSM", tokens[i + 1]):  # 1 1/2SM
            visibility = float(int(t) + Fraction(tokens[i + 1][:-2]))
            i += 1
        elif miles:
            visibility = float(Fraction(miles.group(2)))
            more = miles.group(1) == "P"
        elif re.fullmatch(r"\d{4}", t) and visibility is None:  # meters, outside the US; 9999: 10 km or more
            visibility = round(int(t) / METERS_PER_SM, 2)
            more = t == "9999"
        elif t == "CAVOK":
            visibility, more = 10.0, True
            sky.append(SkyLayer("CAVOK"))
        elif clouds:
            sky.append(SkyLayer(clouds.group(1), int(clouds.group(2)) * 100))
        elif re.fullmatch(r"VV(\d{3}|///)", t):  # sky obscured
            vert_vis = int(t[2:]) * 100 if t[2:].isdigit() else 0
            sky.append(SkyLayer("OVX"))
        elif t in ("CLR", "SKC", "NSC", "NCD"):
            sky.append(SkyLayer(t))
        elif temps:
            temp_c, dewpoint_c = (int(v.replace("M", "-")) if v else None for v in temps.groups())
        elif re.fullmatch(r"A\d{4}", t):
            altim = int(t[1:]) / 100
        elif re.fullmatch(r"Q\d{4}", t):
            altim = round(int(t[1:]) / HPA_PER_INHG, 2)
        elif parse_weather_group(t):
            wx.append(t)
        i += 1  # anything else (AUTO, COR, RVR, NOSIG...) is skipped

    report = Report(
        raw=raw,
        wind_dir=wind_dir,
        wind_speed=wind_speed,
        wind_gust_speed=gust,
        visibility_sm=visibility,
        visibility_more=more,
        vert_vis_ft=vert_vis,
        weather=" ".join(wx),
        temp_c=temp_c,
        dewpoint_c=dewpoint_c,
        altimeter_inhg=altim,
        lightning="LTG" in raw,
        sky_conditions=tuple(sky),
        obs_time=obs_time,
    )
    return replace(report, flight_category=estimate_category(report))


def with_mocks(real, airports, positions, now):
    """
    The METARs with each mocked airport's report replaced by its mock (marked mock=True). The station's own
    name, elevation and position are kept from its real report, or its station lookup. A mock that can't be read
    is logged and the real report stays.
    """
    data = dict(real)
    for airport in airports:
        text = mock_text(airport) if airport.code else ""
        if not text:
            continue
        try:
            mock = parse_raw(text, now)
        except ValueError as e:
            log.warning(f"{airport.code}: mock METAR ignored: {e}")
            continue
        known = real.get(airport.code) or Report()
        station = positions.get(airport.code) or {}
        data[airport.code] = replace(
            mock,
            name=known.name or station.get("name", ""),
            elevation_m=known.elevation_m,
            latitude=known.latitude or station.get("lat"),
            longitude=known.longitude or station.get("lon"),
            mock=True,
        )
    return data


def with_advisories(data, advisories):
    """
    The METARs, each with airmets and sigmets: the G-AIRMET and SIGMET hazards over the airport
    (metarmap.advisories), most important first. Either is None while there are none to go by (before its first fetch
    that worked) or the airport has no position.
    """
    result = {}
    for code, m in data.items():
        if m is None:  # no report: stays None, so every visualizer still shows it as "METAR not available"
            result[code] = m
            continue
        lat, lon = m.latitude, m.longitude
        try:
            hazards = advisories.hazards_at(float(lat), float(lon)) if lat is not None and lon is not None else None
        except (TypeError, ValueError):
            hazards = None
        hazards = hazards or {}
        result[code] = replace(m, airmets=hazards.get("airmets"), sigmets=hazards.get("sigmets"))
    return result


def with_tfrs(data, tfrs):
    """
    The METARs, each with tfrs: the TFRs at or near the airport (metarmap.tfr.Tfrs.at), most important first, or None
    while there's no TFR list to go by or the airport has no position. Airports with no report stay None.
    """
    result = {}
    for code, m in data.items():
        if m is None:
            result[code] = m
            continue
        try:
            found = tfrs.at(float(m.latitude), float(m.longitude))
        except (TypeError, ValueError):
            found = None
        result[code] = replace(m, tfrs=found)
    return result


class Reports:
    """
    Fetches the METARs and keeps each airport's Report (None when it isn't reporting) in .data, by code.
    """

    def __init__(self, cfg, fetch=False, clock: Clock = None, advisories=None, tfrs=None):
        """
        advisories: metarmap.advisories.Advisories, whose hazards are added to each report
        (with_advisories); None for none. tfrs: metarmap.tfr.Tfrs, the same for TFRs (with_tfrs).
        """

        self._config = cfg
        self.advisories = advisories
        self.tfrs = tfrs
        self._clock = clock or Clock()
        self._is_fetching = False
        self._missing_stations = []
        self._stations = []
        self.data = {}  # what the map shows: the fetched reports, with mock METARs in their place (dev_mode)
        self._real = {}  # the fetched reports
        self.lastFetchTime = None
        self.last_fetch_ok = None  # None until the first fetch, then whether the last one worked
        self.positions = {}  # code -> {"lat", "lon", "name"} from STATION_URL, or None if it doesn't know the code
        self.locate_failed = False  # whether the last position lookup failed (e.g. a 502); locate() tries again
        self.apply_mocks()  # mocks show before the first fetch, and without a network
        if fetch:
            self.fetch()

    def fetch(self, callback=None):
        """Fetches and processes the METARs. Returns True if it worked; on an error the old data is kept."""
        ok = False
        try:
            self._is_fetching = True
            log.info("Fetching...")
            url = API_URL + ",".join(airport_codes(self._config.airports))
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, verify=True)
            response.raise_for_status()
            content = response.content
            self._is_fetching = False
            self.lastFetchTime = datetime.now()
            log.info("Fetching completed.")
            self._process(content)
            ok = True
            self.locate()
        except requests.exceptions.RequestException as e:
            log.warning(f"Error occurred (RequestException): {e}")
        except Exception as e:
            log.exception(f"Error occurred: {e}")
        finally:
            self._is_fetching = False
            self.last_fetch_ok = ok
            if callback is not None:
                log.info("Calling callback function...")
                callback()
                log.info("done.")
        return ok

    def locate(self):
        """
        Looks up where each airport is and its name (the Map page shows airports without a report too; the
        Airports page fills in empty names). Each code is looked up once. Returns False if the lookup failed
        (locate_failed); calling it again tries the same codes again.
        """
        missing = [code for code in airport_codes(self._config.airports) if code not in self.positions]
        self.locate_failed = not self._look_up(missing)
        return not self.locate_failed

    def _look_up(self, codes, timeout=30):
        """Looks up codes with aviationweather.gov's station information. Returns False if that failed."""
        if not codes:
            return True
        try:
            response = requests.get(STATION_URL + ",".join(codes), headers={"User-Agent": USER_AGENT}, timeout=timeout)
            response.raise_for_status()
            stations = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            log.warning(f"Could not look up {', '.join(codes)}: {e}")
            return False
        found = {}
        for station in stations if isinstance(stations, list) else []:
            try:
                code = station.get("icaoId") or station["id"]
                found[code] = {
                    "lat": float(station["lat"]),
                    "lon": float(station["lon"]),
                    "name": str(station.get("site") or "").strip(),
                }
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        for code in codes:
            self.positions[code] = found.get(code)  # None: not a station it knows
        return True

    def name_for(self, code, timeout=10):
        """An airport's name, e.g. "Houston/Hobby Arpt", looked up now if it hasn't been; "" if unknown."""
        if code not in self.positions:
            self._look_up([code], timeout=timeout)
        return (self.positions.get(code) or {}).get("name", "")

    def station_names(self):
        """The names looked up so far, as {code: name}."""
        return {code: known["name"] for code, known in self.positions.items() if known and known.get("name")}

    def position(self, code):
        """Where an airport is, as (lat, lon): from its METAR, else from the station lookup; None if unknown."""
        m = self.data.get(code)
        if m and m.latitude and m.longitude:
            return float(m.latitude), float(m.longitude)
        known = self.positions.get(code)
        return (known["lat"], known["lon"]) if known else None

    def is_fetching(self):
        """
        Returns True if the class is fetching metars.
        """
        return self._is_fetching

    def _process(self, content):
        log.info("Processing...")
        # built separately, then swapped in, so readers never see half-filled data
        self._real, self._stations, self._missing_stations = process(
            content, airport_codes(self._config.airports), self._clock.now()
        )
        self.apply_mocks()
        log.info(f"Missing stations: {self._missing_stations}")
        log.info("Processing complete.")

    def apply_mocks(self):
        """
        Puts the mock METARs typed on the Airports page in place of the fetched ones (dev_mode only), or takes them
        away, and adds each airport's G-AIRMET and SIGMET hazards and TFRs. Called after each fetch (METARs, advisories
        or TFRs), and when a mock or the TFR nearby distance changes.
        """
        dev_mode = getattr(getattr(self._config, "data", None), "dev_mode", False)
        airports = self._config.airports if dev_mode is True else []
        data = with_mocks(self._real, airports, self.positions, self._clock.now())
        if self.advisories is not None:
            data = with_advisories(data, self.advisories)
        self.data = with_tfrs(data, self.tfrs) if self.tfrs is not None else data

    def missing_stations(self):
        """
        Returns a list of missing stations from the fetch
        """
        return self._missing_stations

    def stations(self):
        """
        Returns a list of all stations from the fetch
        """
        return self._stations
