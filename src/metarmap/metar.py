"""
Module to handle METAR fetching and processing
"""

import json
import re
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import traceback
import requests
import metarmap.lib.safe_logging as safe_logging
from metarmap.clock import Clock

# without `hours`, the API returns each station's latest report. (With hours=5 it returned up to ~13 reports per
# station and stopped at 400, so a long airport list could lose the newest ones.)
API_URL = "https://aviationweather.gov/api/data/metar?format=json&ids="
# where airports are, for airports the METARs don't place (e.g. not reporting); JSON, one entry per known code
STATION_URL = "https://aviationweather.gov/api/data/stationinfo?format=json&ids="
# a station whose latest report is older than this counts as not reporting (the API returns it however old it is)
MAX_REPORT_AGE = timedelta(hours=5)
ALTIMETER = re.compile(r"\bA(\d{4})\b")  # "A3023": 30.23 inHg, in a US report's body
HPA_PER_INHG = 33.8639
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/86.0.4240.198 Safari/537.36 Edg/86.0.622.69")


def parse_visibility(value):
    """Statute miles from the report: "10+", "6.0", "0.25", "1/2" or "1 1/2" (None if not reported)."""
    text = str(value or '').replace('+', '').strip()
    if not text:
        return None
    return float(sum(Fraction(part) for part in text.split()))


def airport_codes(airports):
    """The airports to fetch: each code once, in LED order, skipping LEDs with no airport."""
    return list(dict.fromkeys(a.code for a in airports if a.code))


# ---- parsing (no state: the METAR class below fetches and keeps the results) ------------------------------------

def latest_reports(content):
    """
    The newest report for each station in a JSON response, as {station: report}. Newest by its time rather than
    its position in the response. An empty response (no reports) is {}.
    """
    text = content.decode() if isinstance(content, bytes) else (content or "")
    reports = json.loads(text) if text.strip() else []
    by_station = {}
    for m in reports if isinstance(reports, list) else []:
        if isinstance(m, dict) and m.get('icaoId'):
            current = by_station.get(m['icaoId'])
            if current is None or (m.get('obsTime') or 0) > (current.get('obsTime') or 0):
                by_station[m['icaoId']] = m
    return by_station


def process(content, codes, now):
    """
    The METARs for `codes` from a JSON response, as (data, reporting, missing): data is {code: parse_report()},
    or {} for an airport with no report, a report older than MAX_REPORT_AGE before `now`, or one that can't be read.
    """
    by_station = latest_reports(content)
    data, reporting, missing = {}, [], []
    oldest_allowed = now - MAX_REPORT_AGE
    for airport in codes:
        metar = by_station.get(airport)
        if metar is None:
            data[airport] = {}
            missing.append(airport)
            continue
        try:
            parsed = parse_report(metar)
            if parsed["obsTime"] is not None and parsed["obsTime"] < oldest_allowed:
                safe_logging.safe_log(f"[m]{airport}: latest report is from {parsed['obsTime']:%Y-%m-%d %H:%MZ}; "
                                      f"treating it as not reporting")
                data[airport] = {}
                missing.append(airport)
                continue
            data[airport] = parsed
            reporting.append(airport)
        except Exception as e:
            # one malformed report only affects its own airport
            safe_logging.safe_log(f"[m]Could not parse METAR for {airport}: {e} raw: {metar.get('raw_text')}\n"
                                  f"{traceback.format_exc()}")
            data[airport] = {}
            missing.append(airport)
    return data, reporting, missing


def parse_report(metar):
    """
    Converts one METAR from the JSON response into the dict used everywhere else.
    """
    def num(key, default=None):
        value = metar.get(key)
        if value in (None, ''):
            return default
        return float(str(value).replace('+', ''))

    raw_metar = (metar.get('rawOb') or '').strip()  # the JSON can end it with a space
    temp_c = num('temp')
    dewpoint_c = num('dewp')
    obs_time = metar.get('obsTime')

    sky_conditions = [{"cover": sc.get('cover', ''), "cloudBaseFt": int(sc.get('base') or 0)}
                      for sc in metar.get('clouds') or [] if isinstance(sc, dict)]
    if not sky_conditions and metar.get('cover'):  # a clear sky has no layers, only "cover": "CLR"
        sky_conditions = [{"cover": metar['cover'], "cloudBaseFt": 0}]

    wind_dir = metar.get('wdir')
    wind_gust_speed = int(num('wgst', 0))
    visibility = parse_visibility(metar.get('visib'))
    return {
        "raw": raw_metar,
        "name": metar.get('name') or '',  # e.g. "Houston/Hobby Arpt, TX, US"
        "elevation_m": int(round(num('elev', 0))),
        "flightCategory": metar.get('fltCat'),
        "windDir": '' if wind_dir is None else str(wind_dir),  # degrees, or "VRB"
        "windSpeed": int(num('wspd', 0)),
        "windGustSpeed": wind_gust_speed,
        "windGust": wind_gust_speed > 0,
        "vis": int(round(visibility or 0)),
        "visibilitySM": visibility,  # exact (e.g. 0.25), None if not reported
        "visibilityMore": "+" in str(metar.get('visib') or ''),  # "10+": more than 10 miles
        "vertVisFt": int(num('vertVis')) * 100 if num('vertVis') is not None else None,  # reported in hundreds of ft
        "obs": metar.get('wxString') or '',
        "tempC": int(round(temp_c)) if temp_c is not None else None,
        "dewpointC": int(round(dewpoint_c)) if dewpoint_c is not None else None,
        "altimHg": altimeter_inhg(raw_metar, num('altim')),
        "lightning": 'LTG' in raw_metar,
        "skyConditions": sky_conditions,
        "obsTime": datetime.fromtimestamp(obs_time, timezone.utc) if obs_time else None,
        "latitude": num('lat'),
        "longitude": num('lon')}


def altimeter_inhg(raw, hectopascals):
    """
    The altimeter setting in inHg: as the report gives it (A3023 -> 30.23), which is exact; otherwise converted
    from the JSON's hectopascals (rounded to 0.1 hPa, so it can be 0.01 inHg off); 0 if neither.
    """
    found = ALTIMETER.search(raw.split(" RMK ")[0])
    if found:
        return int(found.group(1)) / 100
    return round(hectopascals / HPA_PER_INHG, 2) if hectopascals else 0.0


class METAR(object):
    """
    Object to control and handle METARs.
    """

    def __init__(self, cfg, fetch=False, clock: Clock = None):
        """
        Creates a new METAR class.
        """

        self._config = cfg
        self._clock = clock or Clock()
        self._is_fetching = False
        self._missing_stations = []
        self._stations = []
        self.data = {}
        self.lastFetchTime = None
        self.last_fetch_ok = None  # None until the first fetch, then whether the last one worked
        self.positions = {}  # code -> {"lat", "lon"} from STATION_URL, or None if it doesn't know the code
        self.locate_failed = False  # whether the last position lookup failed (e.g. a 502); locate() tries again
        if fetch:
            self.fetch()

    def fetch(self, callback=None):
        """Fetches and processes the METARs. Returns True if it worked; on an error the old data is kept."""
        ok = False
        try:
            self._is_fetching = True
            safe_logging.safe_log("[m]Fetching...")
            url = API_URL + ",".join(airport_codes(self._config.airports))
            response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=30, verify=True)
            response.raise_for_status()
            content = response.content
            self._is_fetching = False
            self.lastFetchTime = datetime.now()
            safe_logging.safe_log("[m]Fetching completed.")
            self._process(content)
            ok = True
            self.locate()
        except requests.exceptions.RequestException as e:
            safe_logging.safe_log(f"[m]Error occurred (RequestException): {e}")
        except Exception as e:
            safe_logging.safe_log(f"[m]Error occurred: {e}\n{traceback.format_exc()}")
        finally:
            self._is_fetching = False
            self.last_fetch_ok = ok
            if callback is not None:
                safe_logging.safe_log("[m]Calling callback function...")
                callback()
                safe_logging.safe_log("[m]done.")
        return ok

    def locate(self):
        """
        Looks up where airports without a report are, so the Map page can still show them. Each code is looked up
        once. Returns False if the lookup failed (locate_failed); calling it again tries the same codes again.
        """
        missing = [code for code in airport_codes(self._config.airports)
                   if not (self.data.get(code) or {}).get("latitude") and code not in self.positions]
        self.locate_failed = False
        if not missing:
            return True
        try:
            response = requests.get(STATION_URL + ",".join(missing), headers={'User-Agent': USER_AGENT}, timeout=30)
            response.raise_for_status()
            stations = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            safe_logging.safe_log(f"[m]Could not look up where {', '.join(missing)} are: {e}")
            self.locate_failed = True
            return False
        found = {}
        for station in stations if isinstance(stations, list) else []:
            try:
                code = station.get("icaoId") or station["id"]
                found[code] = {"lat": float(station["lat"]), "lon": float(station["lon"])}
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        for code in missing:
            self.positions[code] = found.get(code)  # None: not a station it knows
        return True

    def position(self, code):
        """Where an airport is, as (lat, lon): from its METAR, else from the station lookup; None if unknown."""
        m = self.data.get(code) or {}
        if m.get("latitude") and m.get("longitude"):
            return float(m["latitude"]), float(m["longitude"])
        known = self.positions.get(code)
        return (known["lat"], known["lon"]) if known else None

    def is_fetching(self):
        """
        Returns True if the class is fetching metars.
        """
        return self._is_fetching

    def _process(self, content):
        safe_logging.safe_log("[m]Processing...")
        # built separately, then swapped in, so readers never see half-filled data
        self.data, self._stations, self._missing_stations = process(
            content, airport_codes(self._config.airports), self._clock.now())
        safe_logging.safe_log(f"[m]Missing stations: {self._missing_stations}")
        safe_logging.safe_log("[m]Processing complete.")

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

