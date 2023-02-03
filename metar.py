"""
Module to handle METAR fetching and processing
"""

import threading
import sys
import time
import datetime
import urllib.request
import xml.etree.ElementTree as ET
from pprint import pprint
import json
import lib.safe_logging as safe_logging
# from lib.config import Config

class METAR(object):
    """
    Object to control and handle METARs.
    """

    def fetch(self):
        try:
            self.__is_fetching__ = True
            safe_logging.safe_log("Fetching...")
            url = "https://www.aviationweather.gov/adds/dataserver_current/httpparam?dataSource=metars&requestType=retrieve&format=xml&hoursBeforeNow=5&mostRecentForEachStation=true&stationString=" + \
                  ",".join(
                      [item for item in list(self.__airports__.keys()) if "NULL" not in item])
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36 Edg/86.0.622.69'})
            content = urllib.request.urlopen(req).read()
            self.__is_fetching__ = False
            self.lastFetchTime=datetime.datetime.now()
            safe_logging.safe_log("Fetching completed.")
            return self.__process__(content)
        except Exception as e:
            print(e)
            self.__is_fetching__ = False
            return None

    def is_fetching(self):
        """
        Returns True if the class is fetching metars.
        """
        return self.__is_fetching__

    def __process__(self, content):
        safe_logging.safe_log("Processing...")
        # Retrieve flying conditions from the service response and store in a dictionary for each airport
        root = ET.fromstring(content)
        self.data = {
            "NULL": {"raw": "", "flightCategory": "", "windDir": "", "windSpeed": 0, "windGustSpeed": 0, "windGust": False,
                     "lightning": False, "tempC": 0, "dewpointC": 0, "vis": 0, "altimHg": 0, "obs": "",
                     "skyConditions": {}, "latitude": "", "longitude": "",  "obsTime": datetime.datetime.now()}}
        self.data.pop("NULL")
        stationList = []
        missingCondList = []
        for metar in root.iter('METAR'):
            stationId = metar.find('station_id').text
            if metar.find('flight_category') is None:
                print("Missing flight condition, skipping " + stationId)
                missingCondList.append(stationId)
                continue
            rawMetar = metar.find('raw_text').text
            flightCategory = metar.find('flight_category').text
            windDir = ""
            windSpeed = 0
            windGustSpeed = 0
            windGust = False
            lightning = False
            tempC = 0
            dewpointC = 0
            vis = 0
            altimHg = 0.0
            obs = ""
            skyConditions = []
            latitude = metar.find('latitude').text or ""
            longitude = metar.find('longitude').text or ""

            if metar.find('wind_gust_kt') is not None:
                windGustSpeed = int(metar.find('wind_gust_kt').text)
                windGust = (True if (self.__config__.data().wind.always_for_gusts or windGustSpeed > self.__config__.data().wind.threshold) else False)
            if metar.find('wind_speed_kt') is not None:
                windSpeed = int(metar.find('wind_speed_kt').text)
            if metar.find('wind_dir_degrees') is not None:
                windDir = metar.find('wind_dir_degrees').text
            if metar.find('temp_c') is not None:
                tempC = int(round(float(metar.find('temp_c').text)))
            if metar.find('dewpoint_c') is not None:
                dewpointC = int(round(float(metar.find('dewpoint_c').text)))
            if metar.find('visibility_statute_mi') is not None:
                vis = int(round(float(metar.find('visibility_statute_mi').text)))
            if metar.find('altim_in_hg') is not None:
                altimHg = float(round(float(metar.find('altim_in_hg').text), 2))
            if metar.find('wx_string') is not None:
                obs = metar.find('wx_string').text
            if metar.find('observation_time') is not None:
                obsTime = datetime.datetime.fromisoformat(metar.find('observation_time').text.replace("Z", "+00:00"))
            for skyIter in metar.iter("sky_condition"):
                skyCond = {"cover": skyIter.get("sky_cover"),
                           "cloudBaseFt": int(skyIter.get("cloud_base_ft_agl", default=0))}
                skyConditions.append(skyCond)
            if metar.find('raw_text') is not None:
                rawText = metar.find('raw_text').text
                lightning = False if rawText.find('LTG') == -1 else True

            self.data[stationId] = {"raw": rawMetar, "flightCategory": flightCategory, "windDir": windDir, "windSpeed": windSpeed,
                                        "windGustSpeed": windGustSpeed, "windGust": windGust, "vis": vis, "obs": obs,
                                        "tempC": tempC, "dewpointC": dewpointC, "altimHg": altimHg,
                                        "lightning": lightning, "skyConditions": skyConditions, "obsTime": obsTime,
                                        "latitude": latitude, "longitude": longitude}
            stationList.append(stationId)
        self.__missing_stations__ = missingCondList
        self.__stations__ = stationList
        safe_logging.safe_log("Processing complete.")
        return

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

    def __init__(self, airports: dict, cfg, fetch=False):
        """
        Creates a new METAR class.
        """
        self.__airports__ = airports
        self.__config__ = cfg
        self.__is_fetching__ = False
        self.__missing_stations__ = []
        self.__stations__ = []
        self.data = {}
        self.lastFetchTime = None
        if fetch:
            self.fetch()


if __name__ == '__main__':
    airportstr = '{"KDWH": {"text": "Hooks", "display": false, "visits": 0},'\
                '"KIAH": {"text": "IAH", "display": false, "visits": 0}}'

    airports = json.loads(airportstr)
    CONFIG = Config("config.json")
    metars = METAR(airports, CONFIG, fetch=True)
    pprint(metars)
    pprint("missing: " + str(metars.missing_stations()))
    pprint("all: " + str(metars.stations()))
    pprint(metars.data, indent=4)

