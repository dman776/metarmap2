"""
Module to handle METAR fetching and processing
"""

from datetime import datetime
import sys
import requests
import xmltodict
from pprint import pprint
import lib.safe_logging as safe_logging
from config import Config
import lib.utils as utils
from collections import defaultdict
from typing import Dict, List


class METAR(object):
    """
    Object to control and handle METARs.
    """

    def __init__(self, cfg, fetch=False):
        """
        Creates a new METAR class.
        """

        self.__config__ = cfg
        self.__airports__ = self.__config__.airports
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
            url = "https://www.aviationweather.gov/adds/dataserver_current/httpparam?dataSource=metars&requestType=retrieve&format=xml&hoursBeforeNow=5&mostRecentForEachStation=true&stationString=" + \
                  ",".join([item for item in list(self.__airports__.keys()) if "NULL" not in item])
            response = requests.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36 Edg/86.0.622.69'},
                                    timeout=30, verify=True)
            response.raise_for_status()
            content = response.content
            self.__is_fetching__ = False
            self.lastFetchTime = datetime.now()
            safe_logging.safe_log("[m]Fetching completed.")
            self.__process__(content)
        except requests.exceptions.RequestException as e:
            safe_logging.safe_log(f"[m]Error occurred: {e}")
        except Exception as e:
            safe_logging.safe_log(f"[m]Error occurred: {e}")
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
        metars = jcontent['response']['data']['METAR']

        self.data = {
            "NULL": {"raw": "", "flightCategory": "", "windDir": "", "windSpeed": 0, "windGustSpeed": 0,
                     "windGust": False,
                     "lightning": False, "tempC": 0, "dewpointC": 0, "vis": 0, "altimHg": 0, "obs": "",
                     "skyConditions": {}, "latitude": "", "longitude": "", "obsTime": datetime.now()}}
        self.data.pop("NULL")

        station_list = []
        missing_stations = []

        for airport in self.__airports__:
            try:
                metar = next(m for m in metars if m['station_id'] == airport)
            except StopIteration:
                self.data[airport] = {}
                missing_stations.append(airport)
                continue
            except Exception as e:
                safe_logging.safe_log(f"[m] {e}")
                continue

            station_id = metar['station_id']
            flight_category = metar.get('flight_category')
            raw_metar = metar.get('raw_text')
            flight_category_color = self.__colors_by_category__(flight_category)
            wind_dir = metar.get('wind_dir_degrees', '')
            wind_speed = int(metar.get('wind_speed_kt', 0))
            wind_gust_speed = int(metar.get('wind_gust_kt', 0))
            wind_gust = wind_gust_speed > 0
            lightning = 'LTG' in metar.get('raw_text', '')
            elevation_m = int(round(float(metar.get('elevation_m', 0))))
            temp_c = int(round(float(metar.get('temp_c', ''))))
            dewpoint_c = int(round(float(metar.get('dewpoint_c', ''))))
            vis = int(round(float(metar.get('visibility_statute_mi', 0))))
            altim_hg = float(round(float(metar.get('altim_in_hg', 0)), 2))
            obs = metar.get('wx_string', '')
            obs_time = datetime.fromisoformat(metar.get('observation_time', '').replace("Z", "+00:00"))
            latitude = metar.get('latitude', '')
            longitude = metar.get('longitude', '')

            if 'raw_text' in metar:
                raw_text = metar.get('raw_text')
                lightning = True if 'LTG' in raw_text else False

            sky_conditions = []
            if "sky_condition" in metar:
                for sc in metar['sky_condition'] if isinstance(metar['sky_condition'], list) else [
                    metar['sky_condition']]:
                    sky_cond = {"cover": sc.get('@sky_cover', ''), "cloudBaseFt": int(sc.get('@cloud_base_ft_agl', 0))}
                    sky_conditions.append(sky_cond)

            self.data[station_id] = {
                "raw": raw_metar,
                "elevation_m": elevation_m,
                "flightCategory": flight_category,
                "flightCategoryColor": flight_category_color,
                "windDir": wind_dir,
                "windSpeed": wind_speed,
                "windGustSpeed": wind_gust_speed,
                "windGust": wind_gust,
                "vis": vis,
                "obs": obs,
                "tempC": temp_c,
                "dewpointC": dewpoint_c,
                "altimHg": altim_hg,
                "lightning": lightning,
                "skyConditions": sky_conditions,
                "obsTime": obs_time,
                "latitude": latitude,
                "longitude": longitude}
            station_list.append(station_id)
        self.__missing_stations__ = missing_stations
        self.__stations__ = station_list
        safe_logging.safe_log(f"[m]Missing stations: {missing_stations}")
        safe_logging.safe_log("[m]Processing complete.")

    def __colors_by_category__(self, category):
        color_map = {
            "VFR": self.__config__.data.color.cat.vfr,
            "MVFR": self.__config__.data.color.cat.mvfr,
            "IFR": self.__config__.data.color.cat.ifr,
            "LIFR": self.__config__.data.color.cat.lifr,
        }
        return color_map.get(category, self.__config__.data.color.clear)

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
