"""
Module to handle METAR fetching and processing
"""

from datetime import datetime, timedelta
from fractions import Fraction
import traceback
import requests
import xmltodict
from pprint import pprint
import metarmap.lib.safe_logging as safe_logging
from metarmap.config import Config
from metarmap.clock import Clock

# without `hours`, the API returns each station's latest report. (With hours=5 it returned up to ~13 reports per
# station and stopped at 400, so a long airport list could lose the newest ones.)
API_URL = "https://aviationweather.gov/api/data/metar?format=xml&ids="
# where airports are, for airports the METARs don't place (e.g. not reporting); JSON, one entry per known code
STATION_URL = "https://aviationweather.gov/api/data/stationinfo?format=json&ids="
# a station whose latest report is older than this counts as not reporting (the API returns it however old it is)
MAX_REPORT_AGE = timedelta(hours=5)
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


class METAR(object):
    """
    Object to control and handle METARs.
    """

    def __init__(self, cfg, fetch=False, clock: Clock = None):
        """
        Creates a new METAR class.
        """

        self.__config__ = cfg
        self.__clock__ = clock or Clock()
        self.__is_fetching__ = False
        self.__missing_stations__ = []
        self.__stations__ = []
        self.data = {}
        self.lastFetchTime = None
        self.last_fetch_ok = None  # None until the first fetch, then whether the last one worked
        self.positions = {}  # code -> {"lat", "lon"} from STATION_URL, or None if it doesn't know the code
        if fetch:
            self.fetch()

    def fetch(self, callback=None):
        """Fetches and processes the METARs. Returns True if it worked; on an error the old data is kept."""
        ok = False
        try:
            self.__is_fetching__ = True
            safe_logging.safe_log("[m]Fetching...")
            url = API_URL + ",".join(airport_codes(self.__config__.airports))
            response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=30, verify=True)
            response.raise_for_status()
            content = response.content
            self.__is_fetching__ = False
            self.lastFetchTime = datetime.now()
            safe_logging.safe_log("[m]Fetching completed.")
            self.__process__(content)
            ok = True
            self.__locate__()
        except requests.exceptions.RequestException as e:
            safe_logging.safe_log(f"[m]Error occurred (RequestException): {e}")
        except Exception as e:
            safe_logging.safe_log(f"[m]Error occurred: {e}\n{traceback.format_exc()}")
        finally:
            self.__is_fetching__ = False
            self.last_fetch_ok = ok
            if callback is not None:
                safe_logging.safe_log("[m]Calling callback function...")
                callback()
                safe_logging.safe_log("[m]done.")
        return ok

    def __locate__(self):
        """
        Looks up where airports without a report are, so the Map page can still show them. Each code is looked up
        once; a failed lookup is tried again after the next fetch.
        """
        missing = [code for code in airport_codes(self.__config__.airports)
                   if not (self.data.get(code) or {}).get("latitude") and code not in self.positions]
        if not missing:
            return
        try:
            response = requests.get(STATION_URL + ",".join(missing), headers={'User-Agent': USER_AGENT}, timeout=30)
            response.raise_for_status()
            stations = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            safe_logging.safe_log(f"[m]Could not look up where {', '.join(missing)} are: {e}")
            return
        found = {}
        for station in stations if isinstance(stations, list) else []:
            try:
                code = station.get("icaoId") or station["id"]
                found[code] = {"lat": float(station["lat"]), "lon": float(station["lon"])}
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        for code in missing:
            self.positions[code] = found.get(code)  # None: not a station it knows

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
        return self.__is_fetching__

    def __process__(self, content):
        safe_logging.safe_log("[m]Processing...")
        jcontent = xmltodict.parse(content)
        response_data = (jcontent.get('response') or {}).get('data') or {}
        metars = response_data.get('METAR') or []
        if isinstance(metars, dict):  # xmltodict returns a single METAR as a dict, not a list
            metars = [metars]

        # keep each station's newest report, by its time rather than its position in the response
        by_station = {}
        for m in metars:
            if isinstance(m, dict) and m.get('station_id'):
                current = by_station.get(m['station_id'])
                if current is None or (m.get('observation_time') or '') > (current.get('observation_time') or ''):
                    by_station[m['station_id']] = m

        # build the new data separately, then swap it in, so readers never see a half-filled dict
        data = {}
        station_list = []
        missing_stations = []
        oldest_allowed = self.__clock__.now() - MAX_REPORT_AGE
        for airport in airport_codes(self.__config__.airports):
            metar = by_station.get(airport)
            if metar is None:
                data[airport] = {}
                missing_stations.append(airport)
                continue
            try:
                parsed = self.__parse__(metar)
                if parsed["obsTime"] is not None and parsed["obsTime"] < oldest_allowed:
                    safe_logging.safe_log(f"[m]{airport}: latest report is from {parsed['obsTime']:%Y-%m-%d %H:%MZ}; "
                                          f"treating it as not reporting")
                    data[airport] = {}
                    missing_stations.append(airport)
                    continue
                data[airport] = parsed
                station_list.append(airport)
            except Exception as e:
                # one malformed report only affects its own airport
                safe_logging.safe_log(f"[m]Could not parse METAR for {airport}: {e} raw: {metar.get('raw_text')}\n"
                                      f"{traceback.format_exc()}")
                data[airport] = {}
                missing_stations.append(airport)

        self.data = data
        self.__missing_stations__ = missing_stations
        self.__stations__ = station_list
        safe_logging.safe_log(f"[m]Missing stations: {missing_stations}")
        safe_logging.safe_log("[m]Processing complete.")

    @staticmethod
    def __parse__(metar):
        """
        Converts one METAR from the XML response into the dict used everywhere else.
        """
        def num(key, default=None):
            value = metar.get(key)
            if value in (None, ''):
                return default
            return float(str(value).replace('+', ''))

        raw_metar = metar.get('raw_text') or ''
        temp_c = num('temp_c')
        dewpoint_c = num('dewpoint_c')
        obs_time = metar.get('observation_time')

        sky_conditions = []
        sky = metar.get('sky_condition') or []
        for sc in sky if isinstance(sky, list) else [sky]:
            sky_conditions.append({"cover": sc.get('@sky_cover', ''),
                                   "cloudBaseFt": int(sc.get('@cloud_base_ft_agl', 0) or 0)})

        wind_gust_speed = int(num('wind_gust_kt', 0))
        visibility = parse_visibility(metar.get('visibility_statute_mi'))
        return {
            "raw": raw_metar,
            "elevation_m": int(round(num('elevation_m', 0))),
            "flightCategory": metar.get('flight_category'),
            "windDir": metar.get('wind_dir_degrees', ''),
            "windSpeed": int(num('wind_speed_kt', 0)),
            "windGustSpeed": wind_gust_speed,
            "windGust": wind_gust_speed > 0,
            "vis": int(round(visibility or 0)),
            "visibilitySM": visibility,  # exact (e.g. 0.25), None if not reported
            "visibilityMore": "+" in str(metar.get('visibility_statute_mi') or ''),  # "10+": more than 10 miles
            "vertVisFt": int(num('vert_vis_ft')) if num('vert_vis_ft') is not None else None,
            "obs": metar.get('wx_string', '') or '',
            "tempC": int(round(temp_c)) if temp_c is not None else None,
            "dewpointC": int(round(dewpoint_c)) if dewpoint_c is not None else None,
            "altimHg": round(num('altim_in_hg', 0), 2),
            "lightning": 'LTG' in raw_metar,
            "skyConditions": sky_conditions,
            "obsTime": datetime.fromisoformat(obs_time.replace("Z", "+00:00")) if obs_time else None,
            "latitude": metar.get('latitude', ''),
            "longitude": metar.get('longitude', '')}

    def missing_stations(self):
        """
        Returns a list of missing stations from the fetch
        """
        return self.__missing_stations__

    def stations(self):
        """
        Returns a list of all stations from the fetch
        """
        return self.__stations__


if __name__ == '__main__':
    # airportstr = '{"KDWH": {"text": "Hooks", "display": false, "visits": 0},'\
    #             '"KIAH": {"text": "IAH", "display": false, "visits": 0},'\
    #             '"KLVJ": {"text": "", "display": false, "visits": 0}}'
    # airports = json.loads(airportstr)

    # with open('airports.json') as f:
    #     data = f.read()
    # airports = json.loads(data)

    config = Config("config.json")
    metars = METAR(config, fetch=True)
    pprint(metars.data)
    # pprint("missing: " + str(metars.missing_stations()))
    # pprint("all: " + str(metars.stations()))
    # pprint(metars.data['KDWH'], indent=4)
