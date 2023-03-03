"""
Module to handle METAR fetching and processing
"""

import datetime
import urllib.request
# import xml.etree.ElementTree as ET
import xmltodict
from pprint import pprint
import json
import lib.safe_logging as safe_logging
from config import Config
import lib.utils as utils

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
            safe_logging.safe_log("[m]" + "Fetching...")
            url = "https://www.aviationweather.gov/adds/dataserver_current/httpparam?dataSource=metars&requestType=retrieve&format=xml&hoursBeforeNow=5&mostRecentForEachStation=true&stationString=" + \
                  ",".join(
                      [item for item in list(self.__airports__.keys()) if "NULL" not in item])
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36 Edg/86.0.622.69'})
            content = urllib.request.urlopen(req).read()
            self.__is_fetching__ = False
            self.lastFetchTime=datetime.datetime.now()
            safe_logging.safe_log("[m]" + "Fetching completed.")
            self.__process__(content)
        except Exception as e:
            print(e)
            self.__is_fetching__ = False
            if callback is not None:
                safe_logging.safe_log("[m]" + "Calling callback function...")
                callback()
                safe_logging.safe_log("[m]" + "done.")
        return

    def is_fetching(self):
        """
        Returns True if the class is fetching metars.
        """
        return self.__is_fetching__

    def __process__(self, content):
        safe_logging.safe_log("[m]" + "Processing...")
        # Retrieve flying conditions from the service response and store in a dictionary for each airport
        jcontent = xmltodict.parse(content)
        metars = jcontent['response']['data']['METAR']

        self.data = {
            "NULL": {"raw": "", "flightCategory": "", "windDir": "", "windSpeed": 0, "windGustSpeed": 0, "windGust": False,
                     "lightning": False, "tempC": 0, "dewpointC": 0, "vis": 0, "altimHg": 0, "obs": "",
                     "skyConditions": {}, "latitude": "", "longitude": "",  "obsTime": datetime.datetime.now()}}
        self.data.pop("NULL")
        stationList = []
        missingCondList = []


        for airport in list(self.__airports__.keys()):
            # safe_logging.safe_log(airport)
            # station_id = ""

            try:
                m = utils.find_in_list("station_id", airport, metars)
                if len(m) > 0:
                    metar = m[0]
                else:
                    # could not find an entry in the metars for the airport
                    self.data[airport] = {}
                    missingCondList.append(airport)
                    continue
            except IndexError:
                missingCondList.append(airport)
                self.data[airport] = {}
                continue
            except Exception as e:
                safe_logging.safe_log("[m]" + str(e))

            stationId = metar['station_id']

            if 'flight_category' not in metar:
                safe_logging.safe_log("Missing flight category, skipping " + stationId)
                missingCondList.append(stationId)
                self.data[stationId] = {}
                continue

            rawMetar = metar['raw_text'] if 'raw_text' in metar else None
            flightCategory = metar['flight_category'] if 'flight_category' in metar else None
            flightCategoryColor = self.__colors_by_category__(flightCategory)
            windDir = ""
            windSpeed = 0
            windGustSpeed = 0
            windGust = False
            lightning = False
            elevation_m = 0
            tempC = ''
            dewpointC = ''
            vis = 0
            altimHg = 0.0
            obs = ""
            skyConditions = []
            latitude = metar['latitude'] or ""
            longitude = metar['longitude'] or ""

            if 'elevation_m' in metar:
                elevation_m = int(metar['elevation_m'])
            if 'wind_gust_kt' in metar:
                windGustSpeed = int(metar['wind_gust_kt'])
                windGust = (True if windGustSpeed > 0 else False)
            if 'wind_speed_kt' in metar:
                windSpeed = int(metar['wind_speed_kt'])
            if 'wind_dir_degrees' in metar:
                windDir = metar['wind_dir_degrees']
            if 'temp_c' in metar:
                tempC = int(round(float(metar['temp_c'])))
            if 'dewpoint_c' in metar:
                dewpointC = int(round(float(metar['dewpoint_c'])))
            if 'visibility_statute_mi' in metar:
                vis = int(round(float(metar['visibility_statute_mi'])))
            if 'altim_in_hg' in metar:
                altimHg = float(round(float(metar['altim_in_hg']), 2))
            if 'wx_string'in metar:
                obs = metar['wx_string']
            if 'observation_time'in metar:
                obsTime = datetime.datetime.fromisoformat(metar['observation_time'].replace("Z", "+00:00"))

            if 'raw_text' in metar:
                rawText = metar['raw_text']
                lightning = True if 'LTG' in rawText else False

            if "sky_condition" in metar:
                skyCond = {}
                if isinstance(metar['sky_condition'], list):
                    for sc in metar['sky_condition']:
                        skyCond = {"cover": sc['@sky_cover'],
                               "cloudBaseFt": int(sc.get('@cloud_base_ft_agl', "0"))}
                elif isinstance(metar['sky_condition'], dict):
                    skyCond = {"cover": metar['sky_condition']['@sky_cover'],
                               "cloudBaseFt": int(metar['sky_condition'].get('@cloud_base_ft_agl', "0"))}
                skyConditions.append(skyCond)

            self.data[stationId] = {"raw": rawMetar,
                                    "elevation_m": elevation_m,
                                    "flightCategory": flightCategory,
                                    "flightCategoryColor": flightCategoryColor,
                                    "windDir": windDir, "windSpeed": windSpeed, "windGustSpeed": windGustSpeed,
                                    "windGust": windGust, "vis": vis, "obs": obs,
                                    "tempC": tempC, "dewpointC": dewpointC, "altimHg": altimHg,
                                    "lightning": lightning, "skyConditions": skyConditions, "obsTime": obsTime,
                                    "latitude": latitude, "longitude": longitude}
            stationList.append(stationId)
        self.__missing_stations__ = missingCondList
        self.__stations__ = stationList
        safe_logging.safe_log("[m]" + "Processing complete.")
        return

    def __colors_by_category__(self, category):
        if category == "VFR":
            return self.__config__.data.color.cat.vfr
        elif category == "MVFR":
            return self.__config__.data.color.cat.mvfr
        elif category == "IFR":
            return self.__config__.data.color.cat.ifr
        elif category == "LIFR":
            return self.__config__.data.color.cat.lifr
        else:
            return self.__config__.data.color.clear

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
    airportstr = '{"KDWH": {"text": "Hooks", "display": false, "visits": 0},'\
                '"KIAH": {"text": "IAH", "display": false, "visits": 0},'\
                '"KLVJ": {"text": "", "display": false, "visits": 0}}'
    airports = json.loads(airportstr)

    # with open('airports.json') as f:
    #     data = f.read()
    # airports = json.loads(data)

    config = Config("config.json")
    metars = METAR(airports, config, fetch=True)
    pprint(metars.data)
    pprint("missing: " + str(metars.missing_stations()))
    # pprint("all: " + str(metars.stations()))
    # pprint(metars.data['KDWH'], indent=4)

