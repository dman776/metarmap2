"""
Module to handle METAR fetching and processing
"""

from datetime import datetime, timedelta
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
# a station whose latest report is older than this counts as not reporting (the API returns it however old it is)
MAX_REPORT_AGE = timedelta(hours=5)
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/86.0.4240.198 Safari/537.36 Edg/86.0.622.69")


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
        if fetch:
            self.fetch()

    def fetch(self, callback=None):
        try:
            self.__is_fetching__ = True
            safe_logging.safe_log("[m]Fetching...")
            url = API_URL + ",".join([item for item in list(self.__config__.airports.keys()) if "NULL" not in item])
            response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=30, verify=True)
            response.raise_for_status()
            content = response.content
            self.__is_fetching__ = False
            self.lastFetchTime = datetime.now()
            safe_logging.safe_log("[m]Fetching completed.")
            self.__process__(content)
        except requests.exceptions.RequestException as e:
            safe_logging.safe_log(f"[m]Error occurred (RequestException): {e}")
        except Exception as e:
            safe_logging.safe_log(f"[m]Error occurred: {e}\n{traceback.format_exc()}")
        finally:
            self.__is_fetching__ = False
            if callback is not None:
                safe_logging.safe_log("[m]Calling callback function...")
                callback()
                safe_logging.safe_log("[m]done.")

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
        for airport in list(self.__config__.airports):
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
        return {
            "raw": raw_metar,
            "elevation_m": int(round(num('elevation_m', 0))),
            "flightCategory": metar.get('flight_category'),
            "windDir": metar.get('wind_dir_degrees', ''),
            "windSpeed": int(num('wind_speed_kt', 0)),
            "windGustSpeed": wind_gust_speed,
            "windGust": wind_gust_speed > 0,
            "vis": int(round(num('visibility_statute_mi', 0))),
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
